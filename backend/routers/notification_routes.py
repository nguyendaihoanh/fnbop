# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
WFM - Notification & Payslip Email Router
Endpoints for generating and sending Payslip and Evaluation PDFs via SMTP or Smart Outbox.
Authoritative On-Premise dispatch without reliance on external services.
"""

import os
import re
import datetime
import unicodedata
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, Response, Query
from pydantic import BaseModel

import base64
import requests

try:
    from backend.services.pdf_generator import render_payslip_pdf, render_eval_notice_pdf
    from backend.services.email_service import (
        send_email_with_pdf, list_outbox_records, get_outbox_pdf_file, clear_outbox_data
    )
    from backend.services.payroll_calc import calculate_staff_payslip_breakdown
    from backend.services.payslip_card_generator import render_payslip_card_png, format_currency
except ImportError:
    from services.pdf_generator import render_payslip_pdf, render_eval_notice_pdf
    from services.email_service import (
        send_email_with_pdf, list_outbox_records, get_outbox_pdf_file, clear_outbox_data
    )
    from services.payroll_calc import calculate_staff_payslip_breakdown
    from services.payslip_card_generator import render_payslip_card_png, format_currency

try:
    from backend.services.auth import get_current_user, normalize_str
except ImportError:
    from services.auth import get_current_user, normalize_str

router = APIRouter(prefix="/api/v1/cc/notifications", tags=["Notifications & Outbox"])


def require_notification_auth(
    request: Request,
    allowed_roles: Optional[List[str]] = None,
    token_param: Optional[str] = None
) -> dict:
    """
    Verifies authentication via Authorization Bearer header OR ?token= query param.
    Enforces role-based access control (RBAC).
    """
    token = None
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1].strip()
    elif token_param:
        token = token_param.strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Yêu cầu xác thực tài khoản. Vui lòng đăng nhập."
        )

    user = get_current_user(token)
    if allowed_roles:
        u_role = str(user.get("role") or "").upper()
        if u_role not in [r.upper() for r in allowed_roles]:
            raise HTTPException(
                status_code=403,
                detail="Bạn không có quyền thực hiện thao tác này."
            )
    return user


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------
from models.notification import (
    SendPayslipEmailRequest,
    SendEvalEmailRequest,
    SendPayslipZaloCardRequest,
    SendBulkPayslipZaloCardsRequest,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_slug(text: str) -> str:
    if not text:
        return "nhan_su"
    s = unicodedata.normalize("NFD", str(text))
    s = "".join([c for c in s if unicodedata.category(c) != "Mn"])
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_")
    return s.lower() or "staff"


def _compute_server_breakdown(staff_name: str, month: str = "9") -> Dict[str, Any]:
    """Computes authoritative breakdown using backend data files and SQLite."""
    try:
        try:
            from backend.routers.fnb_ops import (
                get_data_file, load_shift_approvals, load_evaluations
            )
            from backend.services.storage import safe_json_read
            from backend.services.auth import load_staff_auth
            from backend.services.attendance_service import load_attendance_logs
            from backend.services.db import list_staff_ledgers
            from backend.services.store_config import get_store_config
        except ImportError:
            from routers.fnb_ops import (
                get_data_file, load_shift_approvals, load_evaluations
            )
            from services.storage import safe_json_read
            from services.auth import load_staff_auth
            from services.attendance_service import load_attendance_logs
            from services.db import list_staff_ledgers
            from services.store_config import get_store_config

        data_file = get_data_file()
        data = safe_json_read(data_file, default={})
        approvals = load_shift_approvals()
        evals = load_evaluations()
        attendance_logs = load_attendance_logs()
        auth_data = load_staff_auth()
        store_cfg = get_store_config()
        cur_m = str(month or datetime.datetime.now().month).strip()
        staff_ledgers = list_staff_ledgers(month=cur_m)

        return calculate_staff_payslip_breakdown(
            staff_name, cur_m, data, approvals, evals, attendance_logs, staff_ledgers,
            staff_accounts=auth_data.get("staff_accounts", {}),
            store_config=store_cfg
        )
    except Exception as e:
        # Fallback minimal breakdown if server data sources are empty in testing
        return {
            "staff_name": staff_name,
            "month": month,
            "base_wage": 17000,
            "total_shifts": 0,
            "total_worked_minutes": 0,
            "total_hours": 0.0,
            "standard_pay": 0,
            "eval_bonus": 0,
            "advance_amount": 0,
            "eval_deductions": 0,
            "late_penalty_total": 0,
            "violations": [],
            "gross_salary": 0,
            "total_deductions": 0,
            "net_pay": 0,
            "shift_records": []
        }


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/send-payslip-email")
async def api_send_payslip_email(payload: SendPayslipEmailRequest, request: Request):
    """
    Renders payslip PDF for a staff member and dispatches via SMTP or Outbox.
    Requires ADMIN or MANAGER role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN", "MANAGER"])

    staff_name = payload.staff_name.strip()
    if not staff_name:
        raise HTTPException(status_code=400, detail="Tên nhân viên không được để trống")

    month = str(payload.month or datetime.datetime.now().month).strip()

    # 1. Resolve or compute breakdown
    if payload.breakdown and isinstance(payload.breakdown, dict) and "net_pay" in payload.breakdown:
        breakdown = payload.breakdown
    else:
        breakdown = _compute_server_breakdown(staff_name, month)

    # 2. Render PDF
    pdf_bytes = render_payslip_pdf(staff_name=staff_name, month=month, breakdown=breakdown)
    clean_name = _clean_slug(staff_name)
    filename = f"PhieuLuong_{clean_name.upper()}_T{month}.pdf"

    # 3. Determine recipient email
    to_email = payload.to_email
    if not to_email:
        to_email = f"{clean_name}@fnbops.local"

    # 4. Compose Email Body
    net_pay_val = int(breakdown.get("net_pay") or 0)
    total_hours_val = float(breakdown.get("total_hours") or 0.0)
    total_shifts_val = int(breakdown.get("total_shifts") or 0)

    subject = f"[FnBOps] Phiếu Lương Kỳ Tháng {month} - {staff_name}"
    body_text = (
        f"Kính gửi {staff_name},\n\n"
        f"Hệ thống FnBOps xin gửi Phiếu Lương chi tiết kỳ Tháng {month} của bạn đính kèm trong email này.\n\n"
        f"--- TỔNG KẾT KỲ CÔNG ---\n"
        f"• Tổng số ca hoàn thành: {total_shifts_val} ca\n"
        f"• Tổng thời gian làm việc: {total_hours_val:.1f} giờ\n"
        f"• THỰC LĨNH (NET PAY): {net_pay_val:,} VNĐ\n\n"
        f"Lưu ý: Mọi thắc mắc hoặc khiếu nại về bảng lương vui lòng liên hệ Quản lý trong vòng 24 giờ.\n\n"
        f"Trân trọng,\n"
        f"Ban Quản Lý FnBOps"
    )

    # 5. Dispatch email or store in outbox
    result = await send_email_with_pdf(
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        pdf_bytes=pdf_bytes,
        filename=filename
    )

    return {
        "success": True,
        "message": "Phiếu lương PDF đã được xử lý và gửi thành công",
        "staff_name": staff_name,
        "month": month,
        "to_email": to_email,
        "net_pay": net_pay_val,
        "filename": filename,
        "email_delivery": result
    }


