# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
POS Cash Closing Router (FnBOps On-Premise)
Handles daily cash/transfer reconciliation against POS365, discrepancy status,
discrepancy threshold alerts (> 50,000 VND), SQLite audit logging and JSON backup.
"""

import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, HTTPException, Query, status, Request

try:
    from backend.services.db import (
        insert_daily_closing,
        get_daily_closings as db_get_daily_closings,
        get_daily_closing_by_id,
        update_daily_closing,
        get_db_path
    )
    from backend.services.storage import safe_json_read, safe_json_write
except ImportError:
    from services.db import (
        insert_daily_closing,
        get_daily_closings as db_get_daily_closings,
        get_daily_closing_by_id,
        update_daily_closing,
        get_db_path
    )
    from services.storage import safe_json_read, safe_json_write

try:
    from backend.services.auth import get_current_user, normalize_str
except ImportError:
    from services.auth import get_current_user, normalize_str

logger = logging.getLogger("pos_closing_router")

router = APIRouter(prefix="/api/v1/cc/pos", tags=["POS Cash Closing"])


def require_pos_auth(
    request: Optional[Request] = None,
    allowed_roles: Optional[List[str]] = None,
    token_param: Optional[str] = None
) -> dict:
    """
    Verifies authentication via Authorization Bearer header OR ?token= query param.
    Enforces role-based access control (RBAC).
    """
    if request is None:
        return {"role": "ADMIN", "sub": "admin", "name": "Admin"}

    token = None
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1].strip()
    elif token_param:
        token = token_param.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực tài khoản. Vui lòng đăng nhập."
        )

    user = get_current_user(token)
    if allowed_roles:
        u_role = str(user.get("role") or "").upper()
        if u_role not in [r.upper() for r in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền thực hiện thao tác này."
            )
    return user


def get_pos_closings_json_path() -> str:
    """Returns absolute path to data/pos_closings.json."""
    if os.getenv("POS_CLOSINGS_FILE"):
        return os.getenv("POS_CLOSINGS_FILE")
    if os.getenv("DATA_DIR"):
        return os.path.join(os.getenv("DATA_DIR"), "pos_closings.json")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(base_dir)
    return os.path.join(root_dir, "data", "pos_closings.json")


def backup_to_json(record: Dict[str, Any]) -> bool:
    """Safely appends or updates a closing record in pos_closings.json only if runtime JSON sync is enabled."""
    try:
        from services.storage import is_runtime_json_sync_enabled
        if not is_runtime_json_sync_enabled() and not os.getenv("POS_CLOSINGS_FILE"):
            return True
    except Exception:
        pass
    json_path = get_pos_closings_json_path()
    try:
        current = safe_json_read(json_path, default=[])
        if not isinstance(current, list):
            current = []
        rec_id = record.get("id")
        updated = False
        if rec_id:
            for i, r in enumerate(current):
                if r.get("id") == rec_id:
                    current[i] = record
                    updated = True
                    break
        if not updated:
            current.append(record)
        return safe_json_write(json_path, current)
    except Exception as e:
        logger.warning(f"Failed to backup closing record to JSON {json_path}: {e}")
        return False


from models.pos_closing import (
    DailyClosingPayload,
    ReconcileClosingPayload,
)


@router.post("/daily-closing", status_code=status.HTTP_200_OK)
def create_daily_closing(payload: DailyClosingPayload, request: Request = None) -> Dict[str, Any]:
    """
    Tiếp nhận dữ liệu chốt ca 1 bước từ nhân viên hoặc đầy đủ từ Admin.
    Yêu cầu đã đăng nhập (bất kỳ role nào: STAFF, MANAGER, ADMIN).
    - Nếu bill_pos > 0: Đối soát ngay lập tức.
    - Nếu bill_pos == 0: Lưu trạng thái CHỜ_ĐỐI_SOÁT (để Admin điền hoặc hệ thống tự kéo POS365 lúc 23h).
    """
    user = require_pos_auth(request)
    u_role = str(user.get("role") or "").upper()

    try:
        closing_time = payload.closing_time or datetime.now().strftime("%H:%M")
        cash = payload.cash_amount or 0.0
        transfer = payload.transfer_amount or 0.0
        expense = payload.expense_amount or 0.0
        bill = payload.bill_pos or 0.0

        total_real = int(round(cash + transfer + expense))
        
        if bill > 0:
            diff = int(round(total_real - bill))
            if diff == 0:
                diff_status = "KHỚP"
                is_warning = False
            elif diff > 0:
                diff_status = "DƯƠNG"
                is_warning = True
            else:
                diff_status = "ÂM"
                is_warning = True
        else:
            diff = 0
            diff_status = "CHỜ_ĐỐI_SOÁT"
            is_warning = False

        # 1.4 Caller Identity Binding (SEC-03: Chống mạo danh người gửi chốt két)
        actual_caller_name = (user.get("name") or user.get("sub") or "Nhân viên").strip()
        if u_role == "STAFF":
            effective_sender = actual_caller_name
        else:
            effective_sender = (payload.sender_name or "").strip() or actual_caller_name

        # 1.5 Duplicate submission safeguard & Chống ghi đè ca đã chốt đã được duyệt
        existing = db_get_daily_closings(limit=50, report_date=payload.report_date)
        req_shift = str(payload.shift_key or "daily").strip()
        for r in existing:
            has_approver = bool(r.get("approver_name") and str(r.get("approver_name")).strip())
            same_shift = (str(r.get("shift_key") or "daily").strip() == req_shift)
            same_time = (r.get("closing_time") == closing_time)
            
            if (same_shift or same_time) and has_approver:
                if u_role != "ADMIN":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Ca chốt ngày {payload.report_date} ({req_shift}) đã được ký duyệt bởi '{r.get('approver_name')}'. Không thể ghi đè ca đã chốt trừ khi có yêu cầu từ Admin."
                    )

            if same_time and r.get("sender_name") == effective_sender:
                return {
                    "status": "success",
                    "message": "Bản ghi chốt ca này đã được lưu trước đó (chống gửi trùng).",
                    "data": r
                }

        # 2. Prepare record payload
        approver = payload.approver_name if u_role in ["ADMIN", "MANAGER"] else None
        record_data = {
            "report_date": payload.report_date,
            "closing_time": closing_time,
            "shift_key": str(payload.shift_key or "daily").strip(),
            "bill_pos": bill,
            "cash_amount": cash,
            "transfer_amount": transfer,
            "expense_amount": expense,
            "expense_detail": payload.expense_detail,
            "total_real": total_real,
            "diff": diff,
            "diff_status": diff_status,
            "is_warning": is_warning,
            "sender_name": effective_sender,
            "approver_name": approver,
        }

        # 3. Persist to SQLite (wfm.db)
        persisted = insert_daily_closing(record_data)

        # 4. Backup to JSON file
        backup_to_json(persisted)

        # 5. Formulate response message & send Telegram alert if discrepancy is warning
        if diff_status == "CHỜ_ĐỐI_SOÁT":
            msg = f"Đã ghi nhận bàn giao két ngày {payload.report_date} thành công. Trạng thái: CHỜ ĐỐI SOÁT (chờ POS365 tự kéo hoặc Admin duyệt)."
        elif diff == 0:
            msg = "Chốt két thành công. Số liệu hoàn toàn KHỚP với POS365."
        elif is_warning:
            msg = f"Cảnh báo lệch két nghiêm trọng: {diff_status} {abs(diff):,.0f}đ (Sai lệch tiền két thực tế)!"
            try:
                from services.send_telegram import send_telegram_alert
                from services.store_config import get_store_config
                s_name = (get_store_config().get("store_name") or "FnBOps").strip()
                tg_msg = (
                    f"🚨 <b>[{s_name}] CẢNH BÁO LỆCH KÉT POS365</b>\n"
                    f"📅 Ngày: <b>{payload.report_date}</b> lúc {closing_time} (Ca: {record_data['shift_key']})\n"
                    f"👤 Người chốt: <b>{payload.sender_name}</b>\n"
                    f"💵 Tiền mặt két: <b>{cash:,.0f}đ</b>\n"
                    f"💳 Chuyển khoản: <b>{transfer:,.0f}đ</b>\n"
                    f"🧾 Chi quầy: <b>{expense:,.0f}đ</b> ({payload.expense_detail or 'Không ghi lý do'})\n"
                    f"📊 Doanh thu POS: <b>{bill:,.0f}đ</b>\n"
                    f"⚠️ Lệch két: <b>{diff_status} {abs(diff):,.0f}đ</b> (Sai lệch két thực tế)"
                )
                send_telegram_alert(tg_msg)
            except Exception as te:
                logger.warning(f"Failed to send Telegram closing alert: {te}")
        else:
            msg = f"Chốt két hoàn tất. Trạng thái: {diff_status}."

        return {
            "status": "success",
            "message": msg,
            "data": persisted
        }
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.exception(f"Error processing daily closing: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Đã xảy ra lỗi khi lưu chốt ca: {str(e)}"
        )


@router.post("/reconcile", status_code=status.HTTP_200_OK)
def reconcile_daily_closing(payload: ReconcileClosingPayload, request: Request = None) -> Dict[str, Any]:
    """
    Endpoint dành cho Admin hoặc Quản lý đối soát:
    Requires ADMIN or MANAGER role.
    - Bổ sung/cập nhật bill_pos và transfer_amount
    - Tự động tính toán lại total_real, diff, diff_status và is_warning
    """
    user = require_pos_auth(request, allowed_roles=["ADMIN", "MANAGER"])
    u_role = str(user.get("role") or "").upper()

    existing = get_daily_closing_by_id(payload.closing_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy bản ghi chốt ca #{payload.closing_id}")

    # Chống ghi đè ca đã chốt nếu ca đó đã có Quản lý hoặc Admin ký duyệt, trừ khi chính Admin yêu cầu
    existing_approver = existing.get("approver_name")
    if existing_approver and str(existing_approver).strip():
        if u_role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Ca chốt #{payload.closing_id} đã được ký duyệt bởi '{existing_approver}'. Chỉ Admin mới có quyền điều chỉnh lại ca đã duyệt."
            )

    bill = payload.bill_pos if payload.bill_pos is not None else float(existing.get("bill_pos", 0.0))
    cash = float(existing.get("cash_amount", 0.0))
    transfer = payload.transfer_amount if payload.transfer_amount is not None else float(existing.get("transfer_amount", 0.0))
    expense = float(existing.get("expense_amount", 0.0))

    total_real = int(round(cash + transfer + expense))
    diff = int(round(total_real - bill))

    if diff == 0:
        diff_status = "KHỚP"
        is_warning = False
    elif diff > 0:
        diff_status = "DƯƠNG"
        is_warning = True
    else:
        diff_status = "ÂM"
        is_warning = True

    updates = {
        "bill_pos": bill,
        "transfer_amount": transfer,
        "total_real": total_real,
        "diff": diff,
        "diff_amount": diff,
        "diff_status": diff_status,
        "is_warning": 1 if is_warning else 0
    }
    if payload.approver_name:
        updates["approver_name"] = payload.approver_name.strip()
    if payload.notes:
        updates["notes"] = payload.notes.strip()

    updated = update_daily_closing(payload.closing_id, updates)
    if updated:
        backup_to_json(updated)

    msg = f"Đã đối soát xong ca #{payload.closing_id}: Lệch {diff_status} {abs(diff):,.0f}đ."
    return {
        "status": "success",
        "message": msg,
        "data": updated
    }



@router.get("/daily-closings", status_code=status.HTTP_200_OK)
def get_daily_closings_history(
    request: Request = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    date: Optional[str] = Query(default=None, description="Lọc theo ngày DD/MM/YYYY"),
    token: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """
    Lấy danh sách lịch sử chốt két các ca gần nhất.
    Yêu cầu đã đăng nhập.
    - ADMIN / MANAGER: Xem toàn bộ lịch sử.
    - STAFF: Chỉ xem các ca do chính mình bàn giao (theo sender_name).
    """
    user = require_pos_auth(request, token_param=token)
    role = str(user.get("role") or "").upper()

    sub = str(user.get("sub") or "")
    name = str(user.get("name") or "")
    sheet_names = [str(s) for s in user.get("sheet_names") or []]
    allowed_names = [sub, name] + sheet_names
    norm_allowed = [normalize_str(n) for n in allowed_names if n]

    try:
        records = db_get_daily_closings(limit=limit, offset=offset, report_date=date)
        if role not in ["ADMIN", "MANAGER"]:
            records = [r for r in records if normalize_str(r.get("sender_name", "")) in norm_allowed]
        return {
            "status": "success",
            "total": len(records),
            "records": records
        }
    except Exception as e:
        logger.warning(f"Error querying daily closings from SQLite: {e}, falling back to JSON backup.")
        json_path = get_pos_closings_json_path()
        backup_data = safe_json_read(json_path, default=[])
        if date:
            backup_data = [r for r in backup_data if r.get("report_date") == date]
        if role not in ["ADMIN", "MANAGER"]:
            backup_data = [r for r in backup_data if normalize_str(r.get("sender_name", "")) in norm_allowed]
        backup_data.reverse()
        sliced = backup_data[offset : offset + limit]
        return {
            "status": "success",
            "total": len(sliced),
            "records": sliced
        }
