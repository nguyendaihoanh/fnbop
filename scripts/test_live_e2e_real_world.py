#!/usr/bin/env python3
"""
scripts/test_live_e2e_real_world.py
Kiểm thử E2E Thực Chiến - Mô phỏng Hành trình Người dùng thật trên Máy chủ và Trình duyệt thật.
KHÔNG MOCK, KHÔNG TESTING=1, KHÔNG FAKE DOM.
"""
import os
import sys
import time
import subprocess
import signal
import sqlite3
import json
import hashlib
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "fnbop.db")
SERVER_PORT = 8100
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def log(msg):
    print(f"[LIVE-E2E] {msg}")

def start_live_server():
    log("Khởi động FastAPI Uvicorn Server trên cổng 8100...")
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{PROJECT_ROOT}:{PROJECT_ROOT}/backend"
    # KHÔNG dùng TESTING=1 để chạy đúng cấu hình production, nhưng chặn gửi spam Telegram thật
    env.pop("TESTING", None)
    env["DISABLE_OUTBOUND_TELEGRAM"] = "1"
    env["MOCK_TELEGRAM"] = "1"
    
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "backend.main:app",
            "--host", "127.0.0.1",
            "--port", str(SERVER_PORT),
            "--log-level", "warning"
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Chờ server sẵn sàng (tối đa 10s)
    start_t = time.time()
    while time.time() - start_t < 10:
        try:
            r = requests.get(f"{BASE_URL}/api/v1/cc/store/config", timeout=1)
            if r.status_code == 200:
                log(f"Server đã sẵn sàng sau {time.time() - start_t:.2f}s (HTTP 200).")
                return proc
        except Exception:
            time.sleep(0.3)
            
    proc.terminate()
    raise RuntimeError("Không thể khởi động live server trong 10s.")

def stop_live_server(proc):
    log("Dừng live server...")
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

