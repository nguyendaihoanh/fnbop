"""
Standalone Test Suite for Dynamic Store & Notification Configuration
(F&B PayrollDashboard / fnbops.local)

Verifies:
1. Dynamic Store Configuration (get_store_config / save_store_config)
   - store_name, wifi_ssid (string / list)
   - notifications (telegram, zalo)
   - 100% preservation of ca kíp (shifts, roster_rules, holiday_rules, auto_close_rules)
2. Telegram Credentials Fallback & Anti-Spam Guard in send_telegram.py
3. Endpoints POST /api/v1/cc/store/test-telegram and POST /store/test-telegram
"""

import os
import sys
import json
import copy

# Ensure correct sys.path whether executed from root or backend
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_DIR = os.path.dirname(BACKEND_DIR)

# Auto-reexec with project .venv if available and running under system python
VENV_DIR = os.path.join(PROJECT_DIR, ".venv")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python3")
if os.path.exists(VENV_PYTHON) and os.path.abspath(sys.prefix) != os.path.abspath(VENV_DIR):
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Set test environment flags
os.environ["TESTING"] = "1"
os.environ["MOCK_TELEGRAM"] = "1"
os.environ["ON_PREMISE_MODE"] = "true"

from services.store_config import (
    DEFAULT_STORE_CONFIG,
    get_store_config,
    save_store_config,
    get_config_file_path
)
from services.send_telegram import (
    get_telegram_config,
    test_telegram_connection as svc_test_telegram_connection,
    send_telegram_alert
)
from main import app
from starlette.testclient import TestClient

client = TestClient(app)


def setup_teardown_fixture():
    """Backup original config before tests and restore after."""
    original_cfg = copy.deepcopy(get_store_config())
    return original_cfg


def test_1_default_store_config_schema():
    """Test 1: DEFAULT_STORE_CONFIG has all required dynamic fields."""
    print("\n--- TEST 1: Default Store Config Schema ---")
    cfg = DEFAULT_STORE_CONFIG

    # Check store_name and wifi_ssid
    assert "store_name" in cfg, "Missing store_name in DEFAULT_STORE_CONFIG"
    assert cfg["store_name"] in ("FnBOps Store Lounge", "WFM Store Lounge")
    assert "wifi_ssid" in cfg, "Missing wifi_ssid in DEFAULT_STORE_CONFIG"
    assert cfg["wifi_ssid"] in ("FnBOps_Store_WiFi", "WFM_Store_WiFi")

    # Check notifications schema
    assert "notifications" in cfg, "Missing notifications in DEFAULT_STORE_CONFIG"
    notifs = cfg["notifications"]
    assert "telegram" in notifs, "Missing telegram in notifications"
    assert "zalo" in notifs, "Missing zalo in notifications"

    # Check telegram config
    tg = notifs["telegram"]
    assert tg.get("enabled") is True
    assert "bot_token" in tg
    assert "chat_id" in tg

    # Check zalo config
    zl = notifs["zalo"]
    assert zl.get("enabled") is False
    assert zl.get("status") == "disconnected"
    assert zl.get("gateway_url") == "http://127.0.0.1:8177"

    # Check shift configurations preserved
    assert "shifts" in cfg
    assert "sang" in cfg["shifts"]
    assert "toi" in cfg["shifts"]
    assert "roster_rules" in cfg
    assert "holiday_rules" in cfg
    assert "auto_close_rules" in cfg
    print("PASS: DEFAULT_STORE_CONFIG contains all required fields and shift rules.")


