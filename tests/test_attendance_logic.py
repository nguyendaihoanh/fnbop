"""
Unit and Integration tests for Attendance & SOP Router (FnBOps)
Compatible with Python 3.9+ standard unittest framework.
"""

import sys
import os
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
os.environ["MOCK_TELEGRAM"] = "1"
os.environ["DISABLE_BACKGROUND_WORKER"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from main import app
import routers.attendance as att_router
import routers.roster as r_module
from routers.fnb_ops import create_access_token
from services.storage import safe_json_read, safe_json_write


class TestAttendanceLogic(unittest.TestCase):
    def setUp(self):
        try:
            from services.db import clear_all_rate_limits
            clear_all_rate_limits()
        except Exception:
            pass
        self.client = TestClient(app)
        self.temp_dir = tempfile.mkdtemp()
        
        self.test_hb_file = os.path.join(self.temp_dir, "pos_heartbeat.json")
        self.test_logs_file = os.path.join(self.temp_dir, "attendance_logs.json")
        self.test_sop_file = os.path.join(self.temp_dir, "sop_templates.json")
        
        real_sop = os.path.join(os.path.dirname(__file__), "..", "data", "sop_templates.json")
        if os.path.exists(real_sop):
            shutil.copyfile(real_sop, self.test_sop_file)
            
        self.orig_hb = att_router.HEARTBEAT_FILE
        self.orig_logs = att_router.LOGS_FILE
        self.orig_sop = att_router.SOP_FILE
        self.orig_ip = att_router._cached_cafe_ip
        
        self.orig_auth_file = os.getenv("AUTH_FILE")
        self.test_auth_file = os.path.join(self.temp_dir, "staff_auth.json")
        real_auth = os.path.join(os.path.dirname(__file__), "..", "data", "staff_auth.json")
        auth_data = safe_json_read(real_auth, default={"payroll_locks": {}, "staff_accounts": {}})
        staff_accs = auth_data.setdefault("staff_accounts", {})
        for u in ["khoa", "nhanvien02", "hung", "nhanvien03", "phuongoanh", "nhanvien05", "manager"]:
            if u in staff_accs:
                staff_accs[u]["status"] = "ACTIVE"
            else:
                staff_accs[u] = {"full_name": u, "role": "STAFF", "status": "ACTIVE", "pin": "1234"}
        staff_accs["test_inactive_user"] = {"full_name": "Test Inactive", "role": "STAFF", "status": "INACTIVE", "pin": "9999"}
        for i in range(30):
            u = f"staff_user_{i}"
            if u not in staff_accs:
                staff_accs[u] = {"full_name": u, "role": "STAFF", "status": "ACTIVE", "pin": "1234"}
        for i in range(40):
            u = f"fullload_user_{i:02d}"
            if u not in staff_accs:
                staff_accs[u] = {"full_name": u, "role": "STAFF", "status": "ACTIVE", "pin": "1234"}
        safe_json_write(self.test_auth_file, auth_data)
        os.environ["AUTH_FILE"] = self.test_auth_file

        att_router.HEARTBEAT_FILE = self.test_hb_file
        att_router.LOGS_FILE = self.test_logs_file
        att_router.SOP_FILE = self.test_sop_file
        att_router._cached_cafe_ip = "203.0.113.10"

        self.orig_post = self.client.post
        def custom_post(url, *args, **kwargs):
            headers = kwargs.get("headers")
            if headers is None:
                headers = {}
                kwargs["headers"] = headers
            json_data = kwargs.get("json") or {}
            if url in ["/api/v1/cc/attendance/checkin", "/api/v1/cc/attendance/checkout"] and "Authorization" not in headers:
                uname = json_data.get("username", "phuongoanh")
                token = create_access_token({"sub": uname, "role": "STAFF"})
                headers["Authorization"] = f"Bearer {token}"
            return self.orig_post(url, *args, **kwargs)
        self.client.post = custom_post

    def tearDown(self):
        self.client.post = self.orig_post
        att_router.HEARTBEAT_FILE = self.orig_hb
        att_router.LOGS_FILE = self.orig_logs
        att_router.SOP_FILE = self.orig_sop
        att_router._cached_cafe_ip = self.orig_ip
        if self.orig_auth_file is not None:
            os.environ["AUTH_FILE"] = self.orig_auth_file
        else:
            os.environ.pop("AUTH_FILE", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pos_heartbeat_syncs_cafe_ip(self):
        secret = getattr(att_router, "POS_SECRET", "fnbop_pos_secret_2026")
        res = self.client.post(
            "/api/v1/cc/attendance/pos/heartbeat",
            headers={"X-POS-Secret": secret},
            json={"override_ip": "203.0.113.99"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["cafe_ip"], "203.0.113.99")
        self.assertEqual(att_router.get_current_cafe_ip(), "203.0.113.99")

    def test_pos_heartbeat_invalid_secret_rejected(self):
        res = self.client.post(
            "/api/v1/cc/attendance/pos/heartbeat",
            headers={"X-POS-Secret": "wrong_secret"}
        )
        self.assertEqual(res.status_code, 403)

    def test_checkin_blocked_when_outside_cafe_wifi(self):
        att_router.set_current_cafe_ip("203.0.113.10")
        res = self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "171.244.50.12"},
            json={"username": "nhanvien02", "role": "Pha chế", "dev_override_wifi": False}
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("Vui lòng kết nối WiFi", res.json()["detail"])

    def test_is_matching_cafe_wifi_strict_exact(self):
        """Verifies strict 100% exact match and elimination of /24 subnet match."""
        # Exact match
        self.assertTrue(att_router.is_matching_cafe_wifi("203.0.113.10", "203.0.113.10"))
        self.assertTrue(att_router.is_matching_cafe_wifi("  203.0.113.10  ", "203.0.113.10"))
        
        # Subnet /24 match must now return FALSE (Hardened)
        self.assertFalse(att_router.is_matching_cafe_wifi("203.0.113.11", "203.0.113.10"))
        self.assertFalse(att_router.is_matching_cafe_wifi("203.0.113.1", "203.0.113.10"))
        
        # Completely different
        self.assertFalse(att_router.is_matching_cafe_wifi("1.2.3.4", "203.0.113.10"))
        
        # Empty or None
        self.assertFalse(att_router.is_matching_cafe_wifi("", "203.0.113.10"))
        self.assertFalse(att_router.is_matching_cafe_wifi(None, "203.0.113.10"))
        self.assertFalse(att_router.is_matching_cafe_wifi("203.0.113.10", None))

    def test_checkin_blocked_when_in_same_subnet_24(self):
        """Staff in same /24 subnet but different host IP is rejected."""
        att_router.set_current_cafe_ip("203.0.113.10")
        res = self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.88"},
            json={"username": "nhanvien02", "role": "Pha chế", "dev_override_wifi": False}
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("Vui lòng kết nối WiFi", res.json()["detail"])

    def test_checkin_on_time_morning_shift(self):
        att_router.set_current_cafe_ip("203.0.113.10")
        res = self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={
                "username": "phuongoanh",
                "display_name": "Nhân Viên 02",
                "role": "Pha chế",
                "shift_override": "sang",
                "custom_time_str": "06:05"
            }
        )
        self.assertEqual(res.status_code, 200)
        rec = res.json()["record"]
        self.assertEqual(rec["status"], "ON_TIME")
        self.assertFalse(rec["is_late"])
        self.assertEqual(rec["late_mins"], 0)
        self.assertEqual(rec["checkin_time"], "06:05")

    def test_checkin_inactive_staff_rejected(self):
        att_router.set_current_cafe_ip("203.0.113.10")
        res = self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={
                "username": "test_inactive_user",
                "role": "Pha chế",
                "custom_time_str": "06:05"
            }
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("nghỉ việc", res.json().get("detail", ""))

    def test_checkin_late_morning_shift(self):
        att_router.set_current_cafe_ip("203.0.113.10")
        res = self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={
                "username": "nhanvien03",
                "role": "Phục vụ",
                "shift_override": "sang",
                "custom_time_str": "06:25"
            }
        )
        self.assertEqual(res.status_code, 200)
        rec = res.json()["record"]
        self.assertEqual(rec["status"], "LATE")
        self.assertTrue(rec["is_late"])
        self.assertEqual(rec["late_mins"], 25)
        self.assertEqual(rec["checkin_time"], "06:25")

    def test_checkout_calculates_total_minutes(self):
        att_router.set_current_cafe_ip("203.0.113.10")
        self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={"username": "nhanvien05", "role": "Thu ngân", "custom_time_str": "06:00"}
        )
        res_out = self.client.post(
            "/api/v1/cc/attendance/checkout",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={"username": "nhanvien05", "custom_time_str": "11:30"}
        )
        self.assertEqual(res_out.status_code, 200)
        rec = res_out.json()["record"]
        self.assertEqual(rec["checkout_time"], "11:30")
        self.assertEqual(rec["total_mins"], 330)
        self.assertEqual(rec["closed_by"], "STAFF")

    def test_auto_close_rule_after_48h(self):
        old_time_str = (datetime.now() - timedelta(hours=50)).isoformat()
        old_records = [
            {
                "id": "ATT_OLD_MORN",
                "username": "nhanvien17",
                "shift_key": "sang",
                "checkin_time": "06:00",
                "checkout_time": None,
                "created_at": old_time_str
            },
            {
                "id": "ATT_OLD_EVE",
                "username": "nhanvien15",
                "shift_key": "toi",
                "checkin_time": "17:00",
                "checkout_time": None,
                "created_at": old_time_str
            }
        ]
        att_router.save_attendance_logs(old_records)
        
        # 1. Unauthenticated -> 401
        res_unauth = self.client.post("/api/v1/cc/attendance/manager/auto-close-check")
        self.assertEqual(res_unauth.status_code, 401)

        # 2. Staff -> 403
        staff_token = create_access_token({"sub": "nhanvien03", "role": "STAFF", "name": "Nhân Viên 03"})
        res_staff = self.client.post(
            "/api/v1/cc/attendance/manager/auto-close-check",
            headers={"Authorization": f"Bearer {staff_token}"}
        )
        self.assertEqual(res_staff.status_code, 403)

        # 3. Manager -> 200
        mgr_token = create_access_token({"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})
        res = self.client.post(
            "/api/v1/cc/attendance/manager/auto-close-check",
            headers={"Authorization": f"Bearer {mgr_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["closed_count"], 2)
        
        updated_logs = att_router.load_attendance_logs()
        morn_rec = next(r for r in updated_logs if r["id"] == "ATT_OLD_MORN")
        eve_rec = next(r for r in updated_logs if r["id"] == "ATT_OLD_EVE")
        
        self.assertEqual(morn_rec["checkout_time"], "11:00")
        self.assertEqual(morn_rec["closed_by"], "AUTO_CLOSE_48H")
        self.assertEqual(eve_rec["checkout_time"], "22:00")
        self.assertEqual(eve_rec["closed_by"], "AUTO_CLOSE_48H")

    def test_sop_retrieval_by_role(self):
        res_bar = self.client.get("/api/v1/cc/attendance/sop?role=Pha+chế")
        self.assertEqual(res_bar.status_code, 200)
        d_bar = res_bar.json()
        self.assertEqual(d_bar["role_key"], "pha_che")
        self.assertIn("open", d_bar["sop"]["phases"])

    def test_early_checkout_requires_confirmation(self):
        att_router.set_current_cafe_ip("203.0.113.10")
        self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={"username": "khoa", "role": "Phục vụ", "custom_time_str": "06:00"}
        )
        # Check out early without confirm -> 400
        res_unconfirmed = self.client.post(
            "/api/v1/cc/attendance/checkout",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={"username": "khoa", "custom_time_str": "06:20", "confirm_early": False}
        )
        self.assertEqual(res_unconfirmed.status_code, 400)
        self.assertIn("dưới 60 phút", res_unconfirmed.json()["detail"])

        # Check out early with confirm -> 200
        res_confirmed = self.client.post(
            "/api/v1/cc/attendance/checkout",
            headers={"CF-Connecting-IP": "203.0.113.10"},
            json={"username": "khoa", "custom_time_str": "06:20", "confirm_early": True}
        )
        self.assertEqual(res_confirmed.status_code, 200)
        rec = res_confirmed.json()["record"]
        self.assertEqual(rec["total_mins"], 20)
        self.assertTrue(rec["is_early_checkout"])

    def test_total_mins_calculation_and_over_7h_safeguard(self):
        att_router.set_current_cafe_ip("203.0.113.10")
        mgr_token = create_access_token({"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})
        staff_token_02 = create_access_token({"sub": "nhanvien02", "role": "STAFF", "name": "Nhân Viên 02"})
        staff_token_03 = create_access_token({"sub": "nhanvien03", "role": "STAFF", "name": "Nhân Viên 03"})

        self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10", "Authorization": f"Bearer {staff_token_02}"},
            json={"username": "nhanvien02", "role": "Phục vụ", "custom_time_str": "06:00"}
        )
        status = self.client.get("/api/v1/cc/attendance/status?username=nhanvien02").json()
        rec_record = status.get("user_record") or status.get("last_closed_record")
        rec_id = rec_record["id"] if rec_record else None

        res_close = self.client.post(
            "/api/v1/cc/attendance/manager/manual-close",
            headers={"Authorization": f"Bearer {mgr_token}"},
            json={"record_id": rec_id, "manual_checkout": "11:30", "manager_note": "Chốt giờ chuẩn"}
        )
        self.assertEqual(res_close.status_code, 200)
        self.assertEqual(res_close.json()["record"]["total_mins"], 330)

        # Normal shift with late clean-up (06:00 to 14:00 = 8h = 480 mins <= 540 mins, should NOT be penalized)
        self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10", "Authorization": f"Bearer {staff_token_03}"},
            json={"username": "nhanvien03", "role": "Phục vụ", "custom_time_str": "06:00", "dev_override_wifi": True}
        )
        res_normal = self.client.post(
            "/api/v1/cc/attendance/checkout",
            headers={"CF-Connecting-IP": "203.0.113.10", "Authorization": f"Bearer {staff_token_03}"},
            json={"username": "nhanvien03", "custom_time_str": "14:00", "dev_override_wifi": True}
        )
        self.assertEqual(res_normal.status_code, 200)
        norm_rec = res_normal.json()["record"]
        self.assertEqual(norm_rec["checkout_time"], "14:00")
        self.assertEqual(norm_rec["total_mins"], 480)

        # Forgotten checkout > 9h / 540 mins (06:00 to 16:00 = 10h = 600 mins, resets to scheduled_end 11:30)
        self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10", "Authorization": f"Bearer {staff_token_03}"},
            json={"username": "nhanvien03", "role": "Phục vụ", "custom_time_str": "06:00", "dev_override_wifi": True}
        )
        res_forgot = self.client.post(
            "/api/v1/cc/attendance/checkout",
            headers={"CF-Connecting-IP": "203.0.113.10", "Authorization": f"Bearer {staff_token_03}"},
            json={"username": "nhanvien03", "custom_time_str": "16:00", "dev_override_wifi": True}
        )
        self.assertEqual(res_forgot.status_code, 200)
        forgot_rec = res_forgot.json()["record"]
        self.assertEqual(forgot_rec["checkout_time"], "11:30")
        self.assertEqual(forgot_rec["total_mins"], 330)

    def test_checkin_checkout_impersonation_blocked(self):
        att_router.set_current_cafe_ip("203.0.113.10")
        token_khoa = create_access_token({"sub": "khoa", "role": "STAFF", "name": "Đăng Khoa"})
        
        res_fake = self.client.post(
            "/api/v1/cc/attendance/checkin",
            headers={"CF-Connecting-IP": "203.0.113.10", "Authorization": f"Bearer {token_khoa}"},
            json={"username": "hung", "role": "Phục vụ", "dev_override_wifi": True}
        )
        self.assertEqual(res_fake.status_code, 403)
        self.assertIn("không thể chấm công thay", res_fake.json()["detail"])

    def test_checkin_service_18_roster_slot_on_time(self):
        """Staff assigned to service_18 (18:00 - 23:00) checking in at 18:05 is ON_TIME."""
        att_router.set_current_cafe_ip("203.0.113.10")
        today_str = datetime.now().strftime("%Y-%m-%d")
        iso_year, iso_week, _ = datetime.now().isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        mock_roster = {
            "weeks": {
                week_id: {
                    "week_id": week_id,
                    "shifts": {
                        today_str: {
                            "evening": {
                                "time": "17:00 - 23:00",
                                "manager": "manager",
                                "service_17": "nhanvien08",
                                "service_18": "nhanvien10"
                            }
                        }
                    }
                }
            }
        }
        with patch.object(r_module, "load_roster_data", return_value=mock_roster):
            res = self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien10", "role": "Phục vụ", "custom_time_str": "18:05"}
            )
            self.assertEqual(res.status_code, 200)
            rec = res.json()["record"]
            self.assertEqual(rec["status"], "ON_TIME")
            self.assertFalse(rec["is_late"])
            self.assertEqual(rec["late_mins"], 0)
            self.assertEqual(rec["roster_slot"], "service_18")
            self.assertEqual(rec["scheduled_start"], "18:00")
            self.assertEqual(rec["scheduled_end"], "23:00")

    def test_checkin_service_18_roster_slot_late(self):
        """Staff assigned to service_18 checking in at 18:25 is LATE by 25 mins."""
        att_router.set_current_cafe_ip("203.0.113.10")
        today_str = datetime.now().strftime("%Y-%m-%d")
        iso_year, iso_week, _ = datetime.now().isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        mock_roster = {
            "weeks": {
                week_id: {
                    "week_id": week_id,
                    "shifts": {
                        today_str: {
                            "evening": {
                                "time": "17:00 - 23:00",
                                "service_18": "nhanvien10"
                            }
                        }
                    }
                }
            }
        }
        with patch.object(r_module, "load_roster_data", return_value=mock_roster):
            res = self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien10", "role": "Phục vụ", "custom_time_str": "18:25"}
            )
            self.assertEqual(res.status_code, 200)
            rec = res.json()["record"]
            self.assertEqual(rec["status"], "LATE")
            self.assertTrue(rec["is_late"])
            self.assertEqual(rec["late_mins"], 25)
            self.assertEqual(rec["roster_slot"], "service_18")

    def test_checkin_service_17_roster_slot(self):
        """Staff in service_17: at 17:08 is ON_TIME, at 17:25 is LATE 25m."""
        att_router.set_current_cafe_ip("203.0.113.10")
        today_str = datetime.now().strftime("%Y-%m-%d")
        iso_year, iso_week, _ = datetime.now().isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        mock_roster = {
            "weeks": {
                week_id: {
                    "week_id": week_id,
                    "shifts": {
                        today_str: {
                            "evening": {
                                "time": "17:00 - 23:00",
                                "service_17": "nhanvien08",
                                "service_18": "nhanvien10"
                            }
                        }
                    }
                }
            }
        }
        with patch.object(r_module, "load_roster_data", return_value=mock_roster):
            res = self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien08", "role": "Phục vụ", "custom_time_str": "17:08"}
            )
            self.assertEqual(res.status_code, 200)
            rec = res.json()["record"]
            self.assertEqual(rec["status"], "ON_TIME")
            self.assertEqual(rec["roster_slot"], "service_17")
            self.assertEqual(rec["scheduled_start"], "17:00")
            self.assertEqual(rec["scheduled_end"], "23:00")

    def test_forgotten_checkout_service_18_resets_to_23h(self):
        """Forgotten checkout (> 7h) in service_18 resets to scheduled_end 23:00 (300 mins)."""
        att_router.set_current_cafe_ip("203.0.113.10")
        today_str = datetime.now().strftime("%Y-%m-%d")
        iso_year, iso_week, _ = datetime.now().isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        mock_roster = {
            "weeks": {
                week_id: {
                    "week_id": week_id,
                    "shifts": {
                        today_str: {
                            "evening": {
                                "time": "17:00 - 23:00",
                                "service_18": "nhanvien10"
                            }
                        }
                    }
                }
            }
        }
        with patch.object(r_module, "load_roster_data", return_value=mock_roster):
            res_in = self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien10", "role": "Phục vụ", "custom_time_str": "18:00"}
            )
            self.assertEqual(res_in.status_code, 200)

            # Check out next day at 04:00 (> 540 mins unclosed, resets to 23:00)
            res_out = self.client.post(
                "/api/v1/cc/attendance/checkout",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien10", "custom_time_str": "04:00", "dev_override_wifi": True}
            )
            self.assertEqual(res_out.status_code, 200)
            rec = res_out.json()["record"]
            self.assertEqual(rec["checkout_time"], "23:00")
            self.assertEqual(rec["total_mins"], 300)

    def test_full_load_concurrent_checkin(self):
        """Stress testing full load: 20 simultaneous concurrent check-in requests."""
        att_router.set_current_cafe_ip("203.0.113.10")
        staff_names = [f"staff_user_{i}" for i in range(20)]
        
        def do_checkin(user):
            return self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": user, "role": "Phục vụ", "shift_override": "sang", "custom_time_str": "06:05"}
            )

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(do_checkin, staff_names))

        for res in results:
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "success")

        # Verify logs file integrity
        saved_logs = att_router.load_attendance_logs()
        self.assertEqual(len(saved_logs), 20)
        checked_users = {r["username"] for r in saved_logs}
        self.assertEqual(checked_users, set(staff_names))

    def test_upcoming_shift_service_18_outside_hours(self):
        """When outside shift hours (e.g. 15:00), staff with evening shift sees upcoming_shift."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        iso_year, iso_week, _ = datetime.now().isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        mock_roster = {
            "weeks": {
                week_id: {
                    "week_id": week_id,
                    "shifts": {
                        today_str: {
                            "evening": {
                                "time": "17:00 - 23:00",
                                "service_18": "nhanvien10"
                            }
                        }
                    }
                }
            }
        }
        with patch.object(r_module, "load_roster_data", return_value=mock_roster):
            res = self.client.get(
                "/api/v1/cc/attendance/status?username=nhanvien10&dev_mode=true&simulated_time=15:00"
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIsNone(data["active_shift"])
            self.assertIsNotNone(data["upcoming_shift"])
            self.assertEqual(data["upcoming_shift"]["slot_type"], "service_18")
            self.assertEqual(data["upcoming_shift"]["official_start"], "18:00")
            self.assertEqual(data["upcoming_shift"]["tolerance_limit"], "18:10")

    def test_simulated_time_detects_service_18_active_shift(self):
        """In dev_mode with simulated_time 18:05, active_shift is detected as service_18."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        iso_year, iso_week, _ = datetime.now().isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        mock_roster = {
            "weeks": {
                week_id: {
                    "week_id": week_id,
                    "shifts": {
                        today_str: {
                            "evening": {
                                "time": "17:00 - 23:00",
                                "service_18": "nhanvien10"
                            }
                        }
                    }
                }
            }
        }
        with patch.object(r_module, "load_roster_data", return_value=mock_roster):
            res = self.client.get(
                "/api/v1/cc/attendance/status?username=nhanvien10&dev_mode=true&simulated_time=18:05"
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIsNotNone(data["active_shift"])
            self.assertEqual(data["active_shift"]["official_start"], "18:00")
            self.assertEqual(data["active_shift"]["tolerance_limit"], "18:10")
            self.assertEqual(data["active_shift"]["slot_type"], "service_18")

    def test_checkin_checkout_service_18_full_shift_300mins(self):
        """E2E test: service_18 staff works from 18:00 to 23:00, gets full 300 minutes (5 hours)."""
        att_router.set_current_cafe_ip("203.0.113.10")
        today_str = datetime.now().strftime("%Y-%m-%d")
        iso_year, iso_week, _ = datetime.now().isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        mock_roster = {
            "weeks": {
                week_id: {
                    "week_id": week_id,
                    "shifts": {
                        today_str: {
                            "evening": {
                                "time": "17:00 - 23:00",
                                "service_18": "nhanvien10"
                            }
                        }
                    }
                }
            }
        }
        with patch.object(r_module, "load_roster_data", return_value=mock_roster):
            # Check-in at 18:00
            res_in = self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien10", "role": "Phục vụ", "custom_time_str": "18:00"}
            )
            self.assertEqual(res_in.status_code, 200)
            in_rec = res_in.json()["record"]
            self.assertEqual(in_rec["status"], "ON_TIME")
            self.assertEqual(in_rec["scheduled_start"], "18:00")
            self.assertEqual(in_rec["scheduled_end"], "23:00")
            self.assertEqual(in_rec["roster_slot"], "service_18")

            # Check-out at 23:00
            res_out = self.client.post(
                "/api/v1/cc/attendance/checkout",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien10", "custom_time_str": "23:00"}
            )
            self.assertEqual(res_out.status_code, 200)
            out_rec = res_out.json()["record"]
            self.assertEqual(out_rec["checkout_time"], "23:00")
            self.assertEqual(out_rec["total_mins"], 300)
            self.assertEqual(out_rec["closed_by"], "STAFF")

    def test_checkin_service_18_boundary_tolerance_limits(self):
        """Boundary test: 18:10 is ON_TIME (0 min late), 18:11 is LATE (11 min late)."""
        att_router.set_current_cafe_ip("203.0.113.10")
        today_str = datetime.now().strftime("%Y-%m-%d")
        iso_year, iso_week, _ = datetime.now().isocalendar()
        week_id = f"{iso_year}-W{iso_week:02d}"

        mock_roster = {
            "weeks": {
                week_id: {
                    "week_id": week_id,
                    "shifts": {
                        today_str: {
                            "evening": {
                                "service_18": "nhanvien10"
                            }
                        }
                    }
                }
            }
        }
        with patch.object(r_module, "load_roster_data", return_value=mock_roster):
            # Check-in exactly at 18:10 (edge of tolerance)
            res1 = self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien10", "role": "Phục vụ", "custom_time_str": "18:10"}
            )
            self.assertEqual(res1.status_code, 200)
            rec1 = res1.json()["record"]
            self.assertEqual(rec1["status"], "ON_TIME")
            self.assertFalse(rec1["is_late"])
            self.assertEqual(rec1["late_mins"], 0)

            # Reset logs for next check
            att_router.save_attendance_logs([])

            # Check-in at 18:11 (1 minute past tolerance -> late 11 minutes from 18:00)
            res2 = self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={"username": "nhanvien10", "role": "Phục vụ", "custom_time_str": "18:11"}
            )
            self.assertEqual(res2.status_code, 200)
            rec2 = res2.json()["record"]
            self.assertEqual(rec2["status"], "LATE")
            self.assertTrue(rec2["is_late"])
            self.assertEqual(rec2["late_mins"], 11)

    def test_full_load_30_staff_checkin_and_checkout_stress(self):
        """Full load stress test: 30 concurrent staff check-in and subsequent check-out."""
        att_router.set_current_cafe_ip("203.0.113.10")
        staff_list = [f"fullload_user_{i:02d}" for i in range(30)]

        # 1. Concurrent check-ins
        def do_checkin(uname):
            return self.client.post(
                "/api/v1/cc/attendance/checkin",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={
                    "username": uname,
                    "role": "Phục vụ",
                    "shift_override": "sang",
                    "custom_time_str": "06:05"
                }
            )

        with ThreadPoolExecutor(max_workers=15) as pool:
            checkin_results = list(pool.map(do_checkin, staff_list))

        for res in checkin_results:
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "success")

        logs_after_in = att_router.load_attendance_logs()
        self.assertEqual(len(logs_after_in), 30)

        # 2. Concurrent check-outs
        def do_checkout(uname):
            return self.client.post(
                "/api/v1/cc/attendance/checkout",
                headers={"CF-Connecting-IP": "203.0.113.10"},
                json={
                    "username": uname,
                    "custom_time_str": "11:30"
                }
            )

        with ThreadPoolExecutor(max_workers=15) as pool:
            checkout_results = list(pool.map(do_checkout, staff_list))

        for res in checkout_results:
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "success")
            self.assertEqual(res.json()["record"]["total_mins"], 325)

        logs_after_out = att_router.load_attendance_logs()
        self.assertEqual(len(logs_after_out), 30)
        for rec in logs_after_out:
            self.assertIsNotNone(rec["checkout_time"])
            self.assertEqual(rec["checkout_time"], "11:30")
            self.assertEqual(rec["total_mins"], 325)


if __name__ == "__main__":
    unittest.main()