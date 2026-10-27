# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Payroll Disbursement, Sổ Phụ, and Sổ Cái Lương Router for FnBOps
Endpoints:
- POST   /admin/toggle-lock
- POST   /staff/confirm-payroll
- GET    /shifts/approvals
- POST   /shifts/confirm-ot
- GET    /payroll/ledger
- POST   /payroll/ledger
- DELETE /payroll/ledger/{ledger_id}
- GET    /payroll/summary
- GET    /payroll-summary
- GET    /payroll/disbursements
- POST   /payroll/disbursements/toggle
- GET    /admin/so-cai-luong
"""

import os
import sys
import time
import json
import random
import logging
import datetime
import threading
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, Request, HTTPException, Query

from models.disbursement import (
    StaffLedgerCreateRequest,
    ToggleLockData,
    ConfirmPayrollData,
    DisbursementToggleRequest,
    ConfirmOTData,
)
from services.auth import (
    get_current_user,
    load_staff_auth,
    save_staff_auth,
    normalize_str,
    SECRET_KEY,
    ALGORITHM,
)
from services.storage import safe_json_read, safe_json_write
from services.payroll_calc import calculate_staff_payslip_breakdown
from services.attendance_service import load_attendance_logs
from routers.evaluation import load_evaluations
from services.db import (
    DEFAULT_TENANT_ID,
    get_store_setting_db,
    check_api_rate_limit,
    list_staff_ledgers,
    insert_staff_ledger,
    delete_staff_ledger,
    get_staff_ledger_by_id,
    list_shift_approvals_db,
    upsert_shift_approval_db,
    delete_shift_approval_db,
    record_so_cai_luong,
    list_so_cai_luong,
    get_db_path,
    upsert_payroll_lock_db,
    upsert_payroll_confirmation,
    upsert_payroll_disbursement_db,
    get_payroll_disbursements_db,
)

logger = logging.getLogger("disbursement_router")
router = APIRouter(prefix="", tags=["cc-disbursement"])

_staff_ledger_dedup_lock = threading.Lock()
_staff_ledger_dedup_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_dir = os.path.dirname(_base_dir)


def _get_active_fn(fn_name: str, fallback_fn):
    for mod_name in ("routers.fnb_ops", "backend.routers.fnb_ops"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, fn_name):
            val = getattr(mod, fn_name)
            if val is not None:
                return val
    return fallback_fn


def _get_root_data_dir() -> str:
    if os.getenv("DATA_DIR"):
        return os.getenv("DATA_DIR")
    if _root_dir and _root_dir != "/" and os.path.exists(os.path.join(_root_dir, "data")):
        return os.path.join(_root_dir, "data")
    return os.path.join(_base_dir, "data")


def get_data_file() -> str:
    env_df = os.getenv("DATA_FILE")
    if env_df and os.path.exists(env_df):
        return env_df
    for p in [os.path.join(_root_dir, "frontend", "data.json"), os.path.join(_base_dir, "data.json"), os.path.join(_get_root_data_dir(), "data.json")]:
        if os.path.exists(p):
            return p
    return os.path.join(_root_dir, "frontend", "data.json")


def get_approvals_file() -> str:
    if os.getenv("APPROVALS_FILE"):
        return os.getenv("APPROVALS_FILE")
    data_dir = _get_root_data_dir()
    p = os.path.join(data_dir, "shift_approvals.json")
    if os.path.exists(p):
        return p
    return os.path.join(_root_dir, "data", "shift_approvals.json")


def load_shift_approvals() -> Dict[str, Any]:
    """Single Source of Truth: Đọc từ SQLite shift_approvals, fallback JSON nếu rỗng."""
    if os.getenv("APPROVALS_FILE"):
        return safe_json_read(get_approvals_file(), default={})
    try:
        db_data = list_shift_approvals_db()
        if db_data:
            return db_data
    except Exception:
        pass
    return safe_json_read(get_approvals_file(), default={})


def save_shift_approvals(data: dict) -> None:
    try:
        for sk, aval in (data or {}).items():
            if isinstance(aval, dict):
                upsert_shift_approval_db(
                    shift_key=str(sk),
                    status=str(aval.get("status", "APPROVE")),
                    approved_mins=int(aval.get("approved_mins", 300) or 300),
                    manager=str(aval.get("manager", "QUẢN LÝ")),
                    note=str(aval.get("note", "")),
                    updated_at=str(aval.get("updated_at", ""))
                )
    except Exception:
        pass

    _real_data_dir = os.path.join(_root_dir, "data")
    appr_env = os.getenv("APPROVALS_FILE")
    if appr_env and not os.path.abspath(appr_env).startswith(_real_data_dir):
        return safe_json_write(appr_env, data)

    try:
        from services.storage import is_runtime_json_sync_enabled
        if is_runtime_json_sync_enabled():
            return safe_json_write(get_approvals_file(), data)
    except Exception:
        pass
    return True


DEFAULT_DISBURSEMENT_FILE = os.path.join(_root_dir, "data", "payroll_disbursements.json")


def get_disbursements_file() -> str:
    if os.getenv("DISBURSEMENTS_FILE"):
        return os.getenv("DISBURSEMENTS_FILE")
    data_dir = _get_root_data_dir()
    p = os.path.join(data_dir, "payroll_disbursements.json")
    if os.path.exists(p):
        return p
    return os.path.join(_root_dir, "data", "payroll_disbursements.json")


def load_disbursements() -> Dict[str, Any]:
    """Single Source of Truth: Đọc từ SQLite payroll_disbursements, fallback JSON."""
    if os.getenv("DISBURSEMENTS_FILE"):
        return safe_json_read(get_disbursements_file(), default={})
    try:
        db_data = get_payroll_disbursements_db()
        if db_data:
            return db_data
    except Exception:
        pass
    fpath = get_disbursements_file()
    return safe_json_read(fpath, default={})


def save_disbursements(data: Dict[str, Any]) -> None:
    """Lưu trữ Single Source of Truth vào SQLite payroll_disbursements và backup JSON."""
    try:
        for month_str, staff_dict in (data or {}).items():
            if isinstance(staff_dict, dict):
                for staff_name, entry in staff_dict.items():
                    if isinstance(entry, dict):
                        upsert_payroll_disbursement_db(
                            month=str(month_str),
                            staff_name=str(staff_name),
                            status=str(entry.get("status", "UNPAID")),
                            amount=int(entry.get("amount", 0) or 0),
                            paid_by=str(entry.get("paid_by", "")),
                            updated_at=str(entry.get("updated_at", ""))
                        )
    except Exception:
        pass
    fpath = get_disbursements_file()
    _real_data_dir = os.path.join(_root_dir, "data")
    disb_env = os.getenv("DISBURSEMENTS_FILE")
    if disb_env and not os.path.abspath(disb_env).startswith(_real_data_dir):
        safe_json_write(disb_env, data)
        return

    try:
        from services.storage import is_runtime_json_sync_enabled
        if is_runtime_json_sync_enabled():
            safe_json_write(fpath, data)
    except Exception:
        pass


def check_payroll_lock_status(month: Optional[str] = None) -> Tuple[bool, str]:
    """
    Checks if a given month's payroll is locked by Admin.
    Returns (is_locked, lock_message).
    """
    if not month:
        return False, ""
    clean_m = str(month).strip()
    try:
        auth = load_staff_auth()
        locks = auth.get("payroll_locks", {})
        lock_info = locks.get(clean_m)
        if lock_info and isinstance(lock_info, dict):
            if str(lock_info.get("status", "")).strip().upper() == "LOCKED":
                msg = lock_info.get("message") or f"Kỳ lương tháng {clean_m} đang khóa đối soát."
                return True, msg
    except Exception as e:
        logger.warning(f"Error checking payroll lock status for month {month}: {e}")
    return False, ""


def enforce_api_rate_limit(request: Request, limit: int = 30, window_seconds: int = 60, key_prefix: str = "api"):
    """
    Enforces per-client rate limit stored atomically in SQLite WAL.
    Raises HTTP 429 Too Many Requests if limit is exceeded.
    """
    client_ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Real-IP") or (request.client.host if request.client else "127.0.0.1")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    
    on_premise = os.getenv("ON_PREMISE_MODE", "false").lower() in ("true", "1")
    is_testing = os.getenv("TESTING") == "1"
    if (on_premise or is_testing) and client_ip:
        if client_ip in ("127.0.0.1", "localhost", "::1", "testclient"):
            limit = max(limit, 500)
        else:
            try:
                import ipaddress
                ip_obj = ipaddress.ip_address(client_ip)
                is_lan = ip_obj.is_loopback or any(ip_obj in net for net in (
                    ipaddress.ip_network('10.0.0.0/8'),
                    ipaddress.ip_network('172.16.0.0/12'),
                    ipaddress.ip_network('192.168.0.0/16'),
                    ipaddress.ip_network('100.64.0.0/10')
                ))
                if is_lan:
                    limit = max(limit, 300)
            except ValueError:
                pass

    user_id = client_ip
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            import jwt
            t = auth_header.split(" ")[1].strip()
            p = jwt.decode(t, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_signature": False, "verify_exp": False})
            if p.get("sub"):
                user_id = f"{client_ip}:{p.get('sub')}"
        except Exception:
            pass

    key = f"{key_prefix}:{user_id}"
    is_allowed, count, retry_after = check_api_rate_limit(key, limit=limit, window_seconds=window_seconds)
    if not is_allowed:
        logger.warning(f"Rate limit exceeded: key={key}, count={count}, limit={limit}")
        raise HTTPException(
            status_code=429,
            detail=f"Thao tác quá nhanh. Vui lòng chờ {int(retry_after)} giây trước khi thử lại.",
            headers={"Retry-After": str(int(retry_after))}
        )


@router.post("/admin/toggle-lock")
def toggle_lock(request: Request, data: ToggleLockData):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Admin mới có quyền khóa/mở kỳ lương")

    auth = load_staff_auth()
    locks = auth.setdefault("payroll_locks", {})
    accounts = auth.get("staff_accounts", {})
    m = str(data.month).strip()
    status = data.status.strip().upper()
    if status not in ["OPEN", "LOCKED"]:
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ (OPEN hoặc LOCKED)")

    # Thu thập danh sách nhân sự đang có khiếu nại công chưa xử lý trong tháng
    disputed_staff = []
    for u, acc in accounts.items():
        c = acc.get("confirmations", {}).get(m, {})
        if isinstance(c, dict) and c.get("status") == "DISPUTED":
            disputed_staff.append(acc.get("full_name") or u)

    locks[m] = {
        "status": status,
        "message": data.message.strip(),
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "disputed_staff": disputed_staff,
        "dispute_count": len(disputed_staff)
    }
    save_staff_auth(auth)
    try:
        upsert_payroll_lock_db(m, status, data.message.strip())
    except Exception as le:
        logger.warning(f"Failed to upsert payroll lock in SQLite: {le}")
    return {
        "success": True,
        "payroll_locks": locks,
        "disputed_staff": disputed_staff,
        "warning": f"Lưu ý: Có {len(disputed_staff)} nhân sự đang báo sai lệch công chưa giải quyết: {', '.join(disputed_staff)}" if (status == "LOCKED" and disputed_staff) else None
    }


@router.post("/staff/confirm-payroll")
def confirm_payroll(request: Request, data: ConfirmPayrollData):
    enforce_api_rate_limit(request, limit=20, window_seconds=60, key_prefix="confirm")
    if get_store_setting_db("payroll_verification_open", "1") == "0":
        raise HTTPException(
            status_code=403,
            detail="Kỳ đối soát & xác nhận lương hiện đang tạm thời đóng theo chỉ thị Quản lý."
        )
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["STAFF", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ nhân sự / quản lý ca mới được xác nhận công")

    uname = user.get("sub")
    auth = load_staff_auth()
    accounts = auth.get("staff_accounts", {})
    if uname not in accounts:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ nhân viên")

    m = str(data.month).strip()
    st = data.status.strip().upper()
    if st not in ["CONFIRMED", "DISPUTED"]:
        raise HTTPException(status_code=400, detail="Trạng thái xác nhận không hợp lệ (CONFIRMED hoặc DISPUTED)")

    conf = accounts[uname].setdefault("confirmations", {})
    conf[m] = {
        "status": st,
        "note": data.note.strip(),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    save_staff_auth(auth)
    try:
        upsert_payroll_confirmation(uname, m, st, data.note.strip())
    except Exception as ce:
        logger.warning(f"Failed to upsert payroll confirmation in SQLite: {ce}")

    # Nếu nhân viên báo sai lệch công (DISPUTED) -> Bắn Telegram cảnh báo ngay lập tức
    if st == "DISPUTED":
        try:
            if os.getenv("TESTING") != "1" and os.getenv("MOCK_TELEGRAM") != "1":
                tele_token = os.getenv("TEST_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
                chat_id = os.getenv("TELEGRAM_CHAT_ID")
                if tele_token and chat_id:
                    staff_full = accounts[uname].get("full_name") or uname
                    tele_msg = f"⚠️ [KHIẾU NẠI CÔNG] Nhân viên {staff_full} ({uname}) vừa báo sai lệch công Tháng {m}!\n📝 Ghi chú: \"{data.note.strip()}\""
                    tele_url = f"https://api.telegram.org/bot{tele_token}/sendMessage?chat_id={chat_id}&text={urllib.parse.quote(tele_msg)}"
                    urllib.request.urlopen(tele_url, timeout=3)
        except Exception as ex:
            logger.warning(f"Failed to send Telegram alert for dispute from {uname}: {ex}")

    return {"success": True, "confirmation": conf[m]}


@router.get("/shifts/approvals")
def get_shift_approvals(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    get_current_user(auth_header.split(" ")[1])
    return load_shift_approvals()


@router.post("/shifts/confirm-ot")
def confirm_ot(request: Request, data: ConfirmOTData):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    role = (user.get("role") or "").upper()
    if role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Admin / Quản lý mới có quyền duyệt ca")

    shift_key = data.shift_key.strip()
    if not shift_key:
        raise HTTPException(status_code=400, detail="Thiếu mã định danh ca (shift_key)")

    # Anti-Conflict of Interest: Manager cannot approve their own OT
    if role == "MANAGER":
        caller_uname = normalize_str(user.get("sub", ""))
        caller_name = normalize_str(user.get("name", ""))
        shift_parts = [normalize_str(p) for p in shift_key.split("|")]
        if caller_uname in shift_parts or (caller_name and caller_name in shift_parts):
            raise HTTPException(
                status_code=403,
                detail="Xung đột lợi ích: Quản lý không thể tự duyệt tăng ca (OT) cho chính mình. Thao tác này cần Admin phê duyệt."
            )

    # Payroll Lock Enforcement
    shift_parts_raw = shift_key.split("|")
    shift_date = shift_parts_raw[0] if len(shift_parts_raw) > 0 else ""
    shift_month = ""
    try:
        if "/" in shift_date:
            parts = shift_date.split("/")
            if len(parts) >= 2:
                shift_month = str(int(parts[1]))
        elif "-" in shift_date:
            parts = shift_date.split("-")
            if len(parts) >= 2:
                shift_month = str(int(parts[1]))
    except Exception:
        pass

    if shift_month:
        is_locked, lock_msg = check_payroll_lock_status(shift_month)
        if is_locked:
            raise HTTPException(
                status_code=423,
                detail=f"Kỳ lương tháng {shift_month} đã bị Admin KHÓA SỔ đối soát ({lock_msg}). Không thể duyệt hoặc chỉnh sửa ca."
            )

    act = data.action.strip().upper()
    if act not in ["APPROVE", "CUT", "RESET"]:
        raise HTTPException(status_code=400, detail="Hành động không hợp lệ (APPROVE, CUT hoặc RESET)")

    # Safeguard: Shifts exceeding 12 hours (720 mins) indicate forgotten checkout / abnormal shift.
    # Only ADMIN can approve full hours. Managers must cut to standard shift or edit checkout time.
    if act == "APPROVE" and (data.approved_mins or 0) > 720:
        if role != "ADMIN":
            raise HTTPException(
                status_code=403,
                detail=f"Cảnh báo quỹ lương: Ca làm việc {data.approved_mins} phút (>12 tiếng) có dấu hiệu quên check-out qua đêm. Chỉ Admin (Chủ Quán) mới có quyền duyệt đủ, Quản lý vui lòng chọn 'Cắt ca' về ca chuẩn."
            )

    approvals = load_shift_approvals()
    if act == "RESET":
        if shift_key in approvals:
            approvals.pop(shift_key)
        try:
            delete_shift_approval_db(shift_key)
        except Exception:
            pass
        msg = f"Đã đặt lại ca {shift_key} về trạng thái chờ duyệt"
    else:
        approvals[shift_key] = {
            "status": act,
            "approved_mins": data.approved_mins,
            "manager": user.get("name", user.get("sub", "QUẢN LÝ")),
            "note": data.manager_note.strip(),
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        msg = f"Đã duyệt đủ {data.approved_mins} phút" if act == "APPROVE" else f"Đã cắt ca về {data.approved_mins} phút"

    save_shift_approvals(approvals)
    return {
        "success": True,
        "message": msg,
        "shift_key": shift_key,
        "approval": approvals.get(shift_key)
    }


@router.get("/payroll/ledger")
def get_staff_ledger_entries(request: Request, month: Optional[str] = None, staff_name: Optional[str] = None):
    """
    Get staff ledger records (Sổ Phụ: Bonus, Advance, Deduction) from SQLite WAL.
    STAFF role can only read their own records.
    MANAGER / ADMIN can read all records or filter by staff_name.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = user.get("role")

    target_month = month or str(datetime.datetime.now().month)

    _list_fn = _get_active_fn("list_staff_ledgers", list_staff_ledgers)
    if role == "STAFF":
        target_name = user.get("name") or user.get("sub")
        items = _list_fn(month=target_month, staff_name=target_name)
    else:
        items = _list_fn(month=target_month, staff_name=staff_name)

    total_bonus = sum(int(x.get("amount") or 0) for x in items if "bonus" in str(x.get("type", "")).lower() or "thuong" in str(x.get("type", "")).lower())
    total_advance = sum(int(x.get("amount") or 0) for x in items if "advance" in str(x.get("type", "")).lower() or "ung" in str(x.get("type", "")).lower())
    total_deduction = sum(int(x.get("amount") or 0) for x in items if "deduction" in str(x.get("type", "")).lower() or "phat" in str(x.get("type", "")).lower() or "tru" in str(x.get("type", "")).lower())

    return {
        "success": True,
        "month": target_month,
        "role": role,
        "count": len(items),
        "ledgers": items,
        "summary": {
            "total_bonus": total_bonus,
            "total_advance": total_advance,
            "total_deduction": total_deduction
        }
    }


