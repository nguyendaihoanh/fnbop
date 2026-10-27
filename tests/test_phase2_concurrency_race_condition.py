"""
Test Suite for Phase 2: Concurrency, Race Condition & Tranh Chấp Dữ Liệu
Tests:
1. Anti-Double Submit / Idempotency for Sổ Phụ (/payroll/ledger) under 20 concurrent requests.
2. Anti-Lost Update for Attendance Logs (/attendance/checkin) under 30 concurrent threads.
3. Edge cases: Different ledger parameters, 5s dedup window expiry, SQLite WAL sync integrity.
"""

import os
import sys
import time
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
os.environ["MOCK_TELEGRAM"] = "1"
os.environ["DISABLE_BACKGROUND_WORKER"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from main import app
from routers.fnb_ops import create_access_token
import routers.attendance as att_router
import routers.disbursement as disb_router
from services.storage import safe_json_read, safe_json_write
from services.db import (
    clear_all_rate_limits,
    get_db_connection,
    get_db_path,
    list_staff_ledgers,
    list_so_cai_luong,
)


class TestPhase2ConcurrencyRaceCondition(unittest.TestCase):
    def setUp(self):
        clear_all_rate_limits()
        self.client = TestClient(app)
        self.temp_dir = tempfile.mkdtemp()

        # Temporary files for test isolation
        self.test_logs_file = os.path.join(self.temp_dir, "attendance_logs.json")
        self.test_hb_file = os.path.join(self.temp_dir, "pos_heartbeat.json")
        self.test_auth_file = os.path.join(self.temp_dir, "staff_auth.json")
        self.test_db_path = os.path.join(self.temp_dir, "fnbop_test.db")

        # Initialize clean files
        safe_json_write(self.test_logs_file, [])
        safe_json_write(self.test_hb_file, {
            "cafe_ip": "203.0.113.10",
            "last_seen": "2026-10-16T08:00:00",
            "updated_at": "2026-10-16 08:00:00"
        })

        # Base auth data with active test accounts
        auth_data = {
            "payroll_locks": {},
            "staff_accounts": {
                "admin1": {"full_name": "Quản Trị Viên", "role": "ADMIN", "status": "ACTIVE", "pin": "9999"},
                "manager1": {"full_name": "Quản Lý Test", "role": "MANAGER", "status": "ACTIVE", "pin": "8888"},
                "khoa": {"full_name": "Đỗ Đăng Khoa", "role": "STAFF", "status": "ACTIVE", "pin": "1234"},
            }
        }
        # Add 30 test staff accounts for attendance concurrency
        for i in range(30):
            uname = f"staff_concur_{i:02d}"
            auth_data["staff_accounts"][uname] = {
                "full_name": f"Nhân Viên {i:02d}",
                "role": "STAFF",
                "status": "ACTIVE",
                "pin": "1234",
                "hourly_rate": 20000
            }

        safe_json_write(self.test_auth_file, auth_data)

        # Store originals
        self.orig_auth_env = os.getenv("AUTH_FILE")
        self.orig_logs_env = os.getenv("ATTENDANCE_LOGS_FILE")
        self.orig_db_env = os.getenv("SQLITE_DB_PATH")
        self.orig_db_path_env = os.getenv("DATABASE_PATH")
        self.orig_logs_file = att_router.LOGS_FILE

        os.environ["AUTH_FILE"] = self.test_auth_file
        os.environ["ATTENDANCE_LOGS_FILE"] = self.test_logs_file
        os.environ["SQLITE_DB_PATH"] = self.test_db_path
        os.environ["DATABASE_PATH"] = self.test_db_path
        att_router.LOGS_FILE = self.test_logs_file
        att_router.HEARTBEAT_FILE = self.test_hb_file

        # Initialize SQLite DB schema on test DB
        from services.db.schema import init_db
        init_db(self.test_db_path)

        # Clear in-memory dedup cache
        disb_router._staff_ledger_dedup_cache.clear()

        # Tokens
        self.admin_token = create_access_token({"sub": "admin1", "role": "ADMIN", "name": "Quản Trị Viên"})
        self.manager_token = create_access_token({"sub": "manager1", "role": "MANAGER", "name": "Quản Lý Test"})

    def tearDown(self):
        # Restore environment variables
        if self.orig_auth_env:
            os.environ["AUTH_FILE"] = self.orig_auth_env
        else:
            os.environ.pop("AUTH_FILE", None)

        if self.orig_logs_env:
            os.environ["ATTENDANCE_LOGS_FILE"] = self.orig_logs_env
        else:
            os.environ.pop("ATTENDANCE_LOGS_FILE", None)

        if self.orig_db_env:
            os.environ["SQLITE_DB_PATH"] = self.orig_db_env
        else:
            os.environ.pop("SQLITE_DB_PATH", None)

        if self.orig_db_path_env:
            os.environ["DATABASE_PATH"] = self.orig_db_path_env
        else:
            os.environ.pop("DATABASE_PATH", None)

        att_router.LOGS_FILE = self.orig_logs_file
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # TEST 1: CHỐNG DOUBLE SUBMIT SỔ PHỤ (20 requests đồng thời trong cùng 1 tích tắc)
    # =========================================================================
    def test_ledger_idempotency_double_submit_20_concurrent_requests(self):
        """
        Bắn 20 requests đồng thời trong cùng 1 tích tắc để ghi Sổ Phụ cùng 1 nội dung
        -> Chỉ 1 bản ghi duy nhất được tạo trong Database và Sổ Cái.
        -> Cả 20 requests đều nhận HTTP 200 với cùng 1 entry id.
        -> Không nhân đôi/nhân 20 số tiền thưởng/phạt.
        """
        target_staff = "khoa"
        target_month = "10"
        payload = {
            "staff_name": target_staff,
            "type": "bonus",
            "amount": 250000,
            "month": target_month,
            "payment_method": "cash",
            "reason": "Thưởng nóng dự án Phase 2"
        }
        headers = {"Authorization": f"Bearer {self.manager_token}"}

        # Bắn 20 requests đồng thời qua ThreadPoolExecutor
        num_requests = 20
        def send_create_ledger():
            return self.client.post("/api/v1/cc/payroll/ledger", json=payload, headers=headers)

        with ThreadPoolExecutor(max_workers=num_requests) as executor:
            futures = [executor.submit(send_create_ledger) for _ in range(num_requests)]
            responses = [f.result() for f in futures]

        # 1. Toàn bộ 20 requests phải thành công (HTTP 200)
        for idx, resp in enumerate(responses):
            self.assertEqual(
                resp.status_code, 200,
                f"Request {idx} thất bại với status {resp.status_code}: {resp.text}"
            )
            data = resp.json()
            self.assertTrue(data.get("success"), f"Request {idx} success field is not True")

        # 2. Toàn bộ 20 requests phải trả về CHÍNH XÁC cùng một entry id (Idempotency)
        entry_ids = [resp.json()["entry"]["id"] for resp in responses]
        unique_entry_ids = set(entry_ids)
        self.assertEqual(
            len(unique_entry_ids), 1,
            f"Phát hiện nhiều ledger ID khác nhau được tạo: {unique_entry_ids}"
        )
        single_ledger_id = list(unique_entry_ids)[0]

        # 3. Kiểm tra Single Source of Truth trong SQLite staff_ledgers: chỉ có ĐÚNG 1 bản ghi
        db_ledgers = list_staff_ledgers(
            month=target_month,
            staff_name=target_staff,
            db_path=self.test_db_path
        )
        self.assertEqual(
            len(db_ledgers), 1,
            f"Số lượng bản ghi trong DB là {len(db_ledgers)}, mong đợi đúng 1 bản ghi duy nhất!"
        )
        self.assertEqual(db_ledgers[0]["id"], single_ledger_id)
        self.assertEqual(int(db_ledgers[0]["amount"]), 250000)

        # 4. Kiểm tra Sổ cái bất biến so_cai_luong: chỉ có ĐÚNG 1 sự kiện THUONG
        so_cai_events = list_so_cai_luong(
            staff_name=target_staff,
            month=target_month,
            db_path=self.test_db_path
        )
        bonus_events = [e for e in so_cai_events if e.get("loai_su_kien") == "THUONG"]
        self.assertEqual(
            len(bonus_events), 1,
            f"Số sự kiện trong so_cai_luong là {len(bonus_events)}, mong đợi đúng 1 sự kiện!"
        )
        self.assertEqual(int(bonus_events[0]["so_tien_thay_doi"]), 250000)

        # 5. Kiểm tra tổng kết GET /payroll/ledger: total_bonus đúng 250,000đ (không bị nhân 20 thành 5,000,000đ)
        summary_resp = self.client.get(
            f"/api/v1/cc/payroll/ledger?month={target_month}&staff_name={target_staff}",
            headers=headers
        )
        self.assertEqual(summary_resp.status_code, 200)
        s_data = summary_resp.json()
        self.assertEqual(s_data["count"], 1)
        self.assertEqual(s_data["summary"]["total_bonus"], 250000)

    def test_ledger_dedup_allows_different_parameters(self):
        """
        Nếu thay đổi số tiền, loại sổ phụ hoặc nhân viên -> Không bị dedup, tạo bản ghi mới bình thường.
        """
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        p1 = {"staff_name": "khoa", "type": "bonus", "amount": 100000, "month": "10", "reason": "Lần 1"}
        p2 = {"staff_name": "khoa", "type": "bonus", "amount": 200000, "month": "10", "reason": "Lần 2 số tiền khác"}
        p3 = {"staff_name": "khoa", "type": "advance", "amount": 100000, "month": "10", "reason": "Lần 3 loại khác"}

        r1 = self.client.post("/api/v1/cc/payroll/ledger", json=p1, headers=headers)
        r2 = self.client.post("/api/v1/cc/payroll/ledger", json=p2, headers=headers)
        r3 = self.client.post("/api/v1/cc/payroll/ledger", json=p3, headers=headers)

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r3.status_code, 200)

        ids = {r1.json()["entry"]["id"], r2.json()["entry"]["id"], r3.json()["entry"]["id"]}
        self.assertEqual(len(ids), 3, "Ba bản ghi với thông số khác nhau phải có 3 ID phân biệt")

    def test_ledger_dedup_expires_after_5_seconds(self):
        """
        Cùng thông số nhưng gửi cách nhau > 5 giây -> Cho phép tạo bản ghi mới.
        """
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        p = {"staff_name": "khoa", "type": "deduction", "amount": 50000, "month": "10", "reason": "Phạt trễ"}

        r1 = self.client.post("/api/v1/cc/payroll/ledger", json=p, headers=headers)
        self.assertEqual(r1.status_code, 200)
        id1 = r1.json()["entry"]["id"]

        # Giả lập thời gian trôi qua > 5.0 giây trong dedup cache và SQLite
        dedup_key = f"khoa:deduction:50000:10:quản lý test"
        if dedup_key in disb_router._staff_ledger_dedup_cache:
            ts, entry = disb_router._staff_ledger_dedup_cache[dedup_key]
            disb_router._staff_ledger_dedup_cache[dedup_key] = (ts - 6.0, entry)

        conn = get_db_connection(self.test_db_path)
        try:
            with conn:
                conn.execute("UPDATE staff_ledgers SET created_at = datetime('now', '-10 seconds')")
        finally:
            conn.close()

        r2 = self.client.post("/api/v1/cc/payroll/ledger", json=p, headers=headers)
        self.assertEqual(r2.status_code, 200)
        id2 = r2.json()["entry"]["id"]

        self.assertNotEqual(id1, id2, "Sau 5 giây, bản ghi mới phải được tạo với ID mới")

    # =========================================================================
    # TEST 2: CHỐNG LOST UPDATE CHẤM CÔNG (30 threads check-in đồng thời)
    # =========================================================================
    def test_attendance_checkin_30_concurrent_threads_no_lost_update(self):
        """
        Bắn 30 threads check-in đồng thời cho 30 nhân viên khác nhau
        -> Toàn bộ 30 lượt chấm công được ghi nhận đầy đủ vào attendance_logs.json.
        -> Không bị đè mất dữ liệu (No Lost Updates).
        -> SQLite WAL đồng bộ an toàn không văng lỗi database is locked.
        """
        num_threads = 30
        users = [f"staff_concur_{i:02d}" for i in range(num_threads)]
        tokens = {
            u: create_access_token({"sub": u, "role": "STAFF", "name": f"Nhân Viên {i:02d}"})
            for i, u in enumerate(users)
        }

        def perform_checkin(username: str):
            token = tokens[username]
            payload = {
                "username": username,
                "display_name": f"Nhân Viên {username[-2:]}",
                "dev_override_wifi": True,
                "shift_override": "sang"
            }
            return self.client.post(
                "/api/v1/cc/attendance/checkin",
                json=payload,
                headers={"Authorization": f"Bearer {token}"}
            )

        # Bắn 30 threads check-in đồng thời
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = {executor.submit(perform_checkin, u): u for u in users}
            results = {}
            for future in futures:
                u = futures[future]
                results[u] = future.result()

        # 1. Tất cả 30 requests đều trả về HTTP 200
        for u, resp in results.items():
            self.assertEqual(
                resp.status_code, 200,
                f"User {u} checkin failed with status {resp.status_code}: {resp.text}"
            )
            r_json = resp.json()
            self.assertIn(
                r_json.get("status"), ["success", "already_checked_in"],
                f"Unexpected status for user {u}: {r_json}"
            )

        # 2. Đọc trực tiếp attendance_logs.json: BẮT BUỘC có đủ 30 bản ghi không mất bản nào
        saved_logs = safe_json_read(self.test_logs_file, default=[])
        logged_usernames = [l.get("username") for l in saved_logs]

        self.assertEqual(
            len(saved_logs), num_threads,
            f"attendance_logs.json chỉ chứa {len(saved_logs)} bản ghi thay vì {num_threads}! Đã bị Lost Update!"
        )
        for u in users:
            self.assertIn(
                u, logged_usernames,
                f"User {u} bị mất lượt chấm công trong attendance_logs.json!"
            )

        # 3. Kiểm tra SQLite WAL attendance_logs table: BẮT BUỘC có đủ 30 bản ghi
        conn = get_db_connection(self.test_db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT username, date, checkin, status FROM attendance_logs")
            rows = cur.fetchall()
            db_users = [r["username"] for r in rows]
            self.assertEqual(
                len(rows), num_threads,
                f"Bảng SQLite attendance_logs chỉ chứa {len(rows)} bản ghi thay vì {num_threads}!"
            )
            for u in users:
                self.assertIn(
                    u, db_users,
                    f"User {u} không tìm thấy trong SQLite attendance_logs!"
                )
        finally:
            conn.close()

    def test_attendance_process_lock_thread_reentrancy(self):
        """
        Kiểm tra tính re-entrant của AttendanceLogsProcessLock:
        Có thể lồng nhiều tầng context manager trên cùng 1 thread mà không gây deadlock hoặc tự nhả lock sớm.
        """
        from services.attendance_service import _logs_lock
        target_file = att_router.LOGS_FILE

        with _logs_lock:
            # Tầng 1
            l1 = safe_json_read(target_file, default=[])
            with _logs_lock:
                # Tầng 2
                safe_json_write(target_file, [{"test": "nested"}])
                with _logs_lock:
                    # Tầng 3
                    l3 = safe_json_read(target_file, default=[])
                    self.assertEqual(len(l3), 1)
            # Sau khi thoát tầng 2, 3: lock tầng 1 vẫn phải được giữ an toàn
            l1_after = safe_json_read(target_file, default=[])
            self.assertEqual(len(l1_after), 1)


if __name__ == "__main__":
    unittest.main()
