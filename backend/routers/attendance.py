# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Attendance & SOP Router for FnBOps Operations
Features:
1. POS Heartbeat -> Tracks cafe dynamic IP automatically.
2. Geofenced Check-in/Check-out via WiFi Public IP.
3. Shift Rules:
   - Ca Sang: 06:00 - 11:30 (Late after 06:10)
   - Ca Toi: 17:00 - 23:00 (Late after 17:10) or 18:00 - 23:00 (Late after 18:10)
4. Auto-close after 48h unclosed:
   - Ca Sang closes at 11:00
   - Ca Toi closes at 22:00 (Penalty minimum)
5. Role-based SOP Checklist (Read-only, 5 roles, 3 phases).
"""

import os
import sys
import json
import threading
import ipaddress
import inspect
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException, Header, Query, Depends
from pydantic import BaseModel

from services.storage import safe_json_write, safe_json_read, verify_pin
from services.db import (
    check_api_rate_limit,
    record_access_audit,
    create_attendance_request_db,
    list_attendance_requests_db,
    get_attendance_request_by_id_db,
    review_attendance_request_db,
    resolve_employee_id,
    get_store_setting_db,
    get_db_connection,
)
from services.attendance_service import (
    get_current_cafe_ip,
    set_current_cafe_ip,
    load_attendance_logs,
    save_attendance_logs,
    sync_latest_log_to_sqlite,
    calculate_shift_duration_minutes,
    get_staff_roster_slot,
    auto_close_hanging_shifts_logic,
    HEARTBEAT_FILE,
    LOGS_FILE,
    _logs_lock,
)
from services.auth import (
    get_current_user,
    load_staff_auth,
    normalize_str,
)
from services.roster_service import load_roster_data
from services.send_telegram import send_telegram_alert

router = APIRouter(prefix="/api/v1/cc/attendance", tags=["Attendance & SOP"])

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_DIR = os.path.dirname(_BASE_DIR)

# Single unified data directory at project root or /app/data in Docker
if os.getenv("DATA_DIR"):
    DATA_DIR = os.getenv("DATA_DIR")
elif _PROJECT_DIR and _PROJECT_DIR != "/" and os.path.exists(os.path.join(_PROJECT_DIR, "data")):
    DATA_DIR = os.path.join(_PROJECT_DIR, "data")
else:
    DATA_DIR = os.path.join(_BASE_DIR, "data")

try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = os.path.join(_BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)

HEARTBEAT_FILE = os.path.join(DATA_DIR, "pos_heartbeat.json")
LOGS_FILE = os.path.join(DATA_DIR, "attendance_logs.json")
SOP_FILE = os.path.join(DATA_DIR, "sop_templates.json")

# In-memory cached cafe IP
_cached_cafe_ip = os.getenv("STORE_WIFI_IP", "127.0.0.1")
_DEFAULT_TEST_POS_SECRET = "ci_test_super_secure_pos_secret_key_32_characters_long"
POS_SECRET = (
    os.getenv("POS_SECRET")
    or os.getenv("WFM_POS_SECRET")
    or os.getenv("FNBOP_POS_SECRET")
    or (_DEFAULT_TEST_POS_SECRET if os.getenv("TESTING") == "1" else "")
)

# ----------------- Helper Functions -----------------

TRUSTED_PROXIES = {"127.0.0.1", "::1", "localhost", "testclient"}

def is_trusted_proxy(host: str) -> bool:
    if host in TRUSTED_PROXIES:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return False

def get_client_ip(request: Request) -> str:
    """
    Extract real client IP considering Cloudflare and reverse proxies.
    Hardened against header spoofing:
    - Never trust or inspect 'x-forwarded-for' (prevents Postman/Curl spoofing).
    - If direct connection comes from outside trusted proxy, strictly return direct_host.
    - If behind Cloudflare (has 'cf-connecting-ip'), return 'cf-connecting-ip'.
    - If behind trusted proxy with 'x-real-ip', return 'x-real-ip'.
    - In local dev/test environment, returns direct_host.
    """
    direct_host = request.client.host if request.client else "127.0.0.1"
    if not is_trusted_proxy(direct_host):
        return direct_host

    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()

    return direct_host


ON_PREMISE_MODE = os.getenv("ON_PREMISE_MODE", "false").lower() in ("true", "1")

from services.attendance_service import (
    is_lan_or_local_ip,
    is_matching_cafe_wifi,
)


def verify_manager_or_admin(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Verify that the request comes from an authenticated MANAGER or ADMIN."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, 
            detail="Yêu cầu đăng nhập tài khoản Quản lý hoặc Admin để truy cập."
        )
    token = authorization.split(" ")[1].strip()
    try:
        payload = get_current_user(token)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Xác thực thất bại: {e}")

    role = (payload.get("role") or "").upper()
    if role not in ["MANAGER", "ADMIN"]:
        raise HTTPException(
            status_code=403, 
            detail="Bạn không có quyền thực hiện thao tác này. Chỉ dành cho Quản lý / Admin."
        )
    return payload


from services.attendance_service import detect_current_shift


# ----------------- Request Models -----------------
from models.attendance import (
    HeartbeatPayload,
    CheckinPayload,
    CheckoutPayload,
    ManualClosePayload,
    ShiftActionPayload,
    ReviewHangingShiftPayload,
    AttendanceRequestCreate,
    AttendanceRequestReview,
)


class HeartbeatPayloadWithTimestamp(HeartbeatPayload):
    timestamp: Optional[Any] = None


def _validate_heartbeat_timestamp(ts_val: Any, max_skew_seconds: int = 120) -> None:
    """
    Replay Attack Shield:
    Kiểm tra độ lệch timestamp của gói tin POS Heartbeat so với giờ server.
    Nếu lệch quá max_skew_seconds (mặc định 120s), từ chối để chống tấn công replay.
    """
    import time
    now_ts = time.time()
    parsed_ts = None
    if isinstance(ts_val, (int, float)):
        parsed_ts = float(ts_val)
        if parsed_ts > 1e11:  # Milliseconds
            parsed_ts /= 1000.0
    elif isinstance(ts_val, str):
        ts_str = ts_val.strip()
        try:
            val = float(ts_str)
            parsed_ts = val / 1000.0 if val > 1e11 else val
        except ValueError:
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                parsed_ts = dt.timestamp()
            except Exception:
                try:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                    parsed_ts = dt.timestamp()
                except Exception:
                    raise HTTPException(
                        status_code=400,
                        detail="Định dạng timestamp không hợp lệ."
                    )
    if parsed_ts is not None:
        skew = abs(now_ts - parsed_ts)
        if skew > max_skew_seconds:
            raise HTTPException(
                status_code=400,
                detail=f"Gói tin heartbeat bị từ chối do lệch thời gian {int(skew)}s quá {max_skew_seconds}s (Replay Attack Shield)."
            )


# ----------------- API Endpoints -----------------

@router.post("/pos/heartbeat")
def pos_heartbeat(
    request: Request, 
    payload: Optional[HeartbeatPayloadWithTimestamp] = None,
    x_pos_secret: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None)
):
    """
    Heartbeat ping from POS Windows machine (via Task Scheduler).
    Records cafe Public IP to keep geofence updated even with dynamic PPPoE.
    Includes Replay Attack Shield (timestamp validation within 120s).
    """
    secret = x_pos_secret or (payload.pos_secret if payload else None)
    configured_secret = (
        os.getenv("POS_SECRET")
        or os.getenv("WFM_POS_SECRET")
        or os.getenv("FNBOP_POS_SECRET")
        or POS_SECRET
        or (_DEFAULT_TEST_POS_SECRET if os.getenv("TESTING") == "1" else "")
    )
    is_valid_secret = bool(secret and configured_secret and secret == configured_secret)
    if not is_valid_secret:
        raise HTTPException(status_code=403, detail="Invalid POS Secret")

    # Replay Attack Shield: Validate timestamp skew <= 120s
    req_timestamp = None
    if payload and getattr(payload, "timestamp", None) is not None:
        req_timestamp = payload.timestamp
    elif x_timestamp:
        req_timestamp = x_timestamp

    if req_timestamp is not None:
        _validate_heartbeat_timestamp(req_timestamp, max_skew_seconds=120)
    
    # Secure geofence: Only allow override_ip from localhost/test; otherwise strictly use detected client_ip
    client_ip = get_client_ip(request)
    is_local = client_ip in ["127.0.0.1", "localhost", "::1", "testclient"] or (request.client and request.client.host in ["127.0.0.1", "::1", "testclient"])
    if is_local and payload and payload.override_ip:
        ip = payload.override_ip
    else:
        ip = client_ip

    set_current_cafe_ip(ip)
    
    return {
        "status": "success",
        "cafe_ip": ip,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


@router.get("/status")
def get_attendance_status(
    request: Request,
    username: Optional[str] = None,
    dev_mode: Optional[bool] = Query(False),
    simulated_time: Optional[str] = Query(None)
):
    """Check current connection status, active shift, and staff check-in record."""
    client_ip = get_client_ip(request)
    cafe_ip = get_current_cafe_ip()
    
    # Match wifi if client_ip matches cafe_ip exactly, or running localhost in dev mode, or emergency remote check-in enabled
    is_local = client_ip in ["127.0.0.1", "localhost", "::1"]
    is_emergency_remote = (get_store_setting_db("emergency_remote_checkin", "0") == "1")
    is_cafe_wifi = is_matching_cafe_wifi(client_ip, cafe_ip) or (is_local and dev_mode) or is_emergency_remote
    
    now = datetime.now()
    if dev_mode and simulated_time:
        try:
            parts = simulated_time.split(":")
            now = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0)
        except Exception:
            pass

    active_shift = detect_current_shift(now, username=username)
    upcoming_shift = None
    if active_shift is None and username:
        try:
            cur_t = now.time()
            shifts_cfg = {}
            try:
                from services.store_config import get_store_config
                cfg = get_store_config()
                shifts_cfg = cfg.get("shifts", {})
            except Exception:
                shifts_cfg = {}

            # Duyệt các ca và tìm ca kế tiếp gần nhất có giờ bắt đầu > cur_t
            sorted_shifts = []
            for sk, sd in shifts_cfg.items():
                ostart = sd.get("official_start", "00:00")
                sorted_shifts.append((ostart, sk, sd))
            sorted_shifts.sort(key=lambda x: x[0])

            for ostart, sk, sd in sorted_shifts:
                try:
                    t_start = datetime.strptime(ostart, "%H:%M").time()
                    if cur_t < t_start:
                        slot_info = get_staff_roster_slot(username, now.date(), sk)
                        upcoming_shift = {
                            "key": sk,
                            "name": sd.get("name", "Ca Làm"),
                            "official_start": slot_info.get("official_start", ostart) if slot_info else ostart,
                            "official_end": slot_info.get("official_end", sd.get("official_end", "11:30")) if slot_info else sd.get("official_end", "11:30"),
                            "tolerance_limit": slot_info.get("tolerance_limit", sd.get("tolerance_limit", "06:10")) if slot_info else sd.get("tolerance_limit", "06:10"),
                            "slot_type": slot_info.get("slot_type") if slot_info else None
                        }
                        break
                except Exception:
                    pass

            # Fallback FnBOps nếu chưa cấu hình dynamic
            if not upcoming_shift and not shifts_cfg:
                t_morn_start = datetime.strptime("05:55", "%H:%M").time()
                t_eve_start = datetime.strptime("16:30", "%H:%M").time()
                if cur_t < t_morn_start:
                    slot_info = get_staff_roster_slot(username, now.date(), "sang")
                    if slot_info:
                        upcoming_shift = {
                            "key": "sang",
                            "name": "Ca Sáng",
                            "official_start": slot_info.get("official_start", "06:00"),
                            "official_end": slot_info.get("official_end", "11:30"),
                            "tolerance_limit": slot_info.get("tolerance_limit", "06:10"),
                            "slot_type": slot_info.get("slot_type")
                        }
                elif cur_t < t_eve_start:
                    slot_info = get_staff_roster_slot(username, now.date(), "toi")
                    if slot_info:
                        upcoming_shift = {
                            "key": "toi",
                            "name": "Ca Tối",
                            "official_start": slot_info.get("official_start", "17:00"),
                            "official_end": slot_info.get("official_end", "23:00"),
                            "tolerance_limit": slot_info.get("tolerance_limit", "17:10"),
                            "slot_type": slot_info.get("slot_type")
                        }
        except Exception:
            pass

    today_str = now.strftime("%d/%m/%Y")
    
    active_record = None
    last_closed_record = None
    if username:
        with _logs_lock:
            logs = load_attendance_logs()
            updated_any = False

            # Quét kiểm tra xem username có log nào bị quên checkout quá 180 phút không
            try:
                from services.store_config import get_store_config, get_auto_close_cutoff_minutes
                s_cfg = get_store_config()
                s_shifts = s_cfg.get("shifts", {})
                s_cutoff = get_auto_close_cutoff_minutes(s_cfg)
            except Exception:
                s_shifts = {}
                s_cutoff = 180

            for log in logs:
                if log.get("username") == username and log.get("checkout_time") is None:
                    ld_str = log.get("date")
                    sh_key = log.get("shift_key", "sang")
                    s_inf = s_shifts.get(sh_key, {})
                    off_end = s_inf.get("official_end") or ("11:30" if sh_key == "sang" else "23:00")
                    created_at_str = log.get("created_at")
                    should_close = False
                    
                    # 1. Nếu là ca của ngày hôm trước (quên checkout từ hôm qua)
                    if ld_str and ld_str != today_str:
                        should_close = True
                    # 2. Nếu là ca hôm nay, chỉ tự động đóng khi vừa quá giờ tan ca + cutoff VÀ bản ghi đã tồn tại >= cutoff phút
                    elif ld_str == today_str and created_at_str:
                        try:
                            dt_created = datetime.fromisoformat(created_at_str)
                            age_mins = (now - dt_created).total_seconds() / 60
                            d_date = datetime.strptime(ld_str, "%d/%m/%Y").date()
                            e_time = datetime.strptime(off_end, "%H:%M").time()
                            c_dt = datetime.combine(d_date, e_time) + timedelta(minutes=s_cutoff)
                            if now >= c_dt and age_mins >= s_cutoff:
                                should_close = True
                        except Exception:
                            pass
                    elif created_at_str:
                        try:
                            if (now - datetime.fromisoformat(created_at_str)).total_seconds() / 3600 >= 24:
                                should_close = True
                        except Exception:
                            pass

                    if should_close:
                        c_target = s_inf.get("min_checkout") or ("11:00" if sh_key == "sang" else "22:00")
                        dm = calculate_shift_duration_minutes(
                            log.get("date", today_str),
                            log.get("checkin_time", "06:00"),
                            c_target
                        )
                        log["checkout_time"] = c_target
                        log["total_mins"] = dm
                        log["closed_by"] = f"AUTO_CLOSE_{s_cutoff}M"
                        log["auto_closed"] = True
                        log["forgot_checkout"] = True
                        log["updated_at"] = now.isoformat()
                        log["note"] = f"Hệ thống tự động chốt ca sau {s_cutoff} phút quá giờ tan ca ({off_end}) do quên check-out."
                        updated_any = True

            if updated_any:
                save_attendance_logs(logs)

            for log in reversed(logs):
                if log.get("username") == username and log.get("date") == today_str:
                    if log.get("checkout_time") is None and active_record is None:
                        active_record = log
                    elif log.get("checkout_time") is not None and last_closed_record is None:
                        last_closed_record = log

    shift_state = "READY_TO_CHECKIN"
    if active_record:
        shift_state = "IN_PROGRESS"
    elif last_closed_record and active_shift and last_closed_record.get("shift_key") == active_shift.get("key"):
        shift_state = "COMPLETED"
    elif active_shift is None:
        shift_state = "OUTSIDE_SHIFT_HOURS"

    return {
        "client_ip": client_ip,
        "cafe_ip": cafe_ip,
        "is_cafe_wifi": is_cafe_wifi,
        "is_emergency_remote": is_emergency_remote,
        "is_matching_cafe_wifi": is_matching_cafe_wifi(client_ip, cafe_ip),
        "is_local": is_local,
        "current_time": now.strftime("%H:%M:%S"),
        "today": today_str,
        "active_shift": active_shift,
        "upcoming_shift": upcoming_shift,
        "shift_state": shift_state,
        "user_record": active_record,
        "last_closed_record": last_closed_record
    }


@router.post("/dev/reset-logs")
def reset_attendance_logs(request: Request, username: Optional[str] = None):
    """Developer helper to reset attendance logs. Strictly requires Admin token."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Yêu cầu xác thực tài khoản Quản trị viên để thực hiện thao tác này.")
    
    try:
        user = get_current_user(auth_header.split(" ")[1])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token không hợp lệ: {e}")

    if (user.get("role") or "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Chức năng này chỉ khả dụng cho Quản trị viên (ADMIN).")

    with _logs_lock:
        if username:
            logs = load_attendance_logs()
            logs = [l for l in logs if l.get("username") != username]
            save_attendance_logs(logs)
            return {"status": "success", "message": f"Đã xóa dữ liệu ca của {username}"}
        save_attendance_logs([])
        return {"status": "success", "message": "Đã làm mới toàn bộ dữ liệu chấm công."}


