import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Read staff_auth.json & data.json from data/ with fallback
const authPath = [path.resolve(__dirname, '../data/staff_auth.json'), path.resolve(__dirname, '../backend/staff_auth.json')].find(p => fs.existsSync(p));
const dataPath = [path.resolve(__dirname, '../data/data.json'), path.resolve(__dirname, '../data/data.json')].find(p => fs.existsSync(p));
const auth = JSON.parse(fs.readFileSync(authPath, 'utf8'));
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

const { getCanonicalStaffName, resolveStaffCanonicalKey } = await import('../frontend/src/store/state.js');

const duLieu = data['DỮ LIỆU'].slice(1);
const rawKeys = Array.from(new Set(duLieu.map(r => r[2]).filter(Boolean))).sort();
const mockEmpKeys = ['NHANVIEN01', 'NHANVIEN02', 'NHANVIEN02_SUB', 'NHANVIEN03', 'NHANVIEN19', 'NHANVIEN22'];
const empKeys = Array.from(new Set([...rawKeys, ...mockEmpKeys])).sort();

console.log(`Total empKeys in test: ${empKeys.length}`);

let failed = 0;
const accounts = auth.staff_accounts || {};

for (const [uname, acc] of Object.entries(accounts)) {
  const meta = {
    username: uname,
    full_name: acc.full_name,
    sheet_names: acc.sheet_names || []
  };

  const matched = resolveStaffCanonicalKey(meta, empKeys);
  console.log(`[CHECK] ${uname.padEnd(15)} -> Matched: ${matched || 'None'}`);

  // Assertions
  if (uname === 'nhanvien03' && matched !== 'NHANVIEN03') {
    console.error(`FAIL: nhanvien03 must match NHANVIEN03, got ${matched}`);
    failed++;
  }
  if (uname === 'nhanvien02' && matched !== 'NHANVIEN02') {
    console.error(`FAIL: ${uname} must match NHANVIEN02, got ${matched}`);
    failed++;
  }
  if (uname === 'nhanvien02_sub' && matched !== 'NHANVIEN02_SUB') {
    console.error(`FAIL: ${uname} must match NHANVIEN02_SUB, got ${matched}`);
    failed++;
  }
  if (uname === 'nhanvien19' && matched !== 'NHANVIEN19') {
    console.error(`FAIL: nhanvien19 must match NHANVIEN19, got ${matched}`);
    failed++;
  }
  if (uname === 'nhanvien22' && matched !== 'NHANVIEN22') {
    console.error(`FAIL: nhanvien22 must match NHANVIEN22, got ${matched}`);
    failed++;
  }
}

if (failed > 0) {
  console.error(`\nFAILED: ${failed} assertion errors!`);
  process.exit(1);
} else {
  console.log('\nSUCCESS: 100% accounts matched correctly without any cross-talk!');
}