@router.post("/send-eval-email")
async def api_send_eval_email(payload: SendEvalEmailRequest, request: Request):
    """
    Renders evaluation notice PDF and dispatches via SMTP or Outbox.
    Requires ADMIN or MANAGER role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN", "MANAGER"])

    eval_data = payload.eval_data or {}
    
    # If eval_id is provided without data, search existing evals
    if payload.eval_id and not eval_data:
        try:
            try:
                from backend.routers.fnb_ops import load_evaluations
            except ImportError:
                from routers.fnb_ops import load_evaluations
            evals = load_evaluations()
            for ev in evals:
                if str(ev.get("id")) == str(payload.eval_id):
                    eval_data = dict(ev)
                    break
        except Exception:
            pass

    if not eval_data:
        eval_data = {
            "id": payload.eval_id or "EV-CUSTOM",
            "staff_name": payload.staff_name or "Nhân sự F&B",
            "type": "BONUS",
            "amount": 0,
            "reason": "Đánh giá ca làm việc định kỳ"
        }

    staff_name = eval_data.get("staff_name") or eval_data.get("staffName") or payload.staff_name or "Nhân sự F&B"
    pdf_bytes = render_eval_notice_pdf(eval_data)
    clean_name = _clean_slug(staff_name)
    eval_id_clean = _clean_slug(str(eval_data.get("id") or "notice"))
    filename = f"BienBan_DanhGia_{eval_id_clean.upper()}_{clean_name.upper()}.pdf"

    to_email = payload.to_email or f"{clean_name}@fnbops.local"
    subject = f"[FnBOps] Biên Bản Đánh Giá Ca Làm Việc - {staff_name}"
    
    is_bonus = any(k in str(eval_data.get("type", "")).upper() for k in ["BONUS", "THUONG", "KHEN"])
    action_str = "Khen thưởng" if is_bonus else "Điều chỉnh vi phạm"
    amount_str = f"{int(eval_data.get('amount', 0)):,} VNĐ"

    body_text = (
        f"Kính gửi {staff_name},\n\n"
        f"Ban Quản Lý FnBOps thông báo kết quả đánh giá ca làm việc của bạn:\n"
        f"• Hình thức: {action_str}\n"
        f"• Mức điều chỉnh: {amount_str}\n"
        f"• Căn cứ: {eval_data.get('reason') or eval_data.get('note') or 'Quy chuẩn ca'}\n\n"
        f"Chi tiết biên bản đính kèm trong tệp PDF dưới đây.\n\n"
        f"Trân trọng,\n"
        f"Ban Quản Lý FnBOps"
    )

    result = await send_email_with_pdf(
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        pdf_bytes=pdf_bytes,
        filename=filename
    )

    return {
        "success": True,
        "message": "Biên bản đánh giá PDF đã được tạo và gửi thành công",
        "staff_name": staff_name,
        "to_email": to_email,
        "filename": filename,
        "email_delivery": result
    }


@router.get("/outbox")
def api_get_outbox(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    token: Optional[str] = Query(None)
):
    """
    Returns the list of PDF files queued or sent via Outbox with delivery status.
    Requires ADMIN or MANAGER role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN", "MANAGER"], token_param=token)

    records = list_outbox_records()
    items = records[:limit]
    
    # Calculate summary statistics
    total_queued = sum(1 for r in records if "queued" in r.get("status", ""))
    total_sent = sum(1 for r in records if r.get("status") == "sent")

    return {
        "success": True,
        "total_records": len(records),
        "total_queued": total_queued,
        "total_sent": total_sent,
        "items": items
    }