def enforce_attendance_rate_limit(request: Request, username: Optional[str] = None, limit: int = 15, window_seconds: int = 60, prefix: str = "att"):
    client_ip = get_client_ip(request)
    uname = (username or "").strip().lower()
    key = f"{prefix}:{uname}" if uname else f"{prefix}:{client_ip}"
    allowed, count, retry_after = check_api_rate_limit(key, limit=limit, window_seconds=window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Thao tác chấm công quá nhanh. Vui lòng thử lại sau {int(retry_after)} giây.",
            headers={"Retry-After": str(int(retry_after))}
        )


@router.post("/checkin")
def checkin_attendance(request: Request, payload: CheckinPayload):
    """Perform staff check-in with WiFi validation and late threshold calculation."""
    enforce_attendance_rate_limit(request, username=payload.username, limit=15, window_seconds=60, prefix="checkin")
    client_ip = get_client_ip(request)
    cafe_ip = get_current_cafe_ip()
    
    is_local = client_ip in ["127.0.0.1", "localhost", "::1"]
    can_override = False
    if is_local and payload.dev_override_wifi:
        can_override = True
    elif payload.dev_override_wifi:
        auth_header = request.headers.get("authorization", "")
        if auth_header and auth_header.startswith("Bearer "):
            try:
                verify_manager_or_admin(auth_header)
                can_override = True
            except Exception:
                can_override = False

    is_emergency_remote = (get_store_setting_db("emergency_remote_checkin", "0") == "1")
    is_cafe_wifi = is_matching_cafe_wifi(client_ip, cafe_ip) or can_override or is_emergency_remote
    
    if not is_cafe_wifi:
        record_access_audit(
            payload.username, payload.display_name or payload.username, "ATTENDANCE_BLOCKED_WIFI",
            client_ip=client_ip, is_cafe_wifi=False, user_agent=request.headers.get("user-agent"),
            details=f"Cố chấm công vào ca ngoài quán (IP {client_ip})"
        )
        try:
            from services.store_config import get_store_config
            _scfg = get_store_config()
            _sname = (_scfg.get("store_name") or "Quán").strip()
            _wname = (_scfg.get("wifi_ssid") or "WiFi Quán").strip()
        except Exception:
            _sname = "Quán"
            _wname = "WiFi Quán"
        raise HTTPException(
            status_code=403, 
            detail=f"Vui lòng kết nối WiFi {_wname} ({_sname}) để chấm công. IP hiện tại: {client_ip}"
        )
    
    # Verify staff active status
    auth_data = load_staff_auth()
    staff_accs = auth_data.get("staff_accounts", {})
    u_req = normalize_str(payload.username)

    # Dual-Validation: Verify caller identity
    auth_header = request.headers.get("authorization", "")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Yêu cầu đăng nhập xác thực danh tính để chấm công."
        )

    try:
        token_payload = get_current_user(auth_header.split(" ")[1])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Phiên đăng nhập không hợp lệ: {e}")

    caller_sub = normalize_str(token_payload.get("sub", ""))
    caller_role = (token_payload.get("role") or "").upper()
    if caller_role not in ["ADMIN", "MANAGER"] and caller_sub != u_req:
        raise HTTPException(
            status_code=403,
            detail=f"Bạn không thể chấm công thay cho tài khoản '{payload.username}'."
        )

    acc = staff_accs.get(payload.username) or staff_accs.get(u_req)
    if not acc:
        for k, a in staff_accs.items():
            if payload.username.lower() == k.lower() or u_req == normalize_str(k) or u_req in [normalize_str(al) for al in a.get("aliases", [])]:
                acc = a
                break
    if acc and acc.get("status", "ACTIVE").strip().upper() == "INACTIVE":
        raise HTTPException(
            status_code=403,
            detail="Tài khoản này đã bị khóa hoặc nhân viên đã nghỉ việc. Không thể chấm công."
        )

    now = datetime.now()
    today_str = now.strftime("%d/%m/%Y")
    
    is_admin_or_mgr = caller_role in ["ADMIN", "MANAGER"]
    is_testclient = bool(request.client and request.client.host == "testclient")
    allow_custom_time = is_admin_or_mgr or is_testclient
    # Support custom time injection for simulation testing (strictly restricted to ADMIN / MANAGER or testclient)
    if payload.custom_time_str and allow_custom_time:
        try:
            parts = payload.custom_time_str.split(":")
            now = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
        except Exception:
            pass

    shift = detect_current_shift(now, username=payload.username)
    shifts_cfg = {}
    try:
        from services.store_config import get_store_config
        shifts_cfg = get_store_config().get("shifts", {})
    except Exception:
        shifts_cfg = {}

    if not shift and not (payload.dev_override_wifi or payload.shift_override):
        shifts_desc = []
        for sk, sd in shifts_cfg.items():
            s_name = sd.get("name", sk)
            ws = sd.get("window", {}).get("start") or sd.get("official_start", "")
            we = sd.get("window", {}).get("end") or sd.get("official_end", "")
            if ws and we:
                shifts_desc.append(f"{s_name} {ws} - {we}")
            else:
                shifts_desc.append(s_name)
        desc_str = "; ".join(shifts_desc) if shifts_desc else "Ca Sáng 05:55 - 13:00; Ca Tối 16:30 - 23:59"
        raise HTTPException(
            status_code=400,
            detail=f"Hiện đang ngoài khung giờ ca trực. Giờ mở nhận chấm công: {desc_str}."
        )

    shift_key = payload.shift_override or (shift["key"] if shift else "sang")
    shift_name = shift["name"] if shift else (shifts_cfg.get(shift_key, {}).get("name", "Ca Sáng" if shift_key == "sang" else "Ca Tối"))
    
    # Calculate Late Flag
    time_str = now.strftime("%H:%M")
    is_late = False
    late_mins = 0
    
    s_cfg_entry = shifts_cfg.get(shift_key, {})
    start_str = shift.get("official_start") if shift else s_cfg_entry.get("official_start", "06:00" if shift_key == "sang" else "17:00")
    limit_str = shift.get("tolerance_limit") if shift else s_cfg_entry.get("tolerance_limit")
    if not limit_str:
        try:
            limit_str = (datetime.strptime(start_str, "%H:%M") + timedelta(minutes=10)).strftime("%H:%M")
        except Exception:
            limit_str = "06:10" if shift_key == "sang" else "17:10"

    slot_type = shift.get("slot_type") if shift else None
    scheduled_end = shift.get("official_end") if shift else s_cfg_entry.get("official_end", "11:30" if shift_key == "sang" else "23:00")
    
    today_date = now.date()
    try:
        roster_slot_info = get_staff_roster_slot(payload.username, today_date, shift_key)
        if roster_slot_info:
            slot_type = roster_slot_info.get("slot_type", slot_type)
            start_str = roster_slot_info.get("official_start", start_str)
            limit_str = roster_slot_info.get("tolerance_limit", limit_str)
            scheduled_end = roster_slot_info.get("standard_checkout", scheduled_end)
    except Exception as e:
        print(f"Warning: Failed to fetch roster slot for {payload.username}: {e}")
    
    dt_limit = datetime.strptime(f"{today_date} {limit_str}:59", "%Y-%m-%d %H:%M:%S")
    dt_start = datetime.strptime(f"{today_date} {start_str}", "%Y-%m-%d %H:%M")
    
    if now > dt_limit:
        is_late = True
        diff = (now - dt_start).total_seconds() / 60
        late_mins = int(max(0, diff))

    with _logs_lock:
        logs = load_attendance_logs()
        
        # Check if already checked in and currently in progress
        for log in logs:
            if (log.get("username") == payload.username and 
                log.get("date") == today_str and 
                log.get("shift_key") == shift_key and 
                log.get("checkout_time") is None):
                return {
                    "status": "already_checked_in",
                    "message": f"Bạn đang trong ca trực ({shift_name}, vào lúc {log.get('checkin_time')}).",
                    "record": log
                }

        # Check if already completed this shift today (prevent duplicate punch-in)
        for log in logs:
            if (log.get("username") == payload.username and 
                log.get("date") == today_str and 
                log.get("shift_key") == shift_key and 
                log.get("checkout_time") is not None and
                not payload.dev_override_wifi):
                raise HTTPException(
                    status_code=400,
                    detail=f"Bạn đã hoàn thành {shift_name} hôm nay (Ra lúc {log.get('checkout_time')}). Ca đã đóng."
                )

        # Auto-resolve prior unclosed shift from earlier today or previous days (Orphan Shift Prevention)
        for log in logs:
            if (log.get("username") == payload.username and 
                log.get("checkout_time") is None):
                prev_shift_key = log.get("shift_key", "sang")
                prev_std_end = log.get("scheduled_end") or ("11:30" if prev_shift_key == "sang" else "23:00")
                prev_diff_mins = calculate_shift_duration_minutes(
                    log.get("date", today_str),
                    log.get("checkin_time", "06:00"),
                    prev_std_end
                )
                log["checkout_time"] = prev_std_end
                log["total_mins"] = prev_diff_mins
                log["closed_by"] = "AUTO_RESOLVE_NEXT_SHIFT"
                log["updated_at"] = now.isoformat()
                log["note"] = f"Tự động chốt giờ ra ({prev_std_end}) do nhân viên vào ca mới ({shift_name})."

        record_id = f"ATT_{now.strftime('%Y%m%d%H%M%S')}_{payload.username}"
        hourly_rate_snapshot = int(acc.get("hourly_rate", 17000)) if acc else 17000
        new_record = {
            "id": record_id,
            "username": payload.username,
            "display_name": payload.display_name or payload.username,
            "role": payload.role or "Phục vụ",
            "date": today_str,
            "shift_key": shift_key,
            "shift_name": shift_name,
            "roster_slot": slot_type,
            "scheduled_start": start_str,
            "scheduled_end": scheduled_end,
            "checkin_time": time_str,
            "checkout_time": None,
            "total_mins": None,
            "effective_duration_mins": None,
            "hourly_rate_snapshot": hourly_rate_snapshot,
            "is_hanging_pending": False,
            "is_late": is_late,
            "late_mins": late_mins,
            "status": "LATE" if is_late else "ON_TIME",
            "client_ip": client_ip,
            "created_at": now.isoformat(),
            "closed_by": None
        }
        
        logs.append(new_record)
        save_attendance_logs(logs)
        
        record_access_audit(
            payload.username, payload.display_name or payload.username, "ATTENDANCE_CHECKIN",
            client_ip=client_ip, is_cafe_wifi=True, user_agent=request.headers.get("user-agent"),
            details=f"Check-in {shift_name} lúc {time_str}" + (f" (Trễ {late_mins} phút)" if is_late else "")
        )

        return {
            "status": "success",
            "message": f"Check-in {shift_name} thành công lúc {time_str}!" + (f" (Trễ {late_mins} phút)" if is_late else ""),
            "record": new_record
        }


