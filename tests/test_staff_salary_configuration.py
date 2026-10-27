import unittest
import os
import json
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_super_secure_key_1234567890"
os.environ["ADMIN_PASSWORD"] = "test_admin_261109"

import tempfile
_orig_auth_file = os.environ.get("AUTH_FILE")
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
test_auth_file = os.path.join(tempfile.gettempdir(), "mock_salary_config_auth.json")
os.environ["AUTH_FILE"] = test_auth_file

mock_auth_data = {
    "staff_accounts": {
        "admin": {
            "full_name": "Quản Trị Viên",
            "pin": "test_admin_261109",
            "role": "ADMIN",
            "status": "ACTIVE"
        },
        "mgr_test": {
            "full_name": "Quản Lý Test",
            "pin": "2222",
            "role": "MANAGER",
            "status": "ACTIVE"
        },
        "barista_test": {
            "full_name": "Trần Thị Barista",
            "pin": "1234",
            "role": "STAFF",
            "position": "BARISTA",
            "allowed_roles": ["BARISTA"],
            "hourly_rate": 17000,
            "status": "ACTIVE"
        }
    }
}
with open(test_auth_file, "w", encoding="utf-8") as f:
    json.dump(mock_auth_data, f, ensure_ascii=False, indent=2)

import sys
sys.path.insert(0, os.path.join(project_root, "backend"))
from main import app
from routers.fnb_ops import create_access_token
from services.payroll_calc import calculate_staff_payslip_breakdown, get_configured_role_rates