@router.get("/preview-payslip-pdf")
def api_preview_payslip_pdf(
    request: Request,
    staff_name: str,
    month: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    """
    Generates and returns the payslip PDF directly for preview/download in browser.
    Employees can only view their own payslip; ADMIN/MANAGER can view any.
    """
    month = str(month or datetime.datetime.now().month).strip()
    user = require_notification_auth(request, token_param=token)
    role = str(user.get("role") or "").upper()
    if role not in ["ADMIN", "MANAGER"]:
        sub = str(user.get("sub") or "")
        name = str(user.get("name") or "")
        sheet_names = [str(s) for s in user.get("sheet_names") or []]
        allowed_names = [sub, name] + sheet_names
        normalized_allowed = [normalize_str(n) for n in allowed_names if n]
        if normalize_str(staff_name) not in normalized_allowed:
            raise HTTPException(
                status_code=403,
                detail="Bạn chỉ có quyền xem phiếu lương của chính mình."
            )

    staff_name = staff_name.strip()
    if not staff_name:
        raise HTTPException(status_code=400, detail="staff_name is required")
    
    breakdown = _compute_server_breakdown(staff_name, month)
    pdf_bytes = render_payslip_pdf(staff_name=staff_name, month=month, breakdown=breakdown)
    clean_fn = f"PhieuLuong_{_clean_slug(staff_name).upper()}_T{month}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={clean_fn}"}
    )