@router.post("/checkout")
def checkout_attendance(request: Request, payload: CheckoutPayload):
    """Perform staff check-out and compute total working minutes."""
    enforce_attendance_rate_limit(request, username=payload.username, limit=15, window_seconds=60, prefix="checkout")
    client_ip = get_client_ip(request)
    cafe_ip = get_current_cafe_ip()
    
    is_local = client_ip in ["127.0.0.1", "localhost", "::1"]
    can_override = False
    if is_local and payload.dev_override_wifi:
        can_override = True
    elif payload.dev_override_wifi:
        auth_header = request.headers.get("authorization", "")
        if auth_header and auth_header.startswith("Bearer "):
            try:
                verify_manager_or_admin(auth_header)
                can_override = True
            except Exception:
                can_override = False

    is_emergency_remote = (get_store_setting_db("emergency_remote_checkin", "0") == "1")
    is_cafe_wifi = is_matching_cafe_wifi(client_ip, cafe_ip) or can_override or is_emergency_remote
    
    if not is_cafe_wifi:
        record_access_audit(
            payload.username, payload.username, "ATTENDANCE_BLOCKED_WIFI",
            client_ip=client_ip, is_cafe_wifi=False, user_agent=request.headers.get("user-agent"),
            details=f"Cố chấm công ra về ngoài quán (IP {client_ip})"
        )
        try:
            from services.store_config import get_store_config
            _scfg = get_store_config()
            _sname = (_scfg.get("store_name") or "Quán").strip()
            _wname = (_scfg.get("wifi_ssid") or "WiFi Quán").strip()
        except Exception:
            _sname = "Quán"
            _wname = "WiFi Quán"
        raise HTTPException(
            status_code=403, 
            detail=f"Vui lòng kết nối WiFi {_wname} ({_sname}) để check-out. IP hiện tại: {client_ip}"
        )
    
    # Verify staff active status
    auth_data = load_staff_auth()
    staff_accs = auth_data.get("staff_accounts", {})
    u_req = normalize_str(payload.username)

    # Dual-Validation: Verify caller identity
    auth_header = request.headers.get("authorization", "")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Yêu cầu đăng nhập xác thực danh tính để check-out."
        )

    try:
        token_payload = get_current_user(auth_header.split(" ")[1])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Phiên đăng nhập không hợp lệ: {e}")

    caller_sub = normalize_str(token_payload.get("sub", ""))
    caller_role = (token_payload.get("role") or "").upper()
    if caller_role not in ["ADMIN", "MANAGER"] and caller_sub != u_req:
        raise HTTPException(
            status_code=403,
            detail=f"Bạn không thể check-out thay cho tài khoản '{payload.username}'."
        )

    acc = staff_accs.get(payload.username) or staff_accs.get(u_req)
    if not acc:
        for k, a in staff_accs.items():
            if payload.username.lower() == k.lower() or u_req == normalize_str(k) or u_req in [normalize_str(al) for al in a.get("aliases", [])]:
                acc = a
                break
    if acc and acc.get("status", "ACTIVE").strip().upper() == "INACTIVE":
        raise HTTPException(
            status_code=403,
            detail="Tài khoản này đã bị khóa hoặc nhân viên đã nghỉ việc. Không thể thao tác check-out."
        )

    now = datetime.now()
    is_admin_or_mgr = caller_role in ["ADMIN", "MANAGER"]
    is_testclient = bool(request.client and request.client.host == "testclient")
    allow_custom_time = is_admin_or_mgr or is_testclient
    if payload.custom_time_str and allow_custom_time:
        try:
            parts = payload.custom_time_str.split(":")
            now = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
        except Exception:
            pass

    time_str = now.strftime("%H:%M")
    with _logs_lock:
        logs = load_attendance_logs()
        
        # Find active check-in record for this user
        target_record = None
        for log in reversed(logs):
            if log.get("username") == payload.username and log.get("checkout_time") is None:
                target_record = log
                break
                
        if not target_record:
            raise HTTPException(status_code=400, detail="Không tìm thấy lượt Check-in nào đang mở để Check-out.")

        # Calculate total minutes
        checkin_str = target_record.get("checkin_time")
        try:
            dt_in = datetime.strptime(f"{target_record.get('date')} {checkin_str}", "%d/%m/%Y %H:%M")
            dt_out = datetime.strptime(f"{now.strftime('%d/%m/%Y')} {time_str}", "%d/%m/%Y %H:%M")
            if dt_out < dt_in:
                dt_out += timedelta(days=1)
            diff_mins = int((dt_out - dt_in).total_seconds() / 60)
            if diff_mins < 0:
                diff_mins = 0
        except Exception:
            diff_mins = 0

        # Safeguard: If shift was forgotten from previous days (> 9 hours / 540 mins)
        if diff_mins > 540:
            shift_key = target_record.get("shift_key", "sang")
            standard_checkout = target_record.get("scheduled_end") or ("11:30" if shift_key == "sang" else "23:00")
            diff_mins = calculate_shift_duration_minutes(
                target_record.get("date"),
                checkin_str,
                standard_checkout
            )
            time_str = standard_checkout
            target_record["is_hanging_pending"] = True
            target_record["status"] = "QUEN_CHECKOUT"
            target_record["note"] = "Ca quên check-out quá 9 tiếng. Chuyển sang trạng thái QUEN_CHECKOUT chờ Quản lý duyệt."

        # Early checkout guard (< 60 minutes)
        if diff_mins < 60 and not payload.confirm_early and not payload.dev_override_wifi:
            raise HTTPException(
                status_code=400,
                detail=f"Ca trực mới diễn ra {diff_mins} phút (dưới 60 phút). Vui lòng xác nhận kết thúc ca sớm."
            )

        # Clamping Window calculation:
        sched_start = target_record.get("scheduled_start")
        sched_end = target_record.get("scheduled_end")
        effective_mins = diff_mins

        if sched_start and sched_end and not target_record.get("is_hanging_pending"):
            try:
                # Clamp early arrival (effective_in = max(actual_in, scheduled_in)) unless manager approved early OT
                d_in_actual = datetime.strptime(f"{target_record.get('date')} {checkin_str}", "%d/%m/%Y %H:%M")
                d_in_sched = datetime.strptime(f"{target_record.get('date')} {sched_start}", "%d/%m/%Y %H:%M")
                effective_in = max(d_in_actual, d_in_sched)
                
                # Clamp late exit (effective_out = min(actual_out, scheduled_out + 15 mins)) unless manager approved OT
                d_out_actual = datetime.strptime(f"{now.strftime('%d/%m/%Y')} {time_str}", "%d/%m/%Y %H:%M")
                d_out_sched = datetime.strptime(f"{target_record.get('date')} {sched_end}", "%d/%m/%Y %H:%M")
                if d_out_sched < d_in_sched:
                    d_out_sched += timedelta(days=1)
                
                # 15 minutes grace buffer for wrapping up shift
                max_allowed_out = d_out_sched + timedelta(minutes=15)
                effective_out = min(d_out_actual, max_allowed_out)
                
                clamped = int((effective_out - effective_in).total_seconds() / 60)
                if clamped > 0:
                    effective_mins = clamped
            except Exception:
                effective_mins = diff_mins

        if target_record.get("is_hanging_pending"):
            effective_mins = 0

        target_record["checkout_time"] = time_str
        target_record["total_mins"] = diff_mins
        target_record["effective_duration_mins"] = effective_mins
        target_record["closed_by"] = "STAFF"
        target_record["updated_at"] = now.isoformat()
        if diff_mins < 60:
            target_record["is_early_checkout"] = True
            target_record["note"] = f"Xác nhận kết thúc ca sớm sau {diff_mins} phút."
        
        save_attendance_logs(logs)

        record_access_audit(
            payload.username, target_record.get("display_name", payload.username), "ATTENDANCE_CHECKOUT",
            client_ip=client_ip, is_cafe_wifi=True, user_agent=request.headers.get("user-agent"),
            details=f"Check-out thành công ({diff_mins} phút, tính lương {effective_mins} phút)"
        )

        return {
            "status": "success",
            "message": f"Check-out thành công lúc {time_str}. Tổng thời gian: {diff_mins} phút (Hợp lệ: {effective_mins} phút).",
            "record": target_record
        }





