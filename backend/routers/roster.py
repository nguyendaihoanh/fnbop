# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
ROSTER PLANNER ENGINE - FNBOPS / FNBOPS.LOCAL
Quản lý lịch ca làm việc theo tuần chuẩn ISO (T2 -> CN)
- Định biên: T2-T6 (Sáng: 1 QL, 1 PC, 2 PV; Tối: 1 QL, 2 PV [17h & 18h])
            T7-CN  (Sáng: 1 QL, 1 PC, 2 PV; Tối: 1 QL, 1 PC, 2 PV [17h & 18h])
- Ràng buộc thể lực: Tối đa 1 Nữ / ca phục vụ, BẮT BUỘC có ít nhất 1 Nam (bưng bê bàn ghế, dọn dẹp)
- Tải làm việc: 3 - 10 ca/tuần/nhân sự
- Quản lý cố định: 6-11 và 17-23
- Đăng ký ca: T7 07:00 -> CN 09:00, tự động nhảy tuần lúc 18:00 CN
- Đổi ca trực tiếp giữa nhân sự (Peer Swap)
"""

import os
import json
import datetime
import threading
import inspect
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

try:
    from backend.services.storage import safe_json_write
    from backend.services.auth import (
        load_staff_auth,
        get_current_user,
        normalize_str,
        DEFAULT_AUTH_FILE,
    )
    from backend.services.roster_service import (
        get_roster_file,
        load_roster_data,
        save_roster_data,
        get_iso_week_info,
        get_active_and_next_week_ids,
        _roster_lock,
        DEFAULT_ROSTER_FILE,
        is_week_registration_open,
        is_registration_window_open,
        validate_service_gender_pair,
        is_bar_capable,
        is_service_capable,
        get_primary_role,
        check_and_auto_publish_roster_deadline,
    )
    from backend.services.send_telegram import send_telegram_alert
    from backend.services.store_config import get_store_config, get_shift_role_requirements
except ImportError:
    from services.storage import safe_json_write
    from services.auth import (
        load_staff_auth,
        get_current_user,
        normalize_str,
        DEFAULT_AUTH_FILE,
    )
    from services.roster_service import (
        get_roster_file,
        load_roster_data,
        save_roster_data,
        get_iso_week_info,
        get_active_and_next_week_ids,
        _roster_lock,
        DEFAULT_ROSTER_FILE,
        is_week_registration_open,
        is_registration_window_open,
        validate_service_gender_pair,
        is_bar_capable,
        is_service_capable,
        get_primary_role,
        check_and_auto_publish_roster_deadline,
    )
    from services.send_telegram import send_telegram_alert
    from services.store_config import get_store_config, get_shift_role_requirements
try:
    from backend.services.db import (
        check_api_rate_limit,
        create_open_shift_db,
        list_open_shifts_db,
        claim_open_shift_db,
        delete_open_shift_db,
        get_store_setting_db,
    )
except ImportError:
    from services.db import (
        check_api_rate_limit,
        create_open_shift_db,
        list_open_shifts_db,
        claim_open_shift_db,
        delete_open_shift_db,
        get_store_setting_db,
    )

router = APIRouter(prefix="/api/v1/cc/roster", tags=["Roster"])


# --------------------------------------------------------------------------
# PYDANTIC MODELS
# --------------------------------------------------------------------------
from models.roster import (
    ShiftPreference,
    AutoFillRequest,
    ClonePreviousWeekRequest,
    UpdateShiftSlotRequest,
    PublishWeekRequest,
    PeerSwapRequest,
    PeerSwapRespondRequest,
    CreateOpenShiftRequest,
)

# --------------------------------------------------------------------------
# API ENDPOINTS
# --------------------------------------------------------------------------

@router.get("/week")
def get_week_schedule(request: Request, week_id: Optional[str] = None):
    """
    Lấy thông tin ca làm việc của 1 tuần (hoặc tuần hiện tại).
    Bắt buộc xác thực: Nhân viên/Quản lý phải có Bearer Token hợp lệ.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập để xem lịch ca")
    current_user = get_current_user(auth_header.split(" ")[1])

    active_info, next_info = get_active_and_next_week_ids()
    if week_id == "next":
        target_week_id = next_info["week_id"]
    elif week_id == "current":
        target_week_id = active_info["week_id"]
    else:
        target_week_id = week_id or active_info["week_id"]

    roster_data = load_roster_data()
    weeks = roster_data.get("weeks", {})

    try:
        target_info = get_iso_week_info(datetime.datetime.strptime(target_week_id + "-1", "%G-W%V-%u").date()) if "-W" in target_week_id else active_info
    except Exception:
        target_info = active_info

    week_entry = weeks.get(target_week_id)
    if not week_entry:
        week_entry = {
            "week_id": target_week_id,
            "start_date": target_info["start_date"],
            "end_date": target_info["end_date"],
            "status": "DRAFT",
            "registrations": {},
            "shifts": {},
            "swaps": []
        }
        store_cfg = get_store_config()
        sang_cfg = store_cfg.get("shifts", {}).get("sang", {})
        toi_cfg = store_cfg.get("shifts", {}).get("toi", {})

        for d in target_info["days"]:
            dt = datetime.datetime.strptime(d, "%Y-%m-%d").date()
            is_weekend = (dt.isocalendar()[2] in [6, 7])
            m_req = get_shift_role_requirements(sang_cfg, is_weekend=is_weekend)
            e_req = get_shift_role_requirements(toi_cfg, is_weekend=is_weekend)

            m_bar_count = m_req.get("barista", 1)
            m_svc_count = m_req.get("service", 2)
            e_bar_count = e_req.get("barista", 1 if is_weekend else 0)
            e_svc_count = e_req.get("service", 2)

            week_entry["shifts"][d] = {
                "morning": {
                    "time": f"{sang_cfg.get('official_start', '06:00')} - {sang_cfg.get('official_end', '11:30')}",
                    "manager": None,
                    "barista": None,
                    "baristas": [None] * m_bar_count,
                    "service": [None] * m_svc_count
                },
                "evening": {
                    "time": f"{toi_cfg.get('official_start', '17:00')} - {toi_cfg.get('official_end', '23:00')}",
                    "manager": None,
                    "barista": None,
                    "baristas": [None] * e_bar_count if e_bar_count > 0 else [],
                    "service": [None] * e_svc_count,
                    "service_17": None,
                    "service_18": None
                }
            }
        weeks[target_week_id] = week_entry
        roster_data["weeks"] = weeks
        save_roster_data(roster_data)

    # Tự động di chuyển / gộp các bản ghi đăng ký nếu từng bị lưu nhầm vào key 'next' hoặc 'current'
    legacy_key = "next" if target_week_id == next_info["week_id"] else ("current" if target_week_id == active_info["week_id"] else None)
    if legacy_key and legacy_key in weeks and isinstance(weeks[legacy_key], dict):
        leg_regs = weeks[legacy_key].get("registrations", {})
        if isinstance(leg_regs, dict) and leg_regs:
            target_regs = week_entry.setdefault("registrations", {})
            for lu, lv in leg_regs.items():
                if lu not in target_regs:
                    target_regs[lu] = lv
            del weeks[legacy_key]
            save_roster_data(roster_data)

    staff_auth = load_staff_auth()
    accounts = staff_auth.get("staff_accounts", {})
    reg_window_open, reg_msg = is_week_registration_open(target_week_id, week_entry)

    return {
        "success": True,
        "week": week_entry,
        "active_week_id": active_info["week_id"],
        "next_week_id": next_info["week_id"],
        "is_active_week": (target_week_id == active_info["week_id"]),
        "registration_window_open": reg_window_open,
        "registration_message": reg_msg,
        "peer_shift_swap_allowed": (get_store_setting_db("peer_shift_swap_allowed", "1") == "1"),
        "days": target_info["days"],
        "current_user": current_user.get("sub") if current_user else None,
        "staff_directory": {
            u: {
                "full_name": a.get("full_name", u),
                "gender": a.get("gender", "NAM"),
                "position": a.get("position", "SERVICE"),
                "role": a.get("role", "STAFF"),
                "status": a.get("status", "ACTIVE"),
                "primary_role": a.get("primary_role"),
                "allowed_roles": a.get("allowed_roles")
            }
            for u, a in accounts.items()
        }
    }