def _get_cached_zalo_uid_db(phone: str, username: Optional[str] = None) -> Optional[str]:
    """Retrieves cached Zalo UID from SQLite staff_accounts."""
    try:
        from services.db.connection import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        if phone:
            cur.execute("SELECT zalo_uid FROM staff_accounts WHERE phone = ? AND zalo_uid IS NOT NULL AND zalo_uid != ''", (phone,))
            row = cur.fetchone()
            if row and row[0]:
                conn.close()
                return str(row[0]).strip()
        if username:
            cur.execute("SELECT zalo_uid FROM staff_accounts WHERE username = ? AND zalo_uid IS NOT NULL AND zalo_uid != ''", (username,))
            row = cur.fetchone()
            if row and row[0]:
                conn.close()
                return str(row[0]).strip()
        conn.close()
    except Exception:
        pass
    return None


def _cache_zalo_uid_db(phone: str, uid: str, username: Optional[str] = None) -> None:
    """Caches resolved Zalo UID in SQLite staff_accounts (zero runtime JSON mutation)."""
    if not uid:
        return
    clean_uid = str(uid).strip()
    clean_phone = str(phone).strip()
    u_key = (username or clean_phone).strip()
    try:
        from services.db.connection import get_db_connection
        conn = get_db_connection()
        with conn:
            conn.execute(
                "UPDATE staff_accounts SET zalo_uid = ? WHERE phone = ? OR username = ?",
                (clean_uid, clean_phone, u_key)
            )
        conn.close()
    except Exception:
        pass


def _resolve_zalo_uid(recipient: str, base_url: str, staff_username: Optional[str] = None) -> str:
    """Resolves phone number to Zalo UID with fast-path SQLite caching."""
    clean = re.sub(r"[^\d+]", "", str(recipient or "").strip())
    if clean.startswith("+84"):
        clean = "0" + clean[3:]
    elif clean.startswith("84") and len(clean) >= 10:
        clean = "0" + clean[2:]

    if len(clean) >= 14 and not clean.startswith("0") and clean.isdigit():
        return clean

    cached_uid = _get_cached_zalo_uid_db(clean, staff_username)
    if cached_uid:
        return cached_uid

    if len(clean) in (10, 11) and clean.isdigit():
        try:
            lookup_url = f"{base_url}/api/action"
            resp = requests.post(lookup_url, json={"action": "findUser", "params": {"phone": clean}}, timeout=6)
            if resp.status_code == 200:
                d = resp.json()
                if d.get("success") and d.get("data") and d["data"].get("uid"):
                    resolved_uid = str(d["data"]["uid"]).strip()
                    _cache_zalo_uid_db(clean, resolved_uid, staff_username)
                    return resolved_uid
        except Exception:
            pass
    return clean


def _dispatch_zalo_image(recipient: str, message: str, image_bytes: bytes, staff_username: Optional[str] = None) -> dict:
    """Dispatches a base64 encoded image card to the Zalo Gateway microservice with SQLite UID resolution."""
    gateway_url = os.getenv("ZALO_GATEWAY_URL", "http://zalo-gateway:8177").rstrip("/")
    gw_token = os.getenv("ZALO_GATEWAY_TOKEN", "").strip()
    gw_headers = {"X-Zalo-Gateway-Token": gw_token} if gw_token else {}
    target_recipient = _resolve_zalo_uid(recipient, gateway_url, staff_username=staff_username)
    payload = {
        "recipient": target_recipient,
        "message": message,
        "image_base64": base64.b64encode(image_bytes).decode("utf-8")
    }
    targets = [f"{gateway_url}/api/zalo/send", "http://127.0.0.1:8177/api/zalo/send"]
    last_err = None
    for url in targets:
        try:
            resp = requests.post(url, json=payload, headers=gw_headers, timeout=25)
            if resp.status_code == 200:
                return resp.json()
            last_err = f"Gateway returned HTTP {resp.status_code}: {resp.text}"
        except Exception as e:
            last_err = str(e)
            continue
    raise RuntimeError(f"Không thể kết nối tới Zalo Gateway: {last_err}")


