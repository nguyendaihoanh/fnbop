# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Web Push Notification Service (FnBOps / FNBOPS.LOCAL)
Manages VAPID keys, browser push subscriptions, and payload dispatch.
Follows RFC 8291 / RFC 8292 standard Web Push protocols.
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
try:
    from pywebpush import webpush, WebPushException
    from py_vapid import Vapid
    HAS_PYWEBPUSH = True
except ImportError:
    webpush = None
    WebPushException = Exception
    Vapid = None
    HAS_PYWEBPUSH = False
    logging.getLogger("webpush_service").warning("pywebpush is not installed. Web Push notifications are disabled until installed.")

try:
    from backend.services.db import (
        save_push_subscription_db,
        list_push_subscriptions_db,
        deactivate_push_subscription_db,
        record_notification_dispatch_db,
        has_notification_dispatched_db,
        get_db_path,
        DEFAULT_TENANT_ID
    )
except ImportError:
    from services.db import (
        save_push_subscription_db,
        list_push_subscriptions_db,
        deactivate_push_subscription_db,
        record_notification_dispatch_db,
        has_notification_dispatched_db,
        get_db_path,
        DEFAULT_TENANT_ID
    )

logger = logging.getLogger("webpush_service")

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.getenv("DATA_DIR") or os.path.join(_BASE_DIR, "data")
_VAPID_FILE = os.path.join(_DATA_DIR, "vapid_keys.json")

VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_SUBJECT", "mailto:admin@fnbops.local")
}


def _ensure_vapid_keys() -> Dict[str, str]:
    """
    Ensures VAPID keypair exists in environment, SQLite store_settings, or data/vapid_keys.json.
    Generates an authoritative NIST P-256 EC keypair if not present.
    """
    env_priv = os.getenv("VAPID_PRIVATE_KEY")
    env_pub = os.getenv("VAPID_PUBLIC_KEY")
    if env_priv and env_pub:
        return {"private_key": env_priv, "public_key": env_pub}

    # 1. Primary Source of Truth: Read from SQLite store_settings
    try:
        from services.db import get_store_setting_db
        raw_val = get_store_setting_db("vapid_keys")
        if raw_val:
            keys = json.loads(raw_val)
            if keys.get("private_key") and keys.get("public_key"):
                return keys
    except Exception as e:
        logger.debug(f"SQLite VAPID lookup skipped/fallback: {e}")

    # 2. Seamless Fallback: Read legacy JSON file
    os.makedirs(_DATA_DIR, exist_ok=True)
    if os.path.exists(_VAPID_FILE):
        try:
            with open(_VAPID_FILE, "r", encoding="utf-8") as f:
                keys = json.load(f)
                if keys.get("private_key") and keys.get("public_key"):
                    # Bootstrap to SQLite
                    try:
                        from services.db import update_store_setting_db
                        update_store_setting_db(
                            "vapid_keys",
                            json.dumps(keys, indent=2),
                            label="VAPID Keys",
                            description="Web Push VAPID cryptographic keys"
                        )
                    except Exception:
                        pass
                    return keys
        except Exception as e:
            logger.warning(f"Error reading existing vapid_keys.json: {e}")

    if not HAS_PYWEBPUSH:
        logger.warning("pywebpush not installed, cannot generate VAPID keys")
        return {"private_key": "", "public_key": ""}

    # Generate new VAPID keys
    vapid = Vapid()
    vapid.generate_keys()
    
    # Export private key (DER base64url or PEM) and public key (uncompressed point base64url)
    import base64
    from cryptography.hazmat.primitives import serialization

    # Raw uncompressed public key (65 bytes: 0x04 + X + Y) in base64url
    pub_bytes = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode("utf-8")

    # Private key in PEM or base64
    priv_pem = vapid.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")

    keys = {
        "private_key": priv_pem,
        "public_key": pub_b64
    }

    # Persist to SQLite store_settings
    try:
        from services.db import update_store_setting_db
        update_store_setting_db(
            "vapid_keys",
            json.dumps(keys, indent=2),
            label="VAPID Keys",
            description="Web Push VAPID cryptographic keys"
        )
    except Exception as e:
        logger.warning(f"Failed to persist VAPID keys to SQLite: {e}")

    try:
        with open(_VAPID_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, indent=2)
        logger.info(f"Generated new VAPID keypair and saved to {_VAPID_FILE}")
    except Exception as e:
        logger.error(f"Failed to save vapid_keys.json: {e}")

    return keys