@router.post("/payroll/ledger")
def create_staff_ledger_entry(request: Request, payload: StaffLedgerCreateRequest):
    """
    Create a staff ledger record (Sổ Phụ: Bonus, Advance, Deduction) in SQLite WAL.
    Restricted to MANAGER / ADMIN roles.
    """
    enforce_api_rate_limit(request, limit=30, window_seconds=60, key_prefix="ledger")
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = user.get("role")
    if role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền ghi Sổ Phụ.")

    if not payload.staff_name or not payload.staff_name.strip():
        raise HTTPException(status_code=400, detail="Vui lòng chọn nhân viên cần ghi Sổ Phụ.")

    clean_type = payload.type.strip().lower()
    if clean_type not in ["bonus", "advance", "deduction"]:
        raise HTTPException(status_code=400, detail="Loại sổ phụ không hợp lệ (Phải là 'bonus', 'advance', hoặc 'deduction').")

    if payload.amount <= 0 or payload.amount > 50000000:
        raise HTTPException(status_code=400, detail="Số tiền không hợp lệ (Phải từ 1đ đến 50,000,000đ).")

    clean_method = payload.payment_method.strip().lower()
    if clean_method not in ["cash", "bank"]:
        clean_method = "cash"

    cur_month = str(payload.month or datetime.datetime.now().month).strip()

    # Payroll Lock Enforcement
    is_locked, lock_msg = check_payroll_lock_status(cur_month)
    if is_locked:
        raise HTTPException(
            status_code=423,
            detail=f"Kỳ lương tháng {cur_month} đã bị Admin KHÓA SỔ đối soát ({lock_msg}). Không thể ghi thêm Sổ Phụ."
        )

    staff_name_clean = payload.staff_name.strip()
    creator_name = (user.get("name") or user.get("sub") or "").strip()
    amount_int = int(payload.amount)

    # Anti-Conflict of Interest: Manager cannot grant bonus or advance to themselves
    if role == "MANAGER":
        caller_uname = normalize_str(user.get("sub", ""))
        caller_name = normalize_str(user.get("name", ""))
        target_clean = normalize_str(staff_name_clean)
        if clean_type in ["bonus", "advance"] and (target_clean == caller_uname or target_clean == caller_name):
            raise HTTPException(
                status_code=403,
                detail="Xung đột lợi ích: Quản lý không thể tự ghi nhận tiền Thưởng (Bonus) hoặc Tạm ứng (Advance) cho chính mình. Thao tác này bắt buộc do Chủ quán (Admin) thực hiện."
            )

    # Idempotency / Dedup:
    # Nếu cùng staff_name, cùng type, cùng amount, cùng month, cùng created_by được gửi liên tiếp trong vòng 5 giây
    # -> Phát hiện gửi trùng và trả về ngay bản ghi vừa tạo, không tạo bản ghi mới trùng lặp.
    dedup_key = f"{staff_name_clean.lower()}:{clean_type}:{amount_int}:{cur_month}:{creator_name.lower()}"

    with _staff_ledger_dedup_lock:
        now_ts = time.time()
        # Clean up entries older than 30s
        expired_keys = [k for k, (t_val, _) in _staff_ledger_dedup_cache.items() if now_ts - t_val > 30.0]
        for k in expired_keys:
            _staff_ledger_dedup_cache.pop(k, None)

        # 1. Check in-memory dedup cache
        if dedup_key in _staff_ledger_dedup_cache:
            last_ts, last_entry = _staff_ledger_dedup_cache[dedup_key]
            if now_ts - last_ts < 5.0:
                logger.info(
                    f"Idempotent dedup triggered for '{dedup_key}' ({now_ts - last_ts:.2f}s ago). "
                    f"Returning existing ledger entry '{last_entry.get('id')}' without duplicate insert."
                )
                return {
                    "success": True,
                    "message": f"Đã ghi nhận {clean_type} {payload.amount:,}đ cho {payload.staff_name}.",
                    "entry": last_entry,
                    "dedup": True
                }

        # 2. Check SQLite staff_ledgers directly (cross-worker / process resilience)
        try:
            from services.db import get_db_connection, get_db_path
            db_target = os.getenv("SQLITE_DB_PATH") or os.getenv("DATABASE_PATH") or get_db_path()
            if db_target and os.path.exists(db_target):
                conn = get_db_connection(db_target)
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT id, tenant_id, staff_name, month, type, amount, payment_method, reason, created_by, created_at
                        FROM staff_ledgers
                        WHERE staff_name = ? AND type = ? AND amount = ? AND month = ? AND (created_by = ? OR created_by = ?)
                        ORDER BY id DESC LIMIT 1
                    """, (staff_name_clean, clean_type, amount_int, cur_month, creator_name, user.get("sub") or ""))
                    row = cur.fetchone()
                    if row:
                        c_at = row["created_at"]
                        if c_at:
                            try:
                                dt_created = datetime.datetime.fromisoformat(str(c_at).replace("Z", "+00:00"))
                                if (datetime.datetime.now(dt_created.tzinfo) - dt_created).total_seconds() < 5.0:
                                    db_entry = dict(row)
                                    _staff_ledger_dedup_cache[dedup_key] = (now_ts, db_entry)
                                    logger.info(f"SQLite dedup triggered for '{dedup_key}'. Returning existing ledger '{db_entry.get('id')}'.")
                                    return {
                                        "success": True,
                                        "message": f"Đã ghi nhận {clean_type} {payload.amount:,}đ cho {payload.staff_name}.",
                                        "entry": db_entry,
                                        "dedup": True
                                    }
                            except Exception:
                                pass
                finally:
                    conn.close()
        except Exception:
            pass

        ledger_id = f"LEDGER_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        entry = {
            "id": ledger_id,
            "tenant_id": DEFAULT_TENANT_ID,
            "staff_name": staff_name_clean,
            "month": cur_month,
            "type": clean_type,
            "amount": amount_int,
            "payment_method": clean_method,
            "reason": (payload.reason or "").strip(),
            "created_by": creator_name,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        saved = insert_staff_ledger(entry)

        # Sync to immutable audit ledger so_cai_luong
        try:
            from services.db import record_so_cai_luong, get_db_path
            evt_map = {"advance": "UNG_LUONG", "bonus": "THUONG", "deduction": "PHAT"}
            evt_type = evt_map.get(clean_type, "UNG_LUONG")
            db_target = os.getenv("SQLITE_DB_PATH") or os.getenv("DATABASE_PATH") or get_db_path()
            record_so_cai_luong(
                tenant_id=DEFAULT_TENANT_ID,
                nhan_vien_id=staff_name_clean,
                staff_name=staff_name_clean,
                loai_su_kien=evt_type,
                so_tien_thay_doi=amount_int,
                ly_do=payload.reason or f"Quản lý ghi {clean_type}",
                nguoi_tao=creator_name or "Manager",
                db_path=db_target
            )
        except Exception as se:
            logger.warning(f"Failed to record so_cai_luong for ledger: {se}")

        _staff_ledger_dedup_cache[dedup_key] = (now_ts, saved)

        return {
            "success": True,
            "message": f"Đã ghi nhận {clean_type} {payload.amount:,}đ cho {payload.staff_name}.",
            "entry": saved
        }


@router.delete("/payroll/ledger/{ledger_id}")
def delete_staff_ledger_entry(request: Request, ledger_id: str):
    """
    Delete a staff ledger entry by ID from SQLite WAL.
    Restricted to MANAGER / ADMIN roles.
    """
    enforce_api_rate_limit(request, limit=30, window_seconds=60, key_prefix="ledger")
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = (user.get("role") or "").upper()
    if role != "ADMIN":
        raise HTTPException(
            status_code=403, 
            detail="Chức năng xóa khoản Sổ Phụ chỉ dành riêng cho Quản trị viên (Admin) để đảm bảo an toàn tài chính."
        )

    entry = get_staff_ledger_by_id(ledger_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy khoản sổ phụ '{ledger_id}' để xóa.")

    e_month = str(entry.get("month") or "").strip()
    is_locked, lock_msg = check_payroll_lock_status(e_month)
    if is_locked:
        raise HTTPException(
            status_code=423,
            detail=f"Kỳ lương tháng {e_month} đã bị Admin KHÓA SỔ đối soát ({lock_msg}). Không thể xóa khoản Sổ Phụ này."
        )

    deleted = delete_staff_ledger(ledger_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy khoản sổ phụ '{ledger_id}' để xóa.")

    return {
        "success": True,
        "message": f"Đã xóa thành công khoản sổ phụ {ledger_id}."
    }


@router.get("/payroll/summary")
def get_payroll_summary(request: Request, month: Optional[str] = None, staff_name: Optional[str] = None):
    """
    Server-side authoritative payroll summary:
    Tamper-proof calculation of base wage, hours, progressive late penalties, bonuses, and net pay.
    Integrates dynamic accounts, static sheets, shift approvals, realtime attendance logs, and SQLite staff ledgers.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = user.get("role")
    uname = user.get("sub")

    cur_month = month or str(datetime.datetime.now().month)

    data_file = get_data_file()
    data = safe_json_read(data_file, default={})
    approvals = load_shift_approvals()
    evals = _get_active_fn("load_evaluations", load_evaluations)()
    attendance_logs = load_attendance_logs()
    _list_fn = _get_active_fn("list_staff_ledgers", list_staff_ledgers)
    staff_ledgers = _list_fn(month=cur_month)

    auth = _get_active_fn("load_staff_auth", load_staff_auth)()
    accounts = auth.get("staff_accounts", {})

    # 1. STAFF: strictly locked to their own payslip
    if role == "STAFF":
        target = user.get("name") or uname
        breakdown = calculate_staff_payslip_breakdown(
            target, cur_month, data, approvals, evals, attendance_logs, staff_ledgers,
            staff_accounts=accounts
        )
        return {
            "success": True,
            "role": "STAFF",
            "breakdown": breakdown
        }

    # 2. MANAGER / ADMIN: Single staff breakdown or all active staff summaries
    if staff_name:
        breakdown = calculate_staff_payslip_breakdown(
            staff_name, cur_month, data, approvals, evals, attendance_logs, staff_ledgers,
            staff_accounts=accounts
        )
        return {
            "success": True,
            "role": role,
            "breakdown": breakdown
        }

    summaries = []
    for u_key, acc in accounts.items():
        if acc.get("status") == "INACTIVE":
            continue
        s_name = acc.get("full_name") or u_key
        sb = calculate_staff_payslip_breakdown(
            s_name, cur_month, data, approvals, evals, attendance_logs, staff_ledgers,
            staff_accounts=accounts
        )
        summaries.append(sb)

    return {
        "success": True,
        "role": role,
        "month": cur_month,
        "count": len(summaries),
        "summaries": summaries
    }


