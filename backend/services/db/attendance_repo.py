# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Attendance & Shifts Repository Layer
Handles shift approvals, open shifts marketplace, and attendance requests/reviews.
"""

import time
import datetime
import logging
from typing import Optional, Dict, Any, List

from services.db.connection import get_db_connection, DEFAULT_TENANT_ID
from services.db.schema import _ensure_v2_operational_tables

logger = logging.getLogger("db_service")

# ==========================================
# SHIFT APPROVALS REPOSITORY (SQLITE)
# ==========================================

def upsert_shift_approval_db(
    shift_key: str,
    status: str,
    approved_mins: int,
    manager: str = "QUẢN LÝ",
    note: str = "",
    updated_at: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> None:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    ts = updated_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with conn:
            conn.execute("""
                INSERT INTO shift_approvals (shift_key, tenant_id, status, approved_mins, manager, note, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shift_key, tenant_id) DO UPDATE SET
                    status = excluded.status,
                    approved_mins = excluded.approved_mins,
                    manager = excluded.manager,
                    note = excluded.note,
                    updated_at = excluded.updated_at
            """, (shift_key, tenant_id, status, int(approved_mins), manager, note, ts))
    finally:
        conn.close()


def delete_shift_approval_db(
    shift_key: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM shift_approvals WHERE shift_key = ? AND tenant_id = ?",
                (shift_key, tenant_id)
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def list_shift_approvals_db(
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    try:
        cur = conn.execute(
            "SELECT shift_key, status, approved_mins, manager, note, updated_at FROM shift_approvals WHERE tenant_id = ?",
            (tenant_id,)
        )
        res = {}
        for r in cur.fetchall():
            res[r["shift_key"]] = {
                "status": r["status"],
                "approved_mins": r["approved_mins"],
                "manager": r["manager"],
                "note": r["note"],
                "updated_at": r["updated_at"]
            }
        return res
    finally:
        conn.close()


# ==========================================
# OPEN SHIFTS MARKETPLACE REPOSITORY (SQLITE)
# ==========================================

def create_open_shift_db(
    record: Dict[str, Any],
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    shift_id = record.get("id") or f"OPEN_{int(time.time())}_{int(time.time() * 1000) % 10000}"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with conn:
            conn.execute("""
                INSERT INTO open_shifts (
                    id, tenant_id, week_key, date, shift_key, slot_type, role_required,
                    note, status, claimed_by, claimed_by_name, claimed_at, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    claimed_by = excluded.claimed_by,
                    claimed_by_name = excluded.claimed_by_name,
                    claimed_at = excluded.claimed_at,
                    note = excluded.note
            """, (
                shift_id,
                tenant_id,
                str(record.get("week_key") or ""),
                str(record.get("date") or ""),
                str(record.get("shift_key") or "sang"),
                str(record.get("slot_type") or "service"),
                str(record.get("role_required") or "SERVICE"),
                str(record.get("note") or ""),
                str(record.get("status") or "OPEN"),
                str(record.get("claimed_by") or ""),
                str(record.get("claimed_by_name") or ""),
                record.get("claimed_at"),
                str(record.get("created_by") or "MANAGER"),
                record.get("created_at") or now_str
            ))
            cur = conn.execute("SELECT * FROM open_shifts WHERE id = ?", (shift_id,))
            row = cur.fetchone()
            return dict(row) if row else record
    finally:
        conn.close()


def list_open_shifts_db(
    week_key: Optional[str] = None,
    status: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    try:
        query = "SELECT * FROM open_shifts WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]
        if week_key:
            query += " AND week_key = ?"
            params.append(week_key)
        if status:
            query += " AND status = ?"
            params.append(status.upper())
        query += " ORDER BY date ASC, created_at DESC"
        cur = conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def claim_open_shift_db(
    shift_id: str,
    username: str,
    display_name: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with conn:
            cur = conn.execute(
                "SELECT * FROM open_shifts WHERE id = ? AND tenant_id = ?",
                (shift_id, tenant_id)
            )
            row = cur.fetchone()
            if not row or row["status"] != "OPEN":
                return None
            conn.execute("""
                UPDATE open_shifts
                SET status = 'CLAIMED', claimed_by = ?, claimed_by_name = ?, claimed_at = ?
                WHERE id = ? AND tenant_id = ? AND status = 'OPEN'
            """, (username, display_name, now_str, shift_id, tenant_id))
            cur2 = conn.execute("SELECT * FROM open_shifts WHERE id = ?", (shift_id,))
            r2 = cur2.fetchone()
            return dict(r2) if r2 else None
    finally:
        conn.close()


def delete_open_shift_db(
    shift_id: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    try:
        with conn:
            cur = conn.execute("DELETE FROM open_shifts WHERE id = ? AND tenant_id = ?", (shift_id, tenant_id))
            return cur.rowcount > 0
    finally:
        conn.close()


# ==========================================
# ATTENDANCE REQUESTS REPOSITORY (SQLITE)
# ==========================================

def create_attendance_request_db(
    record: Dict[str, Any],
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    req_id = record.get("id") or f"ATTREQ_{int(time.time())}_{int(time.time() * 1000) % 10000}"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with conn:
            conn.execute("""
                INSERT INTO attendance_requests (
                    id, tenant_id, username, employee_id, display_name, date, shift_key,
                    request_type, requested_checkin, requested_checkout, reason,
                    status, reviewed_by, review_note, reviewed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req_id,
                tenant_id,
                str(record.get("username") or "").strip().lower(),
                str(record.get("employee_id") or ""),
                str(record.get("display_name") or ""),
                str(record.get("date") or ""),
                str(record.get("shift_key") or "sang"),
                str(record.get("request_type") or "FORGOT_CHECKOUT"),
                str(record.get("requested_checkin") or ""),
                str(record.get("requested_checkout") or ""),
                str(record.get("reason") or ""),
                str(record.get("status") or "PENDING"),
                str(record.get("reviewed_by") or ""),
                str(record.get("review_note") or ""),
                record.get("reviewed_at"),
                record.get("created_at") or now_str
            ))
            cur = conn.execute("SELECT * FROM attendance_requests WHERE id = ?", (req_id,))
            row = cur.fetchone()
            return dict(row) if row else record
    finally:
        conn.close()


def list_attendance_requests_db(
    username: Optional[str] = None,
    status: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    try:
        query = "SELECT * FROM attendance_requests WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]
        if username:
            query += " AND username = ?"
            params.append(username.strip().lower())
        if status:
            query += " AND status = ?"
            params.append(status.strip().upper())
        query += " ORDER BY created_at DESC"
        cur = conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_attendance_request_by_id_db(
    req_id: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    try:
        cur = conn.execute("SELECT * FROM attendance_requests WHERE id = ? AND tenant_id = ?", (req_id, tenant_id))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def review_attendance_request_db(
    req_id: str,
    status: str,
    reviewed_by: str,
    review_note: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    _ensure_v2_operational_tables(conn)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with conn:
            conn.execute("""
                UPDATE attendance_requests
                SET status = ?, reviewed_by = ?, review_note = ?, reviewed_at = ?
                WHERE id = ? AND tenant_id = ?
            """, (status.strip().upper(), reviewed_by, review_note, now_str, req_id, tenant_id))
            cur = conn.execute("SELECT * FROM attendance_requests WHERE id = ? AND tenant_id = ?", (req_id, tenant_id))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