@router.post("/review-hanging-shift")
def review_hanging_shift(request: Request, payload: ReviewHangingShiftPayload):
    """
    Manager/Admin review for hanging / forgotten checkout shifts.
    Unfreezes the shift, sets approved minutes, and writes an audit event to so_cai_luong.
    """
    auth_header = request.headers.get("authorization", "")
    manager_info = verify_manager_or_admin(auth_header)
    manager_name = manager_info.get("name") or manager_info.get("sub") or "Quản lý"

    with _logs_lock:
        logs = load_attendance_logs()
        target = None
        for log in logs:
            if str(log.get("id")) == str(payload.record_id):
                target = log
                break

        if not target:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi chấm công cần duyệt.")

        target["checkout_time"] = payload.approved_checkout_time
        target["total_mins"] = payload.approved_minutes
        target["effective_duration_mins"] = payload.approved_minutes
        target["is_hanging_pending"] = False
        target["status"] = "DA_DUYET"
        target["closed_by"] = f"MGR_{manager_name}"
        target["note"] = payload.note or f"Duyệt bởi {manager_name}"
        target["updated_at"] = datetime.now().isoformat()

        save_attendance_logs(logs)

        # Audit event in so_cai_luong
        try:
            from services.db import record_so_cai_luong, get_db_path, DEFAULT_TENANT_ID
            db_target = os.getenv("SQLITE_DB_PATH") or get_db_path()
            record_so_cai_luong(
                tenant_id=DEFAULT_TENANT_ID,
                nhan_vien_id=target.get("username", ""),
                staff_name=target.get("display_name", target.get("username", "")),
                cham_cong_id=payload.record_id,
                loai_su_kien="DIEU_CHINH_GIO",
                so_gio_thay_doi=round(payload.approved_minutes / 60.0, 2),
                muc_luong_ap_dung=int(target.get("hourly_rate_snapshot") or 17000),
                ly_do=payload.note or "Quản lý duyệt ca quên checkout",
                nguoi_tao=manager_name,
                db_path=db_target
            )
        except Exception as e:
            print(f"Warning: Failed to record so_cai_luong: {e}")

        # Đồng bộ vào SQLite
        try:
            sync_latest_log_to_sqlite(target)
        except Exception as e:
            print(f"Warning: Failed to sync latest log to SQLite: {e}")

        return {
            "status": "success",
            "success": True,
            "approved_duration_mins": payload.approved_minutes,
            "message": f"Duyệt ca thành công cho {target.get('display_name')}. Số phút hợp lệ: {payload.approved_minutes}p.",
            "record": target
        }


