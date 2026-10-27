# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Operations Repository Layer
Handles evaluations, daily closings (POS revenue, audit logs),
data seed migrations from legacy JSON, and store quick settings toggles.
"""

import os
import json
import sqlite3
import logging
import datetime
from typing import Optional, Dict, Any, List

from services.db.connection import (
    get_db_connection,
    DEFAULT_TENANT_ID,
    _BASE_DIR,
    _PROJECT_DIR,
)
from services.db.schema import (
    init_db,
    _ensure_evaluations_table,
    _ensure_daily_closings_table,
    _ensure_v2_operational_tables,
    _ensure_staff_accounts_table,
)

logger = logging.getLogger("db_service")

def insert_evaluation(eval_dict: Dict[str, Any], tenant_id: str = DEFAULT_TENANT_ID, db_path: Optional[str] = None) -> Any:
    conn = get_db_connection(db_path)
    _ensure_evaluations_table(conn)
    staff_name = eval_dict.get("staffName") or eval_dict.get("staff_name") or ""
    date = eval_dict.get("date") or datetime.date.today().strftime("%Y-%m-%d")
    month = str(eval_dict.get("month") or (date.split("-")[1] if "-" in date else "9"))
    ev_type = eval_dict.get("type") or "Đánh Giá"
    amount = int(eval_dict.get("amount") or 0)
    reason = eval_dict.get("reason") or ""
    notes = eval_dict.get("notes") or ""
    manager = eval_dict.get("manager") or eval_dict.get("by") or "Quản Lý"
    created_by = eval_dict.get("created_by") or eval_dict.get("createdBy") or ""
    status = eval_dict.get("status") or "ACTIVE"
    shift = eval_dict.get("shift") or "Ca Sáng"
    created_at = eval_dict.get("created_at") or eval_dict.get("createdAt") or eval_dict.get("timestamp") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    raw_id = eval_dict.get("id")
    eval_key = str(eval_dict.get("eval_key") or (raw_id if raw_id and not str(raw_id).isdigit() else ""))
    admin_note = str(eval_dict.get("admin_note") or "")
    reviewed_by = str(eval_dict.get("reviewed_by") or "")
    reviewed_at = str(eval_dict.get("reviewed_at") or "")

    meta = {}
    for mk in ["ratings", "redFlags", "createdByRole", "createdByName"]:
        if mk in eval_dict:
            meta[mk] = eval_dict[mk]
    meta_json = json.dumps(meta, ensure_ascii=False) if meta else "{}"

    with conn:
        existing_id = None
        if eval_key:
            cur = conn.execute("SELECT id FROM evaluations WHERE tenant_id = ? AND eval_key = ? LIMIT 1", (tenant_id, eval_key))
            r = cur.fetchone()
            if r:
                existing_id = r[0]
        elif raw_id is not None and (isinstance(raw_id, int) or (isinstance(raw_id, str) and raw_id.isdigit())):
            cur = conn.execute("SELECT id FROM evaluations WHERE tenant_id = ? AND id = ? LIMIT 1", (tenant_id, int(raw_id)))
            r = cur.fetchone()
            if r:
                existing_id = r[0]

        if existing_id is not None:
            conn.execute("""
                UPDATE evaluations SET
                    staff_name = ?, date = ?, month = ?, shift = ?, type = ?, amount = ?,
                    reason = ?, notes = ?, manager = ?, created_by = ?, status = ?,
                    eval_key = ?, admin_note = ?, reviewed_by = ?, reviewed_at = ?, meta_json = ?
                WHERE id = ? AND tenant_id = ?
            """, (
                staff_name, date, month, shift, ev_type, amount,
                reason, notes, manager, created_by, status,
                eval_key, admin_note, reviewed_by, reviewed_at, meta_json,
                existing_id, tenant_id
            ))
            eval_id = existing_id
        elif raw_id is not None and (isinstance(raw_id, int) or (isinstance(raw_id, str) and raw_id.isdigit())):
            cur = conn.execute("""
                INSERT INTO evaluations (
                    id, tenant_id, staff_name, date, month, shift, type, amount,
                    reason, notes, manager, created_by, status, created_at,
                    eval_key, admin_note, reviewed_by, reviewed_at, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(raw_id), tenant_id, staff_name, date, month, shift, ev_type, amount,
                reason, notes, manager, created_by, status, created_at,
                eval_key, admin_note, reviewed_by, reviewed_at, meta_json
            ))
            eval_id = cur.lastrowid
        else:
            cur = conn.execute("""
                INSERT INTO evaluations (
                    tenant_id, staff_name, date, month, shift, type, amount,
                    reason, notes, manager, created_by, status, created_at,
                    eval_key, admin_note, reviewed_by, reviewed_at, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tenant_id, staff_name, date, month, shift, ev_type, amount,
                reason, notes, manager, created_by, status, created_at,
                eval_key, admin_note, reviewed_by, reviewed_at, meta_json
            ))
            eval_id = cur.lastrowid
    conn.close()
    return eval_id


def clear_evaluations_db(
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """Clear all evaluations for a tenant in SQLite."""
    conn = get_db_connection(db_path)
    _ensure_evaluations_table(conn)
    with conn:
        conn.execute("DELETE FROM evaluations WHERE tenant_id = ?", (tenant_id,))
    conn.close()
    return True


def update_evaluation_status_db(
    eval_id: Any,
    status: str,
    admin_note: str = "",
    reviewed_by: str = "",
    reviewed_at: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    conn = get_db_connection(db_path)
    _ensure_evaluations_table(conn)
    now_str = reviewed_at or datetime.datetime.now().isoformat()
    with conn:
        if isinstance(eval_id, int) or (isinstance(eval_id, str) and eval_id.isdigit()):
            cur = conn.execute("""
                UPDATE evaluations
                SET status = ?, admin_note = ?, reviewed_by = ?, reviewed_at = ?
                WHERE tenant_id = ? AND (id = ? OR eval_key = ?)
            """, (status, admin_note, reviewed_by, now_str, tenant_id, int(eval_id), str(eval_id)))
        else:
            cur = conn.execute("""
                UPDATE evaluations
                SET status = ?, admin_note = ?, reviewed_by = ?, reviewed_at = ?
                WHERE tenant_id = ? AND eval_key = ?
            """, (status, admin_note, reviewed_by, now_str, tenant_id, str(eval_id)))
        updated = cur.rowcount > 0
    conn.close()
    return updated


def get_evaluation_by_id_db(
    eval_id: Any,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_evaluations_table(conn)
    cur = conn.cursor()
    if isinstance(eval_id, int) or (isinstance(eval_id, str) and eval_id.isdigit()):
        cur.execute(
            "SELECT * FROM evaluations WHERE tenant_id = ? AND (id = ? OR eval_key = ?) LIMIT 1",
            (tenant_id, int(eval_id), str(eval_id))
        )
    else:
        cur.execute(
            "SELECT * FROM evaluations WHERE tenant_id = ? AND eval_key = ? LIMIT 1",
            (tenant_id, str(eval_id))
        )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    r_dict = dict(row)
    r_dict["staffName"] = r_dict.get("staff_name") or ""
    if r_dict.get("eval_key"):
        r_dict["id"] = r_dict["eval_key"]
    if r_dict.get("meta_json"):
        try:
            meta = json.loads(r_dict["meta_json"])
            if isinstance(meta, dict):
                for mk, mv in meta.items():
                    if mk not in r_dict:
                        r_dict[mk] = mv
        except Exception:
            pass
    return r_dict


def list_evaluations(month: Optional[str] = None, tenant_id: str = DEFAULT_TENANT_ID, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_evaluations_table(conn)
    cur = conn.cursor()
    if month and str(month).lower() != "all":
        cur.execute(
            "SELECT * FROM evaluations WHERE tenant_id = ? AND month = ? AND status != 'CANCELLED' ORDER BY date DESC, id DESC",
            (tenant_id, str(month))
        )
    else:
        cur.execute(
            "SELECT * FROM evaluations WHERE tenant_id = ? AND status != 'CANCELLED' ORDER BY date DESC, id DESC",
            (tenant_id,)
        )
    raw_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    rows = []
    for r in raw_rows:
        row_dict = dict(r)
        row_dict["staffName"] = row_dict.get("staff_name") or ""
        if row_dict.get("eval_key"):
            row_dict["id"] = row_dict["eval_key"]
        if row_dict.get("meta_json"):
            try:
                meta = json.loads(row_dict["meta_json"])
                if isinstance(meta, dict):
                    for mk, mv in meta.items():
                        if mk not in row_dict:
                            row_dict[mk] = mv
            except Exception:
                pass
        rows.append(row_dict)
    return rows

def insert_daily_closing(
    record: Dict[str, Any],
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Inserts a daily POS closing record into SQLite and returns the persisted record.
    """
    conn = get_db_connection(db_path)
    _ensure_daily_closings_table(conn)
    diff_val = float(record.get("diff", record.get("diff_amount", 0.0)) or 0.0)
    diff_amt_val = float(record.get("diff_amount", record.get("diff", 0.0)) or 0.0)
    notes_val = str(record.get("notes") or "")
    shift_key_val = str(record.get("shift_key") or "daily")

    try:
        with conn:
            cur = conn.execute("""
                INSERT INTO daily_closings (
                    tenant_id, report_date, closing_time, bill_pos,
                    cash_amount, transfer_amount, expense_amount, expense_detail,
                    total_real, diff, diff_amount, diff_status, is_warning,
                    sender_name, approver_name, notes, shift_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                tenant_id,
                record["report_date"],
                record["closing_time"],
                float(record.get("bill_pos", 0.0) or 0.0),
                float(record.get("cash_amount", 0.0) or 0.0),
                float(record.get("transfer_amount", 0.0) or 0.0),
                float(record.get("expense_amount", 0.0) or 0.0),
                record.get("expense_detail"),
                float(record.get("total_real", 0.0) or 0.0),
                diff_val,
                diff_amt_val,
                record.get("diff_status", "KHỚP"),
                1 if record.get("is_warning") else 0,
                record.get("sender_name", ""),
                record.get("approver_name"),
                notes_val,
                shift_key_val
            ))
            closing_id = cur.lastrowid
            cur2 = conn.execute("SELECT * FROM daily_closings WHERE id = ?", (closing_id,))
            row = cur2.fetchone()
            if row:
                res = dict(row)
                res["is_warning"] = bool(res["is_warning"])
                return res
            res = dict(record)
            res["id"] = closing_id
            res["diff"] = diff_val
            res["diff_amount"] = diff_amt_val
            res["notes"] = notes_val
            return res
    finally:
        conn.close()


def get_daily_closings(
    limit: int = 50,
    offset: int = 0,
    report_date: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Queries daily closings ordered by ID descending.
    """
    conn = get_db_connection(db_path)
    _ensure_daily_closings_table(conn)
    try:
        query = "SELECT * FROM daily_closings WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]
        if report_date:
            query += " AND report_date = ?"
            params.append(report_date)
        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur = conn.execute(query, params)
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["is_warning"] = bool(d["is_warning"])
            rows.append(d)
        return rows
    finally:
        conn.close()


def list_daily_closings(
    limit: int = 50,
    offset: int = 0,
    report_date: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Alias for get_daily_closings for API consistency."""
    return get_daily_closings(limit=limit, offset=offset, report_date=report_date, tenant_id=tenant_id, db_path=db_path)


def get_daily_closing_by_id(
    closing_id: int,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_daily_closings_table(conn)
    try:
        cur = conn.execute("SELECT * FROM daily_closings WHERE id = ? AND tenant_id = ?", (closing_id, tenant_id))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_warning"] = bool(d["is_warning"])
        return d
    finally:
        conn.close()


def update_daily_closing(
    closing_id: int,
    updates: Dict[str, Any],
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_daily_closings_table(conn)
    allowed_cols = {
        "bill_pos", "cash_amount", "transfer_amount", "expense_amount",
        "expense_detail", "total_real", "diff", "diff_amount", "diff_status",
        "is_warning", "approver_name", "notes"
    }
    set_clauses = []
    params = []
    for col, val in updates.items():
        if col in allowed_cols:
            set_clauses.append(f"{col} = ?")
            params.append(val)
    if not set_clauses:
        conn.close()
        return get_daily_closing_by_id(closing_id, tenant_id=tenant_id, db_path=db_path)
    params.extend([closing_id, tenant_id])
    query = f"UPDATE daily_closings SET {', '.join(set_clauses)} WHERE id = ? AND tenant_id = ?"
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()
    return get_daily_closing_by_id(closing_id, tenant_id=tenant_id, db_path=db_path)


def migrate_seed_data_from_json(
    db_path: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Đọc data/staff_auth.json (24+ nhân viên thật), data/shift_approvals.json,
    data/roster_schedule.json, data/attendance_logs.json và frontend/data.json
    để đồng bộ vào SQLite wfm.db kèm chuẩn hóa mã employee_id (EMP_001...).
    """
    import json
    init_db(db_path)
    conn = get_db_connection(db_path)
    _ensure_staff_accounts_table(conn)
    _ensure_v2_operational_tables(conn)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM staff_accounts WHERE tenant_id = ?", (DEFAULT_TENANT_ID,))
    staff_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM evaluations WHERE tenant_id = ?", (DEFAULT_TENANT_ID,))
    eval_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM shift_approvals WHERE tenant_id = ?", (DEFAULT_TENANT_ID,))
    approvals_count = cur.fetchone()[0]
    conn.close()

    result = {
        "success": True,
        "migrated_staff": 0,
        "migrated_evals": 0,
        "migrated_locks": 0,
        "migrated_approvals": 0,
        "skipped": False
    }

    # Always ensure shift_approvals.json is synced into SQLite if SQLite table is empty
    approvals_candidates = [
        os.path.join(_PROJECT_DIR, "data", "shift_approvals.json"),
        os.path.join(_BASE_DIR, "data", "shift_approvals.json"),
        os.getenv("APPROVALS_FILE")
    ]
    approvals_file = next((f for f in approvals_candidates if f and os.path.exists(f)), None)
    if approvals_file and (approvals_count == 0 or force):
        try:
            with open(approvals_file, "r", encoding="utf-8") as f:
                appr_data = json.load(f)
            if isinstance(appr_data, dict):
                conn = get_db_connection(db_path)
                _ensure_v2_operational_tables(conn)
                with conn:
                    for sk, aval in appr_data.items():
                        if isinstance(aval, dict):
                            conn.execute("""
                                INSERT INTO shift_approvals (shift_key, tenant_id, status, approved_mins, manager, note, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(shift_key, tenant_id) DO UPDATE SET
                                    status = excluded.status,
                                    approved_mins = excluded.approved_mins,
                                    manager = excluded.manager,
                                    note = excluded.note,
                                    updated_at = excluded.updated_at
                            """, (
                                str(sk),
                                DEFAULT_TENANT_ID,
                                str(aval.get("status", "APPROVE")),
                                int(aval.get("approved_mins", 300) or 300),
                                str(aval.get("manager", "QUẢN LÝ")),
                                str(aval.get("note", "")),
                                str(aval.get("updated_at", ""))
                            ))
                            result["migrated_approvals"] += 1
                conn.close()
        except Exception as e:
            logger.warning(f"Error migrating shift_approvals.json: {e}")

    if not force and staff_count > 0:
        result["skipped"] = True
        result["migrated_staff"] = staff_count
        result["migrated_evals"] = eval_count
        return result

    # 1. Lookup hourly rates from data.json
    rates_map = {}
    data_candidates = [
        os.path.join(os.path.dirname(_BASE_DIR), "frontend", "data.json"),
        os.path.join(_BASE_DIR, "frontend", "data.json"),
        os.path.join(os.path.dirname(_BASE_DIR), "data.json"),
        os.path.join(_BASE_DIR, "data.json"),
        os.getenv("DATA_FILE")
    ]
    data_file = next((f for f in data_candidates if f and os.path.exists(f)), None)
    if data_file:
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                d_json = json.load(f)
            for row in d_json.get("NHÂN VIÊN", [])[2:]:
                if len(row) > 3 and row[1]:
                    name_key = str(row[1]).strip().upper()
                    try:
                        w = int(float(str(row[3]).replace(",", "").replace(".", "").strip()))
                        if w > 0:
                            rates_map[name_key] = w
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error loading data.json in migration: {e}")

    # 2. Migrate staff_auth.json
    auth_candidates = [
        os.path.join(os.path.dirname(_BASE_DIR), "data", "staff_auth.json"),
        os.path.join(_BASE_DIR, "data", "staff_auth.json"),
        os.path.join(_BASE_DIR, "staff_auth.json"),
        os.getenv("AUTH_FILE"),
    ]
    auth_file = next((f for f in auth_candidates if f and os.path.exists(f)), None)

    try:
        from services.storage import hash_pin, needs_rehash
    except ImportError:
        from backend.services.storage import hash_pin, needs_rehash

    if auth_file and (staff_count == 0 or force):
        try:
            with open(auth_file, "r", encoding="utf-8") as f:
                auth_data = json.load(f)
            accounts = auth_data.get("staff_accounts", {})
            conn = get_db_connection(db_path)
            _ensure_staff_accounts_table(conn)
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
                    last_login = acc.get("last_login")
                    created_at = acc.get("created_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    hourly_rate = 17000
                    if full_name.upper() in rates_map:
                        hourly_rate = rates_map[full_name.upper()]
                    elif u_norm.upper() in rates_map:
                        hourly_rate = rates_map[u_norm.upper()]

                    conn.execute("""
                        INSERT INTO staff_accounts (
                            username, employee_id, tenant_id, full_name, display_name, pin_hash,
                            role, position, gender, status, email, phone, hourly_rate, is_active, last_login, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(username) DO UPDATE SET
                            employee_id = CASE WHEN staff_accounts.employee_id IS NULL OR staff_accounts.employee_id = '' THEN excluded.employee_id ELSE staff_accounts.employee_id END,
                            full_name = excluded.full_name,
                            display_name = excluded.display_name,
                            pin_hash = excluded.pin_hash,
                            role = excluded.role,
                            position = excluded.position,
                            gender = excluded.gender,
                            status = excluded.status,
                            hourly_rate = excluded.hourly_rate,
                            is_active = excluded.is_active,
                            last_login = excluded.last_login
                    """, (
                        u_norm, emp_id, DEFAULT_TENANT_ID, full_name, full_name, pin_hash,
                        role, position, gender, status, email, phone, hourly_rate, is_active, last_login, created_at
                    ))
                    result["migrated_staff"] += 1

                    aliases = set(acc.get("aliases", []))
                    aliases.update(acc.get("sheet_names", []))
                    aliases.add(full_name)
                    for al in aliases:
                        if al:
                            conn.execute("""
                                INSERT OR IGNORE INTO staff_aliases (username, alias, tenant_id)
                                VALUES (?, ?, ?)
                            """, (u_norm, str(al).strip(), DEFAULT_TENANT_ID))

                locks = auth_data.get("payroll_locks", {})
                for m_key, lock_val in locks.items():
                    l_status = lock_val.get("status", "OPEN")
                    msg = lock_val.get("message", "")
                    conn.execute("""
                        INSERT INTO payroll_locks (month, tenant_id, status, message)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(month, tenant_id) DO UPDATE SET
                            status = excluded.status,
                            message = excluded.message
                    """, (str(m_key), DEFAULT_TENANT_ID, l_status, msg))
                    result["migrated_locks"] += 1
            conn.close()
        except Exception as e:
            logger.error(f"Error migrating staff_auth.json: {e}")

    # 3. Migrate eval_logs.json
    eval_candidates = [
        os.path.join(os.path.dirname(_BASE_DIR), "data", "eval_logs.json"),
        os.path.join(_BASE_DIR, "data", "eval_logs.json"),
        os.path.join(_BASE_DIR, "eval_logs.json")
    ]
    eval_file = next((f for f in eval_candidates if f and os.path.exists(f)), None)
    if eval_file and (eval_count == 0 or force):
        try:
            with open(eval_file, "r", encoding="utf-8") as f:
                eval_list = json.load(f)
            conn = get_db_connection(db_path)
            _ensure_evaluations_table(conn)
            with conn:
                for ev in eval_list:
                    staff_name = ev.get("staff_name") or ev.get("staffName") or ""
                    ev_type = ev.get("type", "Đánh Giá")
                    amount = int(ev.get("amount", 0))
                    reason = ev.get("reason", "")
                    date = ev.get("date", "")
                    month = str(ev.get("month") or (date.split("-")[1] if "-" in date else "9"))
                    manager = ev.get("manager") or ev.get("by") or "Quản Lý"
                    status = ev.get("status", "ACTIVE")
                    notes = ev.get("notes", "")
                    created_at = ev.get("created_at") or ev.get("timestamp") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute("""
                        INSERT INTO evaluations (
                            tenant_id, staff_name, type, amount, reason, date, month, manager, status, notes, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        DEFAULT_TENANT_ID, staff_name, ev_type, amount, reason, date, month, manager, status, notes, created_at
                    ))
                    result["migrated_evals"] += 1
            conn.close()
        except Exception as e:
            logger.error(f"Error migrating eval_logs.json: {e}")

    return result


def get_store_setting_db(
    key: str,
    default: str = "",
    db_path: Optional[str] = None
) -> str:
    """Fetches a store setting value by key with safe fallback if table does not exist."""
    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT value FROM store_settings WHERE key = ? LIMIT 1", (key.strip(),))
        row = cur.fetchone()
        conn.close()
        if row:
            return str(row["value"])
    except Exception:
        pass
    return default


def get_all_store_settings_db(db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Returns all operational store settings toggles with safe fallback."""
    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("SELECT key, value, label, description, updated_at, updated_by FROM store_settings")
        rows = cur.fetchall()
        conn.close()
        return {r["key"]: dict(r) for r in rows}
    except Exception:
        return {}


def update_store_setting_db(
    key: str,
    value: str,
    updated_by: str = "manager",
    db_path: Optional[str] = None,
    label: str = "",
    description: str = "",
    **kwargs
) -> bool:
    """Updates or inserts a store setting value with auto-table recovery and kwargs resilience."""
    try:
        conn = get_db_connection(db_path)
        with conn:
            conn.execute("""
                INSERT INTO store_settings (key, value, label, description, updated_at, updated_by)
                VALUES (?, ?, COALESCE(?, ''), COALESCE(?, ''), CURRENT_TIMESTAMP, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    label = CASE WHEN excluded.label != '' THEN excluded.label ELSE store_settings.label END,
                    description = CASE WHEN excluded.description != '' THEN excluded.description ELSE store_settings.description END,
                    updated_at = CURRENT_TIMESTAMP,
                    updated_by = excluded.updated_by
            """, (key.strip(), str(value).strip(), label.strip(), description.strip(), updated_by.strip()))
        conn.close()
        return True
    except sqlite3.OperationalError:
        try:
            init_db(db_path)
            conn = get_db_connection(db_path)
            with conn:
                conn.execute("""
                    INSERT INTO store_settings (key, value, label, description, updated_at, updated_by)
                    VALUES (?, ?, COALESCE(?, ''), COALESCE(?, ''), CURRENT_TIMESTAMP, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        label = CASE WHEN excluded.label != '' THEN excluded.label ELSE store_settings.label END,
                        description = CASE WHEN excluded.description != '' THEN excluded.description ELSE store_settings.description END,
                        updated_at = CURRENT_TIMESTAMP,
                        updated_by = excluded.updated_by
                """, (key.strip(), str(value).strip(), label.strip(), description.strip(), updated_by.strip()))
            conn.close()
            return True
        except Exception:
            return False
    except Exception:
        return False


def get_admin_token_version_db(db_path: Optional[str] = None) -> int:
    """Gets current admin_token_version from store_settings (default 1)."""
    val = get_store_setting_db("admin_token_version", default="1", db_path=db_path)
    try:
        return int(val)
    except (ValueError, TypeError):
        return 1


def increment_admin_token_version_db(db_path: Optional[str] = None) -> int:
    """Atomically increments admin_token_version in store_settings and returns new version."""
    curr = get_admin_token_version_db(db_path=db_path)
    nxt = curr + 1
    update_store_setting_db("admin_token_version", str(nxt), updated_by="admin", db_path=db_path)
    return nxt