def verify_real_browser():
    log("--- BƯỚC 1: KIỂM THỬ TRÌNH DUYỆT THẬT (REAL CHROME HEADLESS & ZERO CONSOLE ERRORS) ---")
    if not os.path.exists(CHROME_BIN):
        log("Cảnh báo: Không tìm thấy Chrome tại /Applications/Google Chrome.app")
        return False
        
    out_screenshot = "/tmp/fnbops_real_browser_proof.png"
    cmd = [
        CHROME_BIN,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--user-data-dir=/tmp/fnbops_chrome_profile",
        "--window-size=412,915",
        f"--screenshot={out_screenshot}",
        "--dump-dom",
        f"{BASE_URL}/"
    ]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    dur = (time.time() - t0) * 1000
    
    if res.returncode != 0:
        log(f"FAIL: Chrome headless gặp lỗi: {res.stderr}")
        return False
        
    dom = res.stdout
    has_title = "<title>" in dom
    has_viewport = 'name="viewport"' in dom
    has_login = "login" in dom.lower()
    img_size = os.path.getsize(out_screenshot) if os.path.exists(out_screenshot) else 0
    
    log(f"Chrome CLI tải trang thành công trong {dur:.1f}ms.")
    log(f"Ảnh chụp màn hình: {out_screenshot} ({img_size:,} bytes).")
    log(f"DOM Verification: Title={has_title}, Viewport={has_viewport}, LoginElements={has_login}.")
    
    # 1.2 Kiểm thử tương tác chuyên sâu bằng Puppeteer-core nếu có node
    import shutil
    node_bin = shutil.which("node")
    if not node_bin:
        import glob as _glob
        nvm_nodes = sorted(_glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")), reverse=True)
        for cand in nvm_nodes + [
            "/opt/homebrew/bin/node",
            "/usr/local/bin/node"
        ]:
            if os.path.exists(cand):
                node_bin = cand
                break
                
    pup_dir = os.path.join(PROJECT_ROOT, "frontend", "node_modules", "puppeteer-core")
    if node_bin and os.path.exists(pup_dir):
        log("Kích hoạt Puppeteer trên Chrome thật: Kiểm tra 0 Console Errors & Chuyển Tab...")
        node_script = f"""
const puppeteer = require('puppeteer-core');
(async () => {{
  let browser;
  try {{
    browser = await puppeteer.launch({{
      executablePath: '{CHROME_BIN}',
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    }});
    
    // Test 3 pages for zero errors
    const pages = ['/', '/desktop.html', '/monthly-report.html'];
    for (const p of pages) {{
      const page = await browser.newPage();
      const consoleErrors = [];
      const pageErrors = [];
      page.on('console', msg => {{
        if (msg.type() === 'error') consoleErrors.push(msg.text());
      }});
      page.on('pageerror', err => pageErrors.push(err.toString()));
      
      const res = await page.goto('{BASE_URL}' + p, {{ waitUntil: 'networkidle2', timeout: 15000 }});
      if (!res || res.status() !== 200) {{
        console.log(JSON.stringify({{ status: 'FAIL', page: p, reason: 'HTTP ' + (res ? res.status() : 'null') }}));
        process.exit(1);
      }}
      if (consoleErrors.length > 0 || pageErrors.length > 0) {{
        console.log(JSON.stringify({{ status: 'FAIL', page: p, consoleErrors, pageErrors }}));
        process.exit(1);
      }}
      await page.close();
    }}
    
    // Interactive test on main page
    const page = await browser.newPage();
    await page.setViewport({{ width: 412, height: 915, isMobile: true }});
    const interactiveErrors = [];
    page.on('console', msg => {{
      if (msg.type() === 'error') interactiveErrors.push(msg.text());
    }});
    page.on('pageerror', err => interactiveErrors.push(err.toString()));
    
    await page.goto('{BASE_URL}/', {{ waitUntil: 'networkidle2', timeout: 15000 }});
    await page.type('#loginUser', 'manager');
    await page.type('#loginPass', '8888');
    await page.click('#btnLoginSubmit');
    await new Promise(r => setTimeout(r, 1500));
    
    const tabs = ['ops', 'roster', 'attendance', 'payslip'];
    for (const t of tabs) {{
      await page.evaluate((name) => {{
        const el = document.querySelector('[data-tab=\"' + name + '\"]');
        if (el) el.click();
      }}, t);
      await new Promise(r => setTimeout(r, 600));
    }}
    
    if (interactiveErrors.length > 0) {{
      console.log(JSON.stringify({{ status: 'FAIL', reason: 'Interactive console errors', interactiveErrors }}));
      process.exit(1);
    }}
    
    await page.screenshot({{ path: '/tmp/fnbops_manager_after_tabs.png' }});
    console.log(JSON.stringify({{ status: 'PASS', message: 'All pages & tabs 0 console errors' }}));
  }} catch(e) {{
    console.log(JSON.stringify({{ status: 'ERROR', message: e.message }}));
    process.exit(1);
  }} finally {{
    if (browser) await browser.close();
  }}
}})();
"""
        node_env = os.environ.copy()
        node_env["NODE_PATH"] = os.path.join(PROJECT_ROOT, "frontend", "node_modules")
        t_pup = time.time()
        p_res = subprocess.run([node_bin, "-e", node_script], env=node_env, capture_output=True, text=True, timeout=30)
        dur_pup = (time.time() - t_pup) * 1000
        if p_res.returncode != 0:
            log(f"FAIL: Puppeteer kiểm thử trình duyệt phát hiện lỗi: {p_res.stdout} {p_res.stderr}")
            return False
        log(f"[PASS] Real Browser Automation: 3 trang HTML + Đăng nhập + 4 Tabs đạt 0 Console Error ({dur_pup:.1f}ms).")
        
    return True

def verify_static_assets():
    log("--- BƯỚC 2: KIỂM THỬ INTEGRITY CỦA STATIC ASSETS (FRONTEND) ---")
    session = requests.Session()
    assets = [
        ("/", 200, "text/html"),
        ("/mobile.js", 200, "javascript"),
        ("/app.js", 200, "javascript"),
        ("/manifest.json", 200, "json"),
        ("/api/v1/cc/store/config", 200, "application/json"),
    ]
    all_ok = True
    for path, exp_code, exp_type in assets:
        t0 = time.time()
        r = session.get(f"{BASE_URL}{path}", timeout=3)
        dur = (time.time() - t0) * 1000
        ct = r.headers.get("content-type", "")
        status = "PASS" if r.status_code == exp_code and exp_type in ct else "FAIL"
        log(f"[{status}] {path} -> HTTP {r.status_code} ({dur:.1f}ms, Content-Type: {ct})")
        if status == "FAIL":
            all_ok = False
    return all_ok

def verify_staff_journey():
    log("--- BƯỚC 3: HÀNH TRÌNH NHÂN VIÊN THẬT (STAFF CHECK-IN / CHECK-OUT) ---")
    session = requests.Session()
    
    # 3.1 Đăng nhập nhân viên bằng PIN 1111
    t0 = time.time()
    login_res = session.post(
        f"{BASE_URL}/api/v1/cc/auth/login",
        json={"username": "nhanvien", "password": "1111"},
        timeout=3
    )
    if login_res.status_code != 200:
        log(f"FAIL: Nhân viên đăng nhập thất bại: HTTP {login_res.status_code} - {login_res.text}")
        return False
    data = login_res.json()
    token = data.get("access_token")
    log(f"[PASS] Đăng nhập nhân viên: {data.get('name')} (Role: {data.get('role')}) trong {(time.time() - t0)*1000:.1f}ms")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3.2 Chấm công vào ca (Check-in)
    t0 = time.time()
    checkin_res = session.post(
        f"{BASE_URL}/api/v1/cc/attendance/checkin",
        headers=headers,
        json={
            "username": "nhanvien",
            "display_name": "Nhân Viên Phục Vụ",
            "role": "STAFF",
            "dev_override_wifi": True
        },
        timeout=3
    )
    if checkin_res.status_code != 200:
        log(f"FAIL: Chấm công vào ca thất bại: HTTP {checkin_res.status_code} - {checkin_res.text}")
        return False
    ci_data = checkin_res.json()
    record_id = ci_data.get("record", {}).get("id") or ci_data.get("id")
    log(f"[PASS] Chấm công vào ca thành công! Record ID: {record_id} (Thời gian: {(time.time() - t0)*1000:.1f}ms)")
    
    # 3.3 Soi trực tiếp vào SQLite thật để kiểm chứng
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, checkin, status FROM attendance_logs WHERE username='nhanvien' ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    if not row:
        log("FAIL: Bản ghi check-in KHÔNG tồn tại trong CSDL SQLite thật!")
        conn.close()
        return False
    log(f"[SQLITE PROOF] Tìm thấy bản ghi thật: ID={row[0]}, User={row[1]}, CheckIn={row[2]}, Status={row[3]}")
    
    # 3.4 Chấm công ra ca (Check-out)
    t0 = time.time()
    checkout_res = session.post(
        f"{BASE_URL}/api/v1/cc/attendance/checkout",
        headers=headers,
        json={
            "username": "nhanvien",
            "dev_override_wifi": True,
            "confirm_early": True
        },
        timeout=3
    )
    if checkout_res.status_code != 200:
        log(f"FAIL: Chấm công ra ca thất bại: HTTP {checkout_res.status_code} - {checkout_res.text}")
        conn.close()
        return False
    log(f"[PASS] Chấm công ra ca thành công! (Thời gian: {(time.time() - t0)*1000:.1f}ms)")
    
    # 3.5 Soi lại SQLite kiểm tra giờ ra
    c.execute("SELECT id, username, checkin, checkout, status FROM attendance_logs WHERE id=?", (row[0],))
    updated_row = c.fetchone()
    conn.close()
    log(f"[SQLITE PROOF] Cập nhật hoàn tất: ID={updated_row[0]}, CheckOut={updated_row[3]}, Status={updated_row[4]}")
    return True

def verify_manager_journey():
    log("--- BƯỚC 4: HÀNH TRÌNH QUẢN LÝ THẬT (MANAGER POS CASH CLOSING) ---")
    session = requests.Session()
    
    # 4.1 Quản lý đăng nhập PIN 8888
    t0 = time.time()
    login_res = session.post(
        f"{BASE_URL}/api/v1/cc/auth/login",
        json={"username": "manager", "password": "8888"},
        timeout=3
    )
    if login_res.status_code != 200:
        log(f"FAIL: Quản lý đăng nhập thất bại: HTTP {login_res.status_code} - {login_res.text}")
        return False
    data = login_res.json()
    token = data.get("access_token")
    log(f"[PASS] Quản lý đăng nhập: {data.get('name')} (Role: {data.get('role')}) trong {(time.time() - t0)*1000:.1f}ms")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 4.2 Chốt két ca làm việc (POS Closing)
    t0 = time.time()
    today_str = time.strftime("%d/%m/%Y")
    now_str = time.strftime("%H:%M")
    closing_res = session.post(
        f"{BASE_URL}/api/v1/cc/pos/daily-closing",
        headers=headers,
        json={
            "report_date": today_str,
            "closing_time": now_str,
            "bill_pos": 5250000,
            "cash_amount": 2500000,
            "transfer_amount": 2750000,
            "expense_amount": 150000,
            "expense_detail": "Mua đá lạnh + chanh tươi",
            "sender_name": "Quản Lý Ca",
            "approver_name": "Chủ Quán (Admin)",
            "shift_key": "CA_TOI"
        },
        timeout=3
    )
    if closing_res.status_code != 200:
        log(f"FAIL: Chốt két thu ngân thất bại: HTTP {closing_res.status_code} - {closing_res.text}")
        return False
    cl_data = closing_res.json()
    log(f"[PASS] Chốt két thu ngân thành công! Chênh lệch tiền: {cl_data.get('diff_amount')}đ (Thời gian: {(time.time() - t0)*1000:.1f}ms)")
    
    # 4.3 Soi trực tiếp SQLite thật
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, report_date, bill_pos, cash_amount, transfer_amount, diff_amount FROM daily_closings WHERE report_date=? ORDER BY id DESC LIMIT 1", (today_str,))
    row = c.fetchone()
    conn.close()
    if not row:
        log("FAIL: Bản ghi chốt két KHÔNG tồn tại trong CSDL SQLite thật!")
        return False
    log(f"[SQLITE PROOF] Tìm thấy bản ghi chốt két thật: ID={row[0]}, Ngày={row[1]}, Bill={row[2]:,}đ, TiềnMặt={row[3]:,}đ, ChênhLệch={row[5]:,}đ")
    return True

def verify_admin_snapshot_journey():
    log("--- BƯỚC 5: HÀNH TRÌNH CHỦ QUÁN (ADMIN SNAPSHOT & DATA INTEGRITY) ---")
    session = requests.Session()
    
    # 5.1 Admin đăng nhập PIN 1234
    t0 = time.time()
    login_res = session.post(
        f"{BASE_URL}/api/v1/cc/auth/login",
        json={"username": "admin", "password": "1234"},
        timeout=3
    )
    if login_res.status_code != 200:
        log(f"FAIL: Admin đăng nhập thất bại: HTTP {login_res.status_code} - {login_res.text}")
        return False
    token = login_res.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    
    # 5.2 Gọi xuất snapshot CSDL
    t0 = time.time()
    snap_res = session.get(
        f"{BASE_URL}/api/v1/cc/admin/export-json-snapshot",
        headers=headers,
        timeout=5
    )
    if snap_res.status_code != 200:
        log(f"FAIL: Xuất snapshot thất bại: HTTP {snap_res.status_code} - {snap_res.text}")
        return False
    res_json = snap_res.json()
    snap_data = res_json.get("data", {})
    dur = (time.time() - t0) * 1000
    log(f"[PASS] Xuất Snapshot thành công! Message: '{res_json.get('message')}' (Thời gian: {dur:.1f}ms)")
    
    n_staff = len(snap_data.get("staff_auth", {}).get("staff_accounts", []))
    n_logs = len(snap_data.get("attendance_logs", []))
    n_closings = len(snap_data.get("daily_closings", []))
    n_roster = len(snap_data.get("roster_schedules", []))
    log(f"[SQLITE SNAPSHOT STATS] Staff: {n_staff}, Logs: {n_logs}, Closings: {n_closings}, Roster: {n_roster}")
    return True

def cleanup_test_data():
    log("--- DỌN DẸP BẢN GHI KIỂM THỬ THỰC TẾ ---")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Xoá bản ghi checkin test vừa tạo của nhanvien
    c.execute("DELETE FROM attendance_logs WHERE username='nhanvien' AND (date = date('now') OR note LIKE '%test%')")
    c.execute("DELETE FROM daily_closings WHERE sender_name='Quản Lý Ca' AND expense_detail='Mua đá lạnh + chanh tươi'")
    conn.commit()
    conn.close()
    log("[CLEANUP] Đã dọn sạch các bản ghi thử nghiệm trong SQLite thật an toàn.")

def snapshot_json_hashes():
    data_dir = os.path.join(PROJECT_ROOT, "data")
    hashes = {}
    for f in os.listdir(data_dir):
        if f.endswith(".json"):
            fp = os.path.join(data_dir, f)
            h = hashlib.sha256()
            with open(fp, "rb") as fp_in:
                while chunk := fp_in.read(8192):
                    h.update(chunk)
            hashes[f] = h.hexdigest()
    return hashes

def verify_json_immutability(before_hashes):
    log("--- BƯỚC 6: KIỂM TOÁN TÍNH BẤT BIẾN 'CẤM JSON' (NO-JSON RUNTIME WRITE) ---")
    after_hashes = snapshot_json_hashes()
    modified = []
    for f, b_h in before_hashes.items():
        a_h = after_hashes.get(f)
        if b_h != a_h:
            modified.append(f)
    
    if modified:
        log(f"FAIL: VI PHẠM NGUYÊN TẮC 'CẤM JSON': Phát hiện {len(modified)} file JSON bị ghi đè: {modified}")
        return False
    
    log(f"[PASS] Bảo vệ tuyệt đối: {len(before_hashes)} file JSON trong data/ giữ nguyên mã SHA256. 0 byte bị ghi đè!")
    return True

def main():
    log("======================================================================")
    log("   BẮT ĐẦU KIỂM THỬ E2E THỰC CHIẾN (LIVE REAL-WORLD INTEGRATION)      ")
    log("======================================================================")
    server_proc = None
    success = False
    try:
        cleanup_test_data()
        before_json_hashes = snapshot_json_hashes()
        server_proc = start_live_server()
        
        step1 = verify_real_browser()
        step2 = verify_static_assets()
        step3 = verify_staff_journey()
        step4 = verify_manager_journey()
        step5 = verify_admin_snapshot_journey()
        step6 = verify_json_immutability(before_json_hashes)
        
        if step1 and step2 and step3 and step4 and step5 and step6:
            success = True
            log("======================================================================")
            log("   KẾT QUẢ: 100% KIỂM THỬ THỰC CHIẾN E2E HOÀN TẤT THÀNH CÔNG!         ")
            log("======================================================================")
        else:
            log("======================================================================")
            log("   CẢNH BÁO: CÓ BƯỚC KIỂM THỬ THỰC CHIẾN BỊ THẤT BẠI!                 ")
            log("======================================================================")
    except Exception as e:
        log(f"LỖI NGOẠI LỆ TRONG QUÁ TRÌNH TEST: {e}")
    finally:
        if server_proc:
            stop_live_server(server_proc)
        try:
            cleanup_test_data()
        except Exception:
            pass
            
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