@router.get("/payroll-summary")
def get_payroll_summary_alias(request: Request, month: Optional[str] = None, staff_name: Optional[str] = None, staff: Optional[str] = None):
    """
    Alias route for /payroll/summary to maintain 100% backwards compatibility with frontend API clients.
    """
    return get_payroll_summary(request, month=month, staff_name=staff_name or staff)


@router.get("/payroll/disbursements")
def get_payroll_disbursements(request: Request):
    """
    Lấy toàn bộ trạng thái giải ngân / chuyển khoản lương của các kỳ.
    Yêu cầu quyền Admin hoặc Quản lý.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = user.get("role")
    if role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Admin hoặc Quản lý mới có quyền xem trạng thái giải ngân.")
    return load_disbursements()


@router.post("/payroll/disbursements/toggle")
def toggle_payroll_disbursement(request: Request, payload: DisbursementToggleRequest):
    """
    Cập nhật trạng thái giải ngân (ĐÃ CK / CHƯA CK) cho một nhân sự trong kỳ lương.
    Lưu trữ đồng bộ vào payroll_disbursements.json và trả về thông tin entry vừa cập nhật.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = user.get("role")
    if role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Admin hoặc Quản lý mới có quyền cập nhật trạng thái giải ngân.")

    month_str = str(payload.month).strip()
    staff_name = str(payload.staff_name).strip()
    new_status = str(payload.status).strip().upper()
    if new_status not in ["PAID", "UNPAID"]:
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ (PAID hoặc UNPAID).")

    all_disbs = load_disbursements()
    month_disbs = all_disbs.setdefault(month_str, {})

    paid_by = user.get("name") or user.get("sub") or "Admin"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = {
        "status": new_status,
        "amount": int(payload.amount or 0),
        "paid_by": paid_by,
        "updated_at": now_str
    }
    month_disbs[staff_name] = entry
    save_disbursements(all_disbs)

    msg = f"Đã đánh dấu ĐÃ CHUYỂN KHOẢN cho {staff_name}" if new_status == "PAID" else f"Đã chuyển về CHƯA CK cho {staff_name}"
    return {
        "status": "ok",
        "message": msg,
        "entry": entry
    }


@router.get("/admin/so-cai-luong")
def get_so_cai_luong_events(
    request: Request,
    staff_name: Optional[str] = Query(None),
    month: Optional[str] = Query(None)
):
    """
    Truy vấn sổ cái sự kiện bất biến (so_cai_luong): Thưởng, phạt, ứng lương, điều chỉnh giờ.
    Dành cho ADMIN, MANAGER hoặc STAFF xem bản ghi của chính mình.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = user.get("role")
    u_sub = user.get("sub", "")
    u_name = user.get("name", "")

    if role not in ["ADMIN", "MANAGER"]:
        if not staff_name or (staff_name != u_sub and staff_name != u_name):
            raise HTTPException(status_code=403, detail="Nhân viên chỉ có quyền xem sổ cái của chính mình.")

    try:
        active_db = os.getenv("SQLITE_DB_PATH") or get_db_path()
        events = list_so_cai_luong(staff_name=staff_name, month=month, db_path=active_db)
        return {
            "success": True,
            "count": len(events),
            "total": len(events),
            "events": events
        }
    except Exception as e:
        logger.exception(f"Lỗi khi tải sổ cái: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi tải sổ cái: {e}")
