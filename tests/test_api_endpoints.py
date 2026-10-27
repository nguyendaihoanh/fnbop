import unittest
import os
import json
from fastapi.testclient import TestClient

# Capture original env vars
_orig_auth_file = os.environ.get("AUTH_FILE")
_orig_admin_pass = os.environ.get("ADMIN_PASSWORD")

# Thiết lập biến môi trường test
os.environ["TESTING"] = "1"
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_super_secure_key_1234567890"
os.environ["ADMIN_PASSWORD"] = "test_admin_261109"
os.environ["STAFF_PASSWORD"] = "test_staff_2026"

import tempfile
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data_candidate = os.path.join(project_root, "data", "data.json")
if not os.path.exists(data_candidate):
    data_candidate = os.path.join(project_root, "data", "data.json")
os.environ["DATA_FILE"] = data_candidate
test_auth_file = os.path.join(tempfile.gettempdir(), "mock_staff_auth.json")
os.environ["AUTH_FILE"] = test_auth_file

# Tạo mock staff_auth.json cho test (merge all production accounts + test accounts)
real_auth_path = os.path.join(project_root, "data", "staff_auth.json")
try:
    with open(real_auth_path, "r", encoding="utf-8") as f:
        mock_auth_data = json.load(f)
except Exception:
    mock_auth_data = {"staff_accounts": {}}

mock_auth_data.setdefault("staff_accounts", {}).update({
    "phache": {
        "full_name": "Pha Chế",
        "pin": "2222",
        "role": "STAFF",
        "status": "ACTIVE",
        "position": "BARISTA",
        "gender": "NAM",
        "sheet_names": ["Pha Chế", "PHACHE"]
    },
    "manager": {
        "full_name": "Quản Lý Ca",
        "pin": "8888",
        "role": "MANAGER",
        "status": "ACTIVE",
        "position": "QUẢN LÝ",
        "aliases": ["manager", "quanly"],
        "sheet_names": ["Quản Lý Ca", "MANAGER"]
    },
    "nhanvien": {
        "full_name": "Nhân Viên",
        "pin": "1111",
        "role": "STAFF",
        "status": "ACTIVE",
        "position": "SERVICE",
        "gender": "NU",
        "sheet_names": ["Nhân Viên", "NHANVIEN"]
    },
    "nhanvien05": {
        "full_name": "Nhân Viên 05",
        "pin": "2468",
        "role": "STAFF",
        "status": "ACTIVE",
        "position": "BARISTA",
        "gender": "NU",
        "sheet_names": ["Nhân Viên 05"]
    },
    "inactive_user": {
        "full_name": "Nhân Viên Đã Nghỉ",
        "pin": "9999",
        "role": "STAFF",
        "status": "INACTIVE",
        "position": "SERVICE",
        "gender": "NAM",
        "sheet_names": ["Nhân Viên Đã Nghỉ"]
    }
})
with open(test_auth_file, "w", encoding="utf-8") as f:
    json.dump(mock_auth_data, f, ensure_ascii=False, indent=2)

import sys
sys.path.insert(0, os.path.join(project_root, "backend"))
from main import app
from routers.fnb_ops import create_access_token
from routers import roster as roster_router

class TestAPIEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        os.environ["TESTING"] = "1"
        os.environ["AUTH_FILE"] = test_auth_file
        os.environ["ADMIN_PASSWORD"] = "test_admin_261109"
        mock_auth_data.setdefault("staff_accounts", {}).pop("nhanvienmoi", None)
        with open(test_auth_file, "w", encoding="utf-8") as f:
            json.dump(mock_auth_data, f, ensure_ascii=False, indent=2)
        try:
            from services.db import clear_login_attempts
            clear_login_attempts("testclient")
            clear_login_attempts("127.0.0.1")
        except Exception:
            pass

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(test_auth_file):
            os.remove(test_auth_file)
        if _orig_auth_file is not None:
            os.environ["AUTH_FILE"] = _orig_auth_file
        else:
            os.environ.pop("AUTH_FILE", None)
        if _orig_admin_pass is not None:
            os.environ["ADMIN_PASSWORD"] = _orig_admin_pass

    def test_01_ping(self):
        """Kiểm tra healthcheck ping endpoint"""
        res = self.client.get("/api/v1/main/ping")
        self.assertEqual(res.status_code, 200)
        self.assertIn("running", res.json()["message"])

    def test_02_admin_login_success(self):
        """Kiểm tra đăng nhập Admin với đúng mật khẩu"""
        payload = {"username": "admin", "password": "test_admin_261109"}
        res = self.client.post("/api/v1/cc/auth/login", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "ADMIN")

    def test_03_staff_login_success(self):
        """Kiểm tra đăng nhập nhân viên với đúng mã PIN cá nhân"""
        payload = {"username": "phache", "password": "2222"}
        res = self.client.post("/api/v1/cc/auth/login", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "STAFF")

    def test_03b_manager_login(self):
        """Kiểm tra đăng nhập Quản lý manager với role MANAGER và pin 8888"""
        payload = {"username": "manager", "password": "8888"}
        res = self.client.post("/api/v1/cc/auth/login", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "MANAGER")

    def test_03c_staff_service_login(self):
        """Kiểm tra đăng nhập nhân viên nhanvien với role STAFF và pin 1111"""
        payload = {"username": "nhanvien", "password": "1111"}
        res = self.client.post("/api/v1/cc/auth/login", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "STAFF")

    def test_04_inactive_staff_rejected(self):
        """Kiểm tra chặn nhân viên đã offboarding / inactive (403)"""
        payload = {"username": "inactive_user", "password": "9999"}
        res = self.client.post("/api/v1/cc/auth/login", json=payload)
        self.assertEqual(res.status_code, 403)

    def test_05_invalid_credentials_rejected(self):
        """Kiểm tra từ chối sai thông tin (401)"""
        payload = {"username": "phache", "password": "wrong_pin"}
        res = self.client.post("/api/v1/cc/auth/login", json=payload)
        self.assertEqual(res.status_code, 401)

    def test_06_protected_data_requires_auth(self):
        """Kiểm tra API /data từ chối khi không có Authorization Bearer (401)"""
        res = self.client.get("/api/v1/cc/data")
        self.assertEqual(res.status_code, 401)

    def test_07_protected_data_with_token(self):
        """Kiểm tra API /data trả về dữ liệu khi có token hợp lệ"""
        # Login lấy token
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.get("/api/v1/cc/data", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("NHÂN VIÊN", data)
        self.assertIn("_meta", data)
        self.assertEqual(data["_meta"]["role"], "ADMIN")

    def test_08_shift_approvals_endpoint(self):
        """Kiểm tra API lấy danh sách phê duyệt ca (/shifts/approvals)"""
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        res = self.client.get("/api/v1/cc/shifts/approvals", headers=headers)
        self.assertEqual(res.status_code, 200)

    def test_09_data_json_sync_integrity(self):
        """Kiểm tra tính toàn vẹn và đồng bộ dữ liệu dùng chung giữa Mobile và Desktop"""
        data_path = os.path.join(project_root, "data", "data.json")
        if not os.path.exists(data_path):
            data_path = os.path.join(project_root, "data", "data.json")
        self.assertTrue(os.path.exists(data_path))
        with open(data_path, "r", encoding="utf-8") as f:
            content = json.load(f)
        
        required_sheets = ["NHÂN VIÊN", "DỮ LIỆU", "ĐÁNH GIÁ", "SỔ PHỤ"]
        for sheet in required_sheets:
            self.assertIn(sheet, content, f"Tab {sheet} phải tồn tại trong data.json")
            self.assertIsInstance(content[sheet], list, f"Tab {sheet} phải là mảng dữ liệu")
    def test_10_admin_update_pin(self):
        """Kiểm tra Admin cập nhật mã PIN cho nhân viên (/admin/update-pin)"""
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        update_res = self.client.post(
            "/api/v1/cc/admin/update-pin",
            headers=headers,
            json={"username": "nhanvien", "new_pin": "5678"}
        )
        self.assertEqual(update_res.status_code, 200)

        # Đăng nhập với PIN mới
        new_login = self.client.post("/api/v1/cc/auth/login", json={"username": "nhanvien", "password": "5678"})
        self.assertEqual(new_login.status_code, 200)

    def test_11_brute_force_rate_limit(self):
        """Kiểm tra chống brute-force đăng nhập sai liên tiếp 5 lần kích hoạt khóa 60s"""
        from services.db import clear_login_attempts
        test_ip = "192.168.1.199"
        clear_login_attempts(test_ip)
        headers = {"X-Real-IP": test_ip}
        for i in range(5):
            res = self.client.post("/api/v1/cc/auth/login", headers=headers, json={"username": "phache", "password": "wrong"})
            self.assertEqual(res.status_code, 401)
        
        # Lần thứ 6 phải bị rate limit (429)
        lockout_res = self.client.post("/api/v1/cc/auth/login", headers=headers, json={"username": "phache", "password": "wrong"})
        self.assertEqual(lockout_res.status_code, 429)
        clear_login_attempts(test_ip)
    def test_12_toggle_payroll_lock(self):
        """Kiểm tra Admin khóa và mở kỳ lương (/admin/toggle-lock)"""
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Khóa kỳ lương tháng 9
        lock_res = self.client.post(
            "/api/v1/cc/admin/toggle-lock",
            headers=headers,
            json={"month": "9", "status": "LOCKED", "message": "Chốt số liệu tháng 9"}
        )
        self.assertEqual(lock_res.status_code, 200)
        self.assertTrue(lock_res.json()["success"])
        self.assertEqual(lock_res.json()["payroll_locks"]["9"]["status"], "LOCKED")

        # Mở lại kỳ lương tháng 9
        unlock_res = self.client.post(
            "/api/v1/cc/admin/toggle-lock",
            headers=headers,
            json={"month": "9", "status": "OPEN", "message": "Mở điều chỉnh"}
        )
        self.assertEqual(unlock_res.status_code, 200)
        self.assertEqual(unlock_res.json()["payroll_locks"]["9"]["status"], "OPEN")

    def test_13_staff_confirm_payroll(self):
        """Kiểm tra nhân viên xác nhận công bảng lương (/staff/confirm-payroll)"""
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "phache", "password": "2222"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        confirm_res = self.client.post(
            "/api/v1/cc/staff/confirm-payroll",
            headers=headers,
            json={"month": "9", "status": "CONFIRMED", "note": "Đã đối soát đủ công"}
        )
        self.assertEqual(confirm_res.status_code, 200)
        self.assertEqual(confirm_res.json()["confirmation"]["status"], "CONFIRMED")

    def test_14_admin_create_staff_account(self):
        """Kiểm tra Admin tạo tài khoản nhân viên mới (/admin/create-staff-account)"""
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        create_res = self.client.post(
            "/api/v1/cc/admin/create-staff-account",
            headers=headers,
            json={
                "username": "nhanvienmoi",
                "full_name": "Nhân Viên Mới",
                "pin": "7890",
                "sheet_names": ["Nhân Viên Mới"],
                "aliases": ["moi"]
            }
        )
        self.assertEqual(create_res.status_code, 200)
        self.assertTrue(create_res.json()["success"])

        # Thử đăng nhập ngay bằng tài khoản vừa tạo
        login_new = self.client.post("/api/v1/cc/auth/login", json={"username": "nhanvienmoi", "password": "7890"})
        self.assertEqual(login_new.status_code, 200)
        self.assertEqual(login_new.json()["role"], "STAFF")

    def test_15_shift_confirm_ot(self):
        """Kiểm tra Quản lý / Admin phê duyệt ca OT (/shifts/confirm-ot)"""
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        ot_res = self.client.post(
            "/api/v1/cc/shifts/confirm-ot",
            headers=headers,
            json={
                "shift_key": "Nguyen Van Bin_2026-09-03_Ca Toi",
                "action": "APPROVE",
                "manager_note": "Duyệt tăng ca đông khách"
            }
        )
        self.assertEqual(ot_res.status_code, 200)
        self.assertTrue(ot_res.json()["success"])

    def test_16_n8n_webhook_access_control(self):
        """Kiểm tra webhook n8n đã được tách rời hoàn toàn (decoupled) và không còn mở endpoint."""
        res = self.client.post("/api/v1/n8n/sync")
        self.assertIn(res.status_code, [404, 405])

    def test_17_multi_shift_preferences_registration_and_autofill(self):
        """Kiểm tra Đăng ký nhiều ca/ngày (Multi-Shift) và Thuật toán Tự động Xếp Lịch Ca"""
        # 1. Đăng nhập Admin/Manager để đăng ký ca bất kỳ lúc nào
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Đăng ký nguyện vọng ca với cấu trúc mảng nhiều ca/ngày
        reg_payload = {
            "week_id": "2026-W38",
            "preferences": {
                "0": ["MORNING"],
                "1": ["OFF"],
                "2": ["MORNING", "EVENING_17"],
                "3": ["OFF"],
                "4": ["OFF"],
                "5": ["MORNING", "EVENING_18"],
                "6": ["OFF"]
            },
            "target_shifts": 5,
            "note": "Đăng ký cả sáng và tối T4, T7"
        }
        reg_res = self.client.post("/api/v1/cc/roster/register", headers=headers, json=reg_payload)
        self.assertEqual(reg_res.status_code, 200)
        self.assertTrue(reg_res.json()["success"])

        # 3. Chạy thuật toán tự động xếp ca (Auto-fill) cho tuần 2026-W38
        autofill_res = self.client.post(
            "/api/v1/cc/roster/auto-fill",
            headers=headers,
            json={"week_id": "2026-W38"}
        )
        self.assertEqual(autofill_res.status_code, 200)
        self.assertTrue(autofill_res.json()["success"])
        shifts = autofill_res.json()["shifts"]
        self.assertIsInstance(shifts, dict)

        # 4. Kiểm tra tuyệt đối: Auto-fill không bao giờ xếp ca cho nhân sự đã nghỉ hoặc admin
        inactive_and_admin = ["nhanvien01", "nhanvien02", "nhanvien30", "inactive_user", "admin"]
        for day, day_data in shifts.items():
            for period in ["morning", "evening"]:
                p_data = day_data.get(period, {})
                for slot_key, slot_val in p_data.items():
                    if slot_key in ["time", "manager"]:
                        continue
                    if isinstance(slot_val, list):
                        for u in slot_val:
                            if u:
                                self.assertNotIn(u, inactive_and_admin, f"Inactive user {u} was scheduled in {day} {period} {slot_key}")
                    elif slot_val:
                        self.assertNotIn(slot_val, inactive_and_admin, f"Inactive user {slot_val} was scheduled in {day} {period} {slot_key}")

    def test_19_staff_directory_barista_and_service_positions(self):
        """Kiểm tra danh mục nhân viên: phache (Barista), nhanvien05 (Barista), nhanvien (Service)"""
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        res = self.client.get("/api/v1/cc/roster/week?week_id=next", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        staff_dir = data.get("staff_directory", {})

        # 1. phache phải là BARISTA
        self.assertIn("phache", staff_dir)
        self.assertEqual(staff_dir["phache"]["position"], "BARISTA")

        # 2. nhanvien05 phải là BARISTA
        self.assertIn("nhanvien05", staff_dir)
        self.assertIn(staff_dir["nhanvien05"]["position"], ["BARISTA", "PHA CHẾ"])

        # 3. nhanvien phải là SERVICE
        self.assertIn("nhanvien", staff_dir)
        self.assertEqual(staff_dir["nhanvien"]["position"], "SERVICE")

    def test_20_roster_swap_barista_role_check(self):
        """Kiểm tra F19: Đổi ca barista cho nhân viên không phải BARISTA phải bị từ chối 400"""
        token_nam = create_access_token({"sub": "phache", "role": "STAFF", "name": "Pha Chế"})
        headers_nam = {"Authorization": f"Bearer {token_nam}"}

        # Setup mock week data where phache is in morning barista slot
        roster_data = roster_router.load_roster_data()
        from datetime import datetime, timedelta
        target_dt = datetime.now() + timedelta(days=1)
        target_date_str = target_dt.strftime("%Y-%m-%d")
        iso_year, iso_week, _ = target_dt.isocalendar()
        target_week_id = f"{iso_year}-W{iso_week:02d}"

        week_entry = roster_data.setdefault("weeks", {}).setdefault(target_week_id, {
            "status": "published",
            "shifts": {}
        })
        week_entry["shifts"][target_date_str] = {
            "morning": {
                "time": "06:00 - 11:30",
                "manager": "manager",
                "barista": "phache",
                "service": ["nhanvien", "nhanvien01"]
            },
            "evening": {
                "time": "17:00 - 23:00",
                "manager": "manager",
                "barista": "phache",
                "service_17": "nhanvien",
                "service_18": "nhanvien"
            }
        }
        roster_router.save_roster_data(roster_data)

        # phache đổi ca barista cho nhanvien (SERVICE) -> Phải bị từ chối
        res_fail = self.client.post("/api/v1/cc/roster/peer-swap", headers=headers_nam, json={
            "week_id": target_week_id,
            "date": target_date_str,
            "shift_period": "morning",
            "slot_type": "barista",
            "target_username": "nhanvien",
            "reason": "Bận việc đột xuất"
        })
        self.assertEqual(res_fail.status_code, 400)
        self.assertIn("chưa có chức danh Pha chế (Barista)", res_fail.json()["detail"])

        # phache đổi ca barista cho nhanvien05 (BARISTA) -> Hợp lệ
        res_ok = self.client.post("/api/v1/cc/roster/peer-swap", headers=headers_nam, json={
            "week_id": target_week_id,
            "date": target_date_str,
            "shift_period": "morning",
            "slot_type": "barista",
            "target_username": "nhanvien05",
            "reason": "Bận việc đột xuất"
        })
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.json()["success"])

    def test_21_publish_current_vs_next_week(self):
        """Kiểm tra F22: Phân biệt publish current week và next week riêng biệt"""
        login_res = self.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        active_info, next_info = roster_router.get_active_and_next_week_ids()
        roster_data_backup = roster_router.load_roster_data()
        try:
            roster_data = roster_router.load_roster_data()
            weeks = roster_data.setdefault("weeks", {})
            weeks[active_info["week_id"]] = {"status": "DRAFT", "shifts": {}}
            weeks[next_info["week_id"]] = {"status": "DRAFT", "shifts": {}}
            roster_router.save_roster_data(roster_data)

            # Publish current week
            res_curr = self.client.post("/api/v1/cc/roster/publish", headers=headers, json={"week_id": "current"})
            self.assertEqual(res_curr.status_code, 200)
            self.assertEqual(res_curr.json()["week_id"], active_info["week_id"])

            # Publish next week
            res_next = self.client.post("/api/v1/cc/roster/publish", headers=headers, json={"week_id": "next"})
            self.assertEqual(res_next.status_code, 200)
            self.assertEqual(res_next.json()["week_id"], next_info["week_id"])
        finally:
            # Khôi phục trạng thái để không làm khóa cổng tuần tiếp theo
            roster_router.save_roster_data(roster_data_backup)

    def test_22_manager_staff_pin_management(self):
        """Kiểm tra quyền Quản lý (MANAGER) được phép xem danh sách nhân sự và cập nhật mã PIN"""
        token_mgr = create_access_token({"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})
        headers_mgr = {"Authorization": f"Bearer {token_mgr}"}

        # 1. Quản lý lấy danh sách tài khoản
        res_list = self.client.get("/api/v1/cc/admin/staff-accounts", headers=headers_mgr)
        self.assertEqual(res_list.status_code, 200)
        self.assertIn("staff_accounts", res_list.json())

        # 2. Quản lý cấp đổi mã PIN cho nhân viên (ví dụ nhanvien)
        res_pin = self.client.post("/api/v1/cc/admin/update-pin", headers=headers_mgr, json={
            "username": "nhanvien",
            "new_pin": "8899"
        })
        self.assertEqual(res_pin.status_code, 200)
        self.assertTrue(res_pin.json()["success"])
        self.assertNotIn("pin", res_pin.json())
        self.assertEqual(res_pin.json()["username"], "nhanvien")

    def test_23_special_week_shift_registration_open(self):
        """Kiểm tra đợt mở đặc biệt tuần 14/09 - 20/09: Nhân viên STAFF đăng ký ca thành công ngày Thứ Hai"""
        token_staff = create_access_token({"sub": "phache", "role": "STAFF", "name": "Pha Chế"})
        headers_staff = {"Authorization": f"Bearer {token_staff}"}

        # Staff đăng ký ca tuần 2026-W38
        old_force = os.environ.get("ROSTER_FORCE_REGISTRATION_OPEN")
        os.environ["ROSTER_FORCE_REGISTRATION_OPEN"] = "1"
        try:
            res_reg = self.client.post("/api/v1/cc/roster/register", headers=headers_staff, json={
                "week_id": "2026-W38",
                "target_shifts": 5,
                "preferences": {
                    "0": ["MORNING"],
                    "1": ["OFF"],
                    "2": ["EVENING_17"],
                    "3": ["OFF"],
                    "4": ["MORNING"],
                    "5": ["OFF"],
                    "6": ["OFF"]
                },
                "note": "Đăng ký thử nghiệm tuần đặc biệt"
            })
            self.assertEqual(res_reg.status_code, 200)
            self.assertTrue(res_reg.json()["success"])
        finally:
            if old_force is not None:
                os.environ["ROSTER_FORCE_REGISTRATION_OPEN"] = old_force
            else:
                os.environ.pop("ROSTER_FORCE_REGISTRATION_OPEN", None)

    def test_24_roster_week_unauthorized_rejected(self):
        """Kiểm tra chặn truy cập xem lịch ca /roster/week khi chưa xác thực token (401)"""
        res = self.client.get("/api/v1/cc/roster/week?week_id=current")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"], "Yêu cầu đăng nhập để xem lịch ca")

    def test_25_admin_update_staff_profile_gender_and_allowed_roles(self):
        """Kiểm tra Quản lý/Admin cập nhật Giới tính, Vị trí và Đa vai trò (allowed_roles) cho nhân sự"""
        token_mgr = create_access_token({"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})
        headers_mgr = {"Authorization": f"Bearer {token_mgr}"}

        # 1. Cập nhật nhân viên 'nhanvien' thành đa nhiệm (vừa Barista vừa Service)
        res_up = self.client.post("/api/v1/cc/admin/update-staff-profile", headers=headers_mgr, json={
            "username": "nhanvien",
            "full_name": "Nhân Viên",
            "gender": "NU",
            "position": "BARISTA",
            "allowed_roles": ["BARISTA", "SERVICE"]
        })
        self.assertEqual(res_up.status_code, 200)
        up_data = res_up.json()
        self.assertTrue(up_data["success"])
        self.assertEqual(up_data["account"]["gender"], "NU")
        self.assertEqual(up_data["account"]["position"], "BARISTA")
        self.assertEqual(up_data["account"]["allowed_roles"], ["BARISTA", "SERVICE"])

        # 2. Tạo nhân viên mới với giới tính và đa vai trò
        res_create = self.client.post("/api/v1/cc/admin/create-staff-account", headers=headers_mgr, json={
            "username": "testmultirole",
            "full_name": "Nhân Viên Thử Nghiệm",
            "pin": "1234",
            "gender": "NAM",
            "position": "SERVICE",
            "allowed_roles": ["SERVICE", "BARISTA"],
            "sheet_names": ["Nhân Viên Thử Nghiệm"]
        })
        self.assertEqual(res_create.status_code, 200)
        cr_data = res_create.json()
        self.assertTrue(cr_data["success"])
        self.assertEqual(cr_data["account"]["gender"], "NAM")
        self.assertEqual(cr_data["account"]["allowed_roles"], ["SERVICE", "BARISTA"])

    @classmethod
    def tearDownClass(cls):
        for f in [test_auth_file, test_auth_file + ".lock"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        if _orig_auth_file is not None:
            os.environ["AUTH_FILE"] = _orig_auth_file
        else:
            os.environ.pop("AUTH_FILE", None)

if __name__ == "__main__":
    unittest.main()


