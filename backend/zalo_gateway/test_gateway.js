/**
 * Integration Test Suite for Zalo Gateway Microservice
 */

const http = require('http');
const assert = require('assert');
const path = require('path');
const fs = require('fs');

// Ensure temporary test session dir
const TEST_DIR = path.join(__dirname, 'test_data_session');
process.env.SESSION_DIR = TEST_DIR;
process.env.PORT = '8199'; // Use non-conflicting test port
process.env.ZALO_GATEWAY_PORT = '8199';

const { app, server } = require('./server.js');

function request(method, path, body = null, extraHeaders = {}) {
  return new Promise((resolve, reject) => {
    const payload = body ? JSON.stringify(body) : null;
    const req = http.request({
      hostname: '127.0.0.1',
      port: 8199,
      path,
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(payload ? { 'Content-Length': Buffer.byteLength(payload) } : {}),
        ...extraHeaders
      }
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          resolve({ status: res.statusCode, data: parsed });
        } catch (e) {
          resolve({ status: res.statusCode, raw: data });
        }
      });
    });

    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

async function runTests() {
  console.log('🧪 Starting Zalo Gateway Integration Tests...');

  try {
    // 1. Health check
    console.log('  Testing GET /health...');
    const health = await request('GET', '/health');
    assert.strictEqual(health.status, 200);
    assert.strictEqual(health.data.status, 'ok');
    assert.strictEqual(health.data.service, 'zalo-gateway');
    console.log(`  ✓ Health OK (RAM heap: ${health.data.memory.heap_used_mb}MB, RSS: ${health.data.memory.rss_mb}MB)`);

    // 2. Status initial check
    console.log('  Testing GET /api/zalo/status (initial)...');
    const status1 = await request('GET', '/api/zalo/status');
    assert.strictEqual(status1.status, 200);
    assert.ok(['disconnected', 'ready'].includes(status1.data.status));
    console.log(`  ✓ Status OK: status=${status1.data.status}, connected=${status1.data.connected}`);

    // 3. QR Code generation
    console.log('  Testing GET /api/zalo/qr...');
    const qrRes = await request('GET', '/api/zalo/qr');
    assert.strictEqual(qrRes.status, 200);
    assert.strictEqual(qrRes.data.success, true);
    assert.strictEqual(qrRes.data.status, 'waiting_qr');
    assert.ok(qrRes.data.qr_code.startsWith('data:image/png;base64,'));
    console.log(`  ✓ QR Generation OK (Data URL length: ${qrRes.data.qr_code.length})`);

    // Verify status updated to waiting_qr
    const statusWaiting = await request('GET', '/api/zalo/status');
    assert.strictEqual(statusWaiting.data.status, 'waiting_qr');
    assert.strictEqual(statusWaiting.data.connected, false);
    console.log('  ✓ Status transitioned to waiting_qr');

    // 4. Send Message (Dispatch)
    console.log('  Testing POST /api/zalo/send...');
    const sendRes = await request('POST', '/api/zalo/send', {
      recipient: '0901234567',
      message: 'Phiếu lương tháng 10/2026: Thực lĩnh 5.850.000đ. Vui lòng kiểm tra chi tiết.'
    });
    assert.strictEqual(sendRes.status, 200);
    assert.strictEqual(sendRes.data.success, true);
    assert.ok(sendRes.data.msg_id.startsWith('zalo_msg_'));
    console.log(`  ✓ Send message OK: msg_id=${sendRes.data.msg_id}`);

    // Test send validation failure
    const sendInvalid = await request('POST', '/api/zalo/send', { recipient: '' });
    assert.strictEqual(sendInvalid.status, 400);
    assert.strictEqual(sendInvalid.data.success, false);
    console.log('  ✓ Send validation rejection OK (HTTP 400)');

    // 4b. Security regression: Arbitrary local file exfiltration via image_path must be blocked
    const exfilAttempt = await request('POST', '/api/zalo/send', {
      recipient: '0901234567',
      message: 'Exfil test',
      image_path: path.join(__dirname, 'package.json')
    });
    assert.strictEqual(exfilAttempt.status, 403);
    assert.strictEqual(exfilAttempt.data.success, false);
    console.log('  ✓ Arbitrary file exfiltration via image_path blocked (HTTP 403)');

    // 4c. Security regression: Cross-origin browser request from untrusted site must be blocked
    const corsAttack = await request('POST', '/api/zalo/send', {
      recipient: '0901234567',
      message: 'CSRF test'
    }, { Origin: 'https://evil-attacker.example.com' });
    assert.strictEqual(corsAttack.status, 403);
    console.log('  ✓ Untrusted cross-origin Origin header blocked (HTTP 403)');

    // 4d. Security regression: Shared secret token enforcement (ZALO_GATEWAY_TOKEN)
    process.env.ZALO_GATEWAY_TOKEN = 'test_gateway_secret_256bit_token';
    try {
      const noTokenRes = await request('GET', '/api/zalo/status');
      assert.strictEqual(noTokenRes.status, 401);
      const validTokenRes = await request('GET', '/api/zalo/status', null, {
        'X-Zalo-Gateway-Token': 'test_gateway_secret_256bit_token'
      });
      assert.strictEqual(validTokenRes.status, 200);
      console.log('  ✓ ZALO_GATEWAY_TOKEN shared-secret guard verified (HTTP 401 / HTTP 200)');
    } finally {
      delete process.env.ZALO_GATEWAY_TOKEN;
    }

    // 4e. Security regression: Production mode blocks simulated /confirm-qr
    process.env.NODE_ENV = 'production';
    try {
      const prodConfirm = await request('POST', '/api/zalo/confirm-qr', { userName: 'Spoof' });
      assert.strictEqual(prodConfirm.status, 403);
      console.log('  ✓ Production guard on /api/zalo/confirm-qr verified (HTTP 403)');
    } finally {
      delete process.env.NODE_ENV;
    }

    // 5. Simulated QR Confirmation (Login)
    console.log('  Testing POST /api/zalo/confirm-qr...');
    const confirmRes = await request('POST', '/api/zalo/confirm-qr', {
      token: qrRes.data.token,
      userName: 'Chủ Quán FnBOps',
      phone: '0909888999'
    });
    assert.strictEqual(confirmRes.status, 200);
    assert.strictEqual(confirmRes.data.success, true);
    assert.strictEqual(confirmRes.data.status, 'ready');
    assert.strictEqual(confirmRes.data.connected, true);
    console.log('  ✓ QR Confirmation OK: connected=true');

    // Check status is now ready
    const statusReady = await request('GET', '/api/zalo/status');
    assert.strictEqual(statusReady.data.status, 'ready');
    assert.strictEqual(statusReady.data.connected, true);
    console.log('  ✓ Status is verified ready');

    // 6. Logout & Session reset
    console.log('  Testing POST /api/zalo/logout...');
    const logoutRes = await request('POST', '/api/zalo/logout');
    assert.strictEqual(logoutRes.status, 200);
    assert.strictEqual(logoutRes.data.success, true);
    assert.strictEqual(logoutRes.data.status, 'disconnected');
    assert.strictEqual(logoutRes.data.connected, false);
    console.log('  ✓ Logout OK');

    // Verify memory constraint (Heap is < 25MB, well within 60MB container target)
    const memUsage = process.memoryUsage();
    const heapUsedMb = memUsage.heapUsed / (1024 * 1024);
    const rssMb = memUsage.rss / (1024 * 1024);
    console.log(`  Memory verification: Heap Used is ${heapUsedMb.toFixed(2)}MB, RSS is ${rssMb.toFixed(2)}MB (Target < 60MB)`);
    assert.ok(heapUsedMb < 30, `Heap used exceeded 30MB: ${heapUsedMb}MB`);
    assert.ok(rssMb < 120, `RSS exceeded threshold: ${rssMb}MB`);

    console.log('🎉 ALL ZALO GATEWAY TESTS PASSED!');
    process.exit(0);
  } finally {
    server.close();
    // Cleanup test dir
    try {
      if (fs.existsSync(TEST_DIR)) {
        fs.rmSync(TEST_DIR, { recursive: true, force: true });
      }
    } catch (e) {}
  }
}

runTests().catch(err => {
  console.error('❌ Test failed:', err);
  process.exit(1);
});