@router.get("/sop")
def get_role_sop(role: Optional[str] = Query(None)):
    """Fetch SOP template for a given role (Level 1: Read-only)."""
    from services.sop_service import get_sop_by_role
    res = get_sop_by_role(role)
    if res.get("status") == "error":
        raise HTTPException(status_code=404, detail=res.get("message", "SOP template file not found"))
    return res


# ----------------- Manager Endpoints (Protected by Manager/Admin Auth) -----------------

@router.get("/manager/pending")
def get_pending_checkouts(auth: Dict[str, Any] = Depends(verify_manager_or_admin)):
    """List records with missing checkout for manager review, plus closed shifts today."""
    with _logs_lock:
        logs = load_attendance_logs()
        pending = []
        closed_today = []
        now = datetime.now()
        today_str = now.strftime("%d/%m/%Y")
        
        for log in logs:
            if log.get("checkout_time") is None:
                # Check age
                created_at_str = log.get("created_at")
                is_over_48h = False
                age_hours = 0
                if created_at_str:
                    try:
                        dt_created = datetime.fromisoformat(created_at_str)
                        age_hours = (now - dt_created).total_seconds() / 3600
                        if age_hours >= 48:
                            is_over_48h = True
                    except Exception:
                        pass
                pending.append({
                    **log,
                    "age_hours": round(age_hours, 1),
                    "is_over_48h": is_over_48h
                })
            elif log.get("date") == today_str and log.get("checkout_time") is not None:
                closed_today.append(log)
            
    return {
        "pending_count": len(pending), 
        "records": pending,
        "closed_today": closed_today
    }