def test_2_save_and_reload_store_config():
    """Test 2: Modifying store_name, wifi_ssid, notifications and verifying 100% preservation."""
    print("\n--- TEST 2: Save and Reload Store Config ---")
    original = copy.deepcopy(get_store_config())

    try:
        modified = copy.deepcopy(original)
        # Modify custom store name and multiple wifi SSIDs
        modified["store_name"] = "WFM Lounge & Bistro"
        modified["wifi_ssid"] = ["WFM_Store", "WFM_5G", "WFM_VIP"]
        modified["notifications"]["telegram"]["bot_token"] = "1234567890:AA_MOCK_DEV_TOKEN_FOR_TESTING_456"
        modified["notifications"]["telegram"]["chat_id"] = "123456789"
        modified["notifications"]["zalo"]["enabled"] = True
        modified["notifications"]["zalo"]["status"] = "connected"

        # Ensure shift rules are present
        assert "shifts" in modified
        assert modified["shifts"]["sang"]["standard_mins"] == 330

        # Save to disk
        success = save_store_config(modified)
        assert success is True, "save_store_config failed to write"

        # Reload from disk
        reloaded = get_store_config()
        assert reloaded["store_name"] == "WFM Lounge & Bistro"
        assert reloaded["wifi_ssid"] == ["WFM_Store", "WFM_5G", "WFM_VIP"]
        assert reloaded["notifications"]["telegram"]["bot_token"] == "1234567890:AA_MOCK_DEV_TOKEN_FOR_TESTING_456"
        assert reloaded["notifications"]["telegram"]["chat_id"] == "123456789"
        assert reloaded["notifications"]["zalo"]["enabled"] is True
        assert reloaded["notifications"]["zalo"]["status"] == "connected"

        # Crucial: verify 100% preservation of shift and closing rules
        assert reloaded["shifts"]["sang"]["official_start"] == original["shifts"]["sang"]["official_start"]
        assert reloaded["shifts"]["toi"]["official_start"] == original["shifts"]["toi"]["official_start"]
        assert reloaded["roster_rules"] == original["roster_rules"]
        assert reloaded["holiday_rules"] == original["holiday_rules"]
        assert reloaded["auto_close_rules"] == original["auto_close_rules"]

        print("PASS: Config saved and reloaded successfully with shift rules 100% intact.")
    finally:
        save_store_config(original)


def test_3_telegram_fallback_and_anti_spam():
    """Test 3: Telegram credentials fallback and Anti-Spam protection."""
    print("\n--- TEST 3: Telegram Fallback & Anti-Spam Guard ---")
    original = copy.deepcopy(get_store_config())

    try:
        # 1. When store_config has empty token, fallback to .env
        cfg_empty_tg = copy.deepcopy(original)
        cfg_empty_tg["notifications"]["telegram"]["bot_token"] = ""
        cfg_empty_tg["notifications"]["telegram"]["chat_id"] = ""
        save_store_config(cfg_empty_tg)

        os.environ["TELEGRAM_BOT_TOKEN"] = "ENV_BOT_TOKEN_123"
        os.environ["TELEGRAM_CHAT_ID"] = "ENV_CHAT_ID_456"

        fb_token, fb_chat = get_telegram_config()
        assert fb_token == "ENV_BOT_TOKEN_123", f"Expected ENV_BOT_TOKEN_123, got {fb_token}"
        assert fb_chat == "ENV_CHAT_ID_456", f"Expected ENV_CHAT_ID_456, got {fb_chat}"

        # 2. When store_config has custom token, it prioritizes store_config over .env
        cfg_custom_tg = copy.deepcopy(original)
        cfg_custom_tg["notifications"]["telegram"]["bot_token"] = "STORE_BOT_TOKEN_789"
        cfg_custom_tg["notifications"]["telegram"]["chat_id"] = "STORE_CHAT_ID_999"
        save_store_config(cfg_custom_tg)

        sc_token, sc_chat = get_telegram_config()
        assert sc_token == "STORE_BOT_TOKEN_789", f"Expected STORE_BOT_TOKEN_789, got {sc_token}"
        assert sc_chat == "STORE_CHAT_ID_999", f"Expected STORE_CHAT_ID_999, got {sc_chat}"

        # 3. Anti-Spam Guard: Token starting with 9876543210 must be rejected
        prod_token = "9876543210:AA_MOCK_PROD_TOKEN_FOR_TESTING_123"
        ok, msg = svc_test_telegram_connection(bot_token=prod_token, chat_id="123456789")
        assert ok is False, "Anti-Spam Guard failed to block prod token"
        assert "ANTI-SPAM GUARD" in msg, f"Expected ANTI-SPAM GUARD in message, got: {msg}"

        # 4. Valid test token in test mode should succeed
        dev_token = "1234567890:AA_MOCK_DEV_TOKEN_FOR_TESTING_456"
        ok_dev, msg_dev = svc_test_telegram_connection(bot_token=dev_token, chat_id="123456789")
        assert ok_dev is True, f"Valid test failed: {msg_dev}"
        assert "Kiểm tra kết nối Telegram thành công" in msg_dev

        print("PASS: Fallback order and Anti-Spam Guard working as intended.")
    finally:
        save_store_config(original)


