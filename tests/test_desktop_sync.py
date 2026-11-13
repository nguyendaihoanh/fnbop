import unittest
import json
import re
import urllib.request
import urllib.error
import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_backend_dir = str(REPO_ROOT / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

class TestDesktopSyncAndIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_js_path = REPO_ROOT / "frontend" / "app.js"
        cls.desktop_html_path = REPO_ROOT / "frontend" / "desktop.html"
        with open(cls.app_js_path, "r", encoding="utf-8") as f:
            cls.app_js_content = f.read()
        with open(cls.desktop_html_path, "r", encoding="utf-8") as f:
            cls.desktop_html_content = f.read()

    def test_case_01_desktop_html_contains_required_dom_ids(self):
        """Case 1: Verify desktop.html has all required DOM element IDs referenced in app.js"""
        required_ids = [
            "btnTelegramPayslip",
            "btnRosterAutoFillDesktop",
            "btnRosterPublishDesktop",
            "rosterStatusBadgeDesktop",
            "rosterAdminActionsDesktop",
            "weeklyRosterContainer",
            "btnPrevWeek",
            "btnNextWeek",
            "weekLabelDisplay",
            "btnOpenEval",
            "btnSubmitEval",
            "adminStaffModalDesktop"
        ]
        for dom_id in required_ids:
            with self.subTest(dom_id=dom_id):
                pattern = f'id="{dom_id}"'
                self.assertIn(pattern, self.desktop_html_content, f"Missing required DOM ID in desktop.html: {dom_id}")

    def test_case_02_app_js_cache_busting_in_desktop_html(self):
        """Case 2: Verify desktop.html uses cache-busting version for app.js"""
        match = re.search(r'<script src="app\.js\?v=(\d+)"></script>', self.desktop_html_content)
        self.assertIsNotNone(match, "desktop.html should include app.js with a ?v= query parameter")
        version = int(match.group(1))
        self.assertGreaterEqual(version, 2007, "Version should be bumped to at least 2007")

    def test_case_03_app_js_has_no_raw_n8n_webhook_urls(self):
        """Case 3: Verify app.js proxies through internal /api/* endpoints instead of external n8n URLs"""
        self.assertNotIn("n8n.fnbops.local/webhook", self.app_js_content, "Found raw n8n webhook URL in app.js!")
        self.assertTrue(
            "const WEBHOOK_URL = '/api/danh-gia';" in self.app_js_content
            or "const WEBHOOK_URL = '/api/v1/cc/admin/eval-webhook';" in self.app_js_content,
            "Evaluation webhook should use secure proxy (/api/danh-gia or /api/v1/cc/admin/eval-webhook)"
        )
        self.assertIn("fetch('/api/send-payslip'", self.app_js_content, "Payslip webhook should use proxy /api/send-payslip")

    def test_case_04_payslip_payload_structure(self):
        """Case 4: Verify payslip payload structure matches backend/n8n expectation"""
        expected_keys = [
            "staffName",
            "monthTitle",
            "finalPayFormatted",
            "totalHours",
            "totalMinsFormatted",
            "shifts",
            "baseWageFormatted",
            "bonusFormatted",
            "violations"
        ]
        for key in expected_keys:
            with self.subTest(key=key):
                self.assertIn(f"{key}:", self.app_js_content, f"Payload should contain key: {key}")

    def test_case_05_role_permission_controls_roster_actions(self):
        """Case 5: Verify applyRolePermissionsDesktop hides or displays roster actions by role"""
        self.assertIn("rosterActions.style.display = (isStaff) ? 'none' : 'flex';", self.app_js_content,
                      "Staff should have rosterAdminActions hidden, managers/admins should have them displayed")

    def test_case_06_live_nginx_proxy_send_payslip_endpoint(self):
        """Case 6: Verify /api/send-payslip legacy proxy rejects unauthenticated and responds 200 with Admin JWT"""
        from fastapi.testclient import TestClient
        from main import app
        from routers.fnb_ops import create_access_token

        client = TestClient(app)
        payload = {
            "staffName": "Nhân Viên",
            "monthTitle": "Tháng 10/2026",
            "finalPayFormatted": "1.800.000 đ",
            "totalHours": "100.0",
            "totalMinsFormatted": "6.000",
            "shifts": "20",
            "baseWageFormatted": "18.000 đ/h",
            "bonusFormatted": "+0 đ",
            "violations": [],
        }
        unauth = client.post("/api/send-payslip", json=payload)
        self.assertEqual(unauth.status_code, 401, "/api/send-payslip must require authentication")

        token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Admin"})
        resp = client.post(
            "/api/send-payslip",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 200, f"/api/send-payslip failed: {resp.text}")

    def test_case_07_live_nginx_proxy_danh_gia_endpoint(self):
        """Case 7: Verify /api/danh-gia proxy rejects unauthenticated and responds 200 with Admin JWT"""
        from fastapi.testclient import TestClient
        from main import app
        from routers.fnb_ops import create_access_token

        client = TestClient(app)
        payload = {
            "staffName": "Nhân Viên",
            "date": "12/10/2026",
            "shift": "Tối",
            "ratings": {"thai_do": 5, "chuyen_mon": 5},
            "red_flags": [],
            "bonus": 0,
            "notes": "Test desktop sync",
            "manager": "Quản Lý Ca",
        }
        unauth = client.post("/api/danh-gia", json=payload)
        self.assertEqual(unauth.status_code, 401, "/api/danh-gia must require authentication")

        token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Admin"})
        resp = client.post(
            "/api/danh-gia",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, 200, f"/api/danh-gia failed: {resp.text}")
        self.assertTrue(resp.json().get("success"))

    def test_case_08_live_backend_roster_week_endpoints(self):
        """Case 8: Verify /api/v1/cc/roster/week returns valid schema for desktop consumption"""
        from fastapi.testclient import TestClient
        from main import app
        from routers.fnb_ops import create_access_token

        client = TestClient(app)
        token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Admin"})
        headers = {"Authorization": f"Bearer {token}"}
        for week_id in ["current", "next"]:
            with self.subTest(week_id=week_id):
                resp = client.get(f"/api/v1/cc/roster/week?week_id={week_id}", headers=headers)
                self.assertEqual(resp.status_code, 200, f"Endpoint for week_id={week_id} should return 200")
                data = resp.json()
                self.assertTrue(data.get("success"), "API should return success: True")
                self.assertIn("week", data, "API should return week object")
                self.assertIn("status", data["week"], "Week object should contain status")
                self.assertIn("shifts", data["week"], "Week object should contain shifts dict")

if __name__ == "__main__":
    unittest.main()