class TestStaffSalaryConfiguration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_auth = os.environ.get("AUTH_FILE")
        os.environ["AUTH_FILE"] = test_auth_file
        with open(test_auth_file, "w", encoding="utf-8") as f:
            json.dump(mock_auth_data, f, ensure_ascii=False, indent=2)
        cls.client = TestClient(app)
        # Login admin
        login_res = cls.client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "test_admin_261109"})
        cls.admin_token = login_res.json()["access_token"]
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

    @classmethod
    def tearDownClass(cls):
        if cls.orig_auth:
            os.environ["AUTH_FILE"] = cls.orig_auth
        else:
            os.environ.pop("AUTH_FILE", None)
        if os.path.exists(test_auth_file):
            try:
                os.remove(test_auth_file)
            except Exception:
                pass

    def setUp(self):
        auth_file = os.environ.get("AUTH_FILE", test_auth_file)
        if os.path.exists(auth_file):
            try:
                with open(auth_file, "r", encoding="utf-8") as f:
                    auth = json.load(f)
                accs = auth.get("staff_accounts", {})
                for u in ["staffdef17k", "staffcustom19k"]:
                    accs.pop(u, None)
                with open(auth_file, "w", encoding="utf-8") as f:
                    json.dump(auth, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def test_01_create_staff_account_default_hourly_rate_17k(self):
        """Khi tạo tài khoản mới không truyền hourly_rate, hệ thống mặc định gán 17.000đ"""
        import time
        uname = f"stfdef{int(time.time() * 1000) % 1000000}"
        res = self.client.post(
            "/api/v1/cc/admin/create-staff-account",
            headers=self.admin_headers,
            json={
                "username": uname,
                "full_name": "Nhân Viên Mặc Định 17K",
                "pin": "1111",
                "gender": "NAM",
                "position": "SERVICE"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["account"]["hourly_rate"], 17000)

    def test_02_create_staff_account_custom_hourly_rate(self):
        """Khi tạo tài khoản mới có truyền hourly_rate riêng (vd 19.000đ), hệ thống lưu chuẩn xác"""
        import time
        uname = f"stfcust{int(time.time() * 1000) % 1000000}"
        res = self.client.post(
            "/api/v1/cc/admin/create-staff-account",
            headers=self.admin_headers,
            json={
                "username": uname,
                "full_name": "Nhân Viên Lương 19K",
                "pin": "1111",
                "gender": "NU",
                "position": "BARISTA",
                "hourly_rate": 19000
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["account"]["hourly_rate"], 19000)

    def test_03_update_staff_profile_hourly_rate(self):
        """Quản lý chỉnh sửa hồ sơ nhân viên để nâng lương từ 17k lên 20k"""
        import time
        uname = f"stfup{int(time.time() * 1000) % 1000000}"
        # Tạo nhân sự trước
        self.client.post(
            "/api/v1/cc/admin/create-staff-account",
            headers=self.admin_headers,
            json={
                "username": uname,
                "full_name": "Nhân Viên Lên Lương",
                "pin": "1111",
                "gender": "NAM",
                "position": "SERVICE"
            }
        )
        res = self.client.post(
            "/api/v1/cc/admin/update-staff-profile",
            headers=self.admin_headers,
            json={
                "username": uname,
                "full_name": "Nhân Viên Lên Lương Đã Duyệt",
                "hourly_rate": 20000,
                "phone": "0987654321"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["account"]["hourly_rate"], 20000)
        self.assertEqual(data["account"]["phone"], "0987654321")

    def test_04_payroll_calc_eliminates_22k_for_barista(self):
        """
        Kiểm tra nghiệp vụ tính lương:
        Nhân sự làm ca Pha chế (BAR) nhưng quán setup 17k -> toàn bộ ca tính 17.000đ/h,
        tuyệt đối không bị nâng ngầm lên 22.000đ/h.
        """
        rates = get_configured_role_rates({})
        self.assertEqual(rates["BAR"], 17000)
        self.assertEqual(rates["SERVICE"], 17000)

        # Mock data ca làm việc: 1 ca BAR 5 tiếng = 300 phút (06:00 - 11:00)
        mock_data = {
            "DỮ LIỆU": [
                ["STT", "NGÀY", "NHÂN VIÊN", "CA", "CHECK IN", "CHECK OUT", "GIỜ CÔNG", "GHI CHÚ", "THÁNG"],
                ["1", "10/10/2026", "Trần Thị Barista", "Ca Sáng", "06:00", "11:00", "300", "BARISTA", "10"]
            ],
            "NHÂN VIÊN": [
                ["STT", "HỌ TÊN", "CHỨC VỤ", "LƯƠNG/H"],
                ["1", "Trần Thị Barista", "Pha chế", "17000"]
            ]
        }
        staff_accounts = {
            "barista_test": {
                "full_name": "Trần Thị Barista",
                "hourly_rate": 17000,
                "position": "BARISTA"
            }
        }

        payroll = calculate_staff_payslip_breakdown(
            staff_name="Trần Thị Barista",
            month="10",
            data_json=mock_data,
            staff_accounts=staff_accounts
        )

        # 5 tiếng * 17.000đ = 85.000đ (nếu bị 22k sẽ là 110.000đ)
        self.assertEqual(payroll["base_wage"], 17000)
        self.assertEqual(payroll["role_breakdown"]["bar"]["rate"], 17000)
        self.assertEqual(payroll["standard_pay"], 85000.0)

    def test_05_payroll_calc_with_custom_staff_rate(self):
        """Nhân viên có lương riêng 25k/h thì được tính đúng 25k/h cho mọi ca"""
        mock_data = {
            "DỮ LIỆU": [
                ["STT", "NGÀY", "NHÂN VIÊN", "CA", "CHECK IN", "CHECK OUT", "GIỜ CÔNG", "GHI CHÚ", "THÁNG"],
                ["1", "12/10/2026", "Chuyên Gia Pha Chế", "Ca Tối", "17:00", "22:00", "300", "BARISTA", "10"]
            ]
        }
        staff_accounts = {
            "pro_barista": {
                "full_name": "Chuyên Gia Pha Chế",
                "hourly_rate": 25000,
                "position": "BARISTA"
            }
        }

        payroll = calculate_staff_payslip_breakdown(
            staff_name="Chuyên Gia Pha Chế",
            month="10",
            data_json=mock_data,
            staff_accounts=staff_accounts
        )

        # 5 tiếng * 25.000đ = 125.000đ
        self.assertEqual(payroll["base_wage"], 25000)
        self.assertEqual(payroll["role_breakdown"]["bar"]["rate"], 25000)
        self.assertEqual(payroll["standard_pay"], 125000.0)

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