def _get_vapid_instance() -> Optional[Any]:
    """Returns initialized Vapid instance from private key."""
    if not HAS_PYWEBPUSH or Vapid is None:
        return None
    keys = _ensure_vapid_keys()
    priv_pem = keys["private_key"]
    if not priv_pem:
        return None
    if isinstance(priv_pem, str):
        priv_pem = priv_pem.encode("utf-8")
    return Vapid.from_pem(priv_pem)


def get_vapid_public_key() -> str:
    """Returns the URL-safe base64 public key for client pushManager subscription."""
    keys = _ensure_vapid_keys()
    return keys.get("public_key", "")


def send_web_push(subscription_info: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sends an encrypted Web Push notification payload to a client endpoint.
    Handles auto-deactivation if endpoint is expired (HTTP 410 / 404).
    """
    endpoint = subscription_info.get("endpoint", "")
    if not HAS_PYWEBPUSH or webpush is None:
        logger.warning("pywebpush is not installed. Skipping push notification dispatch.")
        return {
            "success": False,
            "status_code": 503,
            "error": "pywebpush library not installed",
            "endpoint": endpoint
        }

    vapid_inst = _get_vapid_instance()
    if not vapid_inst:
        logger.warning("VAPID keys not configured. Skipping push notification dispatch.")
        return {
            "success": False,
            "status_code": 503,
            "error": "VAPID keys not available",
            "endpoint": endpoint
        }

    data_str = json.dumps(payload, ensure_ascii=False)

    try:
        response = webpush(
            subscription_info=subscription_info,
            data=data_str,
            vapid_private_key=vapid_inst,
            vapid_claims=VAPID_CLAIMS,
            ttl=86400  # 24 hours
        )
        return {
            "success": True,
            "status_code": response.status_code if response else 200,
            "endpoint": endpoint
        }
    except WebPushException as ex:
        status_code = ex.response.status_code if ex.response is not None else 500
        logger.warning(f"WebPushException for {endpoint}: {status_code} - {ex}")
        # RFC 8291: 404 Not Found or 410 Gone indicates subscription has expired or unsubscribed
        if status_code in (404, 410):
            logger.info(f"Deactivating expired push subscription: {endpoint}")
            deactivate_push_subscription_db(endpoint)
        return {
            "success": False,
            "status_code": status_code,
            "error": str(ex),
            "endpoint": endpoint
        }
    except Exception as e:
        logger.error(f"Unexpected error sending web push to {endpoint}: {e}")
        return {
            "success": False,
            "status_code": 500,
            "error": str(e),
            "endpoint": endpoint
        }


def send_notification_to_user(
    username: str,
    title: str,
    body: str,
    tag: str = "fnb-shift",
    url: str = "/index.html#attendance",
    icon: str = "/favicon.ico",
    data: Optional[Dict[str, Any]] = None,
    tenant_id: str = DEFAULT_TENANT_ID
) -> List[Dict[str, Any]]:
    """
    Sends a push notification to all active devices registered to a specific username.
    """
    subs = list_push_subscriptions_db(username=username, tenant_id=tenant_id)
    if not subs:
        return []

    payload = {
        "title": title,
        "body": body,
        "icon": icon,
        "badge": icon,
        "tag": tag,
        "data": {
            "url": url,
            **(data or {})
        },
        "vibrate": [100, 50, 100]
    }

    results = []
    for sub in subs:
        sub_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"]
            }
        }
        res = send_web_push(sub_info, payload)
        results.append(res)

    return results


def send_notification_to_all(
    title: str,
    body: str,
    tag: str = "fnb-broadcast",
    url: str = "/index.html#roster",
    icon: str = "/favicon.ico",
    data: Optional[Dict[str, Any]] = None,
    tenant_id: str = DEFAULT_TENANT_ID
) -> List[Dict[str, Any]]:
    """
    Broadcasts a push notification to all active devices across all users.
    """
    subs = list_push_subscriptions_db(tenant_id=tenant_id)
    if not subs:
        return []

    payload = {
        "title": title,
        "body": body,
        "icon": icon,
        "badge": icon,
        "tag": tag,
        "data": {
            "url": url,
            **(data or {})
        },
        "vibrate": [150, 50, 150]
    }

    results = []
    for sub in subs:
        sub_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"]
            }
        }
        res = send_web_push(sub_info, payload)
        results.append(res)

    return results
