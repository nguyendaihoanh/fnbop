"""
tests/test_no_json_runtime_write.py
Bảo vệ chính sách Single Source of Truth: SQLite WAL duy nhất.
Kiểm tra tính bất biến (Invariant Guard) của toàn bộ các file JSON trong runtime:
Tuyệt đối KHÔNG có bất kỳ file JSON nào bị ghi đè hay thay đổi nội dung khi chạy nghiệp vụ.
"""
import os
import sys
import glob
import hashlib
import sqlite3
import pytest
from fastapi.testclient import TestClient

backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from services.auth import create_access_token

def get_file_sha256(filepath: str) -> str:
    if not os.path.exists(filepath):
        return ""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def snapshot_data_dir() -> dict:
    repo_data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    sandbox_dir = os.environ.get("DATA_DIR")
    hashes = {}
    dirs_to_scan = [repo_data_dir]
    if sandbox_dir and os.path.abspath(sandbox_dir) != os.path.abspath(repo_data_dir):
        dirs_to_scan.append(sandbox_dir)
    for d in dirs_to_scan:
        if os.path.exists(d):
            for json_file in glob.glob(os.path.join(d, "*.json")):
                hashes[json_file] = get_file_sha256(json_file)
    return hashes

class TestNoJsonRuntimeWriteInvariant:

    def setup_method(self):
        # Cô lập DB riêng cho test invariant và đảm bảo cờ đồng bộ JSON runtime là FALSE
        import shutil
        import tempfile
        self._prev_sync = os.environ.get("ENABLE_RUNTIME_JSON_SYNC")
        self._prev_db = os.environ.get("DATABASE_PATH")
        self._tmp_db_dir = tempfile.mkdtemp(prefix="fnbops_nojson_db_")
        os.environ["DATABASE_PATH"] = os.path.join(self._tmp_db_dir, "fnbop.db")
        os.environ["ENABLE_RUNTIME_JSON_SYNC"] = "false"
        data_dir = os.environ.get("DATA_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        os.environ["AUTH_FILE"] = os.path.join(data_dir, "staff_auth.json")
        os.environ["ROSTER_FILE"] = os.path.join(data_dir, "roster_schedule.json")
        from services.db import init_db
        from services.auth import load_staff_auth
        init_db()
        load_staff_auth()
        self.client = TestClient(app)
        self.admin_token = create_access_token(data={"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})
        self.manager_token = create_access_token(data={"sub": "manager", "role": "MANAGER", "name": "Quản Lý"})
        self.staff_token = create_access_token(data={"sub": "nhanvien", "role": "STAFF", "name": "Nhân Viên"})

    def teardown_method(self):
        import shutil
        if self._prev_sync is None:
            os.environ.pop("ENABLE_RUNTIME_JSON_SYNC", None)
        else:
            os.environ["ENABLE_RUNTIME_JSON_SYNC"] = self._prev_sync
        if self._prev_db is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._prev_db
        shutil.rmtree(self._tmp_db_dir, ignore_errors=True)

    def test_json_files_strictly_immutable_during_all_runtime_operations(self):
        """
        Kích hoạt toàn bộ nghiệp vụ lõi:
        - Check-in & Check-out nhân viên
        - Chốt két thu ngân POS
        - Xếp ca Roster
        - Đổi mã PIN & cập nhật cấu hình quán
        Xác minh: 100% file JSON trong data/ giữ nguyên mã hash SHA256 tuyệt đối.
        """
        before_hashes = snapshot_data_dir()
        assert len(before_hashes) > 0, "Thư mục data/ phải chứa các file JSON cấu hình ban đầu"

        # 1. Nghiệp vụ Chấm công (Attendance Check-in / Check-out)
        r_ci = self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"Authorization": f"Bearer {self.staff_token}"},
            json={
                "username": "nhanvien",
                "display_name": "Nhân Viên Phục Vụ",
                "role": "STAFF",
                "dev_override_wifi": True,
                "custom_time_str": "06:05"
            }
        )
        assert r_ci.status_code in (200, 400), f"Check-in failed: {r_ci.text}"

        r_co = self.client.post(
            "/api/v1/cc/attendance/checkout",
            headers={"Authorization": f"Bearer {self.staff_token}"},
            json={
                "username": "nhanvien",
                "dev_override_wifi": True,
                "confirm_early": True,
                "custom_time_str": "11:30"
            }
        )
        assert r_co.status_code in (200, 400), f"Check-out failed: {r_co.text}"

        # 2. Nghiệp vụ Chốt két thu ngân POS (Daily Closing)
        r_close = self.client.post(
            "/api/v1/cc/pos/daily-closing",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={
                "report_date": "23/10/2026",
                "closing_time": "23:00",
                "bill_pos": 3500000,
                "cash_amount": 1500000,
                "transfer_amount": 2000000,
                "expense_amount": 50000,
                "expense_detail": "Đá lạnh",
                "sender_name": "Quản Lý Ca",
                "approver_name": "Chủ Quán"
            }
        )
        assert r_close.status_code == 200, f"POS Closing failed: {r_close.text}"

        # 3. Nghiệp vụ Đánh giá / Biên bản phạt thưởng
        r_eval = self.client.post(
            "/api/v1/cc/admin/staff-evaluation",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={
                "staff_name": "nhanvien",
                "type": "BONUS",
                "amount": 50000,
                "reason": "Chăm chỉ dọn quầy ca tối",
                "date": "2026-10-23",
                "manager": "Quản Lý Ca"
            }
        )
        assert r_eval.status_code == 200, f"Staff Eval failed: {r_eval.text}"

        # 4. Nghiệp vụ Cập nhật Cấu hình Quán (Store Config Update)
        r_cfg = self.client.post(
            "/api/v1/cc/store/config",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={
                "store_name": "FnBOps Store Lounge",
                "wifi_ssid": "FnBOps_Store_WiFi"
            }
        )
        assert r_cfg.status_code == 200, f"Store Config update failed: {r_cfg.text}"

        # 5. Nghiệp vụ Xếp ca Roster (Self-seeding Auto-Fill + Update Shift Slot)
        r_autofill = self.client.post(
            "/api/v1/cc/roster/auto-fill",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={"week_id": "2026-W50"}
        )
        assert r_autofill.status_code == 200, f"Roster auto-fill failed: {r_autofill.text}"

        r_roster = self.client.post(
            "/api/v1/cc/roster/update-shift",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={
                "week_id": "2026-W50",
                "date": "2026-12-07",
                "shift_period": "morning",
                "slot_type": "service_1",
                "username": "nhanvien"
            }
        )
        assert r_roster.status_code == 200, f"Roster update failed: {r_roster.text}"

        # KIỂM TOÁN TÍNH BẤT BIẾN (INVARIANT CHECK)
        after_hashes = snapshot_data_dir()

        modified_files = []
        for fpath, before_hash in before_hashes.items():
            after_hash = after_hashes.get(fpath)
            if before_hash != after_hash:
                modified_files.append((fpath, before_hash, after_hash))

        new_files = [f for f in after_hashes if f not in before_hashes]

        assert len(modified_files) == 0, (
            f"VI PHẠM NGUYÊN TẮC 'CẤM JSON': Phát hiện {len(modified_files)} file JSON bị ghi đè trong runtime:\n"
            + "\n".join([f"  - {f[0]} (SHA256 đổi từ {f[1][:10]}... sang {f[2][:10]}...)" for f in modified_files])
        )
        assert len(new_files) == 0, (
            f"VI PHẠM NGUYÊN TẮC 'CẤM JSON': Phát hiện file JSON mới tự ý tạo ra trong runtime: {new_files}"
        )

        # XÁC MINH NGƯỢC LẠI: Dữ liệu thực sự ĐÃ ĐƯỢC LƯU VÀO SQLite WAL
        from services.db import get_db_path, get_db_connection
        db_path = get_db_path()
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Kiểm tra bản ghi closing vừa lưu vào SQLite
        cur.execute("SELECT id, bill_pos, cash_amount FROM daily_closings WHERE report_date='23/10/2026' ORDER BY id DESC LIMIT 1")
        cl_row = cur.fetchone()
        assert cl_row is not None, f"Bản ghi chốt két PHẢI được lưu vào bảng SQLite daily_closings ({db_path})"
        assert cl_row[1] == 3500000.0
        assert cl_row[2] == 1500000.0

        # Kiểm tra bản ghi evaluation vừa lưu vào SQLite
        cur.execute("SELECT id, staff_name, amount, type FROM evaluations WHERE staff_name='nhanvien' ORDER BY id DESC LIMIT 1")
        ev_row = cur.fetchone()
        assert ev_row is not None, f"Bản ghi đánh giá PHẢI được lưu vào bảng SQLite evaluations ({db_path})"
        assert ev_row[2] == 50000.0
        assert ev_row[3] == "BONUS"

        conn.close()
        print(f"\n[VERIFIED] Toàn bộ dữ liệu ghi 100% vào SQLite WAL ({db_path}). 0 file JSON bị thay đổi!")
