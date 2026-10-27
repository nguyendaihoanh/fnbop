import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi import Request, HTTPException
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure required environment variable for loading backend
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_super_secure_key_1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_261109")
os.environ.setdefault("STAFF_PASSWORD", "test_staff_2026")

from backend.main import app
from backend.routers.fnb_ops import (
    is_cloudflare_ingress_valid,
    verify_cloudflare_ingress
)


def _make_client_with_ip(app, ip: str, port: int = 54321):
    """Universal client creator supporting all Starlette/FastAPI/httpx versions."""
    try:
        return TestClient(app, client=(ip, port))
    except TypeError:
        async def ip_override_middleware(scope, receive, send):
            if scope["type"] == "http":
                scope = dict(scope)
                scope["client"] = (ip, port)
            await app(scope, receive, send)
        return TestClient(ip_override_middleware)


class TestCloudflareIngressShield(unittest.TestCase):
    def setUp(self):
        self.old_on_premise = os.environ.get("ON_PREMISE_MODE")
        os.environ["ON_PREMISE_MODE"] = "false"

    def tearDown(self):
        if self.old_on_premise is not None:
            os.environ["ON_PREMISE_MODE"] = self.old_on_premise
        else:
            os.environ.pop("ON_PREMISE_MODE", None)

    def test_01_external_ip_without_cf_ray_blocked_403(self):
        """Request từ IP Internet bên ngoài đến fnbops.local không có cf-ray phải bị chặn 403"""
        external_client = _make_client_with_ip(app, "203.0.113.195", 54321)
        response = external_client.get(
            "/ping",
            headers={"Host": "fnbops.local"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("Direct IP access is prohibited. Requests must route through Cloudflare Edge.", response.json()["detail"])

    def test_02_external_ip_with_cf_ray_allowed(self):
        """Request từ IP Internet đến fnbops.local có cf-ray hợp lệ từ Cloudflare Edge được thông qua"""
        external_client = _make_client_with_ip(app, "203.0.113.195", 54321)
        response = external_client.get(
            "/ping",
            headers={
                "Host": "fnbops.local",
                "cf-ray": "8c1234567890abcd-SGN"
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_03_localhost_exemption(self):
        """Request từ localhost/127.0.0.1 đến fnbops.local được miễn trừ (bypass) không cần cf-ray"""
        local_client = _make_client_with_ip(app, "127.0.0.1", 54321)
        response = local_client.get(
            "/ping",
            headers={"Host": "fnbops.local"}
        )
        self.assertEqual(response.status_code, 200)

    def test_04_private_lan_ip_exemption(self):
        """Request từ dải IP mạng LAN nội bộ (192.168.x.x) được miễn trừ (bypass) phục vụ kết nối nội bộ quán"""
        lan_client = _make_client_with_ip(app, "192.168.1.50", 54321)
        response = lan_client.get(
            "/ping",
            headers={"Host": "fnbops.local"}
        )
        self.assertEqual(response.status_code, 200)

    def test_05_testclient_exemption(self):
        """Request từ testclient (mặc định của TestClient) được miễn trừ để bảo vệ các test case cũ"""
        default_client = TestClient(app)
        response = default_client.get(
            "/ping",
            headers={"Host": "fnbops.local"}
        )
        self.assertEqual(response.status_code, 200)

    def test_06_non_cc_domain_not_blocked(self):
        """Request tới các domain khác (như localhost hoặc test server) không bị ảnh hưởng"""
        external_client = _make_client_with_ip(app, "203.0.113.195", 54321)
        response = external_client.get(
            "/ping",
            headers={"Host": "localhost:8100"}
        )
        self.assertEqual(response.status_code, 200)

    def test_07_unit_is_cloudflare_ingress_valid_logic(self):
        """Kiểm tra logic phân loại của hàm is_cloudflare_ingress_valid"""
        # Mock request từ IP lạ không có cf-ray
        req_blocked = MagicMock(spec=Request)
        req_blocked.headers = {"host": "fnbops.local"}
        req_blocked.client = MagicMock(host="198.51.100.22")

        valid, msg = is_cloudflare_ingress_valid(req_blocked)
        self.assertFalse(valid)
        self.assertIn("Direct IP access is prohibited", msg)

        # Cùng request đó nhưng có cf-ray
        req_allowed = MagicMock(spec=Request)
        req_allowed.headers = {"host": "fnbops.local", "cf-ray": "some-ray-id"}
        req_allowed.client = MagicMock(host="198.51.100.22")

        valid, _ = is_cloudflare_ingress_valid(req_allowed)
        self.assertTrue(valid)

        # Request từ mạng LAN nội bộ quán
        req_lan = MagicMock(spec=Request)
        req_lan.headers = {"host": "fnbops.local"}
        req_lan.client = MagicMock(host="192.168.1.100")

        valid, _ = is_cloudflare_ingress_valid(req_lan)
        self.assertTrue(valid)

    def test_08_verify_cloudflare_ingress_raises_http_exception(self):
        """Hàm verify_cloudflare_ingress phải raise HTTPException(403) khi bị chặn"""
        req_blocked = MagicMock(spec=Request)
        req_blocked.headers = {"host": "fnbops.local"}
        req_blocked.client = MagicMock(host="198.51.100.22")

        with self.assertRaises(HTTPException) as ctx:
            verify_cloudflare_ingress(req_blocked)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Direct IP access is prohibited", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