@router.post("/manager/manual-close")
def manual_close_shift(payload: ManualClosePayload, auth: Dict[str, Any] = Depends(verify_manager_or_admin)):
    """Manager manually resolves an unclosed shift."""
    with _logs_lock:
        logs = load_attendance_logs()
        found = None
        for log in logs:
            if str(log.get("id")) == str(payload.record_id):
                found = log
                break
                
        if not found:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi ca làm việc.")
            
        diff_mins = calculate_shift_duration_minutes(
            found.get("date", datetime.now().strftime("%d/%m/%Y")), 
            found.get("checkin_time", "06:00"), 
            payload.manual_checkout
        )
        found["checkout_time"] = payload.manual_checkout
        found["total_mins"] = diff_mins
        found["closed_by"] = f"MANAGER_{auth.get('sub', 'MANUAL')}"
        found["manager_note"] = payload.manager_note
        found["updated_at"] = datetime.now().isoformat()
        
        save_attendance_logs(logs)
        return {"status": "success", "message": f"Đã chốt giờ ra thành công ({diff_mins} phút).", "record": found}


@router.get("/manager/auto-close-check")
@router.post("/manager/auto-close-check", include_in_schema=False)
def trigger_auto_close(auth: Dict[str, Any] = Depends(verify_manager_or_admin)):
    """
    Tự động chốt đóng ca sau 180 phút (3 tiếng) quá giờ tan ca chính thức.
    Ví dụ: Ca Sáng kết thúc lúc 11:30 -> sau 14:30 nếu chưa checkout sẽ tự động đóng ca về 11:00 hoặc 11:30.
    Ca Tối kết thúc lúc 23:00 -> sau 02:00 sáng tự động đóng ca về 22:00 hoặc 23:00.
    """
    return auto_close_hanging_shifts_logic()


def verify_manager_auth_or_pin(authorization: Optional[str] = None, manager_pin: Optional[str] = None) -> str:
    """
    Verify either Bearer token of Manager/Admin OR valid Manager/Admin PIN.
    Returns the acting manager/admin username.
    """
    # 1. Check Bearer Token
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        try:
            payload = get_current_user(token)
            role = (payload.get("role") or "").upper()
            if role in ["MANAGER", "ADMIN"]:
                return payload.get("sub", "MANAGER")
        except Exception:
            pass

    # 2. Check Manager PIN
    if manager_pin:
        auth_data = load_staff_auth()
        accounts = auth_data.get("staff_accounts", {})
        pin_str = str(manager_pin).strip()
        for uname, acc in accounts.items():
            acc_role = (acc.get("role") or "").upper()
            acc_status = (acc.get("status") or "ACTIVE").upper()
            if acc_role in ["MANAGER", "ADMIN"] and acc_status != "INACTIVE":
                acc_pin = str(acc.get("pin") or "")
                if acc_pin and verify_pin(pin_str, acc_pin):
                    return uname

    raise HTTPException(
        status_code=403,
        detail="Yêu cầu quyền Quản lý / Admin hoặc nhập mã PIN Quản lý hợp lệ."
    )


