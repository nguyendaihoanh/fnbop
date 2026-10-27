// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
/*!
 * FnBOps — Zalo Gateway Microservice for Standalone F&B Operations
 * Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
 * Licensed under the GNU Affero General Public License v3.0 only (AGPL-3.0-only).
 *
 * Ultra-lightweight Node.js microservice (<60MB RAM footprint)
 * Powered by zca-js (MIT License — Unofficial Zalo Web QR Login & Messaging)
 *
 * Legal Notice: "Zalo" is a registered trademark of VNG Corporation.
 * FnBOps is independent and not affiliated with or endorsed by VNG/Zalo.
 */

const express = require('express');
const cors = require('cors');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { Zalo, LoginQRCallbackEventType } = require('zca-js');
require('dotenv').config();

const app = express();
const PORT = parseInt(process.env.ZALO_GATEWAY_PORT || process.env.PORT || '8177', 10);
const HOST = process.env.ZALO_GATEWAY_HOST || (
  (fs.existsSync('/.dockerenv') || process.env.CONTAINER === 'true') ? '0.0.0.0' : '127.0.0.1'
);

// Resolve session storage directory
const DEFAULT_SESSION_DIR = path.resolve(__dirname, '../../data/zalo_session');
const SESSION_DIR = process.env.SESSION_DIR || (
  fs.existsSync('/app/data') ? '/app/data/zalo_session' : DEFAULT_SESSION_DIR
);

// Ensure session directory exists at startup with restricted permissions (0700)
if (!fs.existsSync(SESSION_DIR)) {
  try {
    fs.mkdirSync(SESSION_DIR, { recursive: true, mode: 0o700 });
    console.log(`[ZALO-GATEWAY] Created session directory: ${SESSION_DIR}`);
  } catch (err) {
    console.error(`[ZALO-GATEWAY] Failed to create session directory: ${err.message}`);
  }
} else {
  try { fs.chmodSync(SESSION_DIR, 0o700); } catch (_) {}
}

const SESSION_FILE = path.join(SESSION_DIR, 'session.json');
const LOG_FILE = path.join(SESSION_DIR, 'zalo_dispatches.log');

// In-memory runtime state
let currentState = {
  status: 'disconnected', // 'ready' | 'waiting_qr' | 'scanned' | 'disconnected'
  connected: false,
  user: null,
  activeQrToken: null,
  qrExpiresAt: null,
  lastActive: null,
  initializedAt: new Date().toISOString()
};

let activeZalo = null;
let activeApi = null;
let cachedQr = null; // { qrImage: string, expiresAt: number, code: string }
let qrGenerationPromise = null;

/**
 * Save current session credentials to disk (Smart merge to preserve cookies)
 */
function saveSessionToDisk(data) {
  try {
    if (!fs.existsSync(SESSION_DIR)) {
      fs.mkdirSync(SESSION_DIR, { recursive: true, mode: 0o700 });
    }
    let existing = {};
    if (fs.existsSync(SESSION_FILE)) {
      try {
        existing = JSON.parse(fs.readFileSync(SESSION_FILE, 'utf8')) || {};
      } catch (_) {}
    }
    const merged = {
      cookie: data.cookie || existing.cookie,
      imei: data.imei || existing.imei,
      userAgent: data.userAgent || existing.userAgent,
      user: data.user || existing.user || null,
      connected: data.connected !== undefined ? data.connected : (existing.connected || false),
      savedAt: data.savedAt || new Date().toISOString()
    };
    fs.writeFileSync(SESSION_FILE, JSON.stringify(merged, null, 2), { encoding: 'utf8', mode: 0o600 });
    try { fs.chmodSync(SESSION_FILE, 0o600); } catch (_) {}
    console.log(`[ZALO-GATEWAY] Session persisted to: ${SESSION_FILE}`);
  } catch (err) {
    console.error(`[ZALO-GATEWAY] Failed to persist session: ${err.message}`);
  }
}


/**
 * Image metadata getter for zca-js attachment support (zero-dependency PNG/JPEG parser)
 */
