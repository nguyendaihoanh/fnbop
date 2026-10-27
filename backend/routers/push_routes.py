# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
WFM - Push Notification & Shift Operations Monitoring Router
Handles Web Push subscriptions, test triggers, and real-time Manager Compliance Reporting:
- Missing Check-ins (Có ca nhưng chưa vào ca)
- Forgotten Check-outs (Đã quá giờ ca nhưng chưa chốt ca)
- Missing Roster Registrations (Chưa nộp lịch đăng ký ca tuần mới)
"""

import os
import json
import datetime
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel

try:
    from backend.services.webpush_service import (
        get_vapid_public_key,
        send_notification_to_user,
        send_notification_to_all
    )
    from backend.services.db import (
        save_push_subscription_db,
        list_push_subscriptions_db,
        record_notification_dispatch_db,
        has_notification_dispatched_db,
        save_in_app_reminder_db,
        list_active_in_app_reminders_db,
        ack_in_app_reminder_db,
        ack_all_in_app_reminders_db,
        get_all_store_settings_db,
        update_store_setting_db,
        DEFAULT_TENANT_ID
    )
    from backend.services.auth import (
        get_current_user,
        load_staff_auth,
        normalize_str
    )
    from backend.services.attendance_service import load_attendance_logs
    from backend.services.roster_service import load_roster_data, get_active_and_next_week_ids
except ImportError:
    from services.webpush_service import (
        get_vapid_public_key,
        send_notification_to_user,
        send_notification_to_all
    )
    from services.db import (
        save_push_subscription_db,
        list_push_subscriptions_db,
        record_notification_dispatch_db,
        has_notification_dispatched_db,
        save_in_app_reminder_db,
        list_active_in_app_reminders_db,
        ack_in_app_reminder_db,
        ack_all_in_app_reminders_db,
        get_all_store_settings_db,
        update_store_setting_db,
        DEFAULT_TENANT_ID
    )
    from services.auth import (
        get_current_user,
        load_staff_auth,
        normalize_str
    )
    from services.attendance_service import load_attendance_logs
    from services.roster_service import load_roster_data, get_active_and_next_week_ids

router = APIRouter(prefix="/api/v1/cc/notifications/push", tags=["Web Push & Operations Monitor"])


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------
from models.notification import (
    PushSubscribeRequest,
    TriggerTestPushRequest,
    ManagerRemindRequest,
)


def _require_auth(request: Request) -> Dict[str, Any]:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập để thực hiện thao tác này.")
    token = auth_header.split(" ")[1].strip()
    user = get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.")
    return user


def _require_manager(request: Request) -> Dict[str, Any]:
    user = _require_auth(request)
    role = str(user.get("role", "")).upper()
    if role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Yêu cầu quyền Quản lý hoặc Quản trị viên để thực hiện.")
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/public-key")
def api_get_vapid_public_key():
    """Returns VAPID Public Key for client applicationServerKey."""
    key = get_vapid_public_key()
    return {"success": True, "public_key": key}


@router.post("/subscribe")
def api_subscribe_push(payload: PushSubscribeRequest, request: Request):
    """
    Registers or updates client Web Push subscription.
    Requires valid authentication.
    """
    current_user = _require_auth(request)
    req_username = payload.username.strip()
    user_role = str(current_user.get("role", "")).upper()
    if user_role not in ["ADMIN", "MANAGER"]:
        if current_user.get("sub", "").lower() != req_username.lower():
            raise HTTPException(status_code=403, detail="Không thể đăng ký thiết bị cho tài khoản khác.")

    sub_data = payload.subscription
    endpoint = sub_data.get("endpoint")
    keys = sub_data.get("keys", {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Dữ liệu subscription không hợp lệ (thiếu endpoint, p256dh hoặc auth).")

    user_agent = payload.user_agent or request.headers.get("user-agent", "")
    res = save_push_subscription_db(
        username=req_username,
        endpoint=endpoint.strip(),
        p256dh=p256dh.strip(),
        auth=auth.strip(),
        user_agent=user_agent
    )
    return {"success": True, "message": "Đăng ký nhận thông báo đẩy thành công!", "data": res}


def _require_push_auth(request: Request, allowed_roles: Optional[List[str]] = None) -> dict:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yêu cầu xác thực tài khoản")
    token = auth_header.split(" ")[1].strip()
    user = get_current_user(token)
    role = str(user.get("role", "")).upper()
    if allowed_roles and role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Không đủ quyền hạn truy cập")
    return user


@router.get("/subscriptions")
def api_list_subscriptions(request: Request, username: Optional[str] = None):
    """
    Lists active subscriptions (Admin/Manager inspect).
    """
    user = _require_push_auth(request)
    role = str(user.get("role", "")).upper()
    if role not in ["ADMIN", "MANAGER"]:
        username = user.get("sub")
    subs = list_push_subscriptions_db(username=username)
    return {"success": True, "count": len(subs), "subscriptions": subs}


@router.post("/trigger-test")
def api_trigger_test_push(payload: TriggerTestPushRequest, request: Request):
    """
    Sends one of the 3 canonical WFM notification templates to test on client.
    Requires ADMIN or MANAGER role.
    """
    _require_push_auth(request, allowed_roles=["ADMIN", "MANAGER"])
    t_type = payload.template_type.upper()
    username = payload.username.strip()

    if t_type == "CHECKIN":
        title = payload.custom_title or "FnBOps - Nhắc ca làm việc"
        body = payload.custom_body or "Bạn có ca Sáng lúc 07:00. Kết nối WiFi quán để Vào ca nhé."
        url = "/index.html#attendance"
    elif t_type == "CHECKOUT":
        title = payload.custom_title or "FnBOps - Chốt ca làm việc"
        body = payload.custom_body or "Thời gian làm việc đã kết thúc chưa? Vui lòng bấm kết thúc ca nghen, hỗ trợ cái. Ténnn kìuuu!!!"
        url = "/index.html#attendance"
    elif t_type == "ROSTER":
        title = payload.custom_title or "FnBOps - Lịch làm việc tuần mới"
        body = payload.custom_body or "Cổng đăng ký ca tuần mới đã mở. Vui lòng gửi lịch làm việc tuần trước 12:00 Chủ Nhật!"
        url = "/index.html#roster"
    else:
        title = payload.custom_title or "FnBOps - Thông báo"
        body = payload.custom_body or "Thông báo thử nghiệm từ hệ thống FnBOps."
        url = "/index.html"

    results = send_notification_to_user(
        username=username,
        title=title,
        body=body,
        tag=f"test-{t_type.lower()}",
        url=url
    )

    return {
        "success": True,
        "username": username,
        "template_type": t_type,
        "title": title,
        "body": body,
        "dispatch_count": len(results),
        "results": results
    }


# ---------------------------------------------------------------------------
# MANAGER COMPLIANCE & EXCEPTION MONITORING (BÁO CÁO CHO QUẢN LÝ)
# ---------------------------------------------------------------------------

@router.get("/manager/exceptions")
def api_get_manager_exceptions(request: Request):
    """
    Real-time Operational Compliance Monitor for Managers:
    1. missing_checkin: Ai có ca hôm nay nhưng chưa vào ca.
    2. forgotten_checkout: Ai đã vào ca nhưng quá giờ tan ca > 10 phút chưa bấm Chốt ca.
    3. missing_roster_registration: Ai active chưa đăng ký lịch ca tuần mới.
    """
    _require_manager(request)
    now = datetime.datetime.now()
    today_iso = now.strftime("%Y-%m-%d")
    today_vn = now.strftime("%d/%m/%Y")
    now_hm = now.strftime("%H:%M")

    # 1. Load active roster
    roster_data = load_roster_data()
    weeks = roster_data.get("weeks", roster_data)
    
    # Identify current ISO week ID
    iso_year, iso_week, _ = now.isocalendar()
    cur_week_id = f"{iso_year}-W{iso_week:02d}"
    next_week_id = f"{iso_year}-W{iso_week + 1:02d}"
    
    cur_week = weeks.get(cur_week_id, {})
    shifts_today = cur_week.get("shifts", {}).get(today_iso, {})

    # Extract all staff assigned to today's shifts dynamically
    assigned_today: List[Dict[str, Any]] = []

    def _extract_slot(shift_type: str, shift_label: str, slot_name: str, val: Any, default_time: str):
        if not val:
            return
        users = val if isinstance(val, list) else [val]
        for u in users:
            if u and isinstance(u, str):
                assigned_today.append({
                    "username": normalize_str(u),
                    "shift_type": shift_type,
                    "shift_label": shift_label,
                    "slot": slot_name,
                    "time_range": default_time
                })

    SHIFT_LABELS = {
        "morning": "Ca Sáng",
        "evening": "Ca Tối",
        "afternoon": "Ca Chiều",
        "night": "Ca Đêm"
    }
    SLOT_LABELS = {
        "manager": "Quản lý",
        "barista": "Pha chế",
        "service": "Phục vụ",
        "service_17": "Phục vụ 17h",
        "service_18": "Phục vụ 18h",
        "cashier": "Thu ngân",
        "security": "Bảo vệ"
    }
    METADATA_KEYS = {"time", "missing_barista", "note", "status", "created_at", "updated_at"}

    # Dynamic Shift Extraction: Tự động duyệt toàn bộ các ca và các vị trí có trong lịch ngày
    for s_key, s_data in shifts_today.items():
        if not isinstance(s_data, dict):
            continue
        default_time = s_data.get("time") or ("06:00 - 11:30" if "morn" in s_key else "17:00 - 23:00")
        s_label = SHIFT_LABELS.get(s_key, s_key.replace("_", " ").title())

        for slot_k, slot_val in s_data.items():
            if slot_k in METADATA_KEYS or not slot_val:
                continue
            slot_name = SLOT_LABELS.get(slot_k, slot_k.replace("_", " ").title())
            _extract_slot(s_key, s_label, slot_name, slot_val, default_time)

    # 2. Load attendance logs for today & Build Per-Shift Attendance Sets
    att_logs = load_attendance_logs()
    today_logs = [l for l in att_logs if l.get("date") == today_vn]

    # Load staff account info for friendly names & alias matching
    auth_data = load_staff_auth()
    staff_accounts = auth_data.get("staff_accounts", {})
    if not staff_accounts and "users" in auth_data:
        staff_accounts = auth_data.get("users", {})

    def _get_log_shift_type(log_entry: Dict[str, Any]) -> str:
        s_key = str(log_entry.get("shift_key", "")).lower()
        s_name = str(log_entry.get("shift_name", "")).lower()
        if "sang" in s_key or "morn" in s_key or "sáng" in s_name:
            return "morning"
        if "toi" in s_key or "even" in s_key or "tối" in s_name:
            return "evening"
        c_time = str(log_entry.get("checkin_time", "06:00"))
        try:
            h = int(c_time.split(":")[0])
            return "morning" if h < 14 else "evening"
        except Exception:
            return "evening"

    # Per-shift matching prevents double-shift false-negatives (làm sáng không làm mất cảnh báo tối)
    checked_in_by_shift: Dict[str, set] = {"morning": set(), "evening": set(), "all": set()}
    for l in today_logs:
        u_raw = normalize_str(l.get("username", ""))
        disp = normalize_str(l.get("display_name", ""))
        sh_type = _get_log_shift_type(l)
        
        target_sets = [checked_in_by_shift["all"], checked_in_by_shift.setdefault(sh_type, set())]
        for t_set in target_sets:
            if u_raw: t_set.add(u_raw)
            if disp: t_set.add(disp)
            acc_matched = staff_accounts.get(u_raw, {})
            for a in acc_matched.get("sheet_names", []):
                if a: t_set.add(normalize_str(a))
            if acc_matched.get("full_name"):
                t_set.add(normalize_str(acc_matched.get("full_name")))

    def _get_name(uname: str) -> str:
        acct = staff_accounts.get(uname, {})
        return acct.get("full_name") or acct.get("name") or uname.capitalize()

    # 3. Compute Missing Check-ins (Chỉ theo dõi nhân viên part-time, loại trừ Quản lý/Admin và chỉ báo khi ca sắp đến hoặc đã qua)
    missing_checkin = []
    for item in assigned_today:
        u = item["username"]
        # Loại trừ Quản lý / Admin khỏi danh sách nhắc chấm công nhân viên
        if item.get("slot") == "Quản lý" or u in ["admin", "superadmin"]:
            continue
        acct = staff_accounts.get(u, {})
        if str(acct.get("status", "ACTIVE")).strip().upper() != "ACTIVE" or acct.get("role") in ["ADMIN", "MANAGER"]:
            continue

        # Check if user or any of their aliases have already checked in for THIS specific shift
        user_aliases = {u}
        for a in acct.get("sheet_names", []):
            if a: user_aliases.add(normalize_str(a))
        if acct.get("full_name"):
            user_aliases.add(normalize_str(acct.get("full_name")))

        sh_type = item.get("shift_type", "")
        relevant_checked = checked_in_by_shift.get(sh_type, checked_in_by_shift["all"])
        if not user_aliases.isdisjoint(relevant_checked):
            # Already checked in for this shift
            continue

        # Check if shift start time is close or passed
        time_parts = item["time_range"].split("-")
        start_hm = time_parts[0].strip() if time_parts else "06:00"
        
        # Chỉ hiển thị cảnh báo khi trong vòng 15 phút trước ca hoặc đã qua giờ vào ca
        try:
            sh_h, sh_m = [int(x) for x in start_hm.split(":")]
            now_h, now_m = [int(x) for x in now_hm.split(":")]
            sh_total_mins = sh_h * 60 + sh_m
            now_total_mins = now_h * 60 + now_m
            if now_total_mins < (sh_total_mins - 15):
                # Ca chưa tới (cách hơn 15 phút), không cảnh báo sớm
                continue
            is_overdue = now_total_mins > sh_total_mins
        except Exception:
            is_overdue = now_hm > start_hm

        missing_checkin.append({
            "username": u,
            "name": _get_name(u),
            "shift": item["shift_label"],
            "slot": item["slot"],
            "start_time": start_hm,
            "is_overdue": is_overdue,
            "status_text": "Chậm vào ca" if is_overdue else "Chưa check-in"
        })

    # 4. Compute Forgotten Check-outs (Đã vào ca nhưng quá giờ tan ca > 10p chưa chốt)
    forgotten_checkout = []
    for log in today_logs:
        if log.get("checkout_time") is None:
            uname = normalize_str(log.get("username", ""))
            shift_name = log.get("shift_name", "Ca làm việc")
            c_in = log.get("checkin_time", "06:00")
            s_end = log.get("scheduled_end") or ("11:30" if "sáng" in shift_name.lower() else "23:00")
            
            # Check if current time > scheduled_end + 10 mins
            try:
                end_dt = datetime.datetime.strptime(f"{today_iso} {s_end}", "%Y-%m-%d %H:%M")
                overdue_dt = end_dt + datetime.timedelta(minutes=10)
                is_overdue = now >= overdue_dt
                over_mins = max(0, int((now - end_dt).total_seconds() / 60))
            except Exception:
                is_overdue = False
                over_mins = 0

            if is_overdue:
                forgotten_checkout.append({
                    "id": log.get("id"),
                    "username": uname,
                    "name": _get_name(uname),
                    "shift": shift_name,
                    "checkin_time": c_in,
                    "scheduled_end": s_end,
                    "over_mins": over_mins,
                    "status_text": f"Lố giờ ca ({over_mins} phút chưa chốt)"
                })

    # 5. Compute Missing Roster Registrations (Tuần kế tiếp - CHỈ NHÂN SỰ ĐANG ACTIVE)
    next_week = weeks.get(next_week_id, {})
    registrations = next_week.get("registrations", {})
    registered_users = {normalize_str(u) for u in registrations.keys()}

    missing_roster_registration = []
    for uname, acct in staff_accounts.items():
        u_norm = normalize_str(uname)
        status = str(acct.get("status", "ACTIVE")).strip().upper()
        if status != "ACTIVE":
            continue
        role = str(acct.get("role", "")).upper()
        if role in ["STAFF", "NHAN_VIEN", "BARISTA", "SERVICE"]:
            if u_norm not in registered_users:
                missing_roster_registration.append({
                    "username": u_norm,
                    "name": acct.get("full_name") or acct.get("name") or uname.capitalize(),
                    "role": role,
                    "target_week": next_week_id,
                    "status_text": "Chưa nộp lịch tuần"
                })

    return {
        "success": True,
        "as_of": now.strftime("%Y-%m-%d %H:%M:%S"),
        "cur_week_id": cur_week_id,
        "next_week_id": next_week_id,
        "summary": {
            "missing_checkin_count": len(missing_checkin),
            "forgotten_checkout_count": len(forgotten_checkout),
            "missing_roster_count": len(missing_roster_registration)
        },
        "missing_checkin": missing_checkin,
        "forgotten_checkout": forgotten_checkout,
        "missing_roster_registration": missing_roster_registration
    }


@router.post("/manager/remind-staff")
def api_manager_remind_staff(payload: ManagerRemindRequest, request: Request):
    """
    Allows Manager to trigger an instant reminder to an employee.
    """
    _require_manager(request)
    uname = normalize_str(payload.username)
    r_type = payload.remind_type.upper()

    if r_type == "CHECKIN":
        title = "FnBOps - Nhắc Vào ca khẩn"
        body = payload.custom_message or "Bạn có ca làm việc hôm nay nhưng chưa thấy Check-in. Vui lòng kết nối WiFi quán để Vào ca nhé! Hỗ trợ nhau chút. Thénnn kìuuu!!!"
        url = "/index.html#attendance"
    elif r_type == "CHECKOUT":
        title = "FnBOps - Nhắc Chốt ca"
        body = payload.custom_message or "Thời gian làm việc đã kết thúc chưa? Vui lòng bấm kết thúc ca nghen, hỗ trợ cái. Ténnn kìuuu!!!"
        url = "/index.html#attendance"
    elif r_type == "ROSTER":
        title = "FnBOps - Nhắc Đăng ký ca tuần"
        body = payload.custom_message or "Cổng đăng ký ca tuần mới đã mở. Vui lòng gửi lịch làm việc tuần trước 12:00 Chủ Nhật!"
        url = "/index.html#roster"
    else:
        title = "FnBOps - Thông báo Quản lý"
        body = payload.custom_message or "Bạn có thông báo mới từ Quản lý FnBOps."
        url = "/index.html"

    # Save In-App Reminder to database for real-time modal popup when staff is in-app
    reminder_id = save_in_app_reminder_db(
        username=uname,
        remind_type=r_type,
        title=title,
        message=body,
        url=url
    )

    res = send_notification_to_user(
        username=uname,
        title=title,
        body=body,
        tag=f"manager-remind-{r_type.lower()}",
        url=url
    )

    return {
        "success": True,
        "username": uname,
        "remind_type": r_type,
        "reminder_id": reminder_id,
        "dispatched_count": len(res),
        "results": res
    }


@router.get("/my-reminders")
def api_get_my_reminders(request: Request):
    """
    Returns unread in-app reminders for the authenticated employee.
    Used by the frontend to display an immediate pop-up alert when manager sends a reminder.
    """
    user = _require_auth(request)
    uname = normalize_str(user.get("username") or user.get("sub") or "")
    if not uname:
        return {"success": True, "reminders": []}

    reminders = list_active_in_app_reminders_db(username=uname)
    return {
        "success": True,
        "username": uname,
        "reminders": reminders
    }


@router.post("/ack-reminder/{reminder_id}")
def api_ack_reminder(reminder_id: int, request: Request):
    """
    Acknowledges / dismisses an in-app reminder.
    """
    user = _require_auth(request)
    uname = normalize_str(user.get("username") or user.get("sub") or "")
    if not uname:
        raise HTTPException(status_code=400, detail="Tài khoản không hợp lệ.")

    ack_in_app_reminder_db(reminder_id=reminder_id, username=uname)
    return {
        "success": True,
        "reminder_id": reminder_id,
        "message": "Đã ghi nhận thông báo."
    }


@router.post("/ack-all-reminders")
def api_ack_all_reminders(request: Request):
    """
    Acknowledges / dismisses ALL unread in-app reminders for the user to completely stop duplicate popups.
    """
    user = _require_auth(request)
    uname = normalize_str(user.get("username") or user.get("sub") or "")
    if not uname:
        raise HTTPException(status_code=400, detail="Tài khoản không hợp lệ.")

    count = ack_all_in_app_reminders_db(username=uname)
    return {
        "success": True,
        "dismissed_count": count,
        "message": f"Đã ghi nhận toàn bộ {count} thông báo."
    }


from models.store_config import UpdateOpsTogglePayload


@router.get("/settings/ops-toggles")
def api_get_ops_toggles(request: Request):
    """
    Returns all operational store settings toggles for Managers/Admins.
    """
    _require_manager(request)
    toggles = get_all_store_settings_db()
    return {
        "success": True,
        "toggles": toggles
    }


@router.post("/settings/ops-toggles")
def api_update_ops_toggle(payload: UpdateOpsTogglePayload, request: Request):
    """
    Updates an operational store setting toggle.
    Requires Manager or Admin role.
    """
    user = _require_manager(request)
    key = payload.key.strip()
    val = str(payload.value).strip()
    allowed_keys = [
        "auto_remind_shifts",
        "emergency_remote_checkin",
        "roster_registration_open",
        "peer_shift_swap_allowed",
        "payroll_verification_open"
    ]
    if key not in allowed_keys:
        raise HTTPException(status_code=400, detail=f"Mã công tắc vận hành không hợp lệ: {key}")

    caller_name = user.get("sub") or user.get("username") or "manager"
    update_store_setting_db(key=key, value=val, updated_by=caller_name)
    return {
        "success": True,
        "key": key,
        "value": val,
        "message": "Đã cập nhật công tắc vận hành thành công."
    }


# ---------------------------------------------------------------------------
# ROUTE ALIASES: Hỗ trợ client/frontend gọi tiền tố ngắn /api/v1/cc/push/
# Dập tắt triệt để các lỗi 404 ngầm từ attendanceModule.js
# ---------------------------------------------------------------------------
alias_router = APIRouter(prefix="/api/v1/cc/push", tags=["Push Aliases"])

@alias_router.get("/manager/exceptions")
def alias_get_manager_exceptions(request: Request):
    return api_get_manager_exceptions(request)

@alias_router.post("/manager/remind-staff")
def alias_manager_remind_staff(payload: ManagerRemindRequest, request: Request):
    return api_manager_remind_staff(payload, request)


