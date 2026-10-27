# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Notification Repository Layer
Handles Web Push subscriptions, notification dispatch deduplication,
and in-app persistent staff reminders.
"""

import datetime
import logging
from typing import Optional, Dict, Any, List

from services.db.connection import get_db_connection, DEFAULT_TENANT_ID
from services.db.schema import _ensure_v2_operational_tables

logger = logging.getLogger("db_service")

# PUSH NOTIFICATION & DEDUPLICATION REPOSITORY
# ==========================================

def save_push_subscription_db(
    username: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Saves or updates a Web Push subscription endpoint for a user."""
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("""
            INSERT INTO push_subscriptions (
                username, tenant_id, endpoint, p256dh, auth, user_agent, is_active, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(endpoint) DO UPDATE SET
                username = excluded.username,
                tenant_id = excluded.tenant_id,
                p256dh = excluded.p256dh,
                auth = excluded.auth,
                user_agent = excluded.user_agent,
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
        """, (username.strip(), tenant_id, endpoint.strip(), p256dh.strip(), auth.strip(), user_agent))
    conn.close()
    return {"status": "ok", "username": username, "endpoint": endpoint}


def list_push_subscriptions_db(
    username: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Returns active push subscriptions for a user or all users in tenant."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    if username:
        cur.execute("""
            SELECT id, username, endpoint, p256dh, auth, user_agent, created_at, updated_at
            FROM push_subscriptions
            WHERE tenant_id = ? AND username = ? AND is_active = 1
        """, (tenant_id, username.strip()))
    else:
        cur.execute("""
            SELECT id, username, endpoint, p256dh, auth, user_agent, created_at, updated_at
            FROM push_subscriptions
            WHERE tenant_id = ? AND is_active = 1
        """, (tenant_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def deactivate_push_subscription_db(
    endpoint: str,
    db_path: Optional[str] = None
) -> bool:
    """Marks an expired or invalid push subscription as inactive (HTTP 410 Gone / 404)."""
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("""
            UPDATE push_subscriptions
            SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE endpoint = ?
        """, (endpoint.strip(),))
    conn.close()
    return True


def has_notification_dispatched_db(
    dedup_key: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """Checks if a notification with this dedup_key has already been recorded."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT 1 FROM notification_dispatches
        WHERE tenant_id = ? AND dedup_key = ?
        LIMIT 1
    """, (tenant_id, dedup_key.strip()))
    row = cur.fetchone()
    conn.close()
    return row is not None


def record_notification_dispatch_db(
    dedup_key: str,
    notification_type: str,
    username: str,
    title: str,
    body: str,
    status: str,
    response_code: int = 0,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Records a dispatched notification for deduplication and audit tracking."""
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("""
            INSERT OR IGNORE INTO notification_dispatches (
                tenant_id, dedup_key, notification_type, username, title, body, status, response_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tenant_id,
            dedup_key.strip(),
            notification_type.strip(),
            username.strip(),
            title.strip(),
            body.strip(),
            status.strip(),
            response_code
        ))
    conn.close()
    return {"status": "recorded", "dedup_key": dedup_key}


def save_in_app_reminder_db(
    username: str,
    remind_type: str,
    title: str,
    message: str,
    url: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> int:
    """
    Saves an in-app reminder popup for a user with de-duplication:
    If an unread reminder of the same type already exists, update it instead of creating a duplicate.
    """
    u = username.strip().lower()
    rt = remind_type.strip().upper()
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    with conn:
        cur.execute("""
            SELECT id FROM in_app_reminders
            WHERE tenant_id = ? AND username = ? AND remind_type = ? AND is_read = 0
            ORDER BY id DESC LIMIT 1
        """, (tenant_id, u, rt))
        existing = cur.fetchone()
        if existing:
            reminder_id = existing["id"]
            cur.execute("""
                UPDATE in_app_reminders
                SET title = ?, message = ?, url = ?, created_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (title.strip(), message.strip(), url.strip(), reminder_id))
        else:
            cur.execute("""
                INSERT INTO in_app_reminders (
                    tenant_id, username, remind_type, title, message, url, is_read, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            """, (
                tenant_id,
                u,
                rt,
                title.strip(),
                message.strip(),
                url.strip()
            ))
            reminder_id = cur.lastrowid
    conn.close()
    return reminder_id or 0


def list_active_in_app_reminders_db(
    username: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None,
    max_age_hours: int = 2
) -> List[Dict[str, Any]]:
    """
    Fetches the latest unread in-app reminder for a user (anti-spam limit 1).
    Enforces TTL cutoff (default 2 hours) and shift sanity checks so stale
    morning shift reminders do not haunt users at night.
    """
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, tenant_id, username, remind_type, title, message, url, is_read, created_at
        FROM in_app_reminders
        WHERE tenant_id = ? 
          AND username = ? 
          AND is_read = 0
          AND (created_at IS NULL OR datetime(created_at) >= datetime('now', ?))
        ORDER BY id DESC
        LIMIT 5
    """, (tenant_id, username.strip().lower(), f"-{int(max_age_hours)} hours"))
    rows = cur.fetchall()
    conn.close()

    # Vietnam current hour (UTC+7)
    now_vn_hour = (datetime.datetime.now(datetime.timezone.utc).hour + 7) % 24
    valid_rows = []
    for r in rows:
        r_dict = dict(r)
        t_lower = str(r_dict.get("title", "")).lower()
        # Drop stale morning reminders if it's already afternoon or evening
        if "ca sáng" in t_lower and now_vn_hour >= 14:
            continue
        valid_rows.append(r_dict)
        if len(valid_rows) >= 1:
            break

    return valid_rows


def ack_in_app_reminder_db(
    reminder_id: int,
    username: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """Marks an in-app reminder as read/acknowledged."""
    conn = get_db_connection(db_path)
    with conn:
        conn.execute("""
            UPDATE in_app_reminders
            SET is_read = 1, read_at = CURRENT_TIMESTAMP
            WHERE id = ? AND tenant_id = ? AND username = ?
        """, (reminder_id, tenant_id, username.strip().lower()))
    conn.close()
    return True


def ack_all_in_app_reminders_db(
    username: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> int:
    """Marks ALL unread in-app reminders as read/acknowledged for a user."""
    conn = get_db_connection(db_path)
    with conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE in_app_reminders
            SET is_read = 1, read_at = CURRENT_TIMESTAMP
            WHERE tenant_id = ? AND username = ? AND is_read = 0
        """, (tenant_id, username.strip().lower()))
        count = cur.rowcount
    conn.close()
    return count