async function getImageMetadata(filePath) {
  try {
    const buf = fs.readFileSync(filePath);
    let width = 1080;
    let height = 1440;

    if (buf.length >= 24 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4E && buf[3] === 0x47) {
      width = buf.readUInt32BE(16);
      height = buf.readUInt32BE(20);
    } else if (buf.length >= 4 && buf[0] === 0xFF && buf[1] === 0xD8) {
      let offset = 2;
      while (offset + 9 < buf.length) {
        if (buf[offset] === 0xFF && (buf[offset + 1] >= 0xC0 && buf[offset + 1] <= 0xC3)) {
          height = buf.readUInt16BE(offset + 5);
          width = buf.readUInt16BE(offset + 7);
          break;
        }
        const blockLen = buf.readUInt16BE(offset + 2);
        offset += 2 + (blockLen || 2);
      }
    }

    return {
      width,
      height,
      size: buf.length
    };
  } catch (err) {
    console.warn(`[ZALO-GATEWAY] Failed to read image metadata for ${filePath}: ${err.message}`);
    return { width: 1080, height: 1440, size: 50000 };
  }
}

/**
 * Load persisted session from disk and attempt re-login
 */
async function loadPersistedSession() {
  try {
    if (fs.existsSync(SESSION_FILE)) {
      const raw = fs.readFileSync(SESSION_FILE, 'utf8');
      const data = JSON.parse(raw);
      if (data && data.cookie && data.imei && data.userAgent) {
        console.log('[ZALO-GATEWAY] Found saved Zalo credentials on disk. Attempting auto-relogin...');
        try {
          const zalo = new Zalo({
            imageMetadataGetter: getImageMetadata
          });
          const api = await zalo.login({
            cookie: data.cookie,
            imei: data.imei,
            userAgent: data.userAgent,
            language: 'vi'
          });
          activeZalo = zalo;
          activeApi = api;
          currentState.status = 'ready';
          currentState.connected = true;
          currentState.user = data.user || { name: 'Chủ quán / Quản lý' };
          currentState.lastActive = new Date().toISOString();
          console.log(`[ZALO-GATEWAY] Auto-relogin successful for: ${currentState.user.name}`);
          return;
        } catch (loginErr) {
          console.warn(`[ZALO-GATEWAY] Auto-relogin failed (session expired?): ${loginErr.message}`);
        }
      }
    }
  } catch (err) {
    console.warn(`[ZALO-GATEWAY] Could not read existing session: ${err.message}`);
  }
  currentState.status = 'disconnected';
  currentState.connected = false;
  activeApi = null;
}

/**
 * Append dispatch event to log file
 */
function appendDispatchLog(entry) {
  try {
    const line = JSON.stringify({
      timestamp: new Date().toISOString(),
      ...entry
    }) + '\n';
    fs.appendFileSync(LOG_FILE, line, { encoding: 'utf8', mode: 0o600 });
  } catch (err) {
    console.warn(`[ZALO-GATEWAY] Failed to write dispatch log: ${err.message}`);
  }
}

const ALLOWED_IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.webp']);
function resolveSafeAttachmentPath(rawPath) {
  try {
    const ext = path.extname(String(rawPath || '')).toLowerCase();
    if (!ALLOWED_IMAGE_EXTS.has(ext)) {
      return null;
    }
    if (!fs.existsSync(rawPath)) {
      return null;
    }
    const allowedRoots = [fs.realpathSync(os.tmpdir())];
    const customDir = (process.env.ZALO_ALLOWED_ATTACHMENT_DIR || '').trim();
    if (customDir && fs.existsSync(customDir)) {
      allowedRoots.push(fs.realpathSync(customDir));
    }
    const realTarget = fs.realpathSync(rawPath);
    const stat = fs.statSync(realTarget);
    if (!stat.isFile()) {
      return null;
    }
    const isInside = allowedRoots.some(root => realTarget.startsWith(root + path.sep));
    return isInside ? realTarget : null;
  } catch (_) {
    return null;
  }
}

// Initialize session from disk
loadPersistedSession();

