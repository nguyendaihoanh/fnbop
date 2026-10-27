"""
Unit and Integration Tests for DNS Rebinding Shield
Validates strict Host header filtering against DNS Rebinding and Localhost Pivoting attacks.
"""

import os
import sys
import unittest
from fastapi.testclient import TestClient

# Ensure backend modules can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from main import app, is_allowed_host


class TestDNSRebindingShield(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    # --------------------------------------------------------------------------
    # 1. UNIT TESTS: is_allowed_host logic
    # --------------------------------------------------------------------------
    def test_01_allowed_domains(self):
        """Standard generic domains and local hosts must be allowed."""
        self.assertTrue(is_allowed_host("fnbops.local"))
        self.assertTrue(is_allowed_host("fnbops.local:443"))
        self.assertTrue(is_allowed_host("fnbops.lan"))
        self.assertTrue(is_allowed_host("fnbops.lan:8100"))

    def test_02_allowed_local_and_private_hosts(self):
        """Localhost, loopback, and private RFC1918 LAN IPs must be allowed."""
        self.assertTrue(is_allowed_host("localhost"))
        self.assertTrue(is_allowed_host("localhost:8100"))
        self.assertTrue(is_allowed_host("127.0.0.1"))
        self.assertTrue(is_allowed_host("127.0.0.1:8100"))
        self.assertTrue(is_allowed_host("[::1]:8100"))
        # Docker internal hosts
        self.assertTrue(is_allowed_host("host.docker.internal"))
        self.assertTrue(is_allowed_host("host.docker.internal:8100"))
        self.assertTrue(is_allowed_host("gateway.docker.internal"))
        # Private LAN IPs (RFC 1918)
        self.assertTrue(is_allowed_host("192.168.1.100:8100"))
        self.assertTrue(is_allowed_host("10.0.0.5"))
        self.assertTrue(is_allowed_host("172.16.0.10:8100"))
        self.assertTrue(is_allowed_host("172.31.255.1"))

    def test_03_rejected_malicious_rebind_hosts(self):
        """Attacker domains used in DNS rebinding attacks must be rejected."""
        self.assertFalse(is_allowed_host("evil-rebind.com"))
        self.assertFalse(is_allowed_host("evil-rebind.com:8100"))
        self.assertFalse(is_allowed_host("attacker.xyz"))
        self.assertFalse(is_allowed_host("subdomain.evil.com:8100"))
        self.assertFalse(is_allowed_host(""))
        self.assertFalse(is_allowed_host(None))
        # Public IP that is not in the whitelist
        self.assertFalse(is_allowed_host("8.8.8.8"))

    # --------------------------------------------------------------------------
    # 2. INTEGRATION TESTS: HTTP Middleware behavior
    # --------------------------------------------------------------------------
    def test_04_request_with_valid_host_header_succeeds(self):
        """Request with valid Host header passes through to endpoint."""
        res = self.client.get("/ping", headers={"Host": "localhost:8100"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok", "service": "fnbops_backend"})

    def test_05_request_with_private_lan_host_header_succeeds(self):
        """Request with Private LAN Host header passes through."""
        res = self.client.get("/ping", headers={"Host": "192.168.1.50:8100"})
        self.assertEqual(res.status_code, 200)

    def test_06_request_with_evil_rebind_host_blocked_400(self):
        """Simulated DNS Rebinding: Browser sends Host evil-rebind.com to local server.
        Must be blocked immediately with HTTP 400 Bad Request."""
        res = self.client.get("/ping", headers={"Host": "evil-rebind.attacker.com:8100"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid Host header. DNS Rebinding Protection Active.", res.json()["detail"])

    def test_07_post_request_to_sensitive_endpoint_blocked_on_rebind(self):
        """Attacker attempt to trigger API action via DNS rebinding is rejected."""
        res = self.client.post(
            "/api/v1/cc/auth/login",
            headers={"Host": "rebind-exploit.xyz"},
            json={"username": "admin", "password": "any"}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("DNS Rebinding Protection Active", res.text)

    def test_08_docker_internal_webhook_sync_accepted(self):
        """Request from Docker container with Host host.docker.internal passes DNS shield."""
        res = self.client.get("/health", headers={"Host": "host.docker.internal:8100"})
        self.assertNotEqual(res.status_code, 400, "Must not be rejected by DNS Rebinding Shield")
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()

