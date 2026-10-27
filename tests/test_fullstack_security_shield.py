"""
Automated Full-Stack Security Shield Test Suite
FNBOPS.LOCAL / FnBOps
Covers:
1. XSS Payload Sanitization (Zero-Trust Input & Output)
2. API Rate Limiting (SQLite WAL token bucket)
3. JWT Instant Revocation & Logout Blacklist
4. OWASP Security Headers Shield
5. Sensitive Files & Information Disclosure Protection
6. Exception Traceback Masking
"""

import sys
import os
import time
import json
import uuid
import subprocess
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from main import app
from routers.fnb_ops import create_access_token
import services.db as db
from fastapi.testclient import TestClient


class TestFullStackSecurityShield(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        db.init_db()

    def setUp(self):
        # Clear rate limit state between test methods
        conn = db.get_db_connection()
        conn.execute("DELETE FROM api_rate_limits")
        conn.commit()
        conn.close()

    def test_01_xss_sanitization_15_attack_vectors(self):
        """Validates that frontend/src/utils/sanitize.js escapes 15 classic XSS attack vectors cleanly."""
        payloads = [
            '<script>alert("xss")</script>',
            '<img src=x onerror=alert(1)>',
            '<svg onload=alert(document.cookie)>',
            '<iframe src="javascript:alert(1)">',
            '<a href="javascript:alert(1)">Click Me</a>',
            '<body onload=alert(1)>',
            '"><script>alert(1)</script>',
            "' onfocus=alert(1) autofocus='",
            '<details open ontoggle=alert(1)>',
            '<audio src/onerror=alert(1)>',
            '<video><source onerror="javascript:alert(1)">',
            '<math><mtext><table><mglyph><style><!--</style><img src=x onerror=alert(1)>',
            "javascript:/*--></title></style></textarea></script></xmp><svg/onload=alert(1)>",
            '<script/src="data:text/javascript,alert(1)">',
            '<object data="javascript:alert(1)">'
        ]

        node_script = """
        import { escapeHtml, stripHtml, isSafeUrl } from './frontend/src/utils/sanitize.js';
        import fs from 'fs';
        const raw = fs.readFileSync(0, 'utf-8');
        const payloads = JSON.parse(raw);
        for (const p of payloads) {
            const escaped = escapeHtml(p);
            if (escaped.includes('<') || escaped.includes('>') || escaped.includes('"') || escaped.includes("'")) {
                console.error("FAILED to escape dangerous chars in:", p, "Got:", escaped);
                process.exit(1);
            }
        }
        console.log("ALL_ESCAPED_SAFE");
        """
        res = subprocess.run(
            ["node", "--input-type=module", "-e", node_script],
            input=json.dumps(payloads),
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"Node XSS check failed: {res.stderr}")
        self.assertIn("ALL_ESCAPED_SAFE", res.stdout)

    def test_02_jwt_instant_revocation_blacklist(self):
        """Validates that a token is immediately blocked (401) across all APIs after logout."""
        # 1. Generate an active Admin token with unique nonce
        token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Hộ (Admin)", "nonce": uuid.uuid4().hex})

        # 2. Access protected endpoint before logout -> 200 OK
        res_before = self.client.get(
            "/api/v1/cc/payroll/ledger?month=9",
            headers={"Authorization": f"Bearer {token}", "CF-Ray": "test-ray-1"}
        )
        self.assertEqual(res_before.status_code, 200)

        # 3. Call logout endpoint -> 200 OK
        res_logout = self.client.post(
            "/api/v1/cc/auth/logout",
            headers={"Authorization": f"Bearer {token}", "CF-Ray": "test-ray-1"}
        )
        self.assertEqual(res_logout.status_code, 200)
        self.assertIn("thành công", res_logout.json()["message"])

        # 4. Try using the revoked token immediately -> 401 Unauthorized
        res_after = self.client.get(
            "/api/v1/cc/payroll/ledger?month=9",
            headers={"Authorization": f"Bearer {token}", "CF-Ray": "test-ray-1"}
        )
        self.assertEqual(res_after.status_code, 401)
        self.assertIn("thu hồi", res_after.json()["detail"])

    def test_03_api_rate_limiting_enforcement(self):
        """Validates that exceeding the rate limit returns HTTP 429 Too Many Requests with Retry-After header."""
        fresh_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Hộ (Admin)", "nonce": uuid.uuid4().hex})
        test_ip = f"198.51.100.{int(time.time() * 1000) % 250 + 1}"

        # /payroll/ledger limit is 30 per 60s
        payload = {
            "staff_name": "thuan",
            "month": "9",
            "type": "bonus",
            "amount": 10000,
            "payment_method": "cash",
            "reason": "Test Rate Limit"
        }

        # Send 30 requests -> all should pass 200
        for i in range(30):
            res = self.client.post(
                "/api/v1/cc/payroll/ledger",
                headers={"Authorization": f"Bearer {fresh_token}", "CF-Connecting-IP": test_ip, "CF-Ray": f"ray-{i}"},
                json=payload
            )
            self.assertEqual(res.status_code, 200, f"Request {i+1} failed with status {res.status_code}: {res.text}")

        # The 31st request must trigger 429 Too Many Requests
        res_blocked = self.client.post(
            "/api/v1/cc/payroll/ledger",
            headers={"Authorization": f"Bearer {fresh_token}", "CF-Connecting-IP": test_ip, "CF-Ray": "ray-31"},
            json=payload
        )
        self.assertEqual(res_blocked.status_code, 429)
        self.assertIn("Retry-After", res_blocked.headers)
        self.assertIn("quá nhanh", res_blocked.json()["detail"])

    def test_04_owasp_security_headers_present_on_all_responses(self):
        """Validates that all responses include the mandatory OWASP security headers."""
        res = self.client.get("/ping")
        self.assertEqual(res.status_code, 200)
        headers = res.headers

        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-XSS-Protection"), "1; mode=block")
        self.assertEqual(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("camera=()", headers.get("Permissions-Policy", ""))

    def test_05_sensitive_static_files_shield_returns_404(self):
        """Validates that direct requests to sensitive database, config, or JSON files are blocked with 404."""
        sensitive_targets = [
            "/data.json",
            "/staff_auth.json",
            "/fnbop.db",
            "/shift_approvals.json",
            "/eval_logs.json",
            "/pos_heartbeat.json",
            "/backend/main.py",
            "/.env",
            "/fnb_pos_heartbeat.ps1",
            "/scripts/test.ps1",
            "/deploy.sh",
            "/backup.sql"
        ]
        for target in sensitive_targets:
            res = self.client.get(target)
            self.assertEqual(
                res.status_code,
                404,
                f"Sensitive file {target} should return 404, got {res.status_code}"
            )

    def test_06_unhandled_exception_masks_traceback(self):
        """Validates that unhandled server exceptions return a sanitized message and do not expose stack trace."""
        safe_client = TestClient(app, raise_server_exceptions=False)
        token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Admin", "nonce": uuid.uuid4().hex})
        with patch("routers.fnb_ops.list_staff_ledgers", side_effect=RuntimeError("CRITICAL_INTERNAL_DB_CRASH_DUMP: secret_db_key_xyz123")):
            res = safe_client.get(
                "/api/v1/cc/payroll/ledger?month=9",
                headers={"Authorization": f"Bearer {token}", "CF-Ray": "crash-ray-1"}
            )
            self.assertEqual(res.status_code, 500)
            body = res.json()
            self.assertIn("lỗi hệ thống nội bộ", body.get("detail", ""))
            self.assertNotIn("CRITICAL_INTERNAL_DB_CRASH_DUMP", str(body))
            self.assertNotIn("Traceback", str(body))
            self.assertNotIn("secret_db_key_xyz123", str(body))


if __name__ == "__main__":
    unittest.main()