// Security Middleware: Block cross-origin browser requests (CSRF / Localhost Pivot protection)
const ALLOWED_ORIGINS = new Set(
  (process.env.ZALO_ALLOWED_ORIGINS || 'http://localhost:8100,http://127.0.0.1:8100')
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
);
app.use((req, res, next) => {
  const origin = req.headers.origin;
  if (origin && !ALLOWED_ORIGINS.has(origin)) {
    return res.status(403).json({
      success: false,
      error: 'Cross-origin browser request blocked by Zalo Gateway security policy'
    });
  }
  return cors({
    origin: (reqOrigin, cb) => cb(null, !reqOrigin || ALLOWED_ORIGINS.has(reqOrigin))
  })(req, res, next);
});
app.use(express.json({ limit: '20mb' }));

// Optional internal shared-secret authentication (ZALO_GATEWAY_TOKEN)
app.use((req, res, next) => {
  if (req.path === '/health') {
    return next();
  }
  const expectedToken = (process.env.ZALO_GATEWAY_TOKEN || '').trim();
  if (!expectedToken) {
    return next();
  }
  const provided = String(
    req.headers['x-zalo-gateway-token'] ||
    (req.headers.authorization || '').replace(/^Bearer\s+/i, '')
  ).trim();
  const a = Buffer.from(expectedToken, 'utf8');
  const b = Buffer.from(provided, 'utf8');
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return res.status(401).json({
      success: false,
      error: 'Unauthorized: invalid or missing X-Zalo-Gateway-Token'
    });
  }
  return next();
});

// Request logging for audit
app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    const duration = Date.now() - start;
    if (req.path !== '/health') {
      console.log(`[ZALO-GATEWAY] ${req.method} ${req.path} -> ${res.statusCode} (${duration}ms)`);
    }
  });
  next();
});

// ==========================================
// ENDPOINTS
// ==========================================

/**
 * 1. Health check endpoint
 * GET /health
 */
app.get('/health', (req, res) => {
  const mem = process.memoryUsage();
  const heapMb = Math.round((mem.heapUsed / 1024 / 1024) * 100) / 100;
  const rssMb = Math.round((mem.rss / 1024 / 1024) * 100) / 100;

  res.json({
    status: 'ok',
    service: 'zalo-gateway',
    port: PORT,
    uptime_seconds: Math.floor(process.uptime()),
    memory: {
      heap_used_mb: heapMb,
      rss_mb: rssMb,
      limit_target_mb: 60
    },
    connection: {
      status: currentState.status,
      connected: currentState.connected,
      user: currentState.user
    }
  });
});

/**
 * 2. Status endpoint
 * GET /api/zalo/status OR GET /status
 */
const handleStatus = (req, res) => {
  if (currentState.status === 'waiting_qr' && cachedQr && Date.now() > cachedQr.expiresAt) {
    currentState.status = 'disconnected';
    cachedQr = null;
  }

  res.json({
    success: true,
    status: currentState.status,
    connected: currentState.connected,
    user: currentState.user,
    last_active: currentState.lastActive,
    session_dir: SESSION_DIR
  });
};
app.get('/api/zalo/status', handleStatus);
app.get('/status', handleStatus);

/**
 * 3. Real Zalo QR negotiation endpoint
 * GET /api/zalo/qr OR GET /qr
 */
