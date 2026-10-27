# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Staff Repository Layer
Handles staff accounts, directory lookups, employee ID resolution,
and bootstrapping/syncing authentication data to SQLite.
"""

import os
import json
import logging
import datetime
import unicodedata
from typing import Optional, Dict, Any, List, Union

from services.db.connection import get_db_connection, DEFAULT_TENANT_ID, _BASE_DIR
from services.db.schema import (
    init_db,
    _ensure_staff_accounts_table,
    _ensure_payroll_confirmations_table,
)

logger = logging.getLogger("db_service")

def get_staff_by_username(username: str, tenant_id: str = DEFAULT_TENANT_ID, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_staff_accounts_table(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM staff_accounts WHERE username = ? AND tenant_id = ?",
        (str(username).strip().lower(), tenant_id)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    if "is_active" in d:
        d["is_active"] = bool(d["is_active"])
    return d


def list_staff_accounts(tenant_id: str = DEFAULT_TENANT_ID, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_staff_accounts_table(conn)
    cur = conn.cursor()
    cur.execute(
        """SELECT username, employee_id, tenant_id, full_name, display_name, role, pin_hash,
                  email, phone, hourly_rate, is_active, position, gender, status,
                  last_login, created_at
           FROM staff_accounts WHERE tenant_id = ? ORDER BY full_name ASC""",
        (tenant_id,)
    )
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        d["is_active"] = bool(d["is_active"])
        rows.append(d)
    conn.close()
    return rows


def upsert_staff_account(
    username: str,
    full_name: Optional[str] = None,
    pin_hash: str = "",
    role: str = "STAFF",
    position: str = "SERVICE",
    gender: str = "NAM",
    status: str = "ACTIVE",
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    hourly_rate: int = 17000,
    is_active: Optional[bool] = None,
    employee_id: Optional[str] = None,
    allowed_roles: Optional[Union[List[str], str]] = None,
    salary_type: str = "HOURLY",
    fixed_salary: int = 0,
    token_version: Optional[int] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> None:
    final_display_name = (display_name or full_name or username).strip()
    final_full_name = (full_name or display_name or username).strip()
    if is_active is not None:
        final_is_active = 1 if is_active else 0
        final_status = "ACTIVE" if is_active else "INACTIVE"
    else:
        final_status = status.upper() if status else "ACTIVE"
        final_is_active = 0 if final_status == "INACTIVE" else 1

    if allowed_roles is not None:
        if isinstance(allowed_roles, list):
            import json
            final_allowed_roles = json.dumps(allowed_roles, ensure_ascii=False)
        else:
            final_allowed_roles = str(allowed_roles)
    else:
        final_allowed_roles = "[]"

    conn = get_db_connection(db_path)
    _ensure_staff_accounts_table(conn)
    clean_u = str(username).strip().lower()
    final_emp_id = (employee_id or "").strip()
    if not final_emp_id:
        cur = conn.cursor()
        cur.execute("SELECT employee_id FROM staff_accounts WHERE username = ?", (clean_u,))
        existing = cur.fetchone()
        if existing and existing["employee_id"]:
            final_emp_id = existing["employee_id"]
        else:
            cur.execute("SELECT COUNT(*) FROM staff_accounts")
            next_num = (cur.fetchone()[0] or 0) + 1
            final_emp_id = f"EMP_{next_num:03d}"

    final_token_ver = int(token_version) if token_version is not None else 1

    with conn:
        conn.execute("""
            INSERT INTO staff_accounts (
                username, employee_id, tenant_id, full_name, display_name, pin_hash,
                role, position, gender, status, email, phone, hourly_rate, is_active, allowed_roles,
                salary_type, fixed_salary, token_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                employee_id = CASE WHEN staff_accounts.employee_id IS NULL OR staff_accounts.employee_id = '' THEN excluded.employee_id ELSE staff_accounts.employee_id END,
                full_name = excluded.full_name,
                display_name = excluded.display_name,
                pin_hash = CASE WHEN excluded.pin_hash != '' THEN excluded.pin_hash ELSE staff_accounts.pin_hash END,
                role = excluded.role,
                position = excluded.position,
                gender = excluded.gender,
                status = excluded.status,
                email = COALESCE(excluded.email, staff_accounts.email),
                phone = COALESCE(excluded.phone, staff_accounts.phone),
                hourly_rate = excluded.hourly_rate,
                is_active = excluded.is_active,
                allowed_roles = CASE WHEN excluded.allowed_roles != '[]' THEN excluded.allowed_roles ELSE staff_accounts.allowed_roles END,
                salary_type = excluded.salary_type,
                fixed_salary = excluded.fixed_salary,
                token_version = CASE WHEN ? IS NOT NULL THEN ? ELSE COALESCE(staff_accounts.token_version, 1) END
        """, (
            clean_u,
            final_emp_id,
            tenant_id,
            final_full_name,
            final_display_name,
            pin_hash,
            role.upper(),
            position,
            gender,
            final_status,
            email,
            phone,
            hourly_rate,
            final_is_active,
            final_allowed_roles,
            (salary_type or "HOURLY").upper(),
            int(fixed_salary or 0),
            final_token_ver,
            token_version,
            token_version
        ))
    conn.close()


def get_staff_token_version(username: str, tenant_id: str = DEFAULT_TENANT_ID, db_path: Optional[str] = None) -> int:
    """Reads current staff token_version from SQLite staff_accounts."""
    try:
        conn = get_db_connection(db_path)
        _ensure_staff_accounts_table(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT token_version FROM staff_accounts WHERE username = ? AND tenant_id = ?",
            (str(username).strip().lower(), tenant_id)
        )
        row = cur.fetchone()
        conn.close()
        if row and row["token_version"] is not None:
            return int(row["token_version"])
    except Exception:
        pass
    return 1


def bump_staff_token_version_db(username: str, tenant_id: str = DEFAULT_TENANT_ID, db_path: Optional[str] = None) -> int:
    """Increments staff token_version atomically in SQLite."""
    clean_u = str(username).strip().lower()
    try:
        conn = get_db_connection(db_path)
        _ensure_staff_accounts_table(conn)
        with conn:
            conn.execute("""
                UPDATE staff_accounts 
                SET token_version = COALESCE(token_version, 1) + 1 
                WHERE username = ? AND tenant_id = ?
            """, (clean_u, tenant_id))
        cur = conn.cursor()
        cur.execute("SELECT token_version FROM staff_accounts WHERE username = ? AND tenant_id = ?", (clean_u, tenant_id))
        row = cur.fetchone()
        conn.close()
        if row and row["token_version"] is not None:
            return int(row["token_version"])
    except Exception:
        pass
    return 1

def get_staff_directory_map(
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary of all staff accounts keyed by username, enriched with employee_id and aliases from SQLite.
    """
    conn = get_db_connection(db_path)
    _ensure_staff_accounts_table(conn)
    cur = conn.cursor()
    cur.execute(
        """SELECT username, employee_id, full_name, display_name, role, position, gender, status, hourly_rate, is_active
           FROM staff_accounts WHERE tenant_id = ? ORDER BY employee_id ASC, username ASC""",
        (tenant_id,)
    )
    directory: Dict[str, Dict[str, Any]] = {}
    for r in cur.fetchall():
        u = r["username"]
        directory[u] = {
            "username": u,
            "employee_id": r["employee_id"] or "",
            "full_name": r["full_name"] or u,
            "display_name": r["display_name"] or r["full_name"] or u,
            "role": r["role"] or "STAFF",
            "position": r["position"] or "SERVICE",
            "gender": r["gender"] or "NAM",
            "status": r["status"] or "ACTIVE",
            "hourly_rate": int(r["hourly_rate"] or 17000),
            "is_active": bool(r["is_active"]),
            "aliases": []
        }

    try:
        cur.execute("SELECT username, alias FROM staff_aliases WHERE tenant_id = ?", (tenant_id,))
        for ar in cur.fetchall():
            u = ar["username"]
            al = ar["alias"]
            if u in directory and al and al not in directory[u]["aliases"]:
                directory[u]["aliases"].append(al)
    except Exception:
        pass

    conn.close()
    return directory


def resolve_employee_id(
    raw_identifier: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Resolves an employee by employee_id (EMP_001), username, full_name, or alias in SQLite.
    """
    if not raw_identifier:
        return None
    import unicodedata
    target = unicodedata.normalize("NFC", str(raw_identifier).strip())
    target_upper = target.upper()
    target_lower = target.lower()

    directory = get_staff_directory_map(tenant_id=tenant_id, db_path=db_path)
    # 1. Exact match by employee_id or username
    for u, info in directory.items():
        if info["employee_id"].upper() == target_upper or u.lower() == target_lower:
            return info
    # 2. Exact match by full_name or alias (NFC case-insensitive)
    for u, info in directory.items():
        fn_upper = unicodedata.normalize("NFC", info["full_name"]).strip().upper()
        if fn_upper == target_upper:
            return info
        for al in info.get("aliases", []):
            if unicodedata.normalize("NFC", str(al)).strip().upper() == target_upper:
                return info
    return None

def bootstrap_sync_staff_auth_to_sqlite(
    auth_file_path: Optional[Any] = None,
    db_path: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID
) -> Dict[str, Any]:
    """
    Safely bootstrap & mirror staff_auth (accounts, PINs, aliases, allowed_roles,
    payroll_locks, and confirmations) into SQLite without destroying existing records.
    Accepts either an auth dict or a file path string.
    """
    import json
    init_db(db_path)

    if isinstance(auth_file_path, dict):
        auth_data = auth_file_path
    else:
        auth_file = auth_file_path
        if not auth_file or not os.path.exists(auth_file):
            candidates = [
                os.getenv("AUTH_FILE"),
                os.path.join(_BASE_DIR, "staff_auth.json"),
                os.path.join(_BASE_DIR, "data", "staff_auth.json"),
                os.path.join(os.path.dirname(_BASE_DIR), "data", "staff_auth.json"),
            ]
            auth_file = next((f for f in candidates if f and os.path.exists(f)), None)

        if not auth_file or not os.path.exists(auth_file):
            return {"success": False, "message": "No staff_auth.json found", "synced_staff": 0}

        try:
            with open(auth_file, "r", encoding="utf-8") as f:
                auth_data = json.load(f)
        except Exception as e:
            logger.error(f"Cannot read auth file {auth_file}: {e}")
            return {"success": False, "message": str(e), "synced_staff": 0}

    accounts = auth_data.get("staff_accounts", {})
    locks = auth_data.get("payroll_locks", {})

    try:
        from services.storage import hash_pin, needs_rehash
    except ImportError:
        try:
            from backend.services.storage import hash_pin, needs_rehash
        except ImportError:
            def hash_pin(p: str) -> str: return p
            def needs_rehash(p: str) -> bool: return False

    conn = get_db_connection(db_path)
    _ensure_staff_accounts_table(conn)
    _ensure_payroll_confirmations_table(conn)

    synced_staff = 0
    synced_conf = 0
    synced_locks = 0

    with conn:
        for idx, (u_key, acc) in enumerate(accounts.items(), start=1):
            u_norm = str(u_key).strip().lower()
            emp_id = acc.get("employee_id") or f"EMP_{idx:03d}"
            full_name = acc.get("full_name") or u_key
            pin_raw = str(acc.get("pin", "1234")).strip()
            pin_hash = hash_pin(pin_raw) if needs_rehash(pin_raw) else pin_raw
            role = str(acc.get("role", "STAFF")).strip().upper()
            position = acc.get("position", "SERVICE")
            gender = acc.get("gender", "NAM")
            status = acc.get("status", "ACTIVE")
            is_active = 0 if status == "INACTIVE" else 1
            email = acc.get("email", "")
            phone = acc.get("phone", "")
            hourly_rate = int(acc.get("hourly_rate", 17000))
            last_login = acc.get("last_login")
            created_at = acc.get("created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            allowed_roles = acc.get("allowed_roles")
            allowed_roles_json = json.dumps(allowed_roles, ensure_ascii=False) if allowed_roles is not None else "[]"

            token_ver = int(acc.get("token_version", 1))

            conn.execute("""
                INSERT INTO staff_accounts (
                    username, employee_id, tenant_id, full_name, display_name, pin_hash,
                    role, position, gender, status, email, phone, hourly_rate, is_active,
                    allowed_roles, token_version, last_login, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    employee_id = CASE WHEN staff_accounts.employee_id IS NULL OR staff_accounts.employee_id = '' THEN excluded.employee_id ELSE staff_accounts.employee_id END,
                    full_name = excluded.full_name,
                    display_name = excluded.display_name,
                    pin_hash = CASE WHEN excluded.pin_hash != '' THEN excluded.pin_hash ELSE staff_accounts.pin_hash END,
                    role = excluded.role,
                    position = excluded.position,
                    gender = excluded.gender,
                    status = excluded.status,
                    hourly_rate = excluded.hourly_rate,
                    is_active = excluded.is_active,
                    allowed_roles = CASE WHEN excluded.allowed_roles != '[]' THEN excluded.allowed_roles ELSE staff_accounts.allowed_roles END,
                    token_version = COALESCE(excluded.token_version, staff_accounts.token_version, 1),
                    last_login = COALESCE(excluded.last_login, staff_accounts.last_login)
            """, (
                u_norm, emp_id, tenant_id, full_name, full_name, pin_hash,
                role, position, gender, status, email, phone, hourly_rate, is_active,
                allowed_roles_json, token_ver, last_login, created_at
            ))
            synced_staff += 1

            # Sync aliases & sheet_names
            aliases = set(acc.get("aliases", []))
            aliases.update(acc.get("sheet_names", []))
            aliases.add(full_name)
            for al in aliases:
                if al:
                    conn.execute("""
                        INSERT OR IGNORE INTO staff_aliases (username, alias, tenant_id)
                        VALUES (?, ?, ?)
                    """, (u_norm, str(al).strip(), tenant_id))

            # Sync confirmations
            confirmations = acc.get("confirmations", {})
            if isinstance(confirmations, dict):
                for m_key, conf_data in confirmations.items():
                    c_status = conf_data.get("status", "CONFIRMED")
                    c_note = conf_data.get("note", "")
                    c_ts = conf_data.get("timestamp", "")
                    conn.execute("""
                        INSERT INTO payroll_confirmations (tenant_id, username, month, status, note, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(tenant_id, username, month) DO UPDATE SET
                            status = excluded.status,
                            note = excluded.note,
                            timestamp = excluded.timestamp
                    """, (tenant_id, u_norm, str(m_key), c_status, c_note, c_ts))
                    synced_conf += 1

        # Sync payroll_locks
        for m_key, lock_val in locks.items():
            l_status = lock_val.get("status", "OPEN")
            msg = lock_val.get("message", "")
            conn.execute("""
                INSERT INTO payroll_locks (month, tenant_id, status, message)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(month, tenant_id) DO UPDATE SET
                    status = excluded.status,
                    message = excluded.message
            """, (str(m_key), tenant_id, l_status, msg))
            synced_locks += 1

    conn.close()
    return {
        "success": True,
        "synced_staff": synced_staff,
        "synced_confirmations": synced_conf,
        "synced_locks": synced_locks
    }


def load_staff_auth_from_sqlite(tenant_id: str = DEFAULT_TENANT_ID, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Primary Source of Truth: Loads staff accounts, aliases, confirmations,
    and payroll locks directly from SQLite database.
    """
    try:
        conn = get_db_connection(db_path)
        _ensure_staff_accounts_table(conn)
        cur = conn.cursor()

        # 1. Load accounts
        cur.execute("SELECT * FROM staff_accounts WHERE tenant_id = ? ORDER BY full_name ASC", (tenant_id,))
        accounts_map = {}
        for row in cur.fetchall():
            d = dict(row)
            u = d["username"]
            allowed_roles = []
            if d.get("allowed_roles"):
                try:
                    allowed_roles = json.loads(d["allowed_roles"])
                except Exception:
                    allowed_roles = [d.get("position", "SERVICE")]
            
            accounts_map[u] = {
                "full_name": d.get("full_name") or u,
                "display_name": d.get("display_name") or d.get("full_name") or u,
                "employee_id": d.get("employee_id") or "",
                "role": d.get("role") or "STAFF",
                "pin": d.get("pin_hash") or "",
                "position": d.get("position") or "SERVICE",
                "gender": d.get("gender") or "NAM",
                "status": d.get("status") or "ACTIVE",
                "hourly_rate": d.get("hourly_rate") or 0,
                "salary_type": d.get("salary_type") or "HOURLY",
                "fixed_salary": d.get("fixed_salary") or 0,
                "token_version": d.get("token_version") or 1,
                "phone": d.get("phone") or "",
                "allowed_roles": allowed_roles,
                "aliases": [],
                "sheet_names": [],
                "confirmations": {}
            }

        if not accounts_map:
            conn.close()
            return {}

        # 2. Load aliases
        try:
            cur.execute("SELECT username, alias FROM staff_aliases WHERE tenant_id = ?", (tenant_id,))
            for r in cur.fetchall():
                u_alias = r[0]
                al = r[1]
                if u_alias in accounts_map:
                    if al not in accounts_map[u_alias]["aliases"]:
                        accounts_map[u_alias]["aliases"].append(al)
        except Exception:
            pass

        # 3. Load confirmations
        try:
            cur.execute("SELECT username, month, status, note, timestamp FROM payroll_confirmations WHERE tenant_id = ?", (tenant_id,))
            for r in cur.fetchall():
                u_c, m_c, st_c, n_c, ts_c = r[0], r[1], r[2], r[3], r[4]
                if u_c in accounts_map:
                    accounts_map[u_c]["confirmations"][str(m_c)] = {
                        "status": st_c,
                        "note": n_c or "",
                        "timestamp": ts_c or ""
                    }
        except Exception:
            pass

        # 4. Load payroll_locks
        locks_map = {}
        try:
            cur.execute("SELECT month, status, message FROM payroll_locks WHERE tenant_id = ?", (tenant_id,))
            for r in cur.fetchall():
                locks_map[str(r[0])] = {
                    "status": r[1],
                    "message": r[2] or ""
                }
        except Exception:
            pass

        conn.close()
        return {
            "staff_accounts": accounts_map,
            "payroll_locks": locks_map
        }
    except Exception as e:
        logger.error(f"Error loading staff auth from SQLite: {e}")
        return {}