@router.get("/preview-payslip-card")
def api_preview_payslip_card(
    request: Request,
    staff_name: str,
    month: Optional[str] = "9",
    token: Optional[str] = Query(None)
):
    """
    Renders and streams high-resolution PNG payslip image card.
    Accessible to the employee themselves or ADMIN/MANAGER.
    """
    user = require_notification_auth(request, token_param=token)
    role = str(user.get("role") or "").upper()
    if role not in ["ADMIN", "MANAGER"]:
        sub = str(user.get("sub") or "")
        name = str(user.get("name") or "")
        sheet_names = [str(s) for s in user.get("sheet_names") or []]
        aliases = [str(a) for a in user.get("aliases") or []]
        allowed = [normalize_str(n) for n in [sub, name] + sheet_names + aliases if n]
        if normalize_str(staff_name) not in allowed:
            raise HTTPException(status_code=403, detail="Chỉ có quyền xem phiếu lương của chính mình.")

    clean_name = staff_name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="staff_name is required")

    breakdown = _compute_server_breakdown(clean_name, month)
    png_bytes = render_payslip_card_png(
        staff_name=clean_name,
        month=month,
        breakdown=breakdown
    )
    clean_fn = f"PhieuLuong_{_clean_slug(clean_name).upper()}_T{month}.png"

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename={clean_fn}"}
    )