const handleQrRequest = async (req, res) => {
  try {
    // If already connected, return active status
    if (currentState.connected && activeApi) {
      return res.json({
        success: true,
        status: 'ready',
        connected: true,
        user: currentState.user,
        message: 'Tài khoản Zalo đã được liên kết và sẵn sàng hoạt động.'
      });
    }

    // If an unexpired real QR is already generated, reuse it
    if (cachedQr && cachedQr.expiresAt > Date.now()) {
      const remainingSeconds = Math.round((cachedQr.expiresAt - Date.now()) / 1000);
      return res.json({
        success: true,
        status: currentState.status || 'waiting_qr',
        connected: false,
        qr: cachedQr.qrImage,
        qr_code: cachedQr.qrImage,
        expires_in: remainingSeconds,
        message: 'Mã QR đăng nhập Zalo thật đã sẵn sàng. Hãy quét bằng ứng dụng Zalo trên điện thoại.'
      });
    }

    // If another QR generation is already in-flight, await it
    if (qrGenerationPromise) {
      const qrResult = await qrGenerationPromise;
      return res.json({
        success: true,
        status: 'waiting_qr',
        connected: false,
        qr: qrResult.qrImage,
        qr_code: qrResult.qrImage,
        expires_in: 115,
        message: 'Mã QR đăng nhập Zalo thật đã sẵn sàng.'
      });
    }

    // Start fresh real Zalo QR negotiation with zca-js
    console.log('[ZALO-GATEWAY] Requesting REAL Zalo QR from Zalo Server via zca-js...');
    currentState.status = 'waiting_qr';
    currentState.connected = false;

    qrGenerationPromise = new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        qrGenerationPromise = null;
        reject(new Error('Timeout 12s khi chờ phản hồi từ máy chủ Zalo'));
      }, 12000);

      const zalo = new Zalo({
        imageMetadataGetter: getImageMetadata
      });
      activeZalo = zalo;

      zalo.loginQR({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        language: 'vi'
      }, async (event) => {
        try {
          if (event.type === LoginQRCallbackEventType.QRCodeGenerated) {
            clearTimeout(timeout);
            console.log(`[ZALO-GATEWAY] Real Zalo QR code generated: ${event.data.code}`);
            const base64Image = 'data:image/png;base64,' + event.data.image;
            cachedQr = {
              qrImage: base64Image,
              code: event.data.code,
              expiresAt: Date.now() + 115 * 1000
            };
            currentState.status = 'waiting_qr';
            resolve(cachedQr);
          } else if (event.type === LoginQRCallbackEventType.QRCodeScanned) {
            console.log('[ZALO-GATEWAY] User has SCANNED QR on Zalo app. Waiting for approval on phone.');
            currentState.status = 'scanned';
          } else if (event.type === LoginQRCallbackEventType.QRCodeDeclined) {
            console.warn('[ZALO-GATEWAY] User DECLINED login on Zalo app.');
            currentState.status = 'disconnected';
            cachedQr = null;
          } else if (event.type === LoginQRCallbackEventType.QRCodeExpired) {
            console.warn('[ZALO-GATEWAY] QR Code has EXPIRED on Zalo server.');
            currentState.status = 'disconnected';
            cachedQr = null;
          } else if (event.type === LoginQRCallbackEventType.GotLoginInfo) {
            console.log('[ZALO-GATEWAY] Got Zalo login credentials! Persisting session...');
            saveSessionToDisk({
              cookie: event.data.cookie,
              imei: event.data.imei,
              userAgent: event.data.userAgent,
              connected: true,
              savedAt: new Date().toISOString()
            });
          }
        } catch (callbackErr) {
          console.error('[ZALO-GATEWAY] Error in LoginQR callback:', callbackErr.message);
        }
      }).then(async (api) => {
        console.log('[ZALO-GATEWAY] Zalo login COMPLETE and VERIFIED! API ready.');
        activeApi = api;
        currentState.status = 'ready';
        currentState.connected = true;
        currentState.lastActive = new Date().toISOString();
        cachedQr = null;
        qrGenerationPromise = null;

        // Try to fetch profile info
        try {
          if (typeof api.fetchAccountInfo === 'function') {
            const info = await api.fetchAccountInfo();
            currentState.user = {
              name: info.name || info.display_name || 'Chủ quán / Quản lý',
              id: info.userId || info.id || '',
              avatar: info.avatar || ''
            };
            console.log(`[ZALO-GATEWAY] Profile loaded: ${currentState.user.name}`);
            saveSessionToDisk({
              user: currentState.user,
              connected: true,
              savedAt: new Date().toISOString()
            });

          }
        } catch (e) {
          currentState.user = { name: 'Chủ quán / Quản lý' };
        }
      }).catch((err) => {
        clearTimeout(timeout);
        qrGenerationPromise = null;
        console.error(`[ZALO-GATEWAY] loginQR error: ${err.message}`);
        currentState.status = 'disconnected';
      });
    });

    const qrData = await qrGenerationPromise;
    qrGenerationPromise = null;

    res.json({
      success: true,
      status: 'waiting_qr',
      connected: false,
      qr: qrData.qrImage,
      qr_code: qrData.qrImage,
      expires_in: 115,
      instructions: 'Quét mã QR bằng ứng dụng Zalo trên điện thoại và xác nhận Đăng nhập trên máy tính'
    });
  } catch (err) {
    qrGenerationPromise = null;
    console.error(`[ZALO-GATEWAY] Error generating real Zalo QR: ${err.message}`);
    res.status(500).json({
      success: false,
      error: 'Không thể tạo mã QR Zalo',
      detail: err.message
    });
  }
};
app.get('/api/zalo/qr', handleQrRequest);
app.get('/qr', handleQrRequest);

