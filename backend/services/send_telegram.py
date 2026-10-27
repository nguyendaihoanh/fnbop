# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
import os
import sys
import requests
from typing import Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DEV_BOT_TOKEN = os.getenv("TELEGRAM_DEV_BOT_TOKEN") or os.getenv("TEST_TELEGRAM_BOT_TOKEN")
PROD_BOT_TOKEN = os.getenv("PROD_TELEGRAM_BOT_TOKEN")

try:
    from backend.services.store_config import get_store_config
except ImportError:
    try:
        from services.store_config import get_store_config
    except ImportError:
        get_store_config = None


def get_telegram_config() -> Tuple[Optional[str], Optional[str]]:
    """
    Retrieves (bot_token, chat_id) prioritizing store_config['notifications']['telegram'].
    Falls back to environment variables:
    - Token: TELEGRAM_BOT_TOKEN, then TELEGRAM_DEV_BOT_TOKEN / TEST_TELEGRAM_BOT_TOKEN
    - Chat ID: TELEGRAM_CHAT_ID
    """
    store_token = None
    store_chat = None

    if get_store_config:
        try:
            cfg = get_store_config()
            tg_cfg = cfg.get("notifications", {}).get("telegram", {})
            raw_token = tg_cfg.get("bot_token")
            if raw_token and str(raw_token).strip():
                store_token = str(raw_token).strip()
            raw_chat = tg_cfg.get("chat_id")
            if raw_chat and str(raw_chat).strip():
                store_chat = str(raw_chat).strip()
        except Exception:
            pass

    env_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_DEV_BOT_TOKEN") or os.getenv("TEST_TELEGRAM_BOT_TOKEN")
    env_chat = os.getenv("TELEGRAM_CHAT_ID")

    bot_token = store_token or env_token
    chat_id = store_chat or env_chat
    return bot_token, chat_id


def send_telegram_alert(message: str, chat_id: str = None, token: str = None, channel: str = "prod") -> bool:
    """
    Sends operational alert to Telegram with Dual-Channel support ('prod' vs 'dev').
    """
    if os.getenv("DISABLE_OUTBOUND_TELEGRAM") == "1":
        print(f"[TELEGRAM SUPPRESSED] Outbound Telegram disabled for automated gate: {message[:60]}...")
        return True
    is_testing = os.getenv("TESTING") == "1" or os.getenv("MOCK_TELEGRAM") == "1"
    dev_token = os.getenv("TELEGRAM_DEV_BOT_TOKEN") or os.getenv("TEST_TELEGRAM_BOT_TOKEN")
    prod_token = os.getenv("PROD_TELEGRAM_BOT_TOKEN")

    default_token, default_chat = get_telegram_config()
    target_token = token or default_token
    target_chat = chat_id or default_chat

    # If in test mode or message is a development/test event
    if is_testing or "[TEST]" in message or "[DEV" in message or channel == "dev" or "test" in message.lower():
        if dev_token:
            target_token = dev_token
            target_chat = chat_id or default_chat or CHAT_ID
        elif is_testing:
            print(f"[TEST SUPPRESSED] Mock test mode active, alert suppressed: {message[:60]}...")
            return True
        elif prod_token and target_token == prod_token:
            print(f"[ANTI-SPAM GUARD] Prevented test message from routing to production bot channel.")
            return True
    else:
        target_token = token or default_token or dev_token or TOKEN
        target_chat = chat_id or default_chat or CHAT_ID

    if not target_token or not target_chat:
        print("Lỗi cấu hình: Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong môi trường.")
        return False

    url = f"https://api.telegram.org/bot{target_token}/sendMessage"
    payload = {"chat_id": target_chat, "text": message, "parse_mode": "HTML"}
    try:
        res = requests.post(url, data=payload, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        print(f"Lỗi khi gửi Telegram: {e}")
        return False


def test_telegram_connection(bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> Tuple[bool, str]:
    """
    Sends a test message verifying Telegram connection.
    Prioritizes provided credentials, then dynamic store_config, then .env fallback.
    """
    default_token, default_chat = get_telegram_config()
    target_token = (bot_token.strip() if bot_token else None) or default_token
    target_chat = (str(chat_id).strip() if chat_id else None) or default_chat

    if not target_token or not target_chat:
        return False, "Lỗi cấu hình: Thiếu bot_token hoặc chat_id để kiểm tra kết nối Telegram."

    # Anti-Spam Guard against hitting prod bot
    prod_token = os.getenv("PROD_TELEGRAM_BOT_TOKEN")
    if (prod_token and target_token == prod_token) or (target_token and "PROD" in target_token):
        return False, "ANTI-SPAM GUARD: Tuyệt đối cấm gửi tin nhắn kiểm tra/test vào bot chính sản xuất."

    # Test/Mock mode support for unit testing and CI
    is_testing = os.getenv("TESTING") == "1" or os.getenv("MOCK_TELEGRAM") == "1"
    if is_testing:
        return True, "🔔 [Cài đặt Quán] Kiểm tra kết nối Telegram thành công! (Chế độ Test)"

    test_msg = "🔔 [FnBOps] Kiểm tra kết nối Telegram thành công!"
    url = f"https://api.telegram.org/bot{target_token}/sendMessage"
    payload = {"chat_id": target_chat, "text": test_msg, "parse_mode": "HTML"}

    try:
        res = requests.post(url, data=payload, timeout=10)
        if res.status_code == 200:
            return True, "🔔 [FnBOps] Kiểm tra kết nối Telegram thành công!"
        else:
            try:
                err_data = res.json()
                desc = err_data.get("description", f"Mã lỗi HTTP {res.status_code}")
                return False, f"Telegram API từ chối ({res.status_code}): {desc}"
            except Exception:
                return False, f"Telegram API trả về mã lỗi: {res.status_code}"
    except Exception as e:
        return False, f"Lỗi mạng khi kết nối Telegram: {str(e)}"