def test_4_endpoint_store_test_telegram():
    """Test 4: Endpoints POST /api/v1/cc/store/test-telegram and alias POST /store/test-telegram."""
    print("\n--- TEST 4: Endpoints POST /store/test-telegram ---")
    original = copy.deepcopy(get_store_config())

    try:
        # Prepare valid dev test bot credentials in store_config
        cfg = copy.deepcopy(original)
        cfg["notifications"]["telegram"]["bot_token"] = "1234567890:AA_MOCK_DEV_TOKEN_FOR_TESTING_456"
        cfg["notifications"]["telegram"]["chat_id"] = "123456789"
        save_store_config(cfg)

        from routers.fnb_ops import create_access_token
        admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Admin"})
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. POST /api/v1/cc/store/test-telegram with explicit payload
        payload = {
            "bot_token": "1234567890:AA_MOCK_DEV_TOKEN_FOR_TESTING_456",
            "chat_id": "123456789"
        }
        res1 = client.post("/api/v1/cc/store/test-telegram", json=payload, headers=admin_headers)
        assert res1.status_code == 200, f"Expected 200, got {res1.status_code}: {res1.text}"
        data1 = res1.json()
        assert data1.get("success") is True
        assert "Kiểm tra kết nối Telegram thành công" in data1.get("message", "")

        # 2. POST /api/v1/cc/store/test-telegram with empty payload (relying on store_config)
        res2 = client.post("/api/v1/cc/store/test-telegram", json={}, headers=admin_headers)
        assert res2.status_code == 200, f"Expected 200, got {res2.status_code}: {res2.text}"
        data2 = res2.json()
        assert data2.get("success") is True
        assert "Kiểm tra kết nối Telegram thành công" in data2.get("message", "")

        # 3. POST /store/test-telegram (root alias endpoint)
        res3 = client.post("/store/test-telegram", json=payload, headers=admin_headers)
        assert res3.status_code == 200, f"Expected 200, got {res3.status_code}: {res3.text}"
        data3 = res3.json()
        assert data3.get("success") is True
        assert "Kiểm tra kết nối Telegram thành công" in data3.get("message", "")

        # 4. Anti-Spam check via endpoint: Prod token 9876543210 must return success=False
        spam_payload = {
            "bot_token": "9876543210:AA_MOCK_PROD_TOKEN_FOR_TESTING_123",
            "chat_id": "123456789"
        }
        res4 = client.post("/api/v1/cc/store/test-telegram", json=spam_payload, headers=admin_headers)
        assert res4.status_code == 200
        data4 = res4.json()
        assert data4.get("success") is False
        assert "ANTI-SPAM GUARD" in data4.get("message", "")

        print("PASS: /store/test-telegram endpoints respond with expected schema and security checks.")
    finally:
        save_store_config(original)


def run_all_tests():
    print("=" * 60)
    print("RUNNING STANDALONE STORE CONFIG & NOTIFICATION TEST SUITE")
    print("=" * 60)

    orig = setup_teardown_fixture()
    try:
        test_1_default_store_config_schema()
        test_2_save_and_reload_store_config()
        test_3_telegram_fallback_and_anti_spam()
        test_4_endpoint_store_test_telegram()
        print("\n" + "=" * 60)
        print("ALL TESTS PASSED: 4/4 (100% SUCCESS)")
        print("=" * 60)
        return True
    finally:
        save_store_config(orig)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