@router.post("/send-payslip-zalo-card")
def api_send_payslip_zalo_card(payload: SendPayslipZaloCardRequest, request: Request):
    """
    Renders Dark Luxury payslip image card and dispatches via Zalo Gateway.
    Requires ADMIN or MANAGER role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN", "MANAGER"])
    staff_name = payload.staff_name.strip()
    if not staff_name:
        raise HTTPException(status_code=400, detail="Tên nhân viên không được để trống")

    month = str(payload.month or datetime.datetime.now().month).strip()
    phone = (payload.phone or "").strip()

    try:
        from backend.services.auth import load_staff_auth
    except ImportError:
        from services.auth import load_staff_auth

    auth_data = load_staff_auth()
    staff_accs = auth_data.get("staff_accounts", {})

    matched_acc = None
    clean_target = staff_name.strip().lower()
    
    # Phase 1: So khớp chính xác 100% CÓ DẤU (chữ thường/hoa)
    for uname, acc in staff_accs.items():
        all_exact = [uname.lower(), str(acc.get("full_name", "")).lower()]
        all_exact.extend([str(a).lower() for a in acc.get("aliases", [])])
        all_exact.extend([str(s).lower() for s in acc.get("sheet_names", [])])
        if clean_target in all_exact:
            matched_acc = acc
            break

    # Phase 2: Fallback so khớp không dấu nếu chưa tìm thấy
    if not matched_acc:
        target_norm = normalize_str(staff_name)
        for uname, acc in staff_accs.items():
            aliases = [normalize_str(a) for a in acc.get("aliases", [])]
            sheets = [normalize_str(s) for s in acc.get("sheet_names", [])]
            if target_norm == normalize_str(uname) or target_norm == normalize_str(acc.get("full_name", "")) or target_norm in aliases or target_norm in sheets:
                matched_acc = acc
                break

    if not phone and matched_acc:
        phone = str(matched_acc.get("phone") or "").strip()

    if not phone:
        raise HTTPException(
            status_code=400,
            detail=f"Nhân viên {staff_name} chưa có số điện thoại Zalo trong hồ sơ. Vui lòng cập nhật số điện thoại trước khi gửi."
        )

    if payload.breakdown and isinstance(payload.breakdown, dict) and "net_pay" in payload.breakdown:
        breakdown = payload.breakdown
    else:
        breakdown = _compute_server_breakdown(staff_name, month)

    emp_id = (matched_acc.get("employee_id") if matched_acc else "WFM_STAFF") or "WFM_STAFF"
    role_lbl = (matched_acc.get("position") if matched_acc else "Nhân Viên Vận Hành") or "Nhân Viên Vận Hành"

    png_bytes = render_payslip_card_png(
        staff_name=staff_name,
        month=month,
        breakdown=breakdown,
        role_label=role_lbl,
        employee_id=emp_id
    )

    caption = (
        f"PHIẾU LƯƠNG FNBOPS - THÁNG {month}\n"
        f"Kính gửi: {staff_name}\n"
        f"Hệ thống gửi bạn ảnh phiếu lương đối soát chính thức từ máy POS tại quán.\n"
        f"Thực chuyển khoản: {format_currency(breakdown.get('net_pay', 0))}\n"
        f"Vui lòng kiểm tra và phản hồi trong 24h nếu có thắc mắc."
    )

    try:
        dispatch_resp = _dispatch_zalo_image(recipient=phone, message=caption, image_bytes=png_bytes)
        return {
            "success": True,
            "message": f"Đã gửi ảnh phiếu lương qua Zalo tới {staff_name} ({phone}) thành công.",
            "phone": phone,
            "gateway_result": dispatch_resp
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-bulk-payslip-zalo-cards")
def api_send_bulk_payslip_zalo_cards(payload: SendBulkPayslipZaloCardsRequest, request: Request):
    """
    Renders and dispatches payslip image cards to all active staff with registered phone numbers.
    Requires ADMIN or MANAGER role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN", "MANAGER"])
    month = str(payload.month or datetime.datetime.now().month).strip()

    try:
        from backend.services.auth import load_staff_auth
    except ImportError:
        from services.auth import load_staff_auth

    auth_data = load_staff_auth()
    staff_accs = auth_data.get("staff_accounts", {})

    results = []
    sent_count = 0
    skipped_count = 0

    import time
    # Sắp xếp tuần tự danh sách nhân sự theo mã nhân viên (EMP_001, EMP_002...) để gửi theo trình tự chuẩn xác
    sorted_staff = sorted(staff_accs.items(), key=lambda x: (x[1].get("employee_id") or "ZZZ", x[0]))

    for uname, acc in sorted_staff:
        if acc.get("status") != "ACTIVE":
            continue
        phone = str(acc.get("phone") or "").strip()
        full_name = acc.get("full_name") or uname
        if not phone:
            skipped_count += 1
            results.append({"staff": full_name, "status": "skipped", "reason": "Chưa có SĐT Zalo"})
            continue

        try:
            breakdown = _compute_server_breakdown(full_name, month)
            png_bytes = render_payslip_card_png(
                staff_name=full_name,
                month=month,
                breakdown=breakdown,
                role_label=acc.get("position", "Nhân Viên Vận Hành"),
                employee_id=acc.get("employee_id", "EMP_000")
            )
            caption = (
                f"PHIẾU LƯƠNG FNBOPS - THÁNG {month}\n"
                f"Kính gửi: {full_name}\n"
                f"Hệ thống gửi bạn ảnh phiếu lương đối soát chính thức từ máy POS tại quán.\n"
                f"Thực chuyển khoản: {format_currency(breakdown.get('net_pay', 0))}"
            )
            _dispatch_zalo_image(recipient=phone, message=caption, image_bytes=png_bytes)
            sent_count += 1
            results.append({"staff": full_name, "phone": phone, "status": "sent"})
            time.sleep(1.5)  # Đảm bảo gửi tuần tự từng số điện thoại, chống nghẽn và chống rate limit Zalo
        except Exception as err:
            results.append({"staff": full_name, "phone": phone, "status": "failed", "error": str(err)})

    return {
        "success": True,
        "total_sent": sent_count,
        "total_skipped": skipped_count,
        "details": results
    }


