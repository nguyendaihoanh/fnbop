# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Security Repository Layer
Handles tiered login attempts, IP/User lockouts, token revocations,
API rate limiting, and access audit logs.
"""

import time
import hashlib
import datetime
import logging
from typing import Optional, Dict, Any, List, Tuple

from services.db.connection import get_db_connection, DEFAULT_TENANT_ID
from services.db.schema import _ensure_login_attempts_table, _ensure_security_tables

logger = logging.getLogger("db_service")

def record_failed_attempt_tiered(
    ip: str,
    username: str = "",
    is_whitelisted_cafe: bool = False,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Records a failed login attempt with 3-tier progressive lockout:
    - Tier 1: 5 attempts -> Locks username for 60s
    - Tier 2: 10 attempts -> Locks IP (30 mins). If cafe IP, locks username 30m instead.
    - Tier 3: 11+ attempts -> Locks 5 hours (18000s), sets is_admin_locked=1.
    """
    clean_ip = (ip or "").strip()
    clean_user = (username or "").strip().lower()
    user_key = f"user:{clean_user}" if clean_user else f"ip:{clean_ip}"
    ip_key = f"ip:{clean_ip}"
    now = time.time()

    conn = get_db_connection(db_path)
    _ensure_login_attempts_table(conn)
    cur = conn.cursor()

    cur.execute("""
        SELECT attempts, tier, lockout_until, is_admin_locked 
        FROM login_attempts 
        WHERE (target_key = ? OR identifier = ?)
           OR (target_key = ? OR identifier = ?)
        ORDER BY attempts DESC
        LIMIT 1
    """, (user_key or "", clean_user or "", ip_key or "", clean_ip or ""))
    row = cur.fetchone()

    if row is None:
        attempts = 1
    else:
        attempts = row["attempts"] + 1

    tier = 1
    lockout_until = None
    is_admin_locked = 0
    target_key = user_key
    target_type = "USER"
    identifier = clean_user if clean_user else clean_ip

    if attempts >= 11:
        # TIER 3: Lock for 5 hours (18000s), Admin only unlock
        tier = 3
        lockout_until = now + 18000.0
        is_admin_locked = 1
        if is_whitelisted_cafe and clean_user:
            target_key = user_key
            target_type = "USER"
            identifier = clean_user
        else:
            target_key = ip_key
            target_type = "IP"
            identifier = clean_ip
    elif attempts >= 6:
        # TIER 2: Lock for 30 minutes (1800s)
        tier = 2
        lockout_until = now + 1800.0
        is_admin_locked = 0
        if is_whitelisted_cafe and clean_user:
            target_key = user_key
            target_type = "USER"
            identifier = clean_user
        else:
            target_key = ip_key
            target_type = "IP"
            identifier = clean_ip
    elif attempts >= 5:
        # TIER 1: Lock username for 60 seconds
        tier = 1
        lockout_until = now + 60.0
        is_admin_locked = 0
        target_key = user_key
        target_type = "USER"
        identifier = clean_user if clean_user else clean_ip

    with conn:
        conn.execute("""
            INSERT INTO login_attempts (target_key, target_type, identifier, ip, username, attempts, tier, lockout_until, is_admin_locked, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(target_key) DO UPDATE SET
                target_type = excluded.target_type,
                identifier = excluded.identifier,
                ip = excluded.ip,
                username = excluded.username,
                attempts = excluded.attempts,
                tier = excluded.tier,
                lockout_until = excluded.lockout_until,
                is_admin_locked = excluded.is_admin_locked,
                updated_at = CURRENT_TIMESTAMP
        """, (target_key, target_type, identifier, clean_ip, clean_user, attempts, tier, lockout_until, is_admin_locked))

    conn.close()

    msg = None
    if is_admin_locked == 1 or tier >= 3:
        msg = "Bạn đã đăng nhập sai quá nhiều lần. Tài khoản/IP này đã bị KHÓA 5 TIẾNG (Tầng 3). Chỉ duy nhất Chủ quán (Admin) mới có quyền mở khóa."
    elif tier == 2:
        msg = "Bạn đã đăng nhập sai quá nhiều lần. Tài khoản/IP đã bị tạm khóa 30 PHÚT (Tầng 2). Vui lòng thử lại sau 30 phút hoặc liên hệ Admin/Quản lý."
    elif tier == 1 and attempts >= 5:
        msg = "Bạn đã đăng nhập sai quá nhiều lần. Tài khoản đã bị tạm khóa 60 GIÂY (Tầng 1) do nhập sai mã PIN 5 lần. Vui lòng thử lại sau 60 giây."

    return {
        "target_key": target_key,
        "target_type": target_type,
        "identifier": identifier,
        "attempts": attempts,
        "tier": tier,
        "lockout_until": lockout_until,
        "is_admin_locked": is_admin_locked,
        "is_locked": bool(lockout_until and now < lockout_until) or bool(is_admin_locked),
        "message": msg
    }


