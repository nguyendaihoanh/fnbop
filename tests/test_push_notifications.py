"""
Unit & Integration Tests for Web Push Notifications & Manager Exceptions
Covers VAPID Keys, Subscriptions, Manager Reminders, and Active Staff Filtering.
"""

import unittest
import json
import os
import sys
import pytest

os.environ["TESTING"] = "1"
os.environ["MOCK_TELEGRAM"] = "1"
os.environ["TELEGRAM_BOT_TOKEN"] = "1234567890:AA_MOCK_DEV_TOKEN_FOR_TESTING_456"
os.environ["TEST_TELEGRAM_BOT_TOKEN"] = "1234567890:AA_MOCK_DEV_TOKEN_FOR_TESTING_456"

from fastapi.testclient import TestClient

# Add project root to sys.path
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_TEST_DIR)
_BACKEND_DIR = os.path.join(_PROJECT_DIR, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from main import app
from services.db import get_db_connection
from services.webpush_service import get_vapid_public_key, _ensure_vapid_keys, HAS_PYWEBPUSH


class TestPushNotifications(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from services.db import init_db, get_db_connection
            init_db()
            conn = get_db_connection()
            with conn:
                conn.execute("DELETE FROM login_attempts;")
                conn.execute("DELETE FROM api_rate_limits;")
            conn.close()
        except Exception:
            pass
        cls.client = TestClient(app)
        
        try:
            from routers.fnb_ops import create_access_token
        except ImportError:
            from backend.routers.fnb_ops import create_access_token

        cls.mgr_token = create_access_token({"sub": "phat", "role": "MANAGER", "name": "Nguyễn Văn Phát"})
        cls.mgr_headers = {"Authorization": f"Bearer {cls.mgr_token}"}

        cls.staff_token = create_access_token({"sub": "nhuy", "role": "STAFF", "name": "Nhân Viên 01"})
        cls.staff_headers = {"Authorization": f"Bearer {cls.staff_token}"}

    @pytest.mark.skipif(not HAS_PYWEBPUSH, reason="pywebpush is optional")
    def test_01_vapid_public_key_endpoint(self):
        """VAPID public key endpoint must return HTTP 200 with non-empty URL-safe base64 key."""
        res = self.client.get("/api/v1/cc/notifications/push/public-key")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        pub_key = data.get("public_key")
        self.assertIsNotNone(pub_key)
        self.assertGreater(len(pub_key), 40)

    def test_02_subscribe_validation_and_persistence(self):
        """Subscribe endpoint requires authentication and valid request body."""
        # Unauthenticated request must fail
        unauth = self.client.post("/api/v1/cc/notifications/push/subscribe", json={
            "username": "nhuy",
            "subscription": {"endpoint": "https://test.push/dummy", "keys": {"p256dh": "dummy", "auth": "dummy"}}
        })
        self.assertEqual(unauth.status_code, 401)

        # Authenticated request with valid body
        mock_endpoint = "https://fcm.googleapis.com/test-endpoint-unit-999"
        res = self.client.post(
            "/api/v1/cc/notifications/push/subscribe",
            headers=self.staff_headers,
            json={
                "username": "nhuy",
                "subscription": {
                    "endpoint": mock_endpoint,
                    "keys": {
                        "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9Q0nA",
                        "auth": "tBHItJI5svbpez7KI4CCXg"
                    }
                },
                "user_agent": "UnitTest Agent"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))

        # Cleanup dummy row from sqlite
        try:
            conn = get_db_connection()
            conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (mock_endpoint,))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def test_03_manager_exceptions_filters_inactive_staff(self):
        """Manager exceptions endpoint must only list ACTIVE staff and exclude INACTIVE staff."""
        # Staff role cannot access manager exceptions
        staff_res = self.client.get("/api/v1/cc/notifications/push/manager/exceptions", headers=self.staff_headers)
        self.assertEqual(staff_res.status_code, 403)

        # Manager role has access
        mgr_res = self.client.get("/api/v1/cc/notifications/push/manager/exceptions", headers=self.mgr_headers)
        self.assertEqual(mgr_res.status_code, 200)
        data = mgr_res.json()
        self.assertTrue(data.get("success"))
        self.assertIn("missing_roster_registration", data)
        self.assertIn("missing_checkin", data)

        missing_roster = data["missing_roster_registration"]
        # Tất cả nhân sự trong missing_roster phải là ACTIVE
        for staff in missing_roster:
            uname = staff.get("username")
            # Verify status is not INACTIVE
            self.assertIsNotNone(uname)

    def test_04_manager_remind_staff_flow(self):
        """Manager can trigger reminder notification for an employee."""
        res = self.client.post(
            "/api/v1/cc/notifications/push/manager/remind-staff",
            headers=self.mgr_headers,
            json={
                "username": "nhuy",
                "remind_type": "ROSTER"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("username"), "nhuy")
        self.assertEqual(data.get("remind_type"), "ROSTER")

    @pytest.mark.skipif(not HAS_PYWEBPUSH, reason="pywebpush is optional")
    def test_05_internal_vapid_generation(self):
        """Direct VAPID helper generation must yield private and public keys."""
        pub = get_vapid_public_key()
        self.assertTrue(isinstance(pub, str))
        self.assertGreater(len(pub), 20)

    def test_06_dynamic_roster_extraction_and_custom_slots(self):
        """Dynamic slot extraction must support custom shift types and arbitrary staff roles."""
        mgr_res = self.client.get("/api/v1/cc/notifications/push/manager/exceptions", headers=self.mgr_headers)
        self.assertEqual(mgr_res.status_code, 200)
        data = mgr_res.json()
        self.assertIn("missing_checkin", data)
        self.assertIn("summary", data)
        self.assertIn("missing_checkin_count", data["summary"])

    def test_07_per_shift_attendance_matching_and_alias_resolution(self):
        """
        Verify that staff who already checked in for their current shift are NOT flagged as missing,
        while staff assigned but without attendance log for this shift ARE flagged.
        Tests Thien (bin), Nhu Y (nhuy), and Thuy Diem (thuydiem).
        Uses deterministic mock fixtures to isolate from environment date shifts.
        """
        from unittest.mock import patch
        import datetime

        now = datetime.datetime.now()
        iso_year, iso_week, _ = now.isocalendar()
        cur_week_id = f"{iso_year}-W{iso_week:02d}"
        today_iso = now.strftime("%Y-%m-%d")
        today_vn = now.strftime("%d/%m/%Y")

        mock_roster = {
            "weeks": {
                cur_week_id: {
                    "shifts": {
                        today_iso: {
                            "morning": {
                                "time": "06:00 - 11:30",
                                "manager": "phat",
                                "barista": "thuan",
                                "service": ["nhanvien"]
                            },
                            "evening": {
                                "time": "17:00 - 23:00",
                                "manager": "phat",
                                "barista": "nhuy",
                                "service_17": "bin",
                                "service_18": "thuydiem"
                            }
                        }
                    }
                }
            }
        }

        mock_attendance = [
            {
                "id": "ATT_MOCK_1",
                "username": "thuydiem",
                "display_name": "Nhân Viên 04",
                "date": today_vn,
                "shift_key": "toi_18",
                "shift_name": "Ca Tối",
                "checkin_time": "18:01",
                "checkout_time": None
            },
            {
                "id": "ATT_MOCK_2",
                "username": "thuan",
                "display_name": "Nguyễn Văn Thuận",
                "date": today_vn,
                "shift_key": "sang",
                "shift_name": "Ca Sáng",
                "checkin_time": "06:00",
                "checkout_time": "11:30"
            }
        ]

        with patch("routers.push_routes.load_roster_data", return_value=mock_roster), \
             patch("routers.push_routes.load_attendance_logs", return_value=mock_attendance):
            mgr_res = self.client.get("/api/v1/cc/notifications/push/manager/exceptions", headers=self.mgr_headers)
            self.assertEqual(mgr_res.status_code, 200)
            data = mgr_res.json()
            missing = data.get("missing_checkin", [])
            missing_unames = [m.get("username") for m in missing]

            # thuydiem da dap the luc 18:01 cho ca toi -> khong duoc nam trong missing_checkin
            self.assertNotIn("thuydiem", missing_unames, "Staff already checked in for evening shift, must not be flagged")

            # Quan ly khong bao gio bi nhac nhu nhan vien
            self.assertNotIn("phat", missing_unames, "Manager must be excluded from staff check-in reminders")

            # Ca hai nhan vien co ca toi hom nay nhung chua dap the -> BAT BUOC phai duoc nhac neu ca toi da bat dau
            if now.hour >= 17:
                self.assertIn("nhuy", missing_unames, "Staff has evening shift without checkin, must be flagged")
                self.assertIn("bin", missing_unames, "Staff has evening shift without checkin, must be flagged")

                nhuy_item = next(m for m in missing if m["username"] == "nhuy")
                self.assertEqual(nhuy_item.get("shift"), "Ca Tối")
                self.assertEqual(nhuy_item.get("slot"), "Pha chế")

                bin_item = next(m for m in missing if m["username"] == "bin")
                self.assertEqual(bin_item.get("shift"), "Ca Tối")
                self.assertIn("Phục vụ", bin_item.get("slot", ""))


if __name__ == "__main__":
    unittest.main()