@router.get("/preview-eval-pdf")
def api_preview_eval_pdf(
    request: Request,
    eval_id: Optional[str] = None,
    staff_name: Optional[str] = None,
    token: Optional[str] = Query(None)
):
    """
    Generates and returns an evaluation notice PDF directly for preview/download in browser.
    Employees can only view their own evaluation; ADMIN/MANAGER can view any.
    """
    user = require_notification_auth(request, token_param=token)
    role = str(user.get("role") or "").upper()
    if role not in ["ADMIN", "MANAGER"] and staff_name:
        sub = str(user.get("sub") or "")
        name = str(user.get("name") or "")
        sheet_names = [str(s) for s in user.get("sheet_names") or []]
        allowed_names = [sub, name] + sheet_names
        normalized_allowed = [normalize_str(n) for n in allowed_names if n]
        if normalize_str(staff_name) not in normalized_allowed:
            raise HTTPException(
                status_code=403,
                detail="Bạn chỉ có quyền xem biên bản đánh giá của chính mình."
            )

    eval_data = {
        "id": eval_id or "EV-PREVIEW",
        "staff_name": staff_name or "Nhân Viên Mẫu",
        "type": "BONUS",
        "amount": 50000,
        "reason": "Hoàn thành ca làm việc xuất sắc, thái độ chuẩn 5 sao."
    }
    pdf_bytes = render_eval_notice_pdf(eval_data)
    clean_fn = f"BienBan_{_clean_slug(eval_data['staff_name']).upper()}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={clean_fn}"}
    )


@router.get("/outbox/pdf/{filename}")
def api_get_outbox_pdf(
    filename: str,
    request: Request,
    token: Optional[str] = Query(None)
):
    """
    Serves a stored PDF from data/outbox/pdf.
    Requires ADMIN or MANAGER role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN", "MANAGER"], token_param=token)

    file_path = get_outbox_pdf_file(filename)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file outbox '{filename}'")

    with open(file_path, "rb") as f:
        content = f.read()

    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={os.path.basename(file_path)}"}
    )


@router.get("/outbox/download-all-zip")
def api_download_all_outbox_zip(
    request: Request,
    token: Optional[str] = Query(None)
):
    """
    Zips all PDFs in the outbox directory and returns a single downloadable ZIP file.
    Requires ADMIN or MANAGER role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN", "MANAGER"], token_param=token)

    import io
    import zipfile
    from backend.services.email_service import get_outbox_dir

    outbox_dir = get_outbox_dir()
    pdf_dir = os.path.join(outbox_dir, "pdf")
    if not os.path.exists(pdf_dir):
        raise HTTPException(status_code=404, detail="Thư mục Outbox rỗng, chưa có file PDF nào")

    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
    if not pdf_files:
        raise HTTPException(status_code=404, detail="Chưa có file PDF nào trong Outbox để tải về")

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in sorted(pdf_files):
            fpath = os.path.join(pdf_dir, fname)
            zf.write(fpath, fname)

    mem_zip.seek(0)
    zip_bytes = mem_zip.getvalue()

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=ToanBo_PhieuLuong_PDF.zip"}
    )


@router.delete("/outbox/pdf/{filename}")
def api_delete_outbox_pdf(
    filename: str,
    request: Request,
    token: Optional[str] = Query(None)
):
    """
    Deletes a specific PDF file from the outbox directory.
    Requires ADMIN role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN"], token_param=token)

    file_path = get_outbox_pdf_file(filename)
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file outbox '{filename}'")

    try:
        os.remove(file_path)
        return {"success": True, "message": f"Đã xóa file '{filename}' khỏi Outbox"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi xóa file: {str(e)}")


@router.delete("/outbox/clear")
def api_clear_all_outbox(
    request: Request,
    token: Optional[str] = Query(None)
):
    """
    Clears all outbox records and PDF files.
    Requires ADMIN role.
    """
    require_notification_auth(request, allowed_roles=["ADMIN"], token_param=token)

    clear_outbox_data()
    return {"success": True, "message": "Đã dọn sạch toàn bộ file trong Outbox"}


