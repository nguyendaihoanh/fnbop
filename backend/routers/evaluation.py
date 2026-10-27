# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Staff Evaluation & Recognition Router for FnBOps
Endpoints:
- POST /admin/staff-evaluation
- POST /admin/eval-webhook
- POST /admin/staff-evaluation/review
- GET  /admin/staff-evaluations
"""

import os
import sys
import time
import json
import random
import logging
import datetime
from typing import Optional, Dict, Any, List, Tuple
from fastapi import APIRouter, Request, HTTPException

if __name__ in ("backend.routers.evaluation", "routers.evaluation"):
    sys.modules["backend.routers.evaluation"] = sys.modules[__name__]
    sys.modules["routers.evaluation"] = sys.modules[__name__]

from models.evaluation import (
    StaffEvaluationRequest,
    ApproveEvaluationRequest,
)
from services.auth import (
    get_current_user,
    load_staff_auth,
    normalize_str,
)
from services.storage import safe_json_read, safe_json_write
from services.send_telegram import send_telegram_alert

logger = logging.getLogger("evaluation_router")
router = APIRouter(prefix="", tags=["Staff Evaluations"])
_root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_evaluations_file() -> str:
    if os.getenv("EVAL_LOGS_FILE"):
        return os.getenv("EVAL_LOGS_FILE")
    data_dir = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"))
    return os.path.join(data_dir, "eval_logs.json")


def load_evaluations() -> List[Dict[str, Any]]:
    if os.getenv("EVAL_LOGS_FILE"):
        return safe_json_read(os.getenv("EVAL_LOGS_FILE"), default=[])
    try:
        from services.db import list_evaluations
        return list_evaluations()
    except Exception as e:
        logger.warning(f"Error loading evaluations from SQLite: {e}")
    fpath = get_evaluations_file()
    return safe_json_read(fpath, default=[])


def save_evaluations(evals: List[Dict[str, Any]]) -> None:
    try:
        from services.db import insert_evaluation, clear_evaluations_db
        if not evals:
            clear_evaluations_db()
        else:
            for ev in evals:
                insert_evaluation(ev)
    except Exception as e:
        logger.warning(f"Error persisting evaluation to SQLite: {e}")

    # Test isolation override (only active in TESTING=1 when strict no-json guard is not enforced)
    _real_data_dir = os.path.join(_root_dir, "data")
    eval_env = os.getenv("EVALUATIONS_FILE") or os.getenv("EVAL_LOGS_FILE")
    if (
        os.getenv("TESTING") == "1"
        and os.getenv("ENABLE_RUNTIME_JSON_SYNC") != "false"
        and eval_env
        and not os.path.abspath(eval_env).startswith(_real_data_dir)
    ):
        safe_json_write(eval_env, evals)
        return

    # Decoupled runtime JSON: Tuyệt đối CẤM GHI file trong data/ trừ khi bật cờ rõ ràng ENABLE_RUNTIME_JSON_SYNC=true
    try:
        from services.storage import is_runtime_json_sync_enabled
        if is_runtime_json_sync_enabled():
            fpath = get_evaluations_file()
            safe_json_write(fpath, evals)
    except Exception:
        pass


def check_payroll_lock_status(month: Optional[str] = None) -> Tuple[bool, str]:
    if not month:
        return False, ""
    clean_m = str(month).strip()
    try:
        from services.db import is_payroll_locked_db
        if is_payroll_locked_db(clean_m):
            return True, f"Kỳ lương tháng {clean_m} đã bị khóa đối soát"
    except Exception:
        pass
    try:
        auth = load_staff_auth()
        locks = auth.get("payroll_locks", {})
        lock_info = locks.get(clean_m)
        if lock_info and isinstance(lock_info, dict):
            if str(lock_info.get("status", "")).strip().upper() == "LOCKED" or lock_info.get("locked") is True:
                msg = lock_info.get("message") or f"Kỳ lương tháng {clean_m} đang khóa đối soát."
                return True, msg
    except Exception as e:
        logger.warning(f"Error checking payroll lock status: {e}")
    return False, ""


def enforce_api_rate_limit(request: Request, limit: int = 30, window_seconds: int = 60, key_prefix: str = "eval"):
    try:
        from services.db import check_api_rate_limit
        client_ip = request.client.host if request.client else "127.0.0.1"
        key = f"{key_prefix}_{client_ip}"
        allowed, remaining, reset = check_api_rate_limit(key, limit, window_seconds)
        if not allowed:
            raise HTTPException(status_code=429, detail="Bạn thao tác quá nhanh. Vui lòng chờ giây lát.")
    except HTTPException:
        raise
    except Exception:
        pass


@router.post("/admin/staff-evaluation")
def record_staff_evaluation(request: Request, payload: StaffEvaluationRequest):
    enforce_api_rate_limit(request, limit=30, window_seconds=60, key_prefix="eval")
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = user.get("role")
    if role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền đánh giá / thưởng phạt nhân viên.")

    # Server-Side Input Validation (Zero-Trust)
    if any("\x00" in (s or "") for s in [payload.staff_name, payload.reason, payload.notes, payload.type]):
        raise HTTPException(
            status_code=422,
            detail="Dữ liệu chứa ký tự null (\\x00) không hợp lệ."
        )
    if len(payload.reason or "") > 5000:
        raise HTTPException(
            status_code=422,
            detail="Lý do đánh giá vượt quá độ dài cho phép (tối đa 5000 ký tự)."
        )
    if payload.amount < 0 or payload.amount > 5000000:
        raise HTTPException(
            status_code=400, 
            detail="Số tiền thưởng/phạt không hợp lệ (Phải từ 0đ đến tối đa 5,000,000đ/lần)."
        )
    if not payload.reason or len(payload.reason.strip()) < 3:
        raise HTTPException(
            status_code=400, 
            detail="Vui lòng nêu rõ lý do đánh giá / thưởng phạt (tối thiểu 3 ký tự)."
        )

    evals = load_evaluations()
    eval_id = f"EVAL_{int(time.time())}_{random.randint(1000, 9999)}"
    
    month = str(datetime.datetime.now().month)
    try:
        dt = datetime.datetime.strptime(payload.date, "%Y-%m-%d")
        month = str(dt.month)
    except Exception:
        pass

    # Payroll Lock Enforcement
    is_locked, lock_msg = check_payroll_lock_status(month)
    if is_locked:
        raise HTTPException(
            status_code=423,
            detail=f"Kỳ lương tháng {month} đã bị Admin KHÓA SỔ đối soát ({lock_msg}). Không thể ghi thêm thưởng / phạt."
        )

    is_bonus = "thuong" in normalize_str(payload.type)
    status = "APPROVED" if role == "ADMIN" else "PENDING"

    if role == "MANAGER" and is_bonus:
        if payload.amount > 1000000:
            raise HTTPException(
                status_code=400,
                detail="Quản lý chỉ được đề xuất thưởng tối đa 1,000,000đ cho mỗi nhân viên một lần."
            )
        emp_monthly_bonus = sum(
            int(e.get("amount") or 0) for e in evals
            if str(e.get("month", "")).strip() == str(month).strip()
            and normalize_str(e.get("staffName")) == normalize_str(payload.staff_name)
            and "thuong" in normalize_str(e.get("type", ""))
            and e.get("status") in ["PENDING", "APPROVED", "ACTIVE"]
        )
        if emp_monthly_bonus + payload.amount > 1000000:
            raise HTTPException(
                status_code=400,
                detail=f"Tổng mức thưởng của nhân viên {payload.staff_name} trong tháng {month} do Quản lý đề xuất vượt hạn mức 1,000,000đ/tháng (Hiện tại đã có: {emp_monthly_bonus:,}đ)."
            )

        total_proposed_month = sum(
            int(e.get("amount", 0)) for e in evals
            if "thuong" in normalize_str(e.get("type", ""))
            and str(e.get("month", "")).strip() == str(month).strip()
            and e.get("createdByRole") == "MANAGER"
            and e.get("status") in ["PENDING", "APPROVED", "ACTIVE"]
        )
        if total_proposed_month + payload.amount > 3000000:
            raise HTTPException(
                status_code=400,
                detail=f"Hạn mức quỹ thưởng Quản lý đề xuất tháng {month} đã đạt trần (Tối đa 3.000.000đ/tháng). Đã đề xuất: {total_proposed_month:,}đ."
            )

    entry = {
        "id": eval_id,
        "staffName": payload.staff_name.strip(),
        "date": payload.date,
        "shift": payload.shift,
        "type": payload.type,
        "amount": payload.amount,
        "reason": payload.reason.strip(),
        "notes": (payload.notes or "").strip(),
        "ratings": payload.ratings or {},
        "redFlags": payload.red_flags or [],
        "createdBy": user.get("sub"),
        "createdByName": user.get("name") or user.get("sub"),
        "createdByRole": role,
        "createdAt": datetime.datetime.now().isoformat(),
        "status": status,
        "month": month
    }

    evals.append(entry)
    save_evaluations(evals)

    # Sync to immutable audit ledger so_cai_luong if APPROVED
    if status == "APPROVED":
        try:
            from services.db import record_so_cai_luong, get_db_path, DEFAULT_TENANT_ID
            db_target = os.getenv("SQLITE_DB_PATH") or get_db_path()
            loai_sk = "THUONG" if is_bonus else "PHAT"
            record_so_cai_luong(
                tenant_id=DEFAULT_TENANT_ID,
                nhan_vien_id=payload.staff_name.strip(),
                staff_name=payload.staff_name.strip(),
                loai_su_kien=loai_sk,
                so_tien_thay_doi=payload.amount,
                ly_do=payload.reason.strip(),
                nguoi_tao=user.get("name") or user.get("sub", "Admin"),
                db_path=db_target
            )
        except Exception as se:
            logger.warning(f"Failed to record so_cai_luong: {se}")

    try:
        status_text = "ĐÃ DUYỆT" if status == "APPROVED" else "CHỜ ADMIN DUYỆT"
        msg = (
            f"📋 <b>[WFM] GHI NHẬN {payload.type.upper()}</b> ({status_text})\n"
            f"👤 Nhân viên: <b>{payload.staff_name}</b>\n"
            f"💰 Số tiền: <b>{payload.amount:,}đ</b>\n"
            f"📝 Lý do: {payload.reason}\n"
            f"👮 Tạo bởi: {user.get('name') or user.get('sub')} ({role})"
        )
        send_telegram_alert(msg)
    except Exception as te:
        print(f"Telegram alert error: {te}")

    return {
        "success": True,
        "message": f"Đã ghi nhận {payload.type} cho {payload.staff_name} ({status}).",
        "entry": entry
    }


@router.post("/admin/eval-webhook")
async def proxy_eval_webhook(request: Request):
    """Zero-Trust Webhook Proxy for Staff Evaluations."""
    enforce_api_rate_limit(request, limit=30, window_seconds=60, key_prefix="eval_webhook")
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    role = user.get("role")
    if role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền kích hoạt webhook đánh giá.")

    try:
        body = await request.json()
    except Exception:
        body = {}

    webhook_secret = os.getenv("N8N_EVAL_WEBHOOK_SECRET") or os.getenv("EVAL_WEBHOOK_SECRET") or ""
    body["auth_token"] = webhook_secret

    n8n_url = os.getenv("N8N_EVAL_WEBHOOK_URL", "").strip()
    if not n8n_url:
        return {"success": True, "message": "N8N evaluation webhook disabled (N8N_EVAL_WEBHOOK_URL not configured)"}
    if not (n8n_url.startswith("http://") or n8n_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid webhook URL scheme")
    
    import urllib.request
    try:
        req_data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            n8n_url,
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as response:  # nosec B310
            return {"success": True, "status": response.status, "message": "Đã chuyển tiếp đánh giá sang n8n"}
    except Exception as e:
        return {"success": True, "warning": f"Dispatched: {str(e)}"}


@router.post("/admin/staff-evaluation/review")
def review_staff_evaluation(request: Request, payload: ApproveEvaluationRequest):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền duyệt thưởng/phạt.")

    action = payload.action.upper()
    if action not in ["APPROVE", "REJECT"]:
        raise HTTPException(status_code=400, detail="Hành động không hợp lệ (APPROVE hoặc REJECT).")

    evals = load_evaluations()
    target_eval = None
    for e in evals:
        if e.get("id") == payload.eval_id:
            e["status"] = "APPROVED" if action == "APPROVE" else "REJECTED"
            e["reviewed_by"] = user.get("sub")
            e["reviewed_at"] = datetime.datetime.now().isoformat()
            if payload.admin_note:
                e["admin_note"] = payload.admin_note.strip()
            target_eval = e
            break

    if not target_eval:
        raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi đánh giá.")

    save_evaluations(evals)
    try:
        from services.db import update_evaluation_status_db
        update_evaluation_status_db(
            eval_id=payload.eval_id,
            status="APPROVED" if action == "APPROVE" else "REJECTED",
            admin_note=payload.admin_note.strip() if payload.admin_note else "",
            reviewed_by=user.get("sub", ""),
            reviewed_at=datetime.datetime.now().isoformat()
        )
    except Exception as ue:
        logger.warning(f"Failed to update eval status in SQLite: {ue}")

    if action == "APPROVE":
        try:
            from services.db import record_so_cai_luong, get_db_path, DEFAULT_TENANT_ID
            db_target = os.getenv("SQLITE_DB_PATH") or get_db_path()
            loai_sk = "THUONG" if "thuong" in normalize_str(target_eval.get("type", "")) else "PHAT"
            record_so_cai_luong(
                tenant_id=DEFAULT_TENANT_ID,
                nhan_vien_id=target_eval.get("staffName", ""),
                staff_name=target_eval.get("staffName", ""),
                loai_su_kien=loai_sk,
                so_tien_thay_doi=int(target_eval.get("amount", 0)),
                ly_do=target_eval.get("reason", "") or "Admin duyệt đánh giá",
                nguoi_tao=user.get("name") or user.get("sub", "Admin"),
                db_path=db_target
            )
        except Exception as se:
            logger.warning(f"Failed to record so_cai_luong for approved eval: {se}")

    try:
        status_text = "ĐÃ DUYỆT CỘNG LƯƠNG" if action == "APPROVE" else "ĐÃ BỊ TỪ CHỐI"
        msg = (
            f"🔔 <b>[WFM] KẾT QUẢ DUYỆT {target_eval.get('type', 'ĐÁNH GIÁ').upper()}</b>\n"
            f"👤 Nhân viên: <b>{target_eval.get('staffName')}</b>\n"
            f"💰 Số tiền: <b>{target_eval.get('amount', 0):,}đ</b>\n"
            f"⚖️ Trạng thái: <b>{status_text}</b> bởi Chủ quán"
        )
        send_telegram_alert(msg)
    except Exception as te:
        print(f"Telegram alert error: {te}")

    return {
        "success": True,
        "message": f"Đã {action.lower()} đánh giá {payload.eval_id}.",
        "evaluation": target_eval
    }


@router.get("/admin/staff-evaluations")
def get_staff_evaluations(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Admin / Quản lý mới có quyền xem danh sách đánh giá")
    return load_evaluations()