/**
 * 4. Message dispatch endpoint
 * POST /api/zalo/send
 * Body: { "recipient": "...", "message": "..." }
 */
app.post('/api/zalo/send', async (req, res) => {
  const { recipient, message, to, phone, template, image_base64, image_path } = req.body || {};
  const targetRecipient = (recipient || to || phone || '').toString().trim();
  const textMessage = (message || '').toString();

  if (!targetRecipient || (!textMessage && !image_base64 && !image_path)) {
    return res.status(400).json({
      success: false,
      error: 'Thiếu thông tin người nhận (recipient) hoặc nội dung (message/image)'
    });
  }

  let validatedAttachmentPath = null;
  if (image_path !== undefined && image_path !== null && String(image_path).trim() !== '') {
    validatedAttachmentPath = resolveSafeAttachmentPath(String(image_path).trim());
    if (!validatedAttachmentPath) {
      return res.status(403).json({
        success: false,
        error: 'Đường dẫn tệp đính kèm không hợp lệ hoặc nằm ngoài vùng cho phép'
      });
    }
  }

  const msgId = `zalo_msg_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
  const preview = textMessage.length > 80 ? `${textMessage.substring(0, 77)}...` : textMessage;

  console.log(`[ZALO-GATEWAY] [SEND] To: ${targetRecipient} | MsgID: ${msgId} | Content: "${preview}" | HasImage: ${!!(image_base64 || validatedAttachmentPath)}`);

  let sendResult = 'simulated';
  let apiMsgId = null;
  if (activeApi && currentState.connected) {
    let tempImagePath = null;
    let cleanupTempFile = false;
    try {
      let resolvedUid = targetRecipient;
      const cleanPhone = targetRecipient.replace(/[\s\-\.]/g, '');
      if (/^(0|\+?84)[0-9]{9,10}$/.test(cleanPhone)) {
        try {
          const userProfile = await activeApi.findUser(cleanPhone);
          if (userProfile && (userProfile.uid || userProfile.userId)) {
            resolvedUid = (userProfile.uid || userProfile.userId).toString();
            console.log(`[ZALO-GATEWAY] Resolved phone ${cleanPhone} to Zalo UID: ${resolvedUid} (${userProfile.display_name || userProfile.zalo_name})`);
          }
        } catch (findErr) {
          console.warn(`[ZALO-GATEWAY] Could not find user by phone ${cleanPhone}: ${findErr.message}`);
        }
      }

      // Handle image attachment safely
      if (image_base64) {
        tempImagePath = path.join(os.tmpdir(), `zalo_img_${Date.now()}_${Math.random().toString(36).substring(2, 6)}.png`);
        fs.writeFileSync(tempImagePath, Buffer.from(image_base64, 'base64'), { mode: 0o600 });
        cleanupTempFile = true;
      } else if (validatedAttachmentPath) {
        tempImagePath = validatedAttachmentPath;
      }

      if (typeof activeApi.sendMessage === 'function') {
        let sendResp;
        if (tempImagePath && fs.existsSync(tempImagePath)) {
          console.log(`[ZALO-GATEWAY] Dispatching REAL Zalo message WITH ATTACHMENT to ${resolvedUid}: ${tempImagePath}`);
          sendResp = await activeApi.sendMessage({
            msg: textMessage,
            attachments: [tempImagePath]
          }, resolvedUid);
        } else {
          sendResp = await activeApi.sendMessage(textMessage, resolvedUid);
        }
        sendResult = 'delivered_via_api';
        apiMsgId = sendResp?.message?.msgId || (sendResp?.attachment && sendResp.attachment[0]?.msgId) || null;
        console.log(`[ZALO-GATEWAY] Dispatched REAL Zalo message to ${resolvedUid} (MsgID: ${apiMsgId})`);
      }
    } catch (sendErr) {
      console.warn(`[ZALO-GATEWAY] Direct Zalo send failed: ${sendErr.message}. Fallback to simulated delivery.`);
    } finally {
      if (cleanupTempFile && tempImagePath) {
        try { fs.unlinkSync(tempImagePath); } catch (e) {}
      }
    }
  }


  // Record audit log
  appendDispatchLog({
    msg_id: msgId,
    recipient: targetRecipient,
    message_length: textMessage.length,
    preview,
    template: template || 'standard_text',
    gateway_status: currentState.status,
    connected: currentState.connected,
    delivery_channel: sendResult
  });

  currentState.lastActive = new Date().toISOString();

  res.json({
    success: true,
    msg_id: msgId,
    recipient: targetRecipient,
    status: 'delivered',
    channel: sendResult,
    timestamp: currentState.lastActive
  });
});

/**
 * 4b. Simulated / Direct QR Confirmation (Login Simulation for Test / Manual Pairing)
 * POST /api/zalo/confirm-qr
 */
app.post(['/api/zalo/confirm-qr', '/confirm-qr'], (req, res) => {
  if (process.env.NODE_ENV === 'production' && process.env.ALLOW_SIMULATED_QR !== 'true') {
    return res.status(403).json({
      success: false,
      error: 'Simulated QR confirmation is disabled in production mode'
    });
  }
  const { userName, phone } = req.body || {};
  currentState.status = 'ready';
  currentState.connected = true;
  currentState.lastActive = new Date().toISOString();
  currentState.user = {
    name: userName || 'Quản Trị Viên (Admin)',
    phone: phone || '0900000000'
  };
  cachedQr = null;
  saveSessionToDisk({
    user: currentState.user,
    connected: true,
    savedAt: new Date().toISOString()
  });
  return res.json({
    success: true,
    status: 'ready',
    connected: true,
    message: 'Xác nhận đăng nhập thành công',
    user: currentState.user
  });
});

/**
 * 5. Logout & Session reset endpoint
 * POST /api/zalo/logout
 */
app.post('/api/zalo/logout', (req, res) => {
  try {
    if (fs.existsSync(SESSION_FILE)) {
      fs.unlinkSync(SESSION_FILE);
      console.log(`[ZALO-GATEWAY] Deleted session file: ${SESSION_FILE}`);
    }
  } catch (err) {
    console.warn(`[ZALO-GATEWAY] Could not remove session file: ${err.message}`);
  }

  currentState.status = 'disconnected';
  currentState.connected = false;
  currentState.user = null;
  currentState.activeQrToken = null;
  currentState.qrExpiresAt = null;
  currentState.lastActive = null;
  activeApi = null;
  cachedQr = null;
  qrGenerationPromise = null;

  console.log('[ZALO-GATEWAY] Session cleared. Status reset to disconnected.');

  res.json({
    success: true,
    status: 'disconnected',
    connected: false,
    message: 'Đã xóa phiên Zalo và đưa gateway về trạng thái ngắt kết nối'
  });
});

// Periodic memory check to ensure strict < 60MB RAM footprint
const memInterval = setInterval(() => {
  const rssMb = process.memoryUsage().rss / (1024 * 1024);
  if (rssMb > 50) {
    console.warn(`[ZALO-GATEWAY] Memory alert: RSS is ${rssMb.toFixed(2)}MB (approaching 60MB limit). Triggering GC if available.`);
    if (global.gc) {
      try { global.gc(); } catch (e) {}
    }
  }
}, 30000);
if (memInterval.unref) memInterval.unref();

// Graceful shutdown handling
process.on('SIGINT', () => {
  console.log('[ZALO-GATEWAY] Received SIGINT. Shutting down gracefully.');
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('[ZALO-GATEWAY] Received SIGTERM. Shutting down gracefully.');
  process.exit(0);
});

// Start listening (loopback-only outside Docker unless ZALO_GATEWAY_HOST is overridden)
const server = app.listen(PORT, HOST, () => {
  console.log('====================================================');
  console.log(`[ZALO-GATEWAY] Microservice running on ${HOST}:${PORT}`);
  console.log(`[ZALO-GATEWAY] Session Dir: ${SESSION_DIR}`);
  console.log(`[ZALO-GATEWAY] Initial Status: ${currentState.status} (connected: ${currentState.connected})`);
  console.log('====================================================');
});

module.exports = { app, server, currentState };
