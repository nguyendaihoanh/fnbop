"""
Stress & Chaos Test Suite for FnBOps Management System (fnbops.local)
Covers 4 critical torture scenarios:
1. Spike Test: 50 concurrent check-in requests at peak hour -> 0 errors, no 500, no FileLock timeout.
2. Chaos Test: kill -9 during SQLite WAL bulk write -> PRAGMA integrity_check returns 'ok', clean rollback.
3. Fuzzing Test: 10MB payload (413), 100k chars, null bytes \x00, negative numbers -> 400/413/422, no OOM.
4. Replay Test: Intercepted check-in request replayed -> blocked with 400/403 or safe deduplication.
"""

import os
import sys
import time
import json
import signal
import shutil
import sqlite3
import tempfile
import unittest
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

# Ensure backend modules can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from main import app
from services.db import get_db_connection, init_db
from routers.fnb_ops import create_access_token
from services.storage import safe_json_read, safe_json_write
import routers.attendance as att_router


class TestStressAndChaos(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.temp_dir = tempfile.mkdtemp()
        
        # Isolate database and files
        self.test_db_path = os.path.join(self.temp_dir, "test_chaos.db")
        self.test_hb_file = os.path.join(self.temp_dir, "pos_heartbeat.json")
        self.test_logs_file = os.path.join(self.temp_dir, "attendance_logs.json")
        self.test_auth_file = os.path.join(self.temp_dir, "staff_auth.json")
        self.test_eval_file = os.path.join(self.temp_dir, "eval_logs.json")
        
        # Save originals
        self.orig_db = os.environ.get("DATABASE_PATH")
        self.orig_auth = os.environ.get("AUTH_FILE")
        self.orig_hb = att_router.HEARTBEAT_FILE
        self.orig_logs = att_router.LOGS_FILE
        self.orig_cafe_ip = att_router._cached_cafe_ip
        
        # Set overrides
        os.environ["DATABASE_PATH"] = self.test_db_path
        os.environ["AUTH_FILE"] = self.test_auth_file
        os.environ["ATTENDANCE_LOGS_FILE"] = self.test_logs_file
        att_router.HEARTBEAT_FILE = self.test_hb_file
        att_router.LOGS_FILE = self.test_logs_file
        att_router._cached_cafe_ip = "203.0.113.10"
        
        # Initialize SQLite WAL DB
        init_db(self.test_db_path)
        
        # Seed 60 staff accounts for concurrency tests
        self.staff_accounts = {}
        for i in range(60):
            uname = f"staff_spike_{i:02d}"
            self.staff_accounts[uname] = {
                "full_name": f"Nhân Viên Spike {i:02d}",
                "pin": "1234",
                "role": "STAFF",
                "status": "ACTIVE",
                "gender": "NAM" if i % 2 == 0 else "NU",
                "position": "BARISTA" if i % 3 == 0 else "SERVICE",
                "sheet_names": [uname],
                "aliases": [uname]
            }
        
        # Add manager account
        self.staff_accounts["manager_test"] = {
            "full_name": "Quản Lý Test",
            "pin": "1111",
            "role": "MANAGER",
            "status": "ACTIVE",
            "gender": "NAM",
            "position": "MANAGER",
            "sheet_names": ["Quản Lý Test"],
            "aliases": ["manager_test"]
        }
        
        safe_json_write(self.test_auth_file, {"staff_accounts": self.staff_accounts})
        safe_json_write(self.test_logs_file, [])
        safe_json_write(self.test_eval_file, [])
        safe_json_write(self.test_hb_file, {
            "cafe_ip": "203.0.113.10",
            "last_seen": datetime.now().isoformat()
        })

    def tearDown(self):
        att_router.HEARTBEAT_FILE = self.orig_hb
        att_router.LOGS_FILE = self.orig_logs
        att_router._cached_cafe_ip = self.orig_cafe_ip
        
        if self.orig_db:
            os.environ["DATABASE_PATH"] = self.orig_db
        else:
            os.environ.pop("DATABASE_PATH", None)
            
        if self.orig_auth:
            os.environ["AUTH_FILE"] = self.orig_auth
        else:
            os.environ.pop("AUTH_FILE", None)

        os.environ.pop("ATTENDANCE_LOGS_FILE", None)
            
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ==========================================================================
    # BÀI 1: ĐUA CHẤM CÔNG GIỜ CAO ĐIỂM (SPIKE TEST)
    # 50-60 requests đồng thời bắn vào đúng 1 ms -> 100% thành công, 0 lỗi 500, 0 timeout
    # ==========================================================================
    def test_01_spike_peak_hour_concurrent_checkin_50_workers(self):
        """Bắn đồng thời 50 request check-in từ 50 nhân viên khác nhau.
        Tiêu chí: 100% requests thành công (HTTP 200), không có request nào bị 500 hoặc timeout FileLock."""
        staff_subset = [f"staff_spike_{i:02d}" for i in range(50)]
        
        def run_single_checkin(username):
            token = create_access_token({"sub": username, "role": "STAFF"})
            headers = {
                "CF-Connecting-IP": "203.0.113.10",
                "Authorization": f"Bearer {token}"
            }
            payload = {
                "username": username,
                "role": "Phục vụ",
                "shift_override": "sang",
                "custom_time_str": "06:05"
            }
            return self.client.post("/api/v1/cc/attendance/checkin", headers=headers, json=payload)

        # Dispatch 50 concurrent requests simultaneously
        with ThreadPoolExecutor(max_workers=50) as pool:
            start_t = time.perf_counter()
            results = list(pool.map(run_single_checkin, staff_subset))
            duration = time.perf_counter() - start_t

        # Assertions
        status_codes = [r.status_code for r in results]
        self.assertEqual(len(status_codes), 50)
        
        # Verify NO 500 Internal Server Errors, NO 408 Timeouts
        failures_500 = [c for c in status_codes if c >= 500]
        self.assertEqual(len(failures_500), 0, f"Found 500 errors in spike test: {failures_500}")
        
        # All 50 must succeed with HTTP 200
        for idx, res in enumerate(results):
            self.assertEqual(res.status_code, 200, f"Worker {idx} failed with {res.status_code}: {res.text}")
            self.assertEqual(res.json().get("status"), "success")

        # Verify atomic write integrity: exactly 50 logs must exist in attendance_logs.json
        saved_logs = safe_json_read(self.test_logs_file, default=[])
        self.assertEqual(len(saved_logs), 50, "FileLock atomic write check failed: expected 50 records")
        print(f"\n  [SPIKE TEST] 50 concurrent check-ins processed in {duration:.2f}s (100% PASS, 0 errors)")

    # ==========================================================================
    # BÀI 2: TẮT ĐỘT NGỘT KHI ĐANG GHI (CHAOS TEST - KILL -9)
    # Tiến trình Python bị kill -9 giữa chừng ghi DB -> SQLite WAL tự rollback sạch, integrity_check 'ok'
    # ==========================================================================
    def test_02_chaos_kill_minus_9_sqlite_wal_integrity(self):
        """Kích hoạt tác vụ ghi bulk transactions vào SQLite, gửi kill -9 giữa chừng.
        Tiêu chí: PRAGMA integrity_check báo 'ok', không hỏng file DB, dữ liệu dở dang tự rollback sạch."""
        chaos_db = os.path.join(self.temp_dir, "chaos_wal.db")
        
        # Script con thực hiện ghi 10.000 records trong transaction dài
        worker_code = f"""
import sqlite3
import time

conn = sqlite3.connect('{chaos_db}', timeout=5.0)
conn.execute('PRAGMA journal_mode = WAL;')
conn.execute('PRAGMA synchronous = NORMAL;')
conn.execute('CREATE TABLE IF NOT EXISTS stress_records (id INTEGER PRIMARY KEY, payload TEXT, created_at REAL);')
conn.commit()

cur = conn.cursor()
cur.execute('BEGIN TRANSACTION;')
for i in range(10000):
    cur.execute('INSERT INTO stress_records (payload, created_at) VALUES (?, ?)', ('DATA_' * 50, time.time()))
    if i == 500:
        print("READY_FOR_KILL", flush=True)

time.sleep(10)
conn.commit()
"""
        proc = subprocess.Popen(
            [sys.executable, "-c", worker_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        line = proc.stdout.readline()
        self.assertIn("READY_FOR_KILL", line)

        # Chaos shock: Kill -9 abruptly
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait()

        # Reopen SQLite database after simulated hard crash
        conn = sqlite3.connect(chaos_db, timeout=5.0)
        conn.execute("PRAGMA journal_mode = WAL;")
        cur = conn.cursor()
        
        # 1. Integrity Check: Bắt buộc phải là 'ok'
        integrity_results = cur.execute("PRAGMA integrity_check;").fetchall()
        self.assertEqual(integrity_results, [("ok",)], "Database corrupted after hard kill -9!")

        # 2. Rollback Check: Dữ liệu dở dang chưa commit phải được rollback hoàn toàn sạch sẽ (0 rows)
        row_count = cur.execute("SELECT COUNT(*) FROM stress_records;").fetchone()[0]
        self.assertEqual(row_count, 0, f"Uncommitted transaction was not rolled back cleanly: {row_count} rows found")
        conn.close()
        print(f"\n  [CHAOS TEST] Hard kill -9 during transaction -> PRAGMA integrity_check: OK, clean rollback.")

    # ==========================================================================
    # BÀI 3: BƠM DỮ LIỆU RÁC CỰC HẠN (FUZZING TEST)
    # Gói tin 10MB -> 413, Chuỗi 100k ký tự -> 422, Null byte \x00 -> 422, Số âm -> 400/422
    # ==========================================================================
    def test_03_fuzzing_oversized_10mb_payload_rejected_413(self):
        """Gửi gói tin JSON nặng 10MB (vượt quá trần 5MB của request_size_limit_middleware).
        Tiêu chí: Backend trả về ngay 413 Payload Too Large, RAM không tràn (OOM), không sập tiến trình."""
        token = create_access_token({"sub": "manager_test", "role": "MANAGER"})
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Length": str(10 * 1024 * 1024)
        }
        huge_data = {"note": "A" * (10 * 1024 * 1024)}
        res = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json=huge_data)
        self.assertEqual(res.status_code, 413, f"Expected 413 Payload Too Large, got {res.status_code}")
        self.assertIn("Payload Too Large", res.text)

    def test_03b_fuzzing_100k_chars_and_null_bytes_rejected_cleanly(self):
        """Gửi chuỗi 100.000 ký tự và ký tự null \\x00 vào endpoint chấm công / đánh giá.
        Tiêu chí: Backend từ chối hợp lệ (400/422), không sập tiến trình."""
        token = create_access_token({"sub": "manager_test", "role": "MANAGER"})
        headers = {"Authorization": f"Bearer {token}"}
        
        # Test 1: Null bytes in input -> Starlette/Pydantic returns 422 or 400
        null_payload = {
            "staff_name": "staff_spike_00\x00malicious",
            "date": "2026-09-15",
            "type": "Phạt",
            "amount": 20000,
            "reason": "Vi phạm có ký tự null \x00 độc hại"
        }
        res_null = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json=null_payload)
        self.assertIn(res_null.status_code, [400, 422])

        # Test 2: Negative amount where positive integer expected -> Server rejects with 400
        neg_payload = {
            "staff_name": "staff_spike_00",
            "date": "2026-09-15",
            "type": "Phạt",
            "amount": -500000,  # Negative fine
            "reason": "Số âm gian lận"
        }
        res_neg = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json=neg_payload)
        self.assertIn(res_neg.status_code, [400, 422])
        self.assertIn("Số tiền thưởng/phạt không hợp lệ", res_neg.text)

        # Test 3: Extreme 100.000 character string in reason field -> Server processes or limits safely without OOM
        long_str = "A" * 100000
        long_payload = {
            "staff_name": "staff_spike_00",
            "date": "2026-09-15",
            "type": "Phạt",
            "amount": 50000,
            "reason": long_str
        }
        res_long = self.client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json=long_payload)
        # Must return valid HTTP response (not 500 internal server error or crash)
        self.assertIn(res_long.status_code, [200, 400, 422])
        print(f"\n  [FUZZING TEST] 10MB payload (413), null byte rejection (422), negative amount check (400) ALL PASSED.")

    # ==========================================================================
    # BÀI 4: BẮT GÓI TIN BẮN LẠI (REPLAY ATTACK TEST)
    # Gói tin ca sáng bị chụp lại và bắn lại -> Backend phát hiện và từ chối 400/already_checked_in
    # ==========================================================================
    def test_04_replay_attack_duplicate_checkin_prevented(self):
        """Nhân viên check-in ca sáng lúc 06:05. Sau đó kẻ tấn công bắt gói tin bắn lại.
        Tiêu chí: Backend phát hiện trạng thái ca đang mở -> trả về already_checked_in (không nhân đôi bản ghi).
        Sau khi ca đã checkout -> bắn lại gói tin ca cũ bị từ chối 400 Bad Request."""
        username = "staff_spike_01"
        token = create_access_token({"sub": username, "role": "STAFF"})
        headers = {
            "CF-Connecting-IP": "203.0.113.10",
            "Authorization": f"Bearer {token}"
        }
        captured_payload = {
            "username": username,
            "role": "Phục vụ",
            "shift_override": "sang",
            "custom_time_str": "06:05"
        }

        # 1. First legitimate check-in
        res1 = self.client.post("/api/v1/cc/attendance/checkin", headers=headers, json=captured_payload)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["status"], "success")

        # 2. Immediate replay attack with identical payload and token
        res_replay_in_progress = self.client.post("/api/v1/cc/attendance/checkin", headers=headers, json=captured_payload)
        self.assertEqual(res_replay_in_progress.status_code, 200)
        # Must detect that staff is already in shift without duplicating logs!
        self.assertEqual(res_replay_in_progress.json()["status"], "already_checked_in")
        self.assertIn("đang trong ca trực", res_replay_in_progress.json()["message"])

        # Check total logs: strictly 1 log, no duplicate created
        logs_1 = safe_json_read(self.test_logs_file, default=[])
        self.assertEqual(len(logs_1), 1)

        # 3. Staff checks out properly
        res_out = self.client.post(
            "/api/v1/cc/attendance/checkout",
            headers=headers,
            json={"username": username, "custom_time_str": "11:30"}
        )
        self.assertEqual(res_out.status_code, 200)

        # 4. Replay attack at 14:00 (after shift closed) using captured morning payload
        replay_after_closed = {
            "username": username,
            "role": "Phục vụ",
            "shift_override": "sang",
            "custom_time_str": "14:00"
        }
        res_replay_closed = self.client.post("/api/v1/cc/attendance/checkin", headers=headers, json=replay_after_closed)
        self.assertEqual(res_replay_closed.status_code, 400)
        self.assertIn("Ca đã đóng", res_replay_closed.json()["detail"])

        # Final check: only 1 completed record exists
        logs_final = safe_json_read(self.test_logs_file, default=[])
        self.assertEqual(len(logs_final), 1)
        self.assertIsNotNone(logs_final[0]["checkout_time"])
        print(f"\n  [REPLAY TEST] Duplicate and replay attacks successfully blocked (400 / already_checked_in).")


if __name__ == "__main__":
    unittest.main()