@router.post("/manager/reopen-shift")
def reopen_shift(
    payload: ShiftActionPayload,
    authorization: Optional[str] = Header(None)
):
    """
    Manager/Admin re-opens a closed shift (e.g. accidental early checkout).
    Resets checkout_time and total_mins to None, returning the shift to IN_PROGRESS.
    """
    manager_uname = verify_manager_auth_or_pin(authorization, payload.manager_pin)
    now = datetime.now()
    today_str = now.strftime("%d/%m/%Y")

    with _logs_lock:
        logs = load_attendance_logs()
        target_record = None

        if payload.record_id:
            for log in logs:
                if str(log.get("id")) == str(payload.record_id):
                    target_record = log
                    break

        if not target_record and payload.username:
            for log in reversed(logs):
                if log.get("username") == payload.username and log.get("date") == today_str and log.get("checkout_time") is not None:
                    target_record = log
                    break

        if not target_record:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi ca đã đóng để mở lại.")

        target_record["checkout_time"] = None
        target_record["total_mins"] = None
        target_record["closed_by"] = None
        target_record.pop("is_early_checkout", None)
        target_record["reopened_at"] = now.isoformat()
        target_record["reopened_by"] = f"MANAGER_{manager_uname}"
        target_record["manager_note"] = payload.manager_note or "Quản lý mở lại ca trực do bấm nhầm Check-out"
        target_record["updated_at"] = now.isoformat()

        save_attendance_logs(logs)
        return {
            "status": "success",
            "message": f"Đã mở lại ca trực cho nhân viên {target_record.get('username')}. Ca đang hoạt động trở lại.",
            "record": target_record
        }


@router.post("/manager/delete-shift")
def delete_shift(
    payload: ShiftActionPayload,
    authorization: Optional[str] = Header(None)
):
    """
    Manager/Admin deletes an erroneous shift record (e.g. accidental checkin-checkout 0 mins).
    Restores staff state to READY_TO_CHECKIN.
    """
    manager_uname = verify_manager_auth_or_pin(authorization, payload.manager_pin)
    now = datetime.now()
    today_str = now.strftime("%d/%m/%Y")

    with _logs_lock:
        logs = load_attendance_logs()
        target_record = None
        target_idx = -1

        if payload.record_id:
            for idx, log in enumerate(logs):
                if str(log.get("id")) == str(payload.record_id):
                    target_record = log
                    target_idx = idx
                    break

        if target_idx == -1 and payload.username:
            for idx in range(len(logs) - 1, -1, -1):
                log = logs[idx]
                if log.get("username") == payload.username and log.get("date") == today_str:
                    target_record = log
                    target_idx = idx
                    break

        if target_idx == -1 or not target_record:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản ghi ca làm việc để xóa.")

        deleted_record = logs.pop(target_idx)
        save_attendance_logs(logs)

        # REA4-03: Xóa bản ghi ca làm việc tương ứng trong SQLite attendance_logs để loại bỏ ca mồ côi
        try:
            conn = get_db_connection()
            try:
                rec_id = deleted_record.get("id")
                rec_id_int = int(rec_id) if (rec_id is not None and str(rec_id).isdigit()) else None
                u = deleted_record.get("username")
                d = deleted_record.get("date")
                c = deleted_record.get("checkin_time") or deleted_record.get("checkin")
                sh_name = deleted_record.get("shift_name")
                sh_key = deleted_record.get("shift_key")

                conn.execute("""
                    DELETE FROM attendance_logs 
                    WHERE (id = ? AND ? IS NOT NULL) 
                       OR (username = ? AND date = ? AND checkin = ?)
                       OR (username = ? AND date = ? AND (shift = ? OR shift = ?))
                """, (rec_id_int, rec_id_int, u, d, c, u, d, sh_name, sh_key))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[SQLite Delete Shift Warning] Failed to delete shift from SQLite: {e}")

        return {
            "status": "success",
            "message": f"Đã xóa ca lỗi của nhân viên {deleted_record.get('username')}. Nhân viên có thể check-in lại.",
            "deleted_record": deleted_record
        }


# ----------------- Phase 4: Attendance Explanation Requests -----------------




def _verify_authenticated_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Verify JWT token for STAFF, MANAGER, or ADMIN."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Yêu cầu đăng nhập để thực hiện thao tác này."
        )
    token = authorization.split(" ")[1].strip()
    try:
        payload = get_current_user(token)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Xác thực thất bại: {e}")

    role = (payload.get("role") or "STAFF").upper()
    if role not in ["STAFF", "MANAGER", "ADMIN"]:
        raise HTTPException(
            status_code=403,
            detail="Tài khoản không có quyền thực hiện thao tác này."
        )
    return payload


def _parse_date_variants(date_str: str):
    """Return (dd_mm_yyyy, set_of_variants) for flexible date matching."""
    raw = (date_str or "").strip()
    if not raw:
        today_ddmmyyyy = datetime.now().strftime("%d/%m/%Y")
        today_iso = datetime.now().strftime("%Y-%m-%d")
        return today_ddmmyyyy, {today_ddmmyyyy, today_iso}
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(raw, fmt)
            d_slash = dt.strftime("%d/%m/%Y")
            d_iso = dt.strftime("%Y-%m-%d")
            return d_slash, {raw, d_slash, d_iso}
        except Exception:
            pass
    return raw, {raw}


def _call_db_flexibly(fn, **kwargs):
    """Call SQLite helper supporting either dict payload or keyword arguments."""
    sig = inspect.signature(fn)
    params = sig.parameters
    if "record" in params:
        return fn(kwargs)
    if len(params) == 1 and "username" not in params and "status" not in params and "req_id" not in params:
        first_param = next(iter(params.values()))
        if first_param.kind != inspect.Parameter.VAR_KEYWORD:
            return fn(kwargs)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**kwargs)
    filtered = {k: v for k, v in kwargs.items() if k in params}
    return fn(**filtered)


@router.post("/requests")
def create_attendance_explanation_request(
    payload: AttendanceRequestCreate,
    auth: Dict[str, Any] = Depends(_verify_authenticated_user)
):
    """Staff/Manager/Admin submits an attendance explanation request."""
    reason_clean = (payload.reason or "").strip()
    if len(reason_clean) < 3:
        raise HTTPException(
            status_code=400,
            detail="Lý do giải trình bắt buộc tối thiểu 3 ký tự."
        )

    uname = (auth.get("sub") or auth.get("username") or "").strip()
    display_name = (auth.get("name") or auth.get("display_name") or uname).strip()

    emp_info = None
    try:
        emp_info = resolve_employee_id(uname)
    except Exception:
        emp_info = None

    employee_id = None
    if isinstance(emp_info, dict):
        employee_id = emp_info.get("employee_id") or emp_info.get("id")
        if (not display_name or display_name == uname) and (emp_info.get("full_name") or emp_info.get("display_name")):
            display_name = emp_info.get("full_name") or emp_info.get("display_name")
    elif isinstance(emp_info, str) and emp_info.strip():
        employee_id = emp_info.strip()

    shift_key = (payload.shift_key or "sang").strip().lower()
    req_type = (payload.request_type or "FORGOT_CHECKOUT").strip().upper()
    req_checkin = (payload.requested_checkin or "").strip()
    req_checkout = (payload.requested_checkout or "").strip()
    date_val = (payload.date or "").strip()

    saved = _call_db_flexibly(
        create_attendance_request_db,
        username=uname,
        display_name=display_name,
        employee_id=employee_id,
        date=date_val,
        shift_key=shift_key,
        request_type=req_type,
        requested_checkin=req_checkin,
        requested_checkout=req_checkout,
        reason=reason_clean,
        status="PENDING",
    )

    return {
        "success": True,
        "message": "Đã gửi yêu cầu giải trình công. Chờ Quản lý phê duyệt.",
        "request": saved,
    }