def check_login_lockout(
    ip: str,
    username: str = "",
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Checks if a login attempt is blocked either by username (Tier 1/2/3) or IP (Tier 2/3).
    Returns lockout info dict or None if allowed.
    """
    clean_ip = (ip or "").strip()
    clean_user = (username or "").strip().lower()
    user_key = f"user:{clean_user}" if clean_user else ""
    ip_key = f"ip:{clean_ip}" if clean_ip else ""
    now = time.time()

    conn = get_db_connection(db_path)
    _ensure_login_attempts_table(conn)
    cur = conn.cursor()

    cur.execute("""
        SELECT target_key, target_type, identifier, ip, username, attempts, tier, lockout_until, is_admin_locked
        FROM login_attempts
        WHERE (target_key = ? OR identifier = ?)
           OR (target_key = ? OR identifier = ?)
        ORDER BY is_admin_locked DESC, tier DESC, attempts DESC
    """, (user_key or "", clean_user or "", ip_key or "", clean_ip or ""))
    rows = cur.fetchall()
    conn.close()

    for row in rows:
        r_dict = dict(row)
        lockout = r_dict.get("lockout_until")
        is_admin = r_dict.get("is_admin_locked")
        tier = r_dict.get("tier") or 1
        
        if is_admin == 1 or (lockout and now < lockout):
            rem = max(0, int(lockout - now)) if lockout else 0
            if is_admin == 1 or tier >= 3:
                msg = f"Bạn đã đăng nhập sai quá nhiều lần. Tài khoản/IP này đã bị KHÓA 5 TIẾNG (Tầng 3). Chỉ duy nhất Chủ quán (Admin) mới có quyền mở khóa."
            elif tier == 2:
                mins = max(1, rem // 60)
                msg = f"Bạn đã đăng nhập sai quá nhiều lần. Tài khoản/IP đã bị tạm khóa 30 PHÚT (Tầng 2). Vui lòng thử lại sau {mins} phút hoặc liên hệ Admin/Quản lý."
            else:
                msg = f"Bạn đã đăng nhập sai quá nhiều lần. Tài khoản đã bị tạm khóa 60 GIÂY (Tầng 1) do nhập sai mã PIN 5 lần. Vui lòng thử lại sau {rem} giây."
            
            r_dict["remaining_seconds"] = rem
            r_dict["message"] = msg
            return r_dict

    return None


def clear_login_lockout(ip: str, username: str = "", db_path: Optional[str] = None) -> None:
    """Clear failed login attempts for both IP and username upon successful login."""
    clean_ip = (ip or "").strip()
    clean_user = (username or "").strip().lower()
    user_key = f"user:{clean_user}" if clean_user else ""
    ip_key = f"ip:{clean_ip}" if clean_ip else ""

    conn = get_db_connection(db_path)
    _ensure_login_attempts_table(conn)
    with conn:
        conn.execute("""
            DELETE FROM login_attempts 
            WHERE target_key = ? OR target_key = ? OR identifier = ? OR identifier = ? OR ip = ?
        """, (user_key, ip_key, clean_user, clean_ip, clean_ip))
    conn.close()


def get_active_lockouts(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves all currently locked out accounts and IPs for Admin Dashboard."""
    conn = get_db_connection(db_path)
    _ensure_login_attempts_table(conn)
    now = time.time()
    cur = conn.cursor()
    cur.execute("""
        SELECT target_key, target_type, identifier, ip, username, attempts, tier, lockout_until, is_admin_locked, updated_at
        FROM login_attempts
        WHERE is_admin_locked = 1 OR (lockout_until IS NOT NULL AND lockout_until > ?)
        ORDER BY updated_at DESC
    """, (now,))
    rows = cur.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        lockout = d.get("lockout_until") or now
        d["remaining_seconds"] = max(0, int(lockout - now))
        result.append(d)
    return result


def admin_unlock_target(target_key: str, db_path: Optional[str] = None) -> bool:
    """Admin-only action: removes lockout immediately."""
    if not target_key:
        return False
    clean_target = target_key.strip()
    raw_val = clean_target
    if clean_target.startswith("ip:"):
        raw_val = clean_target[3:]
    elif clean_target.startswith("user:"):
        raw_val = clean_target[5:]

    conn = get_db_connection(db_path)
    _ensure_login_attempts_table(conn)
    with conn:
        cur = conn.execute("""
            DELETE FROM login_attempts 
            WHERE target_key = ? OR target_key = ? OR target_key = ?
               OR identifier = ? OR identifier = ?
               OR ip = ? OR username = ?
        """, (clean_target, f"ip:{raw_val}", f"user:{raw_val}", clean_target, raw_val, raw_val, raw_val))
        deleted = cur.rowcount
    conn.close()
    return deleted > 0


# Backward compatibility helpers
def get_login_attempts(ip: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    clean_ip = (ip or "").strip()
    if not clean_ip:
        return None
    conn = get_db_connection(db_path)
    _ensure_login_attempts_table(conn)
    cur = conn.cursor()
    cur.execute("""
        SELECT target_key, target_type, identifier, ip, username, attempts, tier, lockout_until, is_admin_locked
        FROM login_attempts
        WHERE ip = ? OR target_key = ? OR identifier = ?
        ORDER BY is_admin_locked DESC, tier DESC, attempts DESC
        LIMIT 1
    """, (clean_ip, f"ip:{clean_ip}", clean_ip))
    row = cur.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def record_failed_login(
    ip: str,
    max_attempts: int = 5,
    lockout_seconds: float = 60.0,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    res = record_failed_attempt_tiered(ip=ip, username="", is_whitelisted_cafe=False, db_path=db_path)
    return {"ip": ip, "attempts": res["attempts"], "lockout_until": res["lockout_until"]}


def clear_login_attempts(ip: str, db_path: Optional[str] = None) -> None:
    clear_login_lockout(ip=ip, username="", db_path=db_path)


def _hash_token(token_str: str) -> str:
    """Computes SHA-256 hash of a token string for safe storage."""
    return hashlib.sha256(token_str.strip().encode("utf-8")).hexdigest()


def revoke_token(
    token_str: str,
    reason: str = "LOGOUT",
    expires_at: Optional[float] = None,
    db_path: Optional[str] = None
) -> bool:
    """Revokes a JWT token immediately by adding its hash to the blacklist."""
    if not token_str:
        return False
    t_hash = _hash_token(token_str)
    conn = get_db_connection(db_path)
    _ensure_security_tables(conn)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO revoked_tokens (token_hash, reason, expires_at) VALUES (?, ?, ?)",
                (t_hash, reason, expires_at)
            )
        return True
    except Exception as e:
        logger.error(f"Error revoking token: {e}")
        return False
    finally:
        conn.close()


def is_token_revoked(token_str: str, db_path: Optional[str] = None) -> bool:
    """Checks if a JWT token hash exists in the revocation blacklist."""
    if not token_str:
        return True
    try:
        t_hash = _hash_token(token_str)
        conn = get_db_connection(db_path)
        _ensure_security_tables(conn)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM revoked_tokens WHERE token_hash = ?", (t_hash,))
            row = cur.fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"Error checking revoked token from database: {e}")
        return False


def cleanup_expired_tokens(db_path: Optional[str] = None) -> int:
    """Removes tokens that have passed their expiration timestamp."""
    now = time.time()
    conn = get_db_connection(db_path)
    _ensure_security_tables(conn)
    try:
        with conn:
            cur = conn.execute("DELETE FROM revoked_tokens WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            deleted = cur.rowcount
        return deleted
    finally:
        conn.close()


def check_api_rate_limit(
    key: str,
    limit: int = 30,
    window_seconds: int = 60,
    db_path: Optional[str] = None
) -> Tuple[bool, int, float]:
    """
    Checks and increments rate limit for a specific key (e.g. 'ip:1.2.3.4' or 'user:vinh').
    Atomic SQLite operation via WAL.
    Returns:
        (is_allowed: bool, current_count: int, retry_after: float)
    """
    if not key:
        return True, 0, 0.0
    clean_key = str(key).strip()
    now = time.time()
    conn = get_db_connection(db_path)
    _ensure_security_tables(conn)

    try:
        with conn:
            cur = conn.execute("SELECT count, reset_at FROM api_rate_limits WHERE key = ?", (clean_key,))
            row = cur.fetchone()

            if not row or now >= row["reset_at"]:
                reset_at = now + window_seconds
                conn.execute(
                    "INSERT INTO api_rate_limits (key, count, reset_at, updated_at) VALUES (?, 1, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET count = 1, reset_at = excluded.reset_at, updated_at = CURRENT_TIMESTAMP",
                    (clean_key, reset_at)
                )
                return True, 1, 0.0

            current_count = row["count"]
            reset_at = row["reset_at"]

            if current_count < limit:
                new_count = current_count + 1
                conn.execute(
                    "UPDATE api_rate_limits SET count = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                    (new_count, clean_key)
                )
                return True, new_count, 0.0
            else:
                retry_after = max(1.0, reset_at - now)
                return False, current_count, retry_after
    finally:
        conn.close()


def clear_all_rate_limits(db_path: Optional[str] = None) -> None:
    """Xóa sạch bảng api_rate_limits và login_attempts phục vụ testing và isolation."""
    conn = get_db_connection(db_path)
    _ensure_security_tables(conn)
    try:
        with conn:
            conn.execute("DELETE FROM api_rate_limits")
            conn.execute("DELETE FROM login_attempts")
    finally:
        conn.close()


# ==============================================================================
# ACCESS AUDIT LOGGING & EXECUTIVE WEEKLY DIGEST
# ==============================================================================

def parse_user_agent(ua_string: Optional[str]) -> Tuple[str, str]:
    """
    Parses a User-Agent string to extract Operating System and Device category.
    Ultra-lightweight and zero external dependencies (< 0.01ms).
    Returns: (os_name, device_type)
    """
    if not ua_string:
        return "Unknown", "Unknown"
    ua = ua_string.lower()

    # Determine device category
    if "ipad" in ua or "tablet" in ua:
        device = "Tablet"
    elif "mobile" in ua or "iphone" in ua or "android" in ua:
        device = "Mobile"
    elif any(b in ua for b in ("bot", "crawler", "spider", "uptime", "curl", "python", "http")):
        device = "Bot/Automated"
    else:
        device = "Desktop"

    # Determine OS name
    if any(k in ua for k in ("iphone", "ipad", "ipod", "cpu os", "like mac os x")) and "android" not in ua:
        os_name = "iOS"
    elif "android" in ua:
        os_name = "Android"
    elif "macintosh" in ua or "mac os x" in ua:
        os_name = "macOS"
    elif "windows" in ua:
        os_name = "Windows"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Other"

    return os_name, device


def record_access_audit(
    username: str,
    full_name: str,
    action: str,
    client_ip: Optional[str] = None,
    is_cafe_wifi: bool = False,
    user_agent: Optional[str] = None,
    details: Optional[str] = None,
    role: str = "STAFF",
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """
    Records an access event into SQLite WAL table access_audit_logs.
    Fail-safe: Wrapped in try-except so it never blocks or crashes business operations.
    """
    try:
        os_name, device_type = parse_user_agent(user_agent)
        ts_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection(db_path)
        _ensure_security_tables(conn)
        with conn:
            conn.execute(
                """
                INSERT INTO access_audit_logs 
                (timestamp, username, full_name, role, action, client_ip, is_cafe_wifi, user_agent, os_name, device_type, details, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_now,
                    str(username or "unknown").strip(),
                    str(full_name or "").strip(),
                    str(role or "STAFF").strip().upper(),
                    str(action or "UNKNOWN").strip().upper(),
                    str(client_ip or "").strip(),
                    1 if is_cafe_wifi else 0,
                    str(user_agent or "")[:255],
                    os_name,
                    device_type,
                    str(details or "")[:500] if details else None,
                    tenant_id
                )
            )
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"Non-blocking audit log record failure: {e}")
        return False


def get_access_audit_logs(
    start_time: str,
    end_time: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Queries access audit logs between start_time and end_time (ISO format or YYYY-MM-DD HH:MM:SS).
    """
    conn = get_db_connection(db_path)
    _ensure_security_tables(conn)
    try:
        cur = conn.execute(
            """
            SELECT id, timestamp, username, full_name, role, action, client_ip, is_cafe_wifi, user_agent, os_name, device_type, details
            FROM access_audit_logs
            WHERE tenant_id = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY id ASC
            """,
            (tenant_id, start_time, end_time)
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        conn.close()


def purge_old_access_audit_logs(
    retention_days: int = 90,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> int:
    """
    Purges audit logs older than retention_days (default 90 days) to keep database compact.
    """
    conn = get_db_connection(db_path)
    _ensure_security_tables(conn)
    try:
        cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
        with conn:
            cur = conn.execute(
                "DELETE FROM access_audit_logs WHERE tenant_id = ? AND timestamp < ?",
                (tenant_id, cutoff_date)
            )
            return cur.rowcount
    except Exception as e:
        logger.error(f"Error purging old audit logs: {e}")
        return 0
    finally:
        conn.close()

