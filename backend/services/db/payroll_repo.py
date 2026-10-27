# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Payroll Repository Layer
Handles staff ledgers (bonuses, advances, fines), immutable general ledger (sổ cái lương),
and monthly payroll confirmations/disputes.
"""

import datetime
import logging
from typing import Optional, Dict, Any, List

from services.db.connection import get_db_connection, DEFAULT_TENANT_ID
from services.db.schema import (
    _ensure_staff_ledgers_table,
    _ensure_so_cai_luong_and_attendance_enhancements,
    _ensure_payroll_confirmations_table,
    _ensure_payroll_locks_table,
)

logger = logging.getLogger("db_service")

def _ensure_staff_ledgers_soft_delete_cols(conn) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(staff_ledgers);")
    cols = {r[1] for r in cur.fetchall()}
    if "is_deleted" not in cols:
        conn.execute("ALTER TABLE staff_ledgers ADD COLUMN is_deleted INTEGER DEFAULT 0;")
    if "deleted_at" not in cols:
        conn.execute("ALTER TABLE staff_ledgers ADD COLUMN deleted_at DATETIME;")
    if "deleted_by" not in cols:
        conn.execute("ALTER TABLE staff_ledgers ADD COLUMN deleted_by TEXT DEFAULT '';")


def insert_staff_ledger(
    ledger_dict: Dict[str, Any],
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Insert or update a staff ledger entry (Bonus, Advance, Deduction)."""
    conn = get_db_connection(db_path)
    _ensure_staff_ledgers_table(conn)
    _ensure_staff_ledgers_soft_delete_cols(conn)
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO staff_ledgers (
                id, tenant_id, staff_name, month, type, amount,
                payment_method, reason, created_by, is_deleted, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
        """, (
            ledger_dict["id"],
            tenant_id,
            ledger_dict["staff_name"],
            str(ledger_dict["month"]),
            ledger_dict["type"].lower(),
            int(ledger_dict["amount"]),
            ledger_dict.get("payment_method", "cash").lower(),
            ledger_dict.get("reason", ""),
            ledger_dict.get("created_by", ""),
            ledger_dict.get("created_at")
        ))
    conn.close()
    return ledger_dict


def list_staff_ledgers(
    month: Optional[str] = None,
    staff_name: Optional[str] = None,
    ledger_type: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    include_deleted: bool = False,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List staff ledger entries with optional filtering by month, staff_name, and type."""
    conn = get_db_connection(db_path)
    _ensure_staff_ledgers_table(conn)
    _ensure_staff_ledgers_soft_delete_cols(conn)
    cur = conn.cursor()

    query = "SELECT * FROM staff_ledgers WHERE tenant_id = ?"
    params: List[Any] = [tenant_id]

    if not include_deleted:
        query += " AND (is_deleted = 0 OR is_deleted IS NULL)"

    if month and str(month).lower() != "all":
        query += " AND month = ?"
        params.append(str(month).strip())

    if staff_name:
        query += " AND staff_name = ?"
        params.append(str(staff_name).strip())

    if ledger_type:
        query += " AND type = ?"
        params.append(str(ledger_type).lower().strip())

    query += " ORDER BY created_at DESC, id DESC"
    cur.execute(query, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_staff_ledger_by_id(
    ledger_id: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Retrieve a single staff ledger entry by ID."""
    if not ledger_id:
        return None
    conn = get_db_connection(db_path)
    _ensure_staff_ledgers_table(conn)
    _ensure_staff_ledgers_soft_delete_cols(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM staff_ledgers WHERE id = ? AND tenant_id = ?",
        (ledger_id, tenant_id)
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_staff_ledger(
    ledger_id: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    deleted_by: str = "Admin",
    db_path: Optional[str] = None
) -> bool:
    """
    Soft delete a staff ledger entry by ID.
    Marks is_deleted = 1, sets deleted_at, and records deleted_by to preserve an immutable audit trail.
    Đồng thời tự động ghi bút toán đảo ngược vào sổ cái lương bất biến (so_cai_luong).
    """
    if not ledger_id:
        return False
    ledger = get_staff_ledger_by_id(ledger_id, tenant_id=tenant_id, db_path=db_path)
    conn = get_db_connection(db_path)
    _ensure_staff_ledgers_table(conn)
    _ensure_staff_ledgers_soft_delete_cols(conn)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        cur = conn.execute("""
            UPDATE staff_ledgers 
            SET is_deleted = 1,
                deleted_at = ?,
                deleted_by = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND tenant_id = ?
        """, (now_str, deleted_by or "Admin", ledger_id, tenant_id))
        deleted = cur.rowcount > 0
    conn.close()

    if deleted and ledger:
        try:
            create_reversal_ledger_entry(
                original_entry_id=ledger_id,
                tenant_id=tenant_id,
                staff_name=ledger.get("staff_name", ""),
                nguoi_tao=deleted_by or "Admin",
                ly_do=f"Hủy khoản sổ phụ ({ledger.get('type')}): {ledger.get('reason', '')}".strip(),
                db_path=db_path
            )
        except Exception as e:
            logger.warning(f"Failed to record reversal ledger entry for {ledger_id}: {e}")

    return deleted


def create_reversal_ledger_entry(
    original_entry_id: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    nhan_vien_id: str = "",
    staff_name: str = "",
    loai_su_kien: str = "REVERSAL",
    so_tien_thay_doi: Optional[int] = None,
    so_gio_thay_doi: float = 0.0,
    ly_do: str = "",
    nguoi_tao: str = "Admin",
    muc_luong_ap_dung: int = 17000,
    cham_cong_id: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Tạo bút toán đảo ngược kế toán trong sổ cái lương bất biến (so_cai_luong).
    Hỗ trợ các loại sự kiện đảo ngược: HUY_UNG_LUONG, HUY_THUONG, HUY_PHAT, DIEU_CHINH_GIAM, REVERSAL.
    """
    # Nếu truyền original_entry_id (id của staff_ledger), tự động lookup thông tin gốc nếu chưa đủ
    if original_entry_id and (not staff_name or so_tien_thay_doi is None):
        ledger = get_staff_ledger_by_id(original_entry_id, tenant_id=tenant_id, db_path=db_path)
        if ledger:
            if not staff_name:
                staff_name = ledger.get("staff_name", "")
            orig_amount = int(ledger.get("amount") or 0)
            orig_type = (ledger.get("type") or "").upper()
            if so_tien_thay_doi is None:
                so_tien_thay_doi = -orig_amount
            if loai_su_kien == "REVERSAL":
                if "ADVANCE" in orig_type or "UNG" in orig_type:
                    loai_su_kien = "HUY_UNG_LUONG"
                elif "BONUS" in orig_type or "THUONG" in orig_type:
                    loai_su_kien = "HUY_THUONG"
                elif "DEDUCTION" in orig_type or "PHAT" in orig_type:
                    loai_su_kien = "HUY_PHAT"

    if so_tien_thay_doi is None:
        so_tien_thay_doi = 0

    if not ly_do and original_entry_id:
        ly_do = f"Đảo ngược bút toán sổ phụ ID: {original_entry_id}"
    elif not ly_do:
        ly_do = "Đảo ngược bút toán kế toán"

    return record_so_cai_luong(
        tenant_id=tenant_id,
        nhan_vien_id=nhan_vien_id or staff_name,
        staff_name=staff_name,
        loai_su_kien=loai_su_kien,
        so_gio_thay_doi=so_gio_thay_doi,
        so_tien_thay_doi=so_tien_thay_doi,
        muc_luong_ap_dung=muc_luong_ap_dung,
        ly_do=ly_do,
        nguoi_tao=nguoi_tao,
        cham_cong_id=cham_cong_id or (f"REV_{original_entry_id}" if original_entry_id else None),
        db_path=db_path
    )

def record_so_cai_luong(
    tenant_id: str,
    nhan_vien_id: str,
    staff_name: str,
    loai_su_kien: str,
    so_gio_thay_doi: float = 0.0,
    so_tien_thay_doi: int = 0,
    muc_luong_ap_dung: int = 17000,
    ly_do: str = "",
    nguoi_tao: str = "System",
    cham_cong_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Records an append-only event in the immutable payroll ledger (so_cai_luong).
    Guarantees full financial and audit trail traceability.
    Supports idempotency_key to prevent duplicate transactions.
    """
    conn = get_db_connection(db_path)
    _ensure_so_cai_luong_and_attendance_enhancements(conn)
    cur = conn.cursor()

    clean_idem = str(idempotency_key).strip() if idempotency_key else None
    if clean_idem:
        cur.execute("SELECT id FROM so_cai_luong WHERE idempotency_key = ?", (clean_idem,))
        existing = cur.fetchone()
        if existing:
            conn.close()
            return existing[0]

        cur.execute("""
            INSERT OR IGNORE INTO so_cai_luong (
                tenant_id, nhan_vien_id, staff_name, cham_cong_id, loai_su_kien,
                so_gio_thay_doi, so_tien_thay_doi, muc_luong_ap_dung, ly_do, nguoi_tao, idempotency_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tenant_id or DEFAULT_TENANT_ID,
            nhan_vien_id,
            staff_name,
            cham_cong_id,
            loai_su_kien,
            so_gio_thay_doi,
            so_tien_thay_doi,
            muc_luong_ap_dung,
            ly_do,
            nguoi_tao,
            clean_idem
        ))
    else:
        cur.execute("""
            INSERT INTO so_cai_luong (
                tenant_id, nhan_vien_id, staff_name, cham_cong_id, loai_su_kien,
                so_gio_thay_doi, so_tien_thay_doi, muc_luong_ap_dung, ly_do, nguoi_tao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tenant_id or DEFAULT_TENANT_ID,
            nhan_vien_id,
            staff_name,
            cham_cong_id,
            loai_su_kien,
            so_gio_thay_doi,
            so_tien_thay_doi,
            muc_luong_ap_dung,
            ly_do,
            nguoi_tao
        ))
    conn.commit()
    inserted_id = cur.lastrowid
    conn.close()
    return inserted_id


def list_so_cai_luong(
    staff_name: Optional[str] = None,
    month: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Lists audit ledger events, optionally filtered by staff name and month (YYYY-MM)."""
    conn = get_db_connection(db_path)
    _ensure_so_cai_luong_and_attendance_enhancements(conn)
    cur = conn.cursor()
    query = "SELECT * FROM so_cai_luong WHERE tenant_id = ?"
    params: List[Any] = [tenant_id]

    if staff_name:
        query += " AND staff_name = ?"
        params.append(staff_name)

    if month:
        query += " AND created_at LIKE ?"
        params.append(f"%{month}%")

    query += " ORDER BY id DESC"
    cur.execute(query, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def upsert_payroll_confirmation(
    username: str,
    month: str,
    status: str = "CONFIRMED",
    note: str = "",
    timestamp: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """Upsert a staff payroll confirmation or dispute record."""
    clean_u = str(username).strip().lower()
    clean_m = str(month).strip()
    clean_status = str(status).strip().upper() or "CONFIRMED"
    final_ts = timestamp.strip() or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection(db_path)
    _ensure_payroll_confirmations_table(conn)
    with conn:
        conn.execute("""
            INSERT INTO payroll_confirmations (tenant_id, username, month, status, note, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, username, month) DO UPDATE SET
                status = excluded.status,
                note = excluded.note,
                timestamp = excluded.timestamp
        """, (tenant_id, clean_u, clean_m, clean_status, note.strip(), final_ts))
    conn.close()
    return True


def list_payroll_confirmations(
    month: Optional[str] = None,
    username: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """List staff payroll confirmation and dispute records."""
    conn = get_db_connection(db_path)
    _ensure_payroll_confirmations_table(conn)
    cur = conn.cursor()
    query = "SELECT * FROM payroll_confirmations WHERE tenant_id = ?"
    params: List[Any] = [tenant_id]
    if month is not None:
        query += " AND month = ?"
        params.append(str(month).strip())
    if username is not None:
        query += " AND username = ?"
        params.append(str(username).strip().lower())
    query += " ORDER BY month DESC, timestamp DESC"
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def upsert_payroll_lock_db(
    month: str,
    status: str = "LOCKED",
    message: str = "",
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """Upsert a payroll lock status (OPEN or LOCKED) for a given month."""
    clean_m = str(month).strip()
    clean_status = str(status).strip().upper() or "LOCKED"
    conn = get_db_connection(db_path)
    _ensure_payroll_locks_table(conn)
    with conn:
        conn.execute("""
            INSERT INTO payroll_locks (tenant_id, month, status, message, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(month, tenant_id) DO UPDATE SET
                status = excluded.status,
                message = excluded.message,
                updated_at = CURRENT_TIMESTAMP
        """, (tenant_id, clean_m, clean_status, message.strip()))
    conn.close()
    return True


def is_payroll_locked_db(
    month: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """Check if payroll is locked for a given month."""
    if not month:
        return False
    clean_m = str(month).strip()
    conn = get_db_connection(db_path)
    _ensure_payroll_locks_table(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT status FROM payroll_locks WHERE tenant_id = ? AND month = ? LIMIT 1",
        (tenant_id, clean_m)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    return str(row[0]).strip().upper() == "LOCKED"


def get_payroll_locks_db(
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Retrieve all payroll lock states as a dict keyed by month."""
    conn = get_db_connection(db_path)
    _ensure_payroll_locks_table(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT month, status, message, updated_at FROM payroll_locks WHERE tenant_id = ?",
        (tenant_id,)
    )
    rows = cur.fetchall()
    conn.close()
    locks = {}
    for r in rows:
        locks[str(r[0])] = {
            "status": r[1],
            "locked": (str(r[1]).upper() == "LOCKED"),
            "message": r[2] or "",
            "updated_at": r[3] or ""
        }
    return locks


def upsert_payroll_disbursement_db(
    month: str,
    staff_name: str,
    status: str,
    amount: int = 0,
    paid_by: str = "",
    updated_at: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> bool:
    """Insert or update payroll disbursement status for a staff in a given month."""
    clean_m = str(month).strip()
    clean_name = str(staff_name).strip()
    clean_status = str(status).strip().upper()
    now_str = updated_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection(db_path)
    _ensure_payroll_locks_table(conn)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO payroll_disbursements (tenant_id, month, staff_name, status, amount, paid_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tenant_id, month, staff_name) DO UPDATE SET
            status = excluded.status,
            amount = excluded.amount,
            paid_by = excluded.paid_by,
            updated_at = excluded.updated_at
    """, (tenant_id, clean_m, clean_name, clean_status, int(amount or 0), paid_by or "", now_str))
    conn.commit()
    conn.close()
    return True


def get_payroll_disbursements_db(
    month: Optional[str] = None,
    tenant_id: str = DEFAULT_TENANT_ID,
    db_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retrieve disbursements formatted as {month: {staff_name: {status, amount, paid_by, updated_at}}}.
    If month is specified, returns only for that month.
    """
    conn = get_db_connection(db_path)
    _ensure_payroll_locks_table(conn)
    cur = conn.cursor()
    if month:
        cur.execute(
            "SELECT month, staff_name, status, amount, paid_by, updated_at FROM payroll_disbursements WHERE tenant_id = ? AND month = ?",
            (tenant_id, str(month).strip())
        )
    else:
        cur.execute(
            "SELECT month, staff_name, status, amount, paid_by, updated_at FROM payroll_disbursements WHERE tenant_id = ?",
            (tenant_id,)
        )
    rows = cur.fetchall()
    conn.close()

    result: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        m, name, st, amt, pby, uat = str(r[0]), str(r[1]), r[2], r[3], r[4], r[5]
        month_dict = result.setdefault(m, {})
        month_dict[name] = {
            "status": st,
            "amount": amt,
            "paid_by": pby or "",
            "updated_at": uat or ""
        }
    return result