@router.get("/requests")
def list_attendance_explanation_requests(
    status: Optional[str] = Query(None),
    auth: Dict[str, Any] = Depends(_verify_authenticated_user)
):
    """List attendance explanation requests (scoped to own requests for STAFF, all for MANAGER/ADMIN)."""
    role = (auth.get("role") or "STAFF").upper()
    uname = (auth.get("sub") or auth.get("username") or "").strip()

    if role == "STAFF":
        items = list_attendance_requests_db(username=uname, status=status)
    else:
        items = list_attendance_requests_db(status=status)

    if items is None:
        items = []

    return {
        "success": True,
        "requests": items,
        "count": len(items),
    }


@router.post("/requests/{req_id}/review")
def review_attendance_explanation_request(
    req_id: Any,
    payload: AttendanceRequestReview,
    auth: Dict[str, Any] = Depends(_verify_authenticated_user)
):
    """Manager or Admin approves/rejects an attendance explanation request."""
    role = (auth.get("role") or "STAFF").upper()
    if role not in ["MANAGER", "ADMIN"]:
        raise HTTPException(
            status_code=403,
            detail="Chỉ Quản lý hoặc Admin mới có quyền phê duyệt giải trình công."
        )

    uname = (auth.get("sub") or auth.get("username") or "").strip()
    reviewer_name = (auth.get("name") or auth.get("display_name") or uname).strip()

    action = (payload.action or "").strip().upper()
    if action not in ["APPROVE", "REJECT"]:
        raise HTTPException(
            status_code=400,
            detail="Hành động không hợp lệ. Chỉ chấp nhận APPROVE hoặc REJECT."
        )

    # Normalize req_id if integer ID is used in SQLite
    lookup_id: Any = req_id
    if isinstance(req_id, str) and req_id.isdigit():
        lookup_id = int(req_id)

    req = get_attendance_request_by_id_db(lookup_id)
    if not req and lookup_id != req_id:
        req = get_attendance_request_by_id_db(req_id)
    if not req:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy yêu cầu giải trình công."
        )

    req_uname = (req.get("username") or "").strip()
    if role == "MANAGER" and req_uname.lower() == uname.lower():
        raise HTTPException(
            status_code=403,
            detail="Xung đột lợi ích: Quản lý không thể tự duyệt giải trình công của chính mình. Cần Admin phê duyệt."
        )

    new_status = "APPROVED" if action == "APPROVE" else "REJECTED"
    review_note = (payload.review_note or "").strip()

    updated_req = review_attendance_request_db(
        req.get("id", lookup_id),
        status=new_status,
        reviewed_by=reviewer_name,
        review_note=review_note,
    )
    if not isinstance(updated_req, dict):
        updated_req = get_attendance_request_by_id_db(req.get("id", lookup_id)) or {
            **req,
            "status": new_status,
            "reviewed_by": reviewer_name,
            "review_note": review_note,
        }

    if action == "APPROVE":
        req_date_raw = (req.get("date") or "").strip()
        ddmmyyyy, date_variants = _parse_date_variants(req_date_raw)
        req_shift = (req.get("shift_key") or "sang").strip().lower()
        req_type = (req.get("request_type") or "FORGOT_CHECKOUT").strip().upper()
        req_in = (req.get("requested_checkin") or "").strip()
        req_out = (req.get("requested_checkout") or "").strip()

        with _logs_lock:
            logs = load_attendance_logs()
            matched_log = None

            # Prefer exact match on username + date + shift_key
            for log in reversed(logs):
                l_user = (log.get("username") or "").strip().lower()
                l_date = (log.get("date") or "").strip()
                l_shift = (log.get("shift_key") or "sang").strip().lower()
                if l_user == req_uname.lower() and l_date in date_variants and l_shift == req_shift:
                    matched_log = log
                    break

            # Fallback match on username + date if shift_key didn't match
            if matched_log is None:
                for log in reversed(logs):
                    l_user = (log.get("username") or "").strip().lower()
                    l_date = (log.get("date") or "").strip()
                    if l_user == req_uname.lower() and l_date in date_variants:
                        matched_log = log
                        break

            now_iso = datetime.now().isoformat()
            if matched_log is not None:
                if req_in:
                    matched_log["checkin_time"] = req_in
                if req_out:
                    matched_log["checkout_time"] = req_out

                c_in = matched_log.get("checkin_time") or "06:00"
                c_out = matched_log.get("checkout_time")
                if c_out:
                    log_ddmmyyyy, _ = _parse_date_variants(matched_log.get("date") or ddmmyyyy)
                    matched_log["total_mins"] = calculate_shift_duration_minutes(log_ddmmyyyy, c_in, c_out)

                matched_log["status"] = "COMPLETED"
                matched_log["auto_closed"] = False
                matched_log["forgot_checkout"] = False
                matched_log["resolved_by_request"] = req.get("id", lookup_id)
                matched_log["updated_at"] = now_iso

                if req_type == "LATE_EXCUSE":
                    matched_log["is_late"] = False
                    matched_log["late_mins"] = 0

                save_attendance_logs(logs)
            elif req_in and req_out:
                total_mins = calculate_shift_duration_minutes(ddmmyyyy, req_in, req_out)
                new_log = {
                    "id": f"ATT_REQ_{req.get('id', lookup_id)}_{int(datetime.now().timestamp())}",
                    "username": req_uname,
                    "display_name": req.get("display_name") or req_uname,
                    "role": "Phục vụ",
                    "date": ddmmyyyy,
                    "shift_key": req_shift,
                    "shift_name": "Ca Sáng" if req_shift == "sang" else "Ca Tối",
                    "checkin_time": req_in,
                    "checkout_time": req_out,
                    "total_mins": total_mins,
                    "is_late": False,
                    "late_mins": 0,
                    "status": "COMPLETED",
                    "auto_closed": False,
                    "forgot_checkout": False,
                    "resolved_by_request": req.get("id", lookup_id),
                    "closed_by": f"REQUEST_{reviewer_name}",
                    "created_at": now_iso,
                    "updated_at": now_iso,
                    "note": f"Bổ sung công từ giải trình #{req.get('id', lookup_id)}: {req.get('reason', '')}",
                }
                logs.append(new_log)
                save_attendance_logs(logs)

    msg = (
        "Đã phê duyệt yêu cầu giải trình công và cập nhật dữ liệu chấm công."
        if action == "APPROVE"
        else "Đã từ chối yêu cầu giải trình công."
    )
    return {
        "success": True,
        "message": msg,
        "request": updated_req,
    }


