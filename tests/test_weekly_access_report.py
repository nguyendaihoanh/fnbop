import os
import sys
import unittest
import tempfile
import sqlite3
import datetime

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
sys.path.insert(0, PROJECT_ROOT)

from backend.services.db import (
    init_db,
    parse_user_agent,
    record_access_audit,
    get_access_audit_logs,
    purge_old_access_audit_logs
)
from scripts.report_weekly_access import (
    get_weekly_window,
    build_weekly_report
)


class TestWeeklyAccessReport(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_fnbop.db")
        init_db(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_parse_user_agent(self):
        # iOS iPhone
        ua_iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        os_name, device = parse_user_agent(ua_iphone)
        self.assertEqual(os_name, "iOS")
        self.assertEqual(device, "Mobile")

        # Android
        ua_android = "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36"
        os_name, device = parse_user_agent(ua_android)
        self.assertEqual(os_name, "Android")
        self.assertEqual(device, "Mobile")

        # Windows Desktop
        ua_win = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0"
        os_name, device = parse_user_agent(ua_win)
        self.assertEqual(os_name, "Windows")
        self.assertEqual(device, "Desktop")

        # macOS Desktop
        ua_mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        os_name, device = parse_user_agent(ua_mac)
        self.assertEqual(os_name, "macOS")
        self.assertEqual(device, "Desktop")

        # Empty / None
        self.assertEqual(parse_user_agent(""), ("Unknown", "Unknown"))
        self.assertEqual(parse_user_agent(None), ("Unknown", "Unknown"))

    def test_record_and_query_audit_logs(self):
        # Record sample logs
        record_access_audit(
            username="linh_bar",
            full_name="Trần Thị Mỹ Linh",
            action="LOGIN_SUCCESS",
            client_ip="116.96.78.89",
            is_cafe_wifi=True,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5)",
            db_path=self.db_path
        )
        record_access_audit(
            username="vinh_phucvu",
            full_name="Nguyễn Văn Vinh",
            action="ATTENDANCE_BLOCKED_WIFI",
            client_ip="42.112.5.10",
            is_cafe_wifi=False,
            user_agent="Mozilla/5.0 (Linux; Android 14)",
            details="Cố chấm công ngoài quán",
            db_path=self.db_path
        )

        now = datetime.datetime.now()
        start = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        logs = get_access_audit_logs(start, end, db_path=self.db_path)
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["username"], "linh_bar")
        self.assertEqual(logs[0]["os_name"], "iOS")
        self.assertEqual(logs[0]["is_cafe_wifi"], 1)

        self.assertEqual(logs[1]["username"], "vinh_phucvu")
        self.assertEqual(logs[1]["os_name"], "Android")
        self.assertEqual(logs[1]["action"], "ATTENDANCE_BLOCKED_WIFI")
        self.assertEqual(logs[1]["is_cafe_wifi"], 0)

    def test_purge_old_audit_logs(self):
        conn = sqlite3.connect(self.db_path)
        # Insert one 100-day-old log and one fresh log
        old_time = (datetime.datetime.now() - datetime.timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
        fresh_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            "INSERT INTO access_audit_logs (timestamp, username, full_name, action, tenant_id) VALUES (?, ?, ?, ?, ?)",
            (old_time, "old_user", "Old Staff", "LOGIN_SUCCESS", "default")
        )
        conn.execute(
            "INSERT INTO access_audit_logs (timestamp, username, full_name, action, tenant_id) VALUES (?, ?, ?, ?, ?)",
            (fresh_time, "new_user", "New Staff", "LOGIN_SUCCESS", "default")
        )
        conn.commit()
        conn.close()

        # Purge logs older than 90 days
        deleted = purge_old_access_audit_logs(retention_days=90, db_path=self.db_path)
        self.assertEqual(deleted, 1)

        logs = get_access_audit_logs("2000-01-01 00:00:00", "2099-01-01 00:00:00", db_path=self.db_path)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["username"], "new_user")

    def test_build_weekly_report(self):
        start_dt = datetime.datetime(2026, 9, 14, 0, 0, 0)
        end_dt = datetime.datetime(2026, 9, 20, 9, 0, 0)

        logs = [
            {
                "username": "admin",
                "full_name": "Quản Trị Viên",
                "role": "ADMIN",
                "action": "LOGIN_SUCCESS",
                "is_cafe_wifi": 0,
                "os_name": "macOS",
                "device_type": "Desktop"
            },
            {
                "username": "linh_bar",
                "full_name": "Trần Thị Mỹ Linh",
                "role": "STAFF",
                "action": "ATTENDANCE_CHECKIN",
                "is_cafe_wifi": 1,
                "os_name": "iOS",
                "device_type": "Mobile"
            },
            {
                "username": "vinh_phucvu",
                "full_name": "Nguyễn Văn Vinh",
                "role": "STAFF",
                "action": "ATTENDANCE_BLOCKED_WIFI",
                "is_cafe_wifi": 0,
                "os_name": "Android",
                "device_type": "Mobile"
            }
        ]

        messages = build_weekly_report(start_dt, end_dt, logs)
        self.assertTrue(len(messages) >= 1)
        full_msg = "\n".join(messages)

        self.assertIn("[BÁO CÁO TUẦN] TRUY CẬP HỆ THỐNG FNBOPS.LOCAL", full_msg)
        self.assertIn("Tổng số lượt thao tác: <b>3</b> lượt", full_msg)
        self.assertIn("Tại quán (WiFi Quán): <b>1</b> lượt", full_msg)
        self.assertIn("Ngoài quán (4G/Internet): <b>2</b> lượt", full_msg)
        self.assertIn("cố chấm công ngoài quán bị chặn", full_msg)
        self.assertIn("Trần Thị Mỹ Linh", full_msg)


if __name__ == "__main__":
    unittest.main()