@router.get("/my-schedule")
def get_my_schedule(request: Request, week_id: Optional[str] = "current"):
    """
    Returns the personalized weekly shift schedule for the currently authenticated staff member.
    Automatically checks Sunday 12:00 PM auto-publish deadline and hides unapproved DRAFT shifts from non-managers.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yêu cầu đăng nhập để xem lịch làm việc")
    current_user = get_current_user(auth_header.split(" ")[1])
    caller_sub = (current_user.get("sub") or "").lower()
    caller_role = (current_user.get("role") or "STAFF").upper()

    check_and_auto_publish_roster_deadline()

    active_info, next_info = get_active_and_next_week_ids()
    if week_id == "next":
        target_week_id = next_info["week_id"]
    elif week_id == "current":
        target_week_id = active_info["week_id"]
    else:
        target_week_id = week_id or active_info["week_id"]

    roster_data = load_roster_data()
    weeks = roster_data.get("weeks", {})
    week_entry = weeks.get(target_week_id) or {}
    status = week_entry.get("status", "DRAFT")
    is_published = (status == "PUBLISHED")
    shifts = week_entry.get("shifts", {})

    staff_auth = load_staff_auth()
    accounts = staff_auth.get("staff_accounts", {})
    reg_window_open, reg_msg = is_week_registration_open(target_week_id, week_entry)

    user_aliases = {caller_sub}
    caller_info = accounts.get(caller_sub, {})
    if caller_info:
        fn = caller_info.get("full_name", "")
        if fn:
            user_aliases.add(fn.lower())
            user_aliases.add(normalize_str(fn))
        for al in caller_info.get("aliases", []):
            user_aliases.add(al.lower())
            user_aliases.add(normalize_str(al))
        for sn in caller_info.get("sheet_names", []):
            user_aliases.add(sn.lower())
            user_aliases.add(normalize_str(sn))

    def is_staff_match(val: Any) -> bool:
        if not val or not isinstance(val, str):
            return False
        v_low = val.strip().lower()
        v_norm = normalize_str(val)
        return (v_low in user_aliases or v_norm in user_aliases)

    def get_staff_name(u: str) -> str:
        if not u:
            return ""
        if u in accounts and accounts[u].get("full_name"):
            return accounts[u]["full_name"]
        return u

    my_shifts = []
    can_view_shifts = is_published or (caller_role in ["ADMIN", "MANAGER"])

    if can_view_shifts and shifts:
        for d_str, day_data in sorted(shifts.items()):
            try:
                dt_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
                vn_date = dt_obj.strftime("%d/%m/%Y")
                iso_day = dt_obj.isocalendar()[2]
                day_name = "Chủ Nhật" if iso_day == 7 else f"Thứ {iso_day + 1}"
            except Exception:
                vn_date = d_str
                day_name = d_str

            m = day_data.get("morning", {})
            ev = day_data.get("evening", {})

            is_m_barista = is_staff_match(m.get("barista")) or any(is_staff_match(b) for b in m.get("baristas", []))
            m_services = m.get("service") or []
            is_m_service = any(is_staff_match(s) for s in m_services)
            is_m_manager = is_staff_match(m.get("manager"))

            if is_m_barista or is_m_service or is_m_manager:
                role_label = "Pha chế" if is_m_barista else ("Quản lý" if is_m_manager else "Phục vụ")
                slot_type = "barista" if is_m_barista else ("manager" if is_m_manager else "service")

                teammates = []
                if m.get("manager") and not is_staff_match(m.get("manager")):
                    teammates.append(f"{get_staff_name(m.get('manager'))} (QL)")
                for b in m.get("baristas", []):
                    if b and not is_staff_match(b):
                        teammates.append(f"{get_staff_name(b)} (BAR)")
                if not m.get("baristas") and m.get("barista") and not is_staff_match(m.get("barista")):
                    teammates.append(f"{get_staff_name(m.get('barista'))} (BAR)")
                for s in m_services:
                    if s and not is_staff_match(s):
                        teammates.append(f"{get_staff_name(s)} (PV)")

                my_shifts.append({
                    "date": d_str,
                    "vn_date": vn_date,
                    "day_name": day_name,
                    "shift": "Ca Sáng",
                    "shift_key": "sang",
                    "period": "morning",
                    "time": m.get("time", "06:00 - 11:30"),
                    "role": role_label,
                    "slot_type": slot_type,
                    "teammates": teammates,
                    "is_published": is_published,
                    "status": status
                })

            is_ev_barista = is_staff_match(ev.get("barista")) or any(is_staff_match(b) for b in ev.get("baristas", []))
            is_ev_s17 = is_staff_match(ev.get("service_17"))
            is_ev_s18 = is_staff_match(ev.get("service_18"))
            ev_services = ev.get("service") or []
            is_ev_service = is_ev_s17 or is_ev_s18 or any(is_staff_match(s) for s in ev_services)
            is_ev_manager = is_staff_match(ev.get("manager"))

            if is_ev_barista or is_ev_service or is_ev_manager:
                role_label = "Pha chế" if is_ev_barista else ("Quản lý" if is_ev_manager else "Phục vụ")
                if is_ev_barista:
                    slot_type = "barista"
                    ev_time = ev.get("time", "17:00 - 23:00")
                elif is_ev_manager:
                    slot_type = "manager"
                    ev_time = ev.get("time", "17:00 - 23:00")
                elif is_ev_s18:
                    slot_type = "service_18"
                    ev_time = "18:00 - 23:00"
                else:
                    slot_type = "service_17"
                    ev_time = "17:00 - 23:00"

                teammates = []
                if ev.get("manager") and not is_staff_match(ev.get("manager")):
                    teammates.append(f"{get_staff_name(ev.get('manager'))} (QL)")
                for b in ev.get("baristas", []):
                    if b and not is_staff_match(b):
                        teammates.append(f"{get_staff_name(b)} (BAR)")
                if not ev.get("baristas") and ev.get("barista") and not is_staff_match(ev.get("barista")):
                    teammates.append(f"{get_staff_name(ev.get('barista'))} (BAR)")
                if ev.get("service_17") and not is_staff_match(ev.get("service_17")):
                    teammates.append(f"{get_staff_name(ev.get('service_17'))} (PV 17h)")
                if ev.get("service_18") and not is_staff_match(ev.get("service_18")):
                    teammates.append(f"{get_staff_name(ev.get('service_18'))} (PV 18h)")
                for s in ev_services:
                    if s and not is_staff_match(s) and s != ev.get("service_17") and s != ev.get("service_18"):
                        teammates.append(f"{get_staff_name(s)} (PV)")

                my_shifts.append({
                    "date": d_str,
                    "vn_date": vn_date,
                    "day_name": day_name,
                    "shift": "Ca Tối",
                    "shift_key": "toi",
                    "period": "evening",
                    "time": ev_time,
                    "role": role_label,
                    "slot_type": slot_type,
                    "teammates": teammates,
                    "is_published": is_published,
                    "status": status
                })

    return {
        "success": True,
        "username": caller_sub,
        "role": caller_role,
        "week_id": target_week_id,
        "status": status,
        "is_published": is_published,
        "start_date": week_entry.get("start_date", ""),
        "end_date": week_entry.get("end_date", ""),
        "registration_window_open": reg_window_open,
        "registration_message": reg_msg,
        "shifts": my_shifts,
        "shifts_count": len(my_shifts)
    }


def enforce_roster_rate_limit(request: Request, limit: int = 20, window_seconds: int = 60, prefix: str = "roster"):
    client_ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Real-IP") or (request.client.host if request.client else "127.0.0.1")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    key = f"{prefix}:{client_ip}"
    allowed, count, retry_after = check_api_rate_limit(key, limit=limit, window_seconds=window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Thao tác quá nhanh. Vui lòng chờ {int(retry_after)} giây trước khi thử lại.",
            headers={"Retry-After": str(int(retry_after))}
        )


@router.post("/register")
def register_shift_preferences(request: Request, data: ShiftPreference):
    enforce_roster_rate_limit(request, limit=20, window_seconds=60, prefix="roster_reg")
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    username = user.get("sub")

    active_info, next_info = get_active_and_next_week_ids()
    if data.week_id == "next":
        target_week_id = next_info["week_id"]
    elif data.week_id == "current":
        target_week_id = active_info["week_id"]
    else:
        target_week_id = data.week_id or next_info["week_id"]

    roster_data = load_roster_data()
    weeks = roster_data.setdefault("weeks", {})
    week_entry = weeks.setdefault(target_week_id, {
        "week_id": target_week_id,
        "status": "REGISTRATION_OPEN",
        "registrations": {},
        "shifts": {},
        "swaps": []
    })

    if user.get("role") not in ["ADMIN", "MANAGER"]:
        is_open, reason = is_week_registration_open(target_week_id, week_entry)
        if not is_open:
            raise HTTPException(
                status_code=400,
                detail=reason
            )

    regs = week_entry.setdefault("registrations", {})
    regs[username] = {
        "username": username,
        "preferences": data.preferences,
        "target_shifts": max(3, min(10, data.target_shifts)),
        "role_preference": getattr(data, "role_preference", "BOTH") or "BOTH",
        "note": data.note.strip(),
        "registered_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    save_roster_data(roster_data)

    staff_auth = load_staff_auth()
    full_name = staff_auth.get("staff_accounts", {}).get(username, {}).get("full_name", username)

    return {
        "success": True,
        "message": f"Đã ghi nhận đăng ký ca tuần {target_week_id} của {full_name} ({data.target_shifts} ca).",
        "registration": regs[username]
    }

from services.roster_service import DAY_KEYS_ISO, _extract_day_pref_tags
from services.roster_engine import auto_assign_week_schedule


@router.post("/auto-fill")
def auto_fill_schedule(request: Request, data: AutoFillRequest):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền tự động xếp lịch ca")

    return auto_assign_week_schedule(week_key=data.week_id)

@router.post("/clone-previous-week")
def clone_previous_week_schedule(request: Request, data: ClonePreviousWeekRequest):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền sao chép lịch ca")

    active_info, next_info = get_active_and_next_week_ids()
    if data.target_week_id == "next":
        target_week_id = next_info["week_id"]
    elif data.target_week_id == "current":
        target_week_id = active_info["week_id"]
    elif data.target_week_id:
        target_week_id = data.target_week_id
    else:
        target_week_id = next_info["week_id"]

    try:
        target_monday = datetime.datetime.strptime(target_week_id + "-1", "%G-W%V-%u").date()
        target_info = get_iso_week_info(target_monday)
    except Exception:
        raise HTTPException(status_code=400, detail=f"target_week_id không hợp lệ: {target_week_id}")

    if data.source_week_id:
        source_week_id = data.source_week_id
        try:
            source_monday = datetime.datetime.strptime(source_week_id + "-1", "%G-W%V-%u").date()
            source_info = get_iso_week_info(source_monday)
        except Exception:
            raise HTTPException(status_code=400, detail=f"source_week_id không hợp lệ: {source_week_id}")
    else:
        # Mặc định lấy tuần liền trước của target_week_id
        source_monday = target_monday - datetime.timedelta(days=7)
        source_info = get_iso_week_info(source_monday)
        source_week_id = source_info["week_id"]

    roster_data = load_roster_data()
    weeks = roster_data.get("weeks", {})

    source_week = weeks.get(source_week_id)
    if not source_week or not source_week.get("shifts"):
        raise HTTPException(
            status_code=400,
            detail=f"Không tìm thấy dữ liệu ca trực của tuần nguồn ({source_week_id}) để sao chép."
        )

    # Khởi tạo target_week nếu chưa có
    target_week = weeks.get(target_week_id)
    if not target_week:
        target_week = {
            "week_id": target_week_id,
            "start_date": target_info["start_date"],
            "end_date": target_info["end_date"],
            "status": "DRAFT",
            "registrations": {},
            "shifts": {},
            "swaps": []
        }

    # Clone từng ngày tương ứng từ Thứ 2 đến Chủ Nhật (0 -> 6)
    source_shifts = source_week.get("shifts", {})
    if "shifts" not in target_week:
        target_week["shifts"] = {}

    cloned_days_count = 0
    for i in range(7):
        src_day = source_info["days"][i]
        tgt_day = target_info["days"][i]
        if src_day in source_shifts:
            target_week["shifts"][tgt_day] = json.loads(json.dumps(source_shifts[src_day]))
            cloned_days_count += 1

    target_week["status"] = "DRAFT"
    weeks[target_week_id] = target_week
    roster_data["weeks"] = weeks
    save_roster_data(roster_data)

    return {
        "success": True,
        "message": f"Đã sao chép lịch phân ca từ tuần {source_week_id} sang tuần {target_week_id} thành công.",
        "target_week_id": target_week_id,
        "source_week_id": source_week_id,
        "cloned_days_count": cloned_days_count
    }

@router.post("/update-shift")
def update_shift_slot(request: Request, data: UpdateShiftSlotRequest):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền sửa ca")

    active_info, next_info = get_active_and_next_week_ids()
    target_week_id = active_info["week_id"] if data.week_id == "current" else (next_info["week_id"] if data.week_id in [None, "next"] else data.week_id)

    roster_data = load_roster_data()
    week_entry = roster_data.get("weeks", {}).get(target_week_id)
    if not week_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy dữ liệu tuần")

    staff_auth = load_staff_auth()
    accounts = staff_auth.get("staff_accounts", {})
    managers = [u for u, a in accounts.items() if a.get("role") == "MANAGER" and a.get("status") != "INACTIVE"]
    default_mgr = managers[0] if managers else None

    shifts = week_entry.setdefault("shifts", {})
    if data.date not in shifts:
        store_cfg = get_store_config()
        sang_cfg = store_cfg.get("shifts", {}).get("sang", {})
        toi_cfg = store_cfg.get("shifts", {}).get("toi", {})
        dt = datetime.datetime.strptime(data.date, "%Y-%m-%d").date()
        is_weekend = (dt.isocalendar()[2] in [6, 7])
        m_req = get_shift_role_requirements(sang_cfg, is_weekend=is_weekend)
        e_req = get_shift_role_requirements(toi_cfg, is_weekend=is_weekend)
        shifts[data.date] = {
            "morning": {
                "time": f"{sang_cfg.get('official_start', '06:00')} - {sang_cfg.get('official_end', '11:30')}",
                "manager": None,
                "barista": None,
                "baristas": [None] * m_req.get("barista", 1),
                "service": [None] * m_req.get("service", 2)
            },
            "evening": {
                "time": f"{toi_cfg.get('official_start', '17:00')} - {toi_cfg.get('official_end', '23:00')}",
                "manager": None,
                "barista": None,
                "baristas": [None] * e_req.get("barista", 1 if is_weekend else 0) if e_req.get("barista", 0) > 0 else [],
                "service": [None] * e_req.get("service", 2),
                "service_17": None,
                "service_18": None
            }
        }
    day_shift = shifts[data.date]

    target_user = normalize_str(data.username) if data.username else None
    period = data.shift_period.lower()
    slot = data.slot_type.lower()

    if target_user and slot != "manager" and not slot.startswith("manager_"):
        found_acc = accounts.get(data.username) or accounts.get(target_user)
        if not found_acc:
            for k, a in accounts.items():
                if str(data.username).lower() == k.lower() or target_user == normalize_str(k) or target_user in [normalize_str(al) for al in a.get("aliases", [])]:
                    found_acc = a
                    break
        if not found_acc or found_acc.get("status") == "INACTIVE":
            raise HTTPException(status_code=400, detail="Nhân sự phân ca không hợp lệ hoặc đã nghỉ việc")

    target = day_shift.setdefault(period, {})
    slot_clean = slot.lower()

    # 1. MANAGER
    if slot_clean == "manager" or slot_clean.startswith("manager_"):
        target["manager"] = target_user
        if slot_clean.startswith("manager_"):
            try:
                idx = int(slot_clean.split("_")[1])
                if not isinstance(target.get("managers"), list):
                    target["managers"] = [target.get("manager")] if target.get("manager") else []
                while len(target["managers"]) <= idx:
                    target["managers"].append(None)
                target["managers"][idx] = target_user
            except Exception:
                pass

    # 2. BARISTA
    elif slot_clean == "barista" or slot_clean.startswith("barista_"):
        if slot_clean == "barista":
            target["barista"] = target_user
            if isinstance(target.get("baristas"), list):
                if target["baristas"]:
                    target["baristas"][0] = target_user
                else:
                    target["baristas"] = [target_user]
        else:
            try:
                idx = int(slot_clean.split("_")[1])
                if not isinstance(target.get("baristas"), list):
                    target["baristas"] = [target.get("barista")] if target.get("barista") else []
                while len(target["baristas"]) <= idx:
                    target["baristas"].append(None)
                target["baristas"][idx] = target_user
                if idx == 0:
                    target["barista"] = target_user
            except Exception:
                target["barista"] = target_user

    # 3. SERVICE
    elif slot_clean.startswith("service") or slot_clean in ["service_17", "service_18"]:
        if not isinstance(target.get("service"), list):
            target["service"] = []
            if target.get("service_17"):
                target["service"].append(target.get("service_17"))
            if target.get("service_18"):
                target["service"].append(target.get("service_18"))

        idx = 0
        if slot_clean == "service_1":
            idx = 0
        elif slot_clean == "service_2":
            idx = 1
        elif slot_clean == "service_17":
            idx = 0
            target["service_17"] = target_user
        elif slot_clean == "service_18":
            idx = 1
            target["service_18"] = target_user
        elif "_" in slot_clean:
            try:
                idx = int(slot_clean.split("_")[1])
            except Exception:
                idx = 0

        while len(target["service"]) <= idx:
            target["service"].append(None)

        if target_user:
            other_services = [target["service"][j] for j in range(len(target["service"])) if j != idx and target["service"][j]]
            for other_s in other_services:
                valid, msg = validate_service_gender_pair(target_user, other_s, accounts, shift_key=period)
                if not valid:
                    raise HTTPException(status_code=400, detail=msg)

        target["service"][idx] = target_user
        if period == "evening":
            if idx == 0:
                target["service_17"] = target_user
            elif idx == 1:
                target["service_18"] = target_user

    # Two-way sync: Synchronize updated slot into week_entry["days"] structure
    try:
        dt_val = datetime.datetime.strptime(data.date, "%Y-%m-%d").date()
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        d_key = day_names[dt_val.weekday()]
        if "days" in week_entry and isinstance(week_entry["days"], dict) and d_key in week_entry["days"]:
            d_obj = week_entry["days"][d_key]
            period_key = "sang" if period == "morning" else "toi"
            p_obj = d_obj.setdefault(period_key, {})
            p_obj["barista"] = target.get("baristas", [target.get("barista")]) if (target.get("barista") or target.get("baristas")) else []
            p_obj["service"] = [s for s in target.get("service", []) if s]
            if period == "evening":
                p_obj["service_17"] = target.get("service_17")
                p_obj["service_18"] = target.get("service_18")
    except Exception:
        pass

    save_roster_data(roster_data)

    return {
        "success": True,
        "message": f"Đã cập nhật ca ngày {data.date} ({period} - {slot})",
        "day_shift": day_shift
    }

@router.post("/publish")
def publish_week_schedule(request: Request, data: PublishWeekRequest):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền công bố lịch")

    active_info, next_info = get_active_and_next_week_ids()
    target_week_id = active_info["week_id"] if data.week_id == "current" else (next_info["week_id"] if data.week_id in [None, "next"] else data.week_id)

    roster_data = load_roster_data()
    week_entry = roster_data.get("weeks", {}).get(target_week_id)
    if not week_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy dữ liệu tuần")

    week_entry["status"] = "PUBLISHED"
    week_entry["published_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    week_entry["published_by"] = user.get("sub")

    save_roster_data(roster_data)

    try:
        from services.store_config import get_store_config
        s_name = (get_store_config().get("store_name") or "FnBOps").strip()
    except Exception:
        s_name = "FnBOps"

    msg = (
        f"[{s_name.upper()}] LỊCH CA TUẦN MỚI ĐÃ ĐƯỢC CÔNG BỐ!\n"
        f"Tuần: {target_week_id} ({week_entry.get('start_date')} -> {week_entry.get('end_date')})\n"
        f"Người duyệt: {user.get('sub').upper()}\n\n"
        f"Các bạn nhân viên truy cập hệ thống để xem lịch ca và đồng đội làm chung."
    )
    send_telegram_alert(msg)

    return {
        "success": True,
        "week_id": target_week_id,
        "message": f"Đã công bố lịch ca tuần {target_week_id} thành công!",
        "week": week_entry
    }

@router.post("/peer-swap")
def peer_swap_shift(request: Request, data: PeerSwapRequest):
    enforce_roster_rate_limit(request, limit=20, window_seconds=60, prefix="roster_swap")
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    caller = user.get("sub")
    caller_role = (user.get("role") or "").upper()

    if get_store_setting_db("peer_shift_swap_allowed", "1") == "0" and caller_role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(
            status_code=403,
            detail="Tính năng tự thương lượng đổi ca giữa nhân viên tạm thời bị Quản lý khóa."
        )

    active_info, next_info = get_active_and_next_week_ids()
    target_week_id = active_info["week_id"] if data.week_id == "current" else (next_info["week_id"] if data.week_id in [None, "next"] else data.week_id)

    roster_data = load_roster_data()
    week_entry = roster_data.get("weeks", {}).get(target_week_id)
    if not week_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy tuần làm việc")

    shifts = week_entry.get("shifts", {})
    day_shift = shifts.get(data.date)
    if not day_shift:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca ngày đã chọn")

    # Fix 1: Chống đổi ca quá khứ đối với nhân viên thường
    try:
        swap_date = datetime.datetime.strptime(data.date, "%Y-%m-%d").date()
        if swap_date < datetime.date.today() and caller_role not in ["ADMIN", "MANAGER"]:
            raise HTTPException(
                status_code=400,
                detail=f"Không thể tạo yêu cầu đổi ca cho ngày đã qua trong quá khứ ({data.date})."
            )
    except ValueError:
        pass

    staff_auth = load_staff_auth()
    accounts = staff_auth.get("staff_accounts", {})

    target_user_raw = data.target_username.strip()
    target_user = target_user_raw if target_user_raw in accounts else normalize_str(target_user_raw)
    if target_user not in accounts:
        for k, a in accounts.items():
            if target_user == normalize_str(k) or target_user in [normalize_str(al) for al in a.get("aliases", [])]:
                target_user = k
                break
    if target_user not in accounts or accounts[target_user].get("status") == "INACTIVE":
        raise HTTPException(status_code=400, detail="Nhân viên nhận ca không hợp lệ hoặc đã nghỉ việc")

    period = data.shift_period.lower()
    slot = data.slot_type.lower()

    caller_name = accounts.get(caller, {}).get("full_name", caller)
    target_name = accounts.get(target_user, {}).get("full_name", target_user)

    # Validate slot ownership
    if period == "morning":
        m = day_shift.get("morning", {})
        if not isinstance(m.get("service"), list):
            m["service"] = [None, None]
        while len(m["service"]) < 2:
            m["service"].append(None)

        if slot in ["service_1", "service"]:
            current_holder = m["service"][0]
            if current_holder != caller and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(status_code=403, detail="Bạn không có tên trong ca làm việc này")
            s2 = m["service"][1]
            valid, msg = validate_service_gender_pair(target_user, s2, accounts, shift_key="morning")
            if not valid:
                raise HTTPException(status_code=400, detail=msg)

        elif slot == "service_2":
            current_holder = m["service"][1]
            if current_holder != caller and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(status_code=403, detail="Bạn không có tên trong ca làm việc này")
            s1 = m["service"][0]
            valid, msg = validate_service_gender_pair(s1, target_user, accounts, shift_key="morning")
            if not valid:
                raise HTTPException(status_code=400, detail=msg)

        elif slot == "barista":
            if m.get("barista") != caller and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(status_code=403, detail="Bạn không có tên trong ca làm việc này")
            target_pos = accounts.get(target_user, {}).get("position")
            if target_pos != "BARISTA" and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(status_code=400, detail="Nhân viên nhận ca chưa có chức danh Pha chế (Barista)")

    elif period == "evening":
        ev = day_shift.get("evening", {})
        if slot == "service_17":
            if ev.get("service_17") != caller and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(status_code=403, detail="Bạn không có tên trong ca làm việc này")
            s18 = ev.get("service_18")
            valid, msg = validate_service_gender_pair(target_user, s18, accounts, shift_key="evening")
            if not valid:
                raise HTTPException(status_code=400, detail=msg)

        elif slot == "service_18":
            if ev.get("service_18") != caller and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(status_code=403, detail="Bạn không có tên trong ca làm việc này")
            s17 = ev.get("service_17")
            valid, msg = validate_service_gender_pair(s17, target_user, accounts, shift_key="evening")
            if not valid:
                raise HTTPException(status_code=400, detail=msg)

        elif slot == "barista":
            if ev.get("barista") != caller and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(status_code=403, detail="Bạn không có tên trong ca làm việc này")
            target_pos = accounts.get(target_user, {}).get("position")
            if target_pos != "BARISTA" and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(status_code=400, detail="Nhân viên nhận ca chưa có chức danh Pha chế (Barista)")

    is_manager_override = (caller_role in ["ADMIN", "MANAGER"]) and data.force_admin_override
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    swap_id = f"sw_{int(datetime.datetime.now().timestamp())}_{caller}_{target_user}"

    if is_manager_override:
        # Immediate transfer by Admin / Manager
        if period == "morning":
            if slot in ["service_1", "service"]:
                day_shift["morning"]["service"][0] = target_user
            elif slot == "service_2":
                day_shift["morning"]["service"][1] = target_user
            elif slot == "barista":
                day_shift["morning"]["barista"] = target_user
        elif period == "evening":
            if slot == "service_17":
                day_shift["evening"]["service_17"] = target_user
            elif slot == "service_18":
                day_shift["evening"]["service_18"] = target_user
            elif slot == "barista":
                day_shift["evening"]["barista"] = target_user

        swap_record = {
            "swap_id": swap_id,
            "status": "APPROVED_BY_MANAGER",
            "week_id": target_week_id,
            "date": data.date,
            "shift_period": period,
            "slot_type": slot,
            "from_user": caller,
            "from_name": caller_name,
            "to_user": target_user,
            "to_name": target_name,
            "reason": data.reason.strip(),
            "created_at": now_str,
            "resolved_at": now_str,
            "resolved_by": caller
        }
        week_entry.setdefault("swaps", []).append(swap_record)
        save_roster_data(roster_data)

        try:
            from services.store_config import get_store_config
            _scfg = get_store_config()
            s_name = (_scfg.get("store_name") or "FnBOps").strip()
        except Exception:
            s_name = "FnBOps"

        send_telegram_alert(
            f"[QUẢN LÝ ĐIỀU CHUYỂN CA] {s_name}\n"
            f"Ngày: {data.date} ({period.upper()} - {slot})\n"
            f"Từ: {caller_name} (@{caller}) -> Đến: {target_name} (@{target_user})\n"
            f"Thực hiện bởi: {caller_name} ({caller_role})"
        )
        return {
            "success": True,
            "message": f"Quản lý đã chuyển ca ngày {data.date} sang cho bạn {target_name}.",
            "swap": swap_record
        }

    # Regular Staff: Two-way handshake (Pending recipient confirmation)
    swap_record = {
        "swap_id": swap_id,
        "status": "PENDING",
        "week_id": target_week_id,
        "date": data.date,
        "shift_period": period,
        "slot_type": slot,
        "from_user": caller,
        "from_name": caller_name,
        "to_user": target_user,
        "to_name": target_name,
        "reason": data.reason.strip(),
        "created_at": now_str,
        "resolved_at": None,
        "resolved_by": None
    }
    week_entry.setdefault("swaps", []).append(swap_record)
    save_roster_data(roster_data)

    try:
        from services.store_config import get_store_config
        _scfg = get_store_config()
        s_name = (_scfg.get("store_name") or "FnBOps").strip()
    except Exception:
        s_name = "FnBOps"

    send_telegram_alert(
        f"[YÊU CẦU ĐỔI CA MỚI] {s_name}\n"
        f"Ngày: {data.date} ({period.upper()} - {slot})\n"
        f"Từ bạn: {caller_name} (@{caller})\n"
        f"Đề xuất chuyển cho: {target_name} (@{target_user})\n"
        f"Lý do: {data.reason.strip() or 'Tự thu xếp'}\n"
        f"Lưu ý: Ca trực CHƯA chuyển nhượng cho đến khi bạn {target_name} vào ứng dụng xác nhận ĐỒNG Ý."
    )

    return {
        "success": True,
        "message": f"Đã gửi yêu cầu đổi ca ngày {data.date} cho bạn {target_name}. Ca chỉ được chuyển sau khi bạn {target_name} xác nhận đồng ý!",
        "swap": swap_record
    }


@router.post("/peer-swap/respond")
def respond_peer_swap(request: Request, data: PeerSwapRespondRequest):
    enforce_roster_rate_limit(request, limit=20, window_seconds=60, prefix="roster_swap_resp")
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    caller = normalize_str(user.get("sub"))
    caller_role = (user.get("role") or "").upper()

    act = data.action.strip().upper()
    if act not in ["ACCEPT", "REJECT"]:
        raise HTTPException(status_code=400, detail="Hành động không hợp lệ (chỉ chấp nhận ACCEPT hoặc REJECT)")

    roster_data = load_roster_data()
    weeks = roster_data.get("weeks", {})

    target_swap = None
    target_week_entry = None
    for w_id, w_data in weeks.items():
        if data.week_id and w_id != data.week_id:
            continue
        for sw in w_data.get("swaps", []):
            if sw.get("swap_id") == data.swap_id:
                target_swap = sw
                target_week_entry = w_data
                break
        if target_swap:
            break

    if not target_swap or not target_week_entry:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu đổi ca này")

    if target_swap.get("status") != "PENDING":
        raise HTTPException(status_code=400, detail=f"Yêu cầu đổi ca này đã kết thúc với trạng thái: {target_swap.get('status')}")

    to_user = normalize_str(target_swap.get("to_user"))
    from_user = normalize_str(target_swap.get("from_user"))

    if caller != to_user and caller_role not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ người được đề xuất nhận ca hoặc Quản lý mới có quyền phản hồi yêu cầu này")

    staff_auth = load_staff_auth()
    accounts = staff_auth.get("staff_accounts", {})

    from_name = accounts.get(from_user, {}).get("full_name", from_user)
    to_name = accounts.get(to_user, {}).get("full_name", to_user)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if act == "REJECT":
        target_swap["status"] = "REJECTED"
        target_swap["resolved_at"] = now_str
        target_swap["resolved_by"] = caller
        save_roster_data(roster_data)

        try:
            from services.store_config import get_store_config
            _scfg = get_store_config()
            s_name = (_scfg.get("store_name") or "FnBOps").strip()
        except Exception:
            s_name = "FnBOps"

        send_telegram_alert(
            f"[TỪ CHỐI ĐỔI CA] {s_name}\n"
            f"Ngày: {target_swap.get('date')} ({target_swap.get('shift_period').upper()} - {target_swap.get('slot_type')})\n"
            f"Bạn {to_name} (@{to_user}) đã TỪ CHỐI nhận ca từ {from_name} (@{from_user}).\n"
            f"Trách nhiệm ca làm việc vẫn thuộc về {from_name}."
        )
        return {
            "success": True,
            "message": f"Đã từ chối nhận ca ngày {target_swap.get('date')}. Ca trực vẫn giữ nguyên cho {from_name}.",
            "swap": target_swap
        }

    # If ACCEPT:
    swap_date_str = target_swap.get("date")
    # Fix 1: Chống chấp nhận đổi ca quá khứ đối với nhân viên thường
    if swap_date_str:
        try:
            swap_date = datetime.datetime.strptime(swap_date_str, "%Y-%m-%d").date()
            if swap_date < datetime.date.today() and caller_role not in ["ADMIN", "MANAGER"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Không thể nhận đổi ca cho ngày đã qua trong quá khứ ({swap_date_str})."
                )
        except ValueError:
            pass

    shifts = target_week_entry.get("shifts", {})
    day_shift = shifts.get(swap_date_str)
    if not day_shift:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca ngày đã chọn trong lịch tuần")

    period = target_swap.get("shift_period").lower()
    slot = target_swap.get("slot_type").lower()

    # Concurrency verification: Ensure the slot is STILL held by from_user
    current_slot_user = None
    if period == "morning":
        m_chk = day_shift.get("morning", {})
        srv = m_chk.get("service", [None, None]) if isinstance(m_chk.get("service"), list) else [None, None]
        while len(srv) < 2:
            srv.append(None)
        if slot in ["service_1", "service"]:
            current_slot_user = srv[0]
        elif slot == "service_2":
            current_slot_user = srv[1]
        elif slot == "barista":
            current_slot_user = m_chk.get("barista")
    elif period == "evening":
        ev_chk = day_shift.get("evening", {})
        if slot == "service_17":
            current_slot_user = ev_chk.get("service_17")
        elif slot == "service_18":
            current_slot_user = ev_chk.get("service_18")
        elif slot == "barista":
            current_slot_user = ev_chk.get("barista")

    if current_slot_user != from_user:
        target_swap["status"] = "INVALIDATED"
        target_swap["resolved_at"] = now_str
        target_swap["resolved_by"] = "SYSTEM"
        save_roster_data(roster_data)
        raise HTTPException(
            status_code=409,
            detail=f"Ca trực này hiện không còn thuộc về {from_name} (hiện do {current_slot_user or 'Trống'} đảm nhận). Yêu cầu đổi ca đã hết hiệu lực."
        )

    date_str = target_swap.get("date")
    # Chống trùng ca: Kiểm tra to_user đã có ca trực nào trong ngày date_str chưa (Quy định: Tối đa 1 ca/ngày)
    m_staff = [day_shift.get("morning", {}).get("barista")] + (day_shift.get("morning", {}).get("service") or [])
    ev_staff = [day_shift.get("evening", {}).get("barista"), day_shift.get("evening", {}).get("service_17"), day_shift.get("evening", {}).get("service_18")]
    existing_day_staff = [s for s in m_staff + ev_staff if s]
    if to_user in existing_day_staff:
        to_name = accounts.get(to_user, {}).get("full_name", to_user)
        raise HTTPException(
            status_code=400,
            detail=f"Không thể nhận đổi ca: Nhân sự {to_name} đã có ca trực trong ngày {date_str} (Quy định: Tối đa 1 ca/ngày/nhân sự)."
        )

    if slot == "barista":
        to_pos = accounts.get(to_user, {}).get("position", "SERVICE").upper()
        if to_pos != "BARISTA":
            to_name = accounts.get(to_user, {}).get("full_name", to_user)
            raise HTTPException(
                status_code=400,
                detail=f"Không thể nhận đổi ca: Nhân sự {to_name} không có chuyên môn Pha chế (Barista)!"
            )

    if period == "morning":
        m = day_shift.get("morning", {})
        if not isinstance(m.get("service"), list):
            m["service"] = [None, None]
        while len(m["service"]) < 2:
            m["service"].append(None)

        if slot in ["service_1", "service"]:
            s2 = m["service"][1]
            valid, msg = validate_service_gender_pair(to_user, s2, accounts, shift_key="morning")
            if not valid:
                raise HTTPException(status_code=400, detail=msg)
            m["service"][0] = to_user
        elif slot == "service_2":
            s1 = m["service"][0]
            valid, msg = validate_service_gender_pair(s1, to_user, accounts, shift_key="morning")
            if not valid:
                raise HTTPException(status_code=400, detail=msg)
            m["service"][1] = to_user
        elif slot == "barista":
            m["barista"] = to_user

    elif period == "evening":
        ev = day_shift.get("evening", {})
        if slot == "service_17":
            s18 = ev.get("service_18")
            valid, msg = validate_service_gender_pair(to_user, s18, accounts, shift_key="evening")
            if not valid:
                raise HTTPException(status_code=400, detail=msg)
            ev["service_17"] = to_user
        elif slot == "service_18":
            s17 = ev.get("service_17")
            valid, msg = validate_service_gender_pair(s17, to_user, accounts, shift_key="evening")
            if not valid:
                raise HTTPException(status_code=400, detail=msg)
            ev["service_18"] = to_user
        elif slot == "barista":
            ev["barista"] = to_user

    target_swap["status"] = "ACCEPTED"
    target_swap["resolved_at"] = now_str
    target_swap["resolved_by"] = caller
    save_roster_data(roster_data)

    try:
        from services.store_config import get_store_config
        _scfg = get_store_config()
        s_name = (_scfg.get("store_name") or "FnBOps").strip()
    except Exception:
        s_name = "FnBOps"

    send_telegram_alert(
        f"[ĐỔI CA THÀNH CÔNG] {s_name}\n"
        f"Ngày: {target_swap.get('date')} ({period.upper()} - {slot})\n"
        f"Từ: {from_name} (@{from_user}) -> Đến: {to_name} (@{to_user})\n"
        f"Đã xác nhận chấp thuận bởi: {to_name} (@{to_user})"
    )

    return {
        "success": True,
        "message": f"Bạn {to_name} đã xác nhận đồng ý nhận ca ngày {target_swap.get('date')} thành công!",
        "swap": target_swap
    }


@router.get("/peer-swaps/pending")
def get_pending_peer_swaps(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    caller = normalize_str(user.get("sub"))
    caller_role = (user.get("role") or "").upper()

    roster_data = load_roster_data()
    pending = []
    for w_id, w_entry in roster_data.get("weeks", {}).items():
        for sw in w_entry.get("swaps", []):
            if sw.get("status") == "PENDING":
                to_u = normalize_str(sw.get("to_user"))
                from_u = normalize_str(sw.get("from_user"))
                if caller_role in ["ADMIN", "MANAGER"] or caller in [to_u, from_u]:
                    pending.append(sw)
    return {"pending_swaps": pending}


# --------------------------------------------------------------------------
# OPEN SHIFTS MARKETPLACE (CHỢ CA TRỐNG - STAFFJOY INSPIRED)
# --------------------------------------------------------------------------

def _derive_monday_week_key(date_str: str) -> str:
    try:
        dt = datetime.datetime.strptime(str(date_str).strip()[:10], "%Y-%m-%d").date()
        monday = dt - datetime.timedelta(days=dt.weekday())
        return monday.strftime("%Y-%m-%d")
    except Exception:
        active_info, _ = get_active_and_next_week_ids()
        return active_info["start_date"]


def _invoke_create_open_shift_db(
    week_key: str,
    date: str,
    shift_key: str,
    slot_type: str,
    role_required: str,
    note: str,
    created_by: str
):
    payload = {
        "week_key": week_key,
        "date": date,
        "shift_key": shift_key,
        "slot_type": slot_type,
        "role_required": role_required,
        "note": note,
        "created_by": created_by,
    }
    res = create_open_shift_db(payload)

    if isinstance(res, dict):
        return res
    # Nếu hàm DB trả về ID số nguyên, truy vấn lại bản ghi vừa tạo
    try:
        items = list_open_shifts_db(week_key=week_key)
        for it in items:
            if str(it.get("id")) == str(res):
                return it
    except Exception:
        pass
    return {
        "id": res,
        **payload,
        "status": "OPEN",
    }


@router.get("/open-shifts")
def get_open_shifts(
    request: Request,
    week_key: Optional[str] = None,
    status: Optional[str] = None
):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if (user.get("role") or "STAFF").upper() not in ["STAFF", "MANAGER", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    items = list_open_shifts_db(week_key=week_key, status=status)
    return {"success": True, "open_shifts": items}


@router.post("/open-shifts")
def create_open_shift(request: Request, data: CreateOpenShiftRequest):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    caller_role = (user.get("role") or "").upper()
    if caller_role not in ["MANAGER", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới được phép tạo ca trống trên Chợ Ca")

    raw_shift = (data.shift_key or "").strip().lower()
    if raw_shift in ["sang", "sáng", "morning"]:
        norm_shift_key = "sang"
    elif raw_shift in ["toi", "tối", "evening", "chieu", "chiều"]:
        norm_shift_key = "toi"
    else:
        norm_shift_key = raw_shift or "sang"

    week_key = (data.week_key or "").strip()
    if not week_key:
        week_key = _derive_monday_week_key(data.date)

    created = _invoke_create_open_shift_db(
        week_key=week_key,
        date=data.date.strip(),
        shift_key=norm_shift_key,
        slot_type=(data.slot_type or "service").strip(),
        role_required=(data.role_required or "SERVICE").strip().upper(),
        note=(data.note or "").strip(),
        created_by=normalize_str(user.get("sub") or "manager"),
    )

    return {
        "success": True,
        "message": "Đã phát thông báo ca trống lên Chợ Ca",
        "open_shift": created,
    }


@router.post("/open-shifts/{shift_id}/claim")
def claim_open_shift(shift_id: str, request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    uname = normalize_str(user.get("sub"))
    caller_role = (user.get("role") or "STAFF").upper()
    if caller_role not in ["STAFF", "MANAGER", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Không có quyền nhận ca")

    # 1. Kiểm tra ca trống có tồn tại và status == "OPEN" không
    all_shifts = list_open_shifts_db()
    target_shift = None
    for s in (all_shifts or []):
        if str(s.get("id")) == str(shift_id) or str(s.get("shift_id")) == str(shift_id):
            target_shift = s
            break

    if not target_shift:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca trống này")
    if str(target_shift.get("status") or "").upper() != "OPEN":
        raise HTTPException(status_code=400, detail="Ca trống này đã có người nhận hoặc không còn mở")

    # 2. Kiểm tra điều kiện vị trí (Role / Competency)
    staff_auth = load_staff_auth()
    accounts = staff_auth.get("staff_accounts", {})
    acc = accounts.get(uname, {})
    if not acc:
        for k, v in accounts.items():
            if normalize_str(k) == uname:
                acc = v
                break

    full_name = acc.get("full_name") or user.get("full_name") or user.get("name") or uname
    user_pos = str(acc.get("position") or user.get("position") or "SERVICE").strip().upper()
    user_role = str(acc.get("role") or caller_role or "STAFF").strip().upper()

    role_req = str(target_shift.get("role_required") or "SERVICE").strip().upper()
    if role_req in ["BAR", "BARISTA"]:
        has_bar_skill = (
            user_pos in ["BARISTA", "MANAGER", "BAR"]
            or user_role == "MANAGER"
            or is_bar_capable(acc)
        )
        if not has_bar_skill:
            raise HTTPException(status_code=400, detail="Ca này yêu cầu kỹ năng Pha chế (Barista)")

    # 3. Kiểm tra trùng ca trong roster_schedule.json
    shift_date = str(target_shift.get("date") or "").strip()
    shift_key_raw = str(target_shift.get("shift_key") or "sang").strip().lower()
    norm_shift_key = "sang" if shift_key_raw in ["sang", "sáng", "morning"] else "toi"
    period_key = "morning" if norm_shift_key == "sang" else "evening"
    slot_type = str(target_shift.get("slot_type") or "service").strip().lower()
    w_key = str(target_shift.get("week_key") or "").strip()

    computed_d_key = None
    iso_week_id = None
    monday_str = None
    try:
        dt_obj = datetime.datetime.strptime(shift_date[:10], "%Y-%m-%d").date()
        computed_d_key = DAY_KEYS_ISO[dt_obj.weekday()]
        iso_week_id = get_iso_week_info(dt_obj)["week_id"]
        monday_str = (dt_obj - datetime.timedelta(days=dt_obj.weekday())).strftime("%Y-%m-%d")
    except Exception:
        pass

    roster_data = load_roster_data()
    weeks = roster_data.setdefault("weeks", {})

    matched_week_entry = None
    for candidate_wk in [w_key, iso_week_id, monday_str]:
        if candidate_wk and candidate_wk in weeks:
            matched_week_entry = weeks[candidate_wk]
            break

    def _is_user_in_slot_val(val: Any) -> bool:
        if isinstance(val, list):
            for x in val:
                if x and (normalize_str(str(x)) == uname or str(x).strip().lower() == full_name.lower()):
                    return True
        elif isinstance(val, str) and val:
            if normalize_str(val) == uname or val.strip().lower() == full_name.lower():
                return True
        return False

    matched_day_obj_in_days = None
    if isinstance(matched_week_entry, dict):
        # Kiểm tra cấu trúc days[d_key][shift_key]
        days_map = matched_week_entry.get("days")
        if isinstance(days_map, dict):
            for dk, d_obj in days_map.items():
                if not isinstance(d_obj, dict):
                    continue
                if d_obj.get("date") == shift_date or dk == shift_date or (computed_d_key and dk == computed_d_key):
                    matched_day_obj_in_days = d_obj
                    s_obj = d_obj.get(norm_shift_key) or d_obj.get(period_key) or {}
                    if isinstance(s_obj, dict):
                        for chk_slot in ["barista", "service", "service_17", "service_18", "security"]:
                            if _is_user_in_slot_val(s_obj.get(chk_slot)):
                                raise HTTPException(status_code=400, detail="Bạn đã có lịch làm việc trong ca này rồi")
                    break

        # Kiểm tra cấu trúc shifts[date][period]
        shifts_map = matched_week_entry.get("shifts")
        if isinstance(shifts_map, dict) and shift_date in shifts_map:
            d_shifts_obj = shifts_map[shift_date]
            if isinstance(d_shifts_obj, dict):
                p_obj = d_shifts_obj.get(period_key) or d_shifts_obj.get(norm_shift_key) or {}
                if isinstance(p_obj, dict):
                    for chk_slot in ["barista", "service", "service_17", "service_18", "security"]:
                        if _is_user_in_slot_val(p_obj.get(chk_slot)):
                            raise HTTPException(status_code=400, detail="Bạn đã có lịch làm việc trong ca này rồi")

    # 4. Gọi claim_open_shift_db(shift_id, uname, full_name)
    db_shift_id: Any = int(shift_id) if str(shift_id).isdigit() else shift_id
    claimed = claim_open_shift_db(db_shift_id, uname, full_name)
    if not claimed:
        raise HTTPException(status_code=400, detail="Không thể nhận ca trống này (ca đã được nhận hoặc không hợp lệ)")

    if not isinstance(claimed, dict):
        # Truy vấn lại bản ghi sau khi claim nếu hàm DB trả về bool
        updated_list = list_open_shifts_db()
        claimed_obj = None
        for s in (updated_list or []):
            if str(s.get("id")) == str(shift_id) or str(s.get("shift_id")) == str(shift_id):
                claimed_obj = s
                break
        claimed = claimed_obj or {
            **target_shift,
            "status": "CLAIMED",
            "claimed_by": uname,
            "claimed_by_name": full_name,
        }

    # 5. Tự động điền nhân viên vừa nhận ca vào slot tương ứng trong roster_schedule.json
    if isinstance(matched_week_entry, dict):
        roster_modified = False
        target_slot_key = (
            slot_type
            if slot_type in ["barista", "service", "service_17", "service_18", "security"]
            else ("barista" if role_req in ["BAR", "BARISTA"] else "service")
        )

        if isinstance(matched_day_obj_in_days, dict):
            s_obj = matched_day_obj_in_days.setdefault(norm_shift_key, {})
            if isinstance(s_obj, dict):
                cur_val = s_obj.get(target_slot_key)
                if isinstance(cur_val, list):
                    if uname not in cur_val:
                        if None in cur_val:
                            cur_val[cur_val.index(None)] = uname
                        else:
                            cur_val.append(uname)
                elif cur_val is None:
                    s_obj[target_slot_key] = [uname]
                elif isinstance(cur_val, str):
                    s_obj[target_slot_key] = [cur_val, uname] if cur_val else [uname]
                roster_modified = True

        shifts_map = matched_week_entry.get("shifts")
        if isinstance(shifts_map, dict) and shift_date in shifts_map and isinstance(shifts_map[shift_date], dict):
            p_obj = shifts_map[shift_date].setdefault(period_key, {})
            if isinstance(p_obj, dict):
                if target_slot_key == "barista" or role_req in ["BAR", "BARISTA"]:
                    p_obj["barista"] = uname
                    p_obj["missing_barista"] = False
                elif period_key == "morning":
                    srv = p_obj.get("service")
                    if not isinstance(srv, list):
                        srv = [None, None]
                        p_obj["service"] = srv
                    if slot_type == "service_1" and len(srv) >= 1:
                        srv[0] = uname
                    elif slot_type == "service_2" and len(srv) >= 2:
                        srv[1] = uname
                    elif None in srv:
                        srv[srv.index(None)] = uname
                    elif uname not in srv:
                        srv.append(uname)
                else:
                    if slot_type == "service_17":
                        p_obj["service_17"] = uname
                    elif slot_type == "service_18":
                        p_obj["service_18"] = uname
                    elif not p_obj.get("service_17"):
                        p_obj["service_17"] = uname
                    elif not p_obj.get("service_18"):
                        p_obj["service_18"] = uname
                    else:
                        srv = p_obj.setdefault("service", [])
                        if isinstance(srv, list) and uname not in srv:
                            srv.append(uname)
                roster_modified = True

        if roster_modified:
            save_roster_data(roster_data)

    return {
        "success": True,
        "message": "Nhận ca thành công!",
        "open_shift": claimed,
    }


@router.delete("/open-shifts/{shift_id}")
def delete_open_shift(shift_id: str, request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    caller_role = (user.get("role") or "").upper()
    if caller_role not in ["MANAGER", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới được xóa ca trống")

    db_shift_id: Any = int(shift_id) if str(shift_id).isdigit() else shift_id
    deleted = delete_open_shift_db(db_shift_id)
    if deleted is False:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca trống để xóa")

    return {
        "success": True,
        "message": "Đã xóa ca trống thành công",
        "deleted_id": shift_id,
    }

