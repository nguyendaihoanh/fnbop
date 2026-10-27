import sys
import unittest
import os
import json
from datetime import datetime
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from main import app
import routers.attendance as att
from routers.fnb_ops import create_access_token

client = TestClient(app)

class TestShiftReopenAndDelete(unittest.TestCase):
    def setUp(self):
        self.original_logs = att.load_attendance_logs()
        self.admin_token = create_access_token({"sub": "admin", "role": "ADMIN"})
        self.staff_token = create_access_token({"sub": "nhanvien", "role": "STAFF"})
        
        # Create a sample closed shift for nhanvien today
        now = datetime.now()
        self.today_str = now.strftime("%d/%m/%Y")
        self.test_record = {
            "id": f"ATT_TEST_{now.strftime('%Y%m%d%H%M%S')}_nhanvien",
            "username": "nhanvien",
            "display_name": "Nhân Viên",
            "role": "Phục vụ",
            "date": self.today_str,
            "shift_key": "toi",
            "shift_name": "Ca Tối",
            "checkin_time": "17:21",
            "checkout_time": "17:21",
            "total_mins": 0,
            "is_late": False,
            "is_early_checkout": True,
            "created_at": now.isoformat(),
            "closed_by": "STAFF"
        }
        att.save_attendance_logs([self.test_record])

    def tearDown(self):
        att.save_attendance_logs(self.original_logs)

    def test_reopen_shift_with_admin_token(self):
        res = client.post(
            "/api/v1/cc/attendance/manager/reopen-shift",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"record_id": self.test_record["id"], "username": "nhanvien"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIsNone(data["record"]["checkout_time"])
        self.assertIsNone(data["record"]["total_mins"])
        self.assertEqual(data["record"]["reopened_by"], "MANAGER_admin")

    def test_reopen_shift_with_manager_pin(self):
        # Staff calls with manager PIN (8888 is manager's PIN)
        res = client.post(
            "/api/v1/cc/attendance/manager/reopen-shift",
            json={
                "record_id": self.test_record["id"],
                "username": "nhanvien",
                "manager_pin": "8888"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIsNone(data["record"]["checkout_time"])

    def test_reopen_shift_unauthorized(self):
        # Staff calls with no manager PIN and staff token
        res = client.post(
            "/api/v1/cc/attendance/manager/reopen-shift",
            headers={"Authorization": f"Bearer {self.staff_token}"},
            json={"record_id": self.test_record["id"], "username": "nhanvien"}
        )
        self.assertEqual(res.status_code, 403)

    def test_delete_shift_with_admin_token(self):
        res = client.post(
            "/api/v1/cc/attendance/manager/delete-shift",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"record_id": self.test_record["id"], "username": "nhanvien"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        
        # Verify log is gone
        logs = att.load_attendance_logs()
        self.assertEqual(len(logs), 0)

    def test_delete_shift_with_manager_pin(self):
        res = client.post(
            "/api/v1/cc/attendance/manager/delete-shift",
            json={
                "record_id": self.test_record["id"],
                "username": "nhanvien",
                "manager_pin": "8888"
            }
        )
        self.assertEqual(res.status_code, 200)
        logs = att.load_attendance_logs()
        self.assertEqual(len(logs), 0)

if __name__ == "__main__":
    unittest.main()
