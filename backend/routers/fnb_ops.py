# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel
import jwt
import datetime
import json
import os
import time
import unicodedata
import re
import secrets
import logging

from typing import Optional, Dict, List, Any, Tuple
import random
import ipaddress
import sys

# Ensure identical module identity across both 'routers.fnb_ops' and 'backend.routers.fnb_ops'
if __name__ in ("backend.routers.fnb_ops", "routers.fnb_ops"):
    sys.modules["backend.routers.fnb_ops"] = sys.modules[__name__]
    sys.modules["routers.fnb_ops"] = sys.modules[__name__]
    sys.modules["backend.routers.fnb_ops"] = sys.modules[__name__]
    sys.modules["routers.fnb_ops"] = sys.modules[__name__]

try:
    from backend.services.storage import (
        safe_json_write,
        safe_json_read,
        hash_pin,
        verify_pin,
        needs_rehash
    )
    from backend.services.payroll_calc import (
        calculate_staff_payslip_breakdown,
        compute_all_shift_records_server_side
    )
    from backend.services.db import (
        get_login_attempts,
        record_failed_login,
        clear_login_attempts,
        record_failed_attempt_tiered,
        check_login_lockout,
        clear_login_lockout,
        get_active_lockouts,
        admin_unlock_target,
        insert_staff_ledger,
        get_staff_ledger_by_id,
        list_staff_ledgers,
        delete_staff_ledger,
        revoke_token,
        is_token_revoked,
        check_api_rate_limit,
        record_access_audit,
        upsert_staff_account,
        get_staff_directory_map,
        upsert_shift_approval_db,
        delete_shift_approval_db,
        list_shift_approvals_db,
        get_store_setting_db
    )
except ImportError:
    from services.storage import (
        safe_json_write,
        safe_json_read,
        hash_pin,
        verify_pin,
        needs_rehash
    )
    from services.payroll_calc import (
        calculate_staff_payslip_breakdown,
        compute_all_shift_records_server_side
    )
    from services.db import (
        get_login_attempts,
        record_failed_login,
        clear_login_attempts,
        record_failed_attempt_tiered,
        check_login_lockout,
        clear_login_lockout,
        get_active_lockouts,
        admin_unlock_target,
        insert_staff_ledger,
        get_staff_ledger_by_id,
        list_staff_ledgers,
        delete_staff_ledger,
        revoke_token,
        is_token_revoked,
        check_api_rate_limit,
        record_access_audit,
        upsert_staff_account,
        get_staff_directory_map,
        upsert_shift_approval_db,
        delete_shift_approval_db,
        list_shift_approvals_db,
        get_store_setting_db
    )

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from backend.services.auth import (
        DEFAULT_AUTH_FILE,
        get_auth_file,
        normalize_str,
        load_staff_auth,
        save_staff_auth,
        create_access_token,
        get_current_user,
        verify_token,
        get_admin_token_version,
        increment_admin_token_version,
        bump_staff_token_version,
        SECRET_KEY,
        ALGORITHM,
    )
except ImportError:
    from services.auth import (
        DEFAULT_AUTH_FILE,
        get_auth_file,
        normalize_str,
        load_staff_auth,
        save_staff_auth,
        create_access_token,
        get_current_user,
        verify_token,
        get_admin_token_version,
        increment_admin_token_version,
        bump_staff_token_version,
        SECRET_KEY,
        ALGORITHM,
    )

logger = logging.getLogger("fnb_ops")

router = APIRouter(prefix="/api/v1/cc", tags=["fnb_ops"])
cc_router = router  # Backward compatibility alias


def is_cloudflare_ingress_valid(request: Request) -> Tuple[bool, str]:
    """
    Cloudflare Ingress Shield Verification.
    If the request targets protected domains ('fnbops.local' or CLOUDFLARE_PROTECTED_DOMAINS),
    it MUST have the 'cf-ray' header (originating from Cloudflare Edge), unless the client is an exempt origin:
    - localhost / 127.0.0.1 / ::1
    - testclient (Starlette / pytest TestClient)
    - Private LAN IP (192.168.x.x, 10.x.x.x, 172.16-31.x.x) for store local POS devices
    - Tailscale CGNAT IP (100.x.y.z) for internal admin mesh
    - ON_PREMISE_MODE is active
    """
    if os.getenv("ON_PREMISE_MODE", "false").lower() in ("true", "1"):
        return True, "On-premise mode enabled"

    host = request.headers.get("host", "").split(":")[0].strip().lower()

    # Protected domains (configurable via CLOUDFLARE_PROTECTED_DOMAINS)
    protected_domains = {"fnbops.local"}
    extra_domains = os.getenv("CLOUDFLARE_PROTECTED_DOMAINS", "")
    if extra_domains:
        for dom in extra_domains.split(","):
            if dom.strip():
                protected_domains.add(dom.strip().lower())
    is_protected = host in protected_domains or any(host.endswith("." + d) for d in protected_domains)
    if not is_protected:
        return True, "Domain not subject to Cloudflare Ingress Shield"

    # Check client IP exemptions
    client_ip = request.client.host if request.client else ""

    is_localhost = client_ip in ("localhost", "127.0.0.1", "::1", "testclient")
    is_tailscale = client_ip.startswith("100.")
    is_private_lan = False
    try:
        import ipaddress
        ip_obj = ipaddress.ip_address(client_ip)
        lan_networks = (
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
        )
        if any(ip_obj in net for net in lan_networks):
            is_private_lan = True
    except Exception:
        pass

    if is_localhost or is_tailscale or is_private_lan:
        return True, "Exempt client origin"

    # Cloudflare Edge always adds 'cf-ray' header
    cf_ray = request.headers.get("cf-ray")
    if cf_ray and cf_ray.strip():
        return True, "Valid Cloudflare Edge request"

    return False, "Direct IP access is prohibited. Requests must route through Cloudflare Edge."


def verify_cloudflare_ingress(request: Request):
    """FastAPI Dependency or verification hook to enforce Cloudflare Ingress Shield."""
    valid, message = is_cloudflare_ingress_valid(request)
    if not valid:
        logger.warning(
            f"Blocked direct IP ingress access: host={request.headers.get('host')}, "
            f"client={request.client.host if request.client else 'unknown'}"
        )
        raise HTTPException(
            status_code=403,
            detail="Direct IP access is prohibited. Requests must route through Cloudflare Edge."
        )

# Fail-Closed JWT Secret enforcement (with first-run auto-bootstrap)
try:
    from backend.services.auth import ensure_bootstrap_jwt_secret
except ImportError:
    from services.auth import ensure_bootstrap_jwt_secret

_env_jwt_secret = ensure_bootstrap_jwt_secret()
if not _env_jwt_secret or not _env_jwt_secret.strip():
    raise RuntimeError("CRITICAL BẢO MẬT: JWT_SECRET_KEY là bắt buộc trong .env. Hệ thống từ chối khởi động ở trạng thái mất an toàn.")
SECRET_KEY = _env_jwt_secret.strip()

ADMIN_PASS = os.getenv("ADMIN_PASSWORD")
STAFF_PASS = os.getenv("STAFF_PASSWORD")
ALGORITHM = "HS256"

# Dynamic fallback paths for production / container / local
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_dir = os.path.dirname(_base_dir)

DEFAULT_DATA_FILE = os.getenv("DATA_FILE") or os.path.join(_root_dir, "frontend", "data.json")
DEFAULT_AUTH_FILE = os.path.join(_root_dir, "data", "staff_auth.json")
DEFAULT_APPROVALS_FILE = os.path.join(_root_dir, "data", "shift_approvals.json")
DEFAULT_EVALUATIONS_FILE = os.path.join(_root_dir, "data", "eval_logs.json")

def _is_on_premise():
    return os.getenv("ON_PREMISE_MODE", "false").lower() in ("true", "1")

def get_data_file():
    env_p = os.getenv("DATA_FILE")
    if env_p and os.path.exists(env_p):
        return env_p
    for p in [
        os.path.join(_root_dir, "frontend", "data.json"),
        os.path.join(_root_dir, "data", "data.json"),
        os.path.join(_base_dir, "data.json"),
        os.path.join(_get_root_data_dir(), "data.json")
    ]:
        if os.path.exists(p):
            return p

    # Tự động khởi tạo file data.json mẫu nếu chưa tồn tại thay vì ném 404
    fallback_path = os.path.join(_get_root_data_dir(), "data.json")
    try:
        os.makedirs(os.path.dirname(fallback_path), exist_ok=True)
        default_content = {
            "NHÂN VIÊN": [
                ["TỔNG KẾT LƯƠNG NHÂN VIÊN FNBOPS", "", "", "", "", "", "CÀI ĐẶT LƯƠNG", "", "", "HIỆU SUẤT LÀM VIỆC"],
                ["Tháng:", "", "10", "", "0", "", "TÊN NHÂN VIÊN", "LƯƠNG/GIỜ (VNĐ)", "TRẠNG THÁI", "TÊN", "TỔNG GIỜ CÔNG", "TỔNG LƯƠNG", "TỔNG CA", "ĐI TRỄ (LẦN)", "TỔNG PHÚT TRỄ", "TĂNG CA (PHÚT)", "TIỀN TĂNG CA (VNĐ)", "LƯƠNG LỄ (VNĐ)", "LƯƠNG THỰC LĨNH", "ĐÃ XÁC NHẬN"]
            ],
            "SỔ PHỤ": [
                ["MÃ SỰ KIỆN", "TÊN NHÂN VIÊN", "THÁNG", "LOẠI", "SỐ TIỀN (VNĐ)", "NGÀY ÁP DỤNG", "LÝ DO / GHI CHÚ", "NGƯỜI TẠO", "TRẠNG THÁI"]
            ]
        }
        with open(fallback_path, "w", encoding="utf-8") as f:
            json.dump(default_content, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return fallback_path

def _get_root_data_dir():
    if os.getenv("DATA_DIR"):
        return os.getenv("DATA_DIR")
    if _root_dir and _root_dir != "/" and os.path.exists(os.path.join(_root_dir, "data")):
        return os.path.join(_root_dir, "data")
    return os.path.join(_base_dir, "data")

def get_auth_file():
    if os.getenv("AUTH_FILE"):
        return os.getenv("AUTH_FILE")
    data_dir = _get_root_data_dir()
    p = os.path.join(data_dir, "staff_auth.json")
    if os.path.exists(p):
        return p
    for alt in [os.path.join(_root_dir, "data", "staff_auth.json"), os.path.join(_base_dir, "staff_auth.json")]:
        if os.path.exists(alt):
            return alt
    return p

def get_approvals_file():
    if os.getenv("APPROVALS_FILE"):
        return os.getenv("APPROVALS_FILE")
    data_dir = _get_root_data_dir()
    p = os.path.join(data_dir, "shift_approvals.json")
    if os.path.exists(p):
        return p
    return os.path.join(_root_dir, "data", "shift_approvals.json")

def get_evaluations_file():
    if os.getenv("EVALUATIONS_FILE"):
        return os.getenv("EVALUATIONS_FILE")
    data_dir = _get_root_data_dir()
    p = os.path.join(data_dir, "eval_logs.json")
    if os.path.exists(p):
        return p
    return os.path.join(_root_dir, "data", "eval_logs.json")

DEFAULT_ATTENDANCE_LOGS_FILE = os.path.join(_root_dir, "data", "attendance_logs.json")

def get_attendance_logs_file():
    if os.getenv("ATTENDANCE_LOGS_FILE"):
        return os.getenv("ATTENDANCE_LOGS_FILE")
    data_dir = _get_root_data_dir()
    p = os.path.join(data_dir, "attendance_logs.json")
    if os.path.exists(p):
        return p
    return os.path.join(_root_dir, "data", "attendance_logs.json")

DEFAULT_POS_HEARTBEAT_FILE = os.path.join(_root_dir, "data", "pos_heartbeat.json")

def get_pos_heartbeat_file():
    if os.getenv("HEARTBEAT_FILE"):
        return os.getenv("HEARTBEAT_FILE")
    data_dir = _get_root_data_dir()
    p = os.path.join(data_dir, "pos_heartbeat.json")
    if os.path.exists(p):
        return p
    return os.path.join(_root_dir, "data", "pos_heartbeat.json")

DEFAULT_DISBURSEMENT_FILE = os.path.join(_root_dir, "data", "payroll_disbursements.json")

def get_disbursements_file():
    if os.getenv("DISBURSEMENTS_FILE"):
        return os.getenv("DISBURSEMENTS_FILE")
    data_dir = _get_root_data_dir()
    p = os.path.join(data_dir, "payroll_disbursements.json")
    if os.path.exists(p):
        return p
    return os.path.join(_root_dir, "data", "payroll_disbursements.json")

def load_disbursements() -> Dict[str, Any]:
    if os.getenv("DISBURSEMENTS_FILE"):
        return safe_json_read(get_disbursements_file(), default={})
    try:
        from services.db import get_payroll_disbursements_db
        db_data = get_payroll_disbursements_db()
        if db_data:
            return db_data
    except Exception:
        pass
    fpath = get_disbursements_file()
    return safe_json_read(fpath, default={})

def save_disbursements(data: Dict[str, Any]) -> None:
    try:
        from services.db import upsert_payroll_disbursement_db
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
    disb_env = os.getenv("DISBURSEMENTS_FILE")
    if disb_env and os.getenv("TESTING") == "1":
        if os.path.abspath(disb_env) != os.path.abspath(fpath):
            safe_json_write(disb_env, data)
            return

    try:
        from services.storage import is_runtime_json_sync_enabled
        if is_runtime_json_sync_enabled():
            safe_json_write(fpath, data)
    except Exception:
        pass

def check_is_cafe_wifi(client_ip: Optional[str]) -> bool:
    if get_store_setting_db("emergency_remote_checkin", "0") == "1":
        return True
    if not client_ip:
        return False
    if _is_on_premise():
        if client_ip in ("127.0.0.1", "localhost", "::1", "testclient"):
            return True
        try:
            ip = ipaddress.ip_address(client_ip)
            if ip.is_private or ip.is_loopback:
                return True
        except ValueError:
            pass
    try:
        hb_file = get_pos_heartbeat_file()
        if os.path.exists(hb_file):
            with open(hb_file, "r", encoding="utf-8") as f:
                d = json.load(f)
                cafe_ip = (d.get("cafe_ip") or "").strip()
                return bool(cafe_ip and client_ip.strip() == cafe_ip)
    except Exception:
        pass
    return False

def load_attendance_logs() -> List[Dict[str, Any]]:
    fpath = get_attendance_logs_file()
    return safe_json_read(fpath, default=[])

# Models re-exported from models package
from models.auth import LoginData
from models.store_config import StoreConfigUpdate
from models.staff import (
    UpdatePinData,
    ToggleStaffStatusData,
    CreateStaffAccountData,
    UpdateStaffProfileData,
    AdminUnlockRequest,
)
from models.evaluation import (
    StaffEvaluationRequest,
    ApproveEvaluationRequest,
)
from models.disbursement import (
    StaffLedgerCreateRequest,
    ToggleLockData,
    ConfirmPayrollData,
    DisbursementToggleRequest,
    ConfirmOTData,
)

# Re-exported helpers from extracted routers
try:
    from backend.routers.evaluation import (
        load_evaluations,
        save_evaluations,
        get_evaluations_file,
    )
except ImportError:
    from routers.evaluation import (
        load_evaluations,
        save_evaluations,
        get_evaluations_file,
    )

from routers.disbursement import (
    get_approvals_file,
    load_shift_approvals,
    save_shift_approvals,
    get_disbursements_file,
    load_disbursements,
    save_disbursements,
    DEFAULT_DISBURSEMENT_FILE,
    check_payroll_lock_status,
)

TRUSTED_PROXIES = {"127.0.0.1", "::1", "localhost", "testclient"}
DOCKER_NETWORK = ipaddress.ip_network("172.16.0.0/12")

def is_testing_env() -> bool:
    return os.getenv("TESTING") == "1" or "PYTEST_CURRENT_TEST" in os.environ

def is_trusted_proxy_host(host: str) -> bool:
    if not host:
        return False
    if host in TRUSTED_PROXIES:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or (ip in DOCKER_NETWORK)
    except ValueError:
        return False

def _extract_trusted_client_ip(request: Request) -> str:
    """
    Extract client IP with protection against IP Header Spoofing.
    Only trust CF-Connecting-IP, X-Real-IP, X-Forwarded-For when request.client.host
    belongs to Trusted Proxies (127.0.0.1, ::1, localhost, testclient or Docker 172.16.0.0/12).
    """
    direct_host = request.client.host if request.client else "127.0.0.1"

    if is_trusted_proxy_host(direct_host):
        raw_ip = (
            request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Real-IP")
            or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip())
        )
        if raw_ip:
            raw_ip = raw_ip.strip()
            try:
                ipaddress.ip_address(raw_ip)
                return raw_ip
            except ValueError:
                pass
        if direct_host == "testclient" and is_testing_env():
            return "testclient"

    if direct_host == "testclient" and is_testing_env():
        return "testclient"
    return direct_host


def enforce_api_rate_limit(request: Request, limit: int = 30, window_seconds: int = 60, key_prefix: str = "api"):
    """
    Enforces per-client rate limit stored atomically in SQLite WAL.
    Raises HTTP 429 Too Many Requests if limit is exceeded.
    """
    client_ip = _extract_trusted_client_ip(request)
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    
    # Relax rate limit for internal LAN / local clients when in ON_PREMISE_MODE
    on_premise = os.getenv("ON_PREMISE_MODE", "false").lower() in ("true", "1")
    if on_premise and client_ip:
        if client_ip in ("127.0.0.1", "localhost", "::1", "testclient"):
            limit = max(limit, 300)
        else:
            try:
                import ipaddress
                ip_obj = ipaddress.ip_address(client_ip)
                is_lan = ip_obj.is_loopback or any(ip_obj in net for net in (
                    ipaddress.ip_network('10.0.0.0/8'),
                    ipaddress.ip_network('172.16.0.0/12'),
                    ipaddress.ip_network('192.168.0.0/16')
                ))
                if is_lan:
                    limit = max(limit, 300)
            except ValueError:
                pass

    # Fast user identification if authenticated
    user_id = client_ip
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
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

def _get_live_cafe_ip() -> str:
    try:
        from services.attendance_service import get_current_cafe_ip
        return get_current_cafe_ip()
    except Exception:
        try:
            from backend.services.attendance_service import get_current_cafe_ip
            return get_current_cafe_ip()
        except Exception:
            return os.getenv("STORE_WIFI_IP", "127.0.0.1")


@router.post("/auth/login")
def login(request: Request, data: LoginData):
    client_ip = _extract_trusted_client_ip(request)
    user_agent = request.headers.get("user-agent") or ""
    is_cafe = check_is_cafe_wifi(client_ip)
    now = time.time()
    
    u_raw = data.username.strip()
    u_norm = normalize_str(u_raw)
    p = (data.password or data.pin or "").strip()
    if not p:
        raise HTTPException(status_code=422, detail="Vui lòng nhập mật khẩu hoặc mã PIN.")

    cafe_ip = _get_live_cafe_ip()
    is_whitelisted_cafe = bool(client_ip and cafe_ip and client_ip == cafe_ip)

    # Rate limit check: 3-Tier progressive lockout (Username + IP)
    if not (client_ip == "testclient" and is_testing_env()):
        lockout_info = check_login_lockout(ip=client_ip, username=u_norm)
        if lockout_info:
            rem = lockout_info.get("remaining_seconds", 60)
            tier = lockout_info.get("tier", 1)
            msg = lockout_info.get("message", "Bạn đã đăng nhập sai quá nhiều lần.")
            record_access_audit(
                u_norm, 
                "Khách/Nhân viên", 
                "LOGIN_LOCKED", 
                client_ip=client_ip, 
                is_cafe_wifi=is_cafe, 
                user_agent=user_agent, 
                details=f"Tier {tier} lockout: {rem}s"
            )
            raise HTTPException(
                status_code=429, 
                detail=msg,
                headers={"Retry-After": str(rem)}
            )

    # 1. Admin login (Strict Auth without hardcoded backdoors)
    if (u_norm == "admin" or u_raw.upper() == "ADMIN"):
        auth = load_staff_auth()
        accounts = auth.get("staff_accounts", {})
        admin_acc = accounts.get("admin") or accounts.get("Admin") or {}
        admin_pin = str(admin_acc.get("pin") or "").strip()
        admin_env_pass = (os.getenv("ADMIN_PASSWORD") or ADMIN_PASS or "").strip()

        allowed_admin_passwords = set()
        if admin_pin and not (admin_pin.startswith("pbkdf2_") or admin_pin.startswith("$")):
            allowed_admin_passwords.add(admin_pin)
        if admin_env_pass:
            allowed_admin_passwords.add(admin_env_pass)

        admin_match = False
        if p and p in allowed_admin_passwords:
            admin_match = True
        elif p and admin_pin and (admin_pin.startswith("pbkdf2_") or admin_pin.startswith("$")):
            try:
                admin_match = bool(verify_pin(p, admin_pin))
            except Exception:
                pass

        if admin_match:
            clear_login_lockout(ip=client_ip, username=u_norm)
            clear_login_attempts(client_ip)
            admin_name = admin_acc.get("full_name") or "Chủ Quán (Admin)"
            record_access_audit("admin", admin_name, "LOGIN_SUCCESS", client_ip=client_ip, is_cafe_wifi=is_cafe, user_agent=user_agent, role="ADMIN")
            admin_ver = get_admin_token_version()
            token = create_access_token({"sub": "admin", "role": "ADMIN", "name": admin_name, "ver": admin_ver})
            return {"access_token": token, "token_type": "bearer", "role": "ADMIN", "name": admin_name, "username": "admin", "ver": admin_ver}
        else:
            record_access_audit("admin", "Chủ Quán (Admin)", "LOGIN_FAILED", client_ip=client_ip, is_cafe_wifi=is_cafe, user_agent=user_agent, role="ADMIN", details="Sai mật khẩu Admin")
            if not (client_ip == "testclient" and is_testing_env()):
                failed_info = record_failed_attempt_tiered(ip=client_ip, username="admin", is_whitelisted_cafe=is_whitelisted_cafe)
                tier = failed_info.get("tier", 1)
                if tier == 3:
                    try:
                        from services.send_telegram import send_telegram_alert
                        store_badge = os.getenv("STORE_NAME", "FNBOPS").upper()
                        send_telegram_alert(
                            f"🚨 [CẢNH BÁO AN NINH {store_badge}]\n"
                            f"Phát hiện hành vi dò mật khẩu ADMIN nghiêm trọng!\n"
                            f"• IP: {client_ip} (WiFi Quán: {'CÓ' if is_whitelisted_cafe else 'KHÔNG'})\n"
                            f"• Đã kích hoạt KHÓA TẦNG 3 (5 TIẾNG).\n"
                            f"• Chỉ duy nhất Chủ quán mới có quyền mở khóa trên Dashboard."
                        )
                    except Exception:
                        pass
            raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mã PIN")

    # 2. Staff / Manager login via staff_auth.json
    auth = load_staff_auth()
    accounts = auth.get("staff_accounts", {})
    
    matched_key = None
    matched_acc = None
    for k, acc in accounts.items():
        k_norm = normalize_str(k)
        aliases_norm = [normalize_str(a) for a in acc.get("aliases", [])]
        sheet_norm = [normalize_str(s) for s in acc.get("sheet_names", [])]
        full_norm = normalize_str(acc.get("full_name", ""))
        if u_norm == k_norm or u_norm in aliases_norm or u_norm in sheet_norm or u_norm == full_norm:
            matched_key = k
            matched_acc = acc
            break

    if matched_acc:
        # Offboarding check: If status == INACTIVE, reject login immediately
        acc_status = str(matched_acc.get("status", "ACTIVE")).strip().upper()
        if acc_status == "INACTIVE":
            record_access_audit(matched_key, matched_acc.get("full_name", ""), "LOGIN_BLOCKED", client_ip=client_ip, is_cafe_wifi=is_cafe, user_agent=user_agent, role=str(matched_acc.get("role", "STAFF")), details="Tài khoản INACTIVE")
            raise HTTPException(
                status_code=403, 
                detail="Tài khoản này đã bị vô hiệu hóa hoặc nhân viên đã nghỉ việc. Vui lòng liên hệ Quản lý."
            )

        valid_pin = str(matched_acc.get("pin", "")).strip()
        is_pin_match = bool(valid_pin and verify_pin(p, valid_pin))
        enable_master = (os.getenv("ENABLE_MASTER_STAFF_PASS", "false").lower() == "true")
        is_master_match = bool(enable_master and STAFF_PASS and p == STAFF_PASS)
        
        if is_pin_match or is_master_match:
            clear_login_lockout(ip=client_ip, username=u_norm)
            clear_login_attempts(client_ip)
            matched_acc["last_login"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_staff_auth(auth)
            
            user_role = str(matched_acc.get("role", "STAFF")).strip().upper()
            if user_role == "ADMIN":
                token_ver = max(get_admin_token_version(), int(matched_acc.get("token_version", 1)))
            else:
                token_ver = int(matched_acc.get("token_version", 1))

            record_access_audit(matched_key, matched_acc.get("full_name", ""), "LOGIN_SUCCESS", client_ip=client_ip, is_cafe_wifi=is_cafe, user_agent=user_agent, role=user_role)
            token = create_access_token({
                "sub": matched_key,
                "role": user_role,
                "name": matched_acc.get("full_name"),
                "sheet_names": matched_acc.get("sheet_names", [matched_acc.get("full_name")]),
                "ver": token_ver
            })
            return {
                "access_token": token,
                "token_type": "bearer",
                "role": user_role,
                "name": matched_acc.get("full_name"),
                "username": matched_key,
                "ver": token_ver
            }

    # Record failed attempt via Tiered Rate Limit
    if not (client_ip == "testclient" and is_testing_env()):
        failed_info = record_failed_attempt_tiered(
            ip=client_ip, 
            username=u_norm, 
            is_whitelisted_cafe=is_whitelisted_cafe
        )
        tier = failed_info.get("tier", 1)
        
        # Tầng 3: Bắn cảnh báo Telegram ngay lập tức cho Admin!
        if tier == 3:
            try:
                from services.send_telegram import send_telegram_alert
                tgt = failed_info.get("target_key", u_norm)
                store_badge = os.getenv("STORE_NAME", "FNBOPS").upper()
                send_telegram_alert(
                    f"🚨 [CẢNH BÁO AN NINH {store_badge}]\n"
                    f"Phát hiện hành vi dò mã PIN nghiêm trọng!\n"
                    f"• Mục tiêu: {tgt}\n"
                    f"• IP: {client_ip} (WiFi Quán: {'CÓ' if is_whitelisted_cafe else 'KHÔNG'})\n"
                    f"• Đã kích hoạt KHÓA TẦNG 3 (5 TIẾNG).\n"
                    f"• Chỉ duy nhất Chủ quán mới có quyền mở khóa trên Dashboard."
                )
            except Exception:
                pass

    record_access_audit(matched_key or u_raw, (matched_acc.get("full_name") if matched_acc else u_raw), "LOGIN_FAILED", client_ip=client_ip, is_cafe_wifi=is_cafe, user_agent=user_agent, details="Sai mã PIN hoặc tên đăng nhập")
    raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mã PIN")


@router.post("/auth/refresh")
def refresh_session_token(request: Request):
    """
    Sliding Session Refresh Endpoint:
    Validates current active token, checks token_version against identity store,
    and returns a fresh 7-day token maintaining the active ver.
    """
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"}
        )
    raw_token = auth_header.split(" ")[1].strip()
    current_user = get_current_user(raw_token)

    refresh_payload = {
        "sub": current_user.get("sub"),
        "role": current_user.get("role"),
        "name": current_user.get("name"),
        "ver": current_user.get("ver", 1),
    }
    if "sheet_names" in current_user:
        refresh_payload["sheet_names"] = current_user["sheet_names"]

    new_token = create_access_token(refresh_payload, expires_delta=datetime.timedelta(days=7))
    return {
        "access_token": new_token,
        "token_type": "bearer",
        "expires_in": 7 * 24 * 3600,
        "role": current_user.get("role"),
        "name": current_user.get("name"),
        "username": current_user.get("sub"),
        "ver": current_user.get("ver", 1)
    }


@router.post("/auth/logout")
def logout_user(request: Request):
    """
    Revokes the current JWT token immediately.
    Token hash is added to SQLite WAL blacklist table 'revoked_tokens'.
    """
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return {"status": "success", "message": "Đã đăng xuất."}
    token = auth_header.split(" ")[1].strip()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        exp = payload.get("exp")
        sub = payload.get("sub", "unknown")
        revoke_token(token, reason=f"User '{sub}' logged out", expires_at=exp)
    except Exception:
        revoke_token(token, reason="Logged out")
    return {"status": "success", "message": "Đăng xuất thành công. Token đã bị thu hồi tức thì."}


def filter_table_by_names(table_data, name_col_indexes, exact_allowed, allowed_names_norm, header_rows=1):
    if not table_data:
        return []
    
    headers = table_data[:header_rows]
    data_rows = table_data[header_rows:]
    
    kept_rows = []
    for row in data_rows:
        matched = False
        for idx in name_col_indexes:
            if idx < len(row):
                val = str(row[idx]).strip()
                val_nfc = unicodedata.normalize('NFC', val).upper()
                val_norm = normalize_str(val)
                if val_nfc in exact_allowed or val_norm in allowed_names_norm:
                    matched = True
                    break
        if matched:
            kept_rows.append(row)
            
    return headers + kept_rows

@router.get("/data")
def get_data(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    
    user = get_current_user(token)
    role = user.get("role")
    uname = user.get("sub")
    
    data_file = get_data_file()
    if not os.path.exists(data_file):
        raise HTTPException(status_code=404, detail="Không tìm thấy tập tin dữ liệu chấm công.")

    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error reading data")

    auth = load_staff_auth()
    payroll_locks = auth.get("payroll_locks", {})
    acc = auth.get("staff_accounts", {}).get(uname, {})

    # Merge active evaluations into data["SỔ PHỤ"] so all views (Admin/Manager/Staff) reflect evaluations instantly
    evals = load_evaluations()
    if evals and "SỔ PHỤ" in data:
        so_phu = data["SỔ PHỤ"]
        existing_reasons = set()
        for r in so_phu[1:]:
            if len(r) > 6:
                existing_reasons.add(f"{str(r[1]).strip()}_{str(r[2]).strip()}_{str(r[4]).strip()}_{str(r[6]).strip()}")

        for ev in evals:
            # Maker-Checker safeguard: Only approved or active evaluations apply to payroll
            if ev.get("status") not in ["APPROVED", "ACTIVE"]:
                continue
            amt = int(ev.get("amount") or 0)
            if amt <= 0:
                continue
            ev_type = ev.get("type", "Phạt")
            s_name = ev.get("staffName", "")
            ev_date = ev.get("date", "")
            ev_month = str(ev.get("month") or datetime.datetime.now().month)
            ev_reason = ev.get("reason", "")
            mgr = ev.get("manager", "Quản lý")

            check_key = f"{s_name.strip()}_{ev_month.strip()}_{str(amt).strip()}_{ev_reason.strip()}"
            if check_key not in existing_reasons:
                ts_str = f"{ev_date} 00:00:00"
                so_phu.append([
                    ts_str,
                    s_name,
                    ev_month,
                    ev_type,
                    str(amt),
                    "Trừ lương" if ev_type == "Phạt" else "Chuyển khoản",
                    ev_reason,
                    mgr
                ])
                existing_reasons.add(check_key)

        # Merge staff_ledgers from SQLite WAL into data["SỔ PHỤ"]
        try:
            from services.db import list_staff_ledgers
            ledgers = list_staff_ledgers()
            for lg in ledgers:
                s_name = lg.get("staff_name", "")
                lg_month = str(lg.get("month", ""))
                amt = int(lg.get("amount", 0) or 0)
                lg_type = str(lg.get("type", "")).upper()
                type_display = "Tạm ứng" if ("ADVANCE" in lg_type or "UNG" in lg_type) else ("Thưởng" if ("BONUS" in lg_type or "THUONG" in lg_type) else "Phạt")
                lg_reason = lg.get("reason", "")
                created_by = lg.get("created_by", "Admin")
                c_at = lg.get("created_at") or f"2026-{lg_month.zfill(2)}-01 00:00:00"
                check_key = f"{s_name.strip()}_{lg_month.strip()}_{str(amt).strip()}_{lg_reason.strip()}"
                if check_key not in existing_reasons:
                    so_phu.append([
                        c_at,
                        s_name,
                        lg_month,
                        type_display,
                        str(amt),
                        lg.get("payment_method", "Tiền mặt"),
                        lg_reason,
                        created_by
                    ])
                    existing_reasons.add(check_key)
        except Exception as e:
            logger.debug(f"Merge staff_ledgers fallback: {e}")

    # Merge attendance_logs from SQLite WAL into data["DỮ LIỆU"] to guarantee 100% data sync
    try:
        from services.db.connection import get_db_connection
    except ImportError:
        try:
            from backend.services.db.connection import get_db_connection
        except ImportError:
            get_db_connection = None

    if get_db_connection and "DỮ LIỆU" in data:
        try:
            def _norm_time_str(t):
                if not t:
                    return ""
                t = str(t).strip()
                p_t = t.split(":")
                if len(p_t) >= 2:
                    return f"{p_t[0].zfill(2)}:{p_t[1].zfill(2)}"
                return t

            all_accs = auth.get("staff_accounts", {})
            name_to_u = {}
            for u_k, a_v in all_accs.items():
                if isinstance(a_v, dict):
                    name_to_u[normalize_str(u_k)] = u_k
                    name_to_u[normalize_str(a_v.get("full_name", ""))] = u_k
                    for sn in a_v.get("sheet_names", []):
                        name_to_u[normalize_str(sn)] = u_k
                    for al in a_v.get("aliases", []):
                        name_to_u[normalize_str(al)] = u_k

            existing_keys = set()
            for r in data["DỮ LIỆU"][1:]:
                if len(r) >= 6:
                    dt = str(r[1]).strip()
                    nm = normalize_str(r[2])
                    u_matched = name_to_u.get(nm, nm)
                    cin = _norm_time_str(r[4])
                    cout = _norm_time_str(r[5])
                    existing_keys.add(f"{dt}_{u_matched}_{cin}_{cout}")

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT date, full_name, shift, checkin, checkout, duration_mins, note, username 
                FROM attendance_logs 
                ORDER BY id ASC
            """)
            db_logs = cur.fetchall()
            conn.close()

            for row in db_logs:
                dt = str(row["date"] or "").strip()
                if "-" in dt and len(dt) == 10:
                    parts = dt.split("-")
                    dt = f"{parts[2]}/{parts[1]}/{parts[0]}"
                u_row = str(row["username"] or "").strip().lower()
                if not u_row or u_row not in all_accs:
                    u_row = name_to_u.get(normalize_str(row["full_name"]), normalize_str(row["full_name"]))
                cin = _norm_time_str(row["checkin"])
                cout = _norm_time_str(row["checkout"])
                if not cin or not cout or cin == cout:
                    continue
                k = f"{dt}_{u_row}_{cin}_{cout}"
                if k not in existing_keys:
                    dur = str(row["duration_mins"] or 0)
                    sh = str(row["shift"] or "Sáng")
                    fn = str(row["full_name"] or row["username"] or "").strip()
                    note = str(row["note"] or "")
                    month = ""
                    if "/" in dt:
                        p_dt = dt.split("/")
                        if len(p_dt) >= 2:
                            month = str(int(p_dt[1]))
                    stt = str(len(data["DỮ LIỆU"]))
                    data["DỮ LIỆU"].append([stt, dt, fn, sh, cin, cout, dur, note, month, "0", ""])
                    existing_keys.add(k)
        except Exception as e:
            logger.warning(f"Failed to auto-merge SQLite attendance_logs: {e}")

    shift_approvals_map = load_shift_approvals()
    all_accounts = auth.get("staff_accounts", {})
    staff_directory = {}
    for idx, (u_k, a_val) in enumerate(all_accounts.items(), start=1):
        if not isinstance(a_val, dict):
            continue
        staff_directory[u_k] = {
            "employee_id": a_val.get("employee_id") or f"EMP_{idx:03d}",
            "username": u_k,
            "full_name": a_val.get("full_name") or u_k,
            "position": a_val.get("position", "SERVICE"),
            "role": a_val.get("role", "STAFF"),
            "status": a_val.get("status", "ACTIVE"),
            "sheet_names": a_val.get("sheet_names", []),
            "aliases": a_val.get("aliases", [])
        }

    # 1. ADMIN: Full access to all raw tables, wage settings and logs
    if role == "ADMIN":
        data["_meta"] = {
            "role": "ADMIN",
            "payroll_locks": payroll_locks,
            "payroll_verification_open": (get_store_setting_db("payroll_verification_open", "1") == "1"),
            "disbursements": load_disbursements(),
            "shift_approvals": shift_approvals_map,
            "staff_directory": staff_directory,
            "computed_shifts": compute_all_shift_records_server_side(data, shift_approvals_map, all_accounts)
        }
        return data

    # 2. MANAGER: Full access to shifts (DỮ LIỆU, ĐÁNH GIÁ, SỔ PHỤ) for OT approvals & ops check,
    # BUT mask other employees' wages/salaries in NHÂN VIÊN table for privacy
    if role == "MANAGER":
        manager_data = json.loads(json.dumps(data))
        
        # Build self match criteria for Manager
        sheet_names = acc.get("sheet_names") or user.get("sheet_names") or [user.get("name", "")]
        self_names_norm = set([normalize_str(sn) for sn in sheet_names])
        self_names_norm.add(normalize_str(user.get("name", "")))
        self_names_norm.add(normalize_str(acc.get("full_name", "")))
        self_names_norm.add(normalize_str(uname))

        nv_tab = manager_data.get("NHÂN VIÊN", [])
        if len(nv_tab) > 2:
            # Mask total budget in row 1
            if len(nv_tab) > 1 and len(nv_tab[1]) > 4:
                nv_tab[1][4] = "***"

            # Mask other employees' wage columns (col 3: LƯƠNG/GIỜ, col 4: TỔNG LƯƠNG)
            for r_idx in range(3, len(nv_tab)):
                row = nv_tab[r_idx]
                if len(row) > 1:
                    emp_name = str(row[1]).strip()
                    if normalize_str(emp_name) not in self_names_norm:
                        if len(row) > 3:
                            row[3] = 0
                        if len(row) > 4:
                            row[4] = 0

            # Also mask right table (CÀI ĐẶT LƯƠNG: col 6 name, col 7 wage)
            for r_idx in range(2, len(nv_tab)):
                row = nv_tab[r_idx]
                if len(row) > 6:
                    emp_name = str(row[6]).strip()
                    if normalize_str(emp_name) not in self_names_norm:
                        if len(row) > 7:
                            row[7] = 0

        manager_data["_meta"] = {
            "role": "MANAGER",
            "username": uname,
            "employee_id": acc.get("employee_id", ""),
            "full_name": acc.get("full_name", user.get("name")),
            "payroll_locks": payroll_locks,
            "payroll_verification_open": (get_store_setting_db("payroll_verification_open", "1") == "1"),
            "disbursements": load_disbursements(),
            "confirmations": acc.get("confirmations", {}),
            "shift_approvals": shift_approvals_map,
            "staff_directory": staff_directory,
            "computed_shifts": compute_all_shift_records_server_side(
                manager_data, shift_approvals_map, {uname: acc} if uname else {}
            )
        }
        return manager_data

    # 3. STAFF: Strict privacy filter (only their own records)
    sheet_names = acc.get("sheet_names") or user.get("sheet_names") or [user.get("name", "")]
    aliases = acc.get("aliases", [])
    exact_allowed = set([unicodedata.normalize('NFC', str(sn)).strip().upper() for sn in sheet_names])
    exact_allowed.add(unicodedata.normalize('NFC', str(user.get("name", ""))).strip().upper())
    exact_allowed.add(unicodedata.normalize('NFC', str(acc.get("full_name", ""))).strip().upper())
    for a in aliases:
        exact_allowed.add(unicodedata.normalize('NFC', str(a)).strip().upper())

    allowed_norm = set([normalize_str(sn) for sn in sheet_names])
    allowed_norm.add(normalize_str(user.get("name", "")))
    allowed_norm.add(normalize_str(uname))
    for a in aliases:
        allowed_norm.add(normalize_str(a))

    filtered_data = {}
    
    nv_tab = data.get("NHÂN VIÊN", [])
    if len(nv_tab) > 2:
        headers_left = nv_tab[2]
        idx_name = next((i for i, h in enumerate(headers_left) if str(h).strip() in ["TÊN NHÂN VIÊN", "Tên Nhân Viên"]), -1)
        if idx_name != -1:
            filtered_data["NHÂN VIÊN"] = filter_table_by_names(nv_tab, [idx_name], exact_allowed, allowed_norm, header_rows=3)
        else:
            filtered_data["NHÂN VIÊN"] = nv_tab
    else:
        filtered_data["NHÂN VIÊN"] = nv_tab

    dl_tab = data.get("DỮ LIỆU", [])
    if len(dl_tab) > 0:
        headers = dl_tab[0]
        idx_name = next((i for i, h in enumerate(headers) if str(h).strip() in ["Tên Nhân Viên", "TÊN NHÂN VIÊN", "Nhân Viên"]), 2)
        filtered_data["DỮ LIỆU"] = filter_table_by_names(dl_tab, [idx_name], exact_allowed, allowed_norm, header_rows=1)
    else:
        filtered_data["DỮ LIỆU"] = dl_tab

    dg_tab = data.get("ĐÁNH GIÁ", [])
    if len(dg_tab) > 0:
        headers = dg_tab[0]
        idx_name = next((i for i, h in enumerate(headers) if str(h).strip() in ["Nhân Viên", "Tên Nhân Viên"]), -1)
        if idx_name != -1:
            filtered_data["ĐÁNH GIÁ"] = filter_table_by_names(dg_tab, [idx_name], exact_allowed, allowed_norm, header_rows=1)
        else:
            filtered_data["ĐÁNH GIÁ"] = dg_tab
    else:
        filtered_data["ĐÁNH GIÁ"] = dg_tab

    sp_tab = data.get("SỔ PHỤ", [])
    if len(sp_tab) > 0:
        headers = sp_tab[0]
        idx_name = next((i for i, h in enumerate(headers) if str(h).strip() in ["Tên nhân sự", "Tên Nhân Viên", "Nhân Viên"]), -1)
        if idx_name != -1:
            filtered_data["SỔ PHỤ"] = filter_table_by_names(sp_tab, [idx_name], exact_allowed, allowed_norm, header_rows=1)
        else:
            filtered_data["SỔ PHỤ"] = sp_tab
    else:
        filtered_data["SỔ PHỤ"] = sp_tab

    filtered_data["_meta"] = {
        "role": "STAFF",
        "username": uname,
        "employee_id": acc.get("employee_id", ""),
        "full_name": acc.get("full_name", user.get("name")),
        "payroll_locks": payroll_locks,
        "payroll_verification_open": (get_store_setting_db("payroll_verification_open", "1") == "1"),
        "disbursements": load_disbursements(),
        "confirmations": acc.get("confirmations", {}),
        "shift_approvals": shift_approvals_map,
        "staff_directory": {uname: staff_directory[uname]} if uname in staff_directory else {},
        "computed_shifts": compute_all_shift_records_server_side(
            filtered_data, shift_approvals_map, {uname: acc} if uname else {}
        )
    }

    return filtered_data

# =========================================================================
# MOUNT EXTRACTED MODULAR ROUTERS
# =========================================================================
from routers.staff import router as staff_router
from routers.evaluation import router as evaluation_router
from routers.disbursement import router as disbursement_router

router.include_router(staff_router)
router.include_router(evaluation_router)
router.include_router(disbursement_router)

# Re-export route handlers for backward compatibility
from routers.staff import (
    get_staff_accounts,
    update_pin,
    toggle_staff_status,
    update_staff_profile,
    create_staff_account,
    get_admin_lockouts,
    admin_unlock,
    get_admin_lockouts as get_lockouts,
    admin_unlock as unlock_target,
)
from routers.evaluation import (
    record_staff_evaluation,
    record_staff_evaluation as submit_staff_evaluation,
    proxy_eval_webhook,
    proxy_eval_webhook as eval_webhook,
    review_staff_evaluation,
    get_staff_evaluations,
    load_evaluations,
    save_evaluations,
)
from routers.disbursement import (
    toggle_lock,
    confirm_payroll,
    get_shift_approvals,
    confirm_ot,
    get_staff_ledger_entries,
    create_staff_ledger_entry,
    delete_staff_ledger_entry,
    get_payroll_summary,
    get_payroll_summary_alias,
    get_payroll_disbursements,
    toggle_payroll_disbursement,
    get_so_cai_luong_events,
)

# =========================================================================
# STORE CONFIGURATION ENDPOINTS (MULTI-SHOP CUSTOMIZATION)
# =========================================================================

@router.get("/store/config")
def get_store_configuration(request: Request):
    """
    Lấy cấu hình quán động: Giờ ca, định biên, ngày lễ, chế độ POS.
    Chỉ tài khoản Admin chính mới có quyền xem thông tin cấu hình nhạy cảm (Telegram/Zalo tokens).
    Các vai trò khác chỉ nhận cấu hình vận hành công khai, đã lọc sạch credentials.
    """
    try:
        from services.store_config import get_store_config
        cfg = get_store_config()
        
        # Kiểm tra vai trò của người gọi
        auth_header = request.headers.get("Authorization")
        is_admin = False
        if auth_header and auth_header.startswith("Bearer "):
            try:
                token = auth_header.split(" ")[1]
                user = get_current_user(token)
                is_admin = (user.get("role") == "ADMIN")
            except Exception:
                is_admin = False

        # Nếu không phải Admin, lọc bỏ 100% secrets và token thông báo
        if not is_admin:
            import copy
            cfg = copy.deepcopy(cfg)
            if "notifications" in cfg:
                cfg["notifications"] = {
                    "telegram": {"enabled": bool(cfg.get("notifications", {}).get("telegram", {}).get("enabled", False))},
                    "zalo": {"enabled": bool(cfg.get("notifications", {}).get("zalo", {}).get("enabled", False))}
                }

        return {
            "success": True,
            "config": cfg
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể đọc cấu hình quán: {e}")


@router.post("/store/config")
def update_store_configuration(request: Request, config_data: StoreConfigUpdate):
    """
    Cập nhật cấu hình quán: Chỉ dành riêng cho Chủ quán (Admin).
    Cho phép tùy biến giờ ca, định biên nhân sự, ngưỡng lệch POS, ngày lễ.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền thay đổi cấu hình quán.")

    try:
        from services.store_config import save_store_config, get_store_config
        current = get_store_config()
        current.update(config_data.model_dump(exclude_unset=True))
        save_store_config(current)
        return {
            "success": True,
            "message": "Đã cập nhật cấu hình quán thành công.",
            "config": current
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi lưu cấu hình quán: {e}")


@router.post("/store/config/reset")
def reset_store_configuration(request: Request):
    """
    Khôi phục cấu hình quán mặc định ban đầu (FnBOps Standard).
    Chỉ dành riêng cho Admin.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền khôi phục cấu hình.")

    try:
        from services.store_config import save_store_config, DEFAULT_STORE_CONFIG
        import json
        default_cfg = json.loads(json.dumps(DEFAULT_STORE_CONFIG))
        save_store_config(default_cfg)
        return {
            "success": True,
            "message": "Đã khôi phục cấu hình mặc định WFM thành công.",
            "config": default_cfg
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi khôi phục cấu hình: {e}")


@router.post("/store/test-telegram")
def test_telegram_notification(request: Request, payload: Optional[Dict[str, Any]] = None):
    """
    Kiểm tra kết nối Telegram bot và chat_id.
    Có bảo vệ Anti-Spam Guard chặn token bot chính.
    Chỉ dành riêng cho Chủ quán (Admin).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền kiểm tra Telegram Gateway.")

    try:
        from services.send_telegram import test_telegram_connection
        data = payload or {}
        bot_token = data.get("bot_token")
        chat_id = data.get("chat_id")
        ok, msg = test_telegram_connection(bot_token=bot_token, chat_id=chat_id)
        return {
            "success": ok,
            "message": msg
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Lỗi khi kiểm tra kết nối Telegram: {e}"
        }


@router.get("/store/zalo-status")
def get_zalo_status(request: Request):
    """
    Truy vấn trạng thái kết nối của Zalo Gateway.
    Chỉ dành riêng cho Chủ quán (Admin).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền xem trạng thái Zalo Gateway.")

    if os.getenv("TESTING") == "1":
        return {
            "status": "ready",
            "connected": True,
            "user": {"id": "test_zalo_id", "name": "FnBOps Test"}
        }

    gateway_url = os.getenv("ZALO_GATEWAY_URL", "http://zalo-gateway:8177").rstrip("/")
    gw_token = os.getenv("ZALO_GATEWAY_TOKEN", "").strip()
    gw_headers = {"User-Agent": "FastAPI-Backend"}
    if gw_token:
        gw_headers["X-Zalo-Gateway-Token"] = gw_token
    import urllib.request
    for target in [f"{gateway_url}/api/zalo/status", "http://127.0.0.1:8177/api/zalo/status"]:
        try:
            req = urllib.request.Request(target, headers=gw_headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue

    return {
        "status": "disconnected",
        "connected": False,
        "message": "Không thể kết nối đến Zalo Gateway microservice (:8177)"
    }


@router.get("/store/zalo-qr")
def get_zalo_qr(request: Request):
    """
    Truy vấn mã QR đăng nhập Zalo Web.
    Chỉ dành riêng cho Chủ quán (Admin).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền truy cập mã QR Zalo.")

    if os.getenv("TESTING") == "1":
        return {
            "success": True,
            "connected": False,
            "status": "waiting_qr",
            "qr": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            "message": "Mã QR Zalo Web đã sẵn sàng"
        }

    gateway_url = os.getenv("ZALO_GATEWAY_URL", "http://zalo-gateway:8177").rstrip("/")
    gw_token = os.getenv("ZALO_GATEWAY_TOKEN", "").strip()
    gw_headers = {"User-Agent": "FastAPI-Backend"}
    if gw_token:
        gw_headers["X-Zalo-Gateway-Token"] = gw_token
    import urllib.request
    for target in [f"{gateway_url}/api/zalo/qr", "http://127.0.0.1:8177/api/zalo/qr"]:
        try:
            req = urllib.request.Request(target, headers=gw_headers)
            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue

    return {
        "success": False,
        "message": "Không thể lấy mã QR: Zalo Gateway microservice chưa khởi động."
    }


@router.post("/admin/safe-backup")
async def trigger_safe_backup(request: Request):
    """
    Kích hoạt sao lưu an toàn CSDL SQLite trong chế độ WAL (Write-Ahead Logging).
    Sử dụng sqlite3.Connection.backup() API, không làm gián đoạn hay lock DB.
    Chỉ dành riêng cho Chủ quán (Admin).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền sao lưu CSDL.")

    try:
        import asyncio
        import datetime
        from services.db import safe_sqlite_backup
        backup_path = await asyncio.to_thread(safe_sqlite_backup)
        import os
        filename = os.path.basename(backup_path)
        file_size = os.path.getsize(backup_path) if os.path.exists(backup_path) else 0
        return {
            "success": True,
            "message": f"Sao lưu SQLite an toàn thành công ({filename}).",
            "backup_file": filename,
            "backup_path": backup_path,
            "file_size_bytes": file_size,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        logger.exception(f"Lỗi khi thực hiện safe backup: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi sao lưu: {e}")


@router.get("/admin/export-json-snapshot")
async def export_json_snapshot(request: Request):
    """
    On-Demand Snapshot Export:
    Trích xuất toàn bộ dữ liệu hiện hành từ SQLite WAL (Single Source of Truth) ra bản chụp JSON theo yêu cầu.
    Chỉ dành riêng cho Chủ quán (Admin).
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền xuất bản chụp dữ liệu.")

    try:
        from services.db import (
            list_staff_accounts,
            list_evaluations,
            get_daily_closings,
            list_roster_schedules_db,
            get_payroll_disbursements_db,
            list_shift_approvals_db,
            load_staff_auth_from_sqlite
        )
        from services.attendance_service import load_attendance_logs_from_sqlite
        from services.store_config import get_store_config

        snapshot = {
            "exported_at": datetime.datetime.now().isoformat(),
            "staff_auth": load_staff_auth_from_sqlite(),
            "attendance_logs": load_attendance_logs_from_sqlite(),
            "roster_schedules": list_roster_schedules_db(),
            "daily_closings": get_daily_closings(limit=1000),
            "evaluations": list_evaluations(),
            "store_config": get_store_config(),
            "disbursements": get_payroll_disbursements_db(),
            "shift_approvals": list_shift_approvals_db()
        }
        return {
            "success": True,
            "message": "Trích xuất bản chụp JSON từ SQLite thành công (On-Demand).",
            "data": snapshot
        }
    except Exception as e:
        logger.exception(f"Lỗi khi xuất snapshot: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khi xuất snapshot: {e}")


@router.get("/admin/staff-offboarding-status")
async def get_staff_offboarding_status_endpoint(
    request: Request,
    staff_name: str = Query(..., description="Tên nhân viên cần kiểm tra offboarding"),
    month: Optional[str] = Query(None, description="Kỳ lương cần đối soát")
):
    """
    Offboarding Gate (ADR-011):
    Kiểm tra tình trạng công nợ và quyết toán của nhân viên trước khi thôi việc hoặc khóa sổ.
    Chỉ dành riêng cho Quản lý / Admin.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") not in ("ADMIN", "MANAGER"):
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Chủ quán mới có quyền kiểm tra quyết toán thôi việc.")

    try:
        try:
            from backend.services.payroll_calc import check_staff_offboarding_status
            from backend.services.storage import safe_json_read
            from backend.services.auth import load_staff_auth
            from backend.services.db import list_so_cai_luong
            from backend.services.store_config import get_store_config
        except ImportError:
            from services.payroll_calc import check_staff_offboarding_status
            from services.storage import safe_json_read
            from services.auth import load_staff_auth
            from services.db import list_so_cai_luong
            from services.store_config import get_store_config

        data_file = get_data_file()
        data_json = safe_json_read(data_file, default={}) if os.path.exists(data_file) else {}
        auth_data = load_staff_auth()
        accounts = auth_data.get("staff_accounts", {})
        so_cai = list_so_cai_luong(month=month)
        store_cfg = get_store_config()

        status = check_staff_offboarding_status(
            staff_name=staff_name,
            target_month=month,
            data_json=data_json,
            staff_accounts=accounts,
            so_cai_luong=so_cai,
            store_config=store_cfg
        )
        return {"success": True, "data": status}
    except Exception as e:
        logger.exception(f"Lỗi khi kiểm tra offboarding status: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi máy chủ: {e}")


class AutoUpdateTogglePayload(BaseModel):
    enabled: bool


@router.get("/system/update-status")
async def get_system_update_status(request: Request):
    """
    Lấy thông tin phiên bản hiện tại, trạng thái cập nhật và cờ tự động cập nhật.
    """
    try:
        from backend.services.updater import get_update_config
    except ImportError:
        from services.updater import get_update_config
    return get_update_config()


@router.post("/system/check-update")
async def check_system_update(request: Request):
    """
    Kiểm tra phiên bản mới nhất từ GitHub Releases (hoặc offline cache).
    """
    try:
        from backend.services.updater import check_for_updates
    except ImportError:
        from services.updater import check_for_updates
    return check_for_updates()


@router.post("/system/apply-update")
async def apply_system_update(request: Request):
    """
    Thực thi Cập nhật 1-Click:
    - Tự động sao lưu an toàn SQLite Database trước khi nâng cấp
    - Kéo mã nguồn mới nhất (git pull --ff-only / update release)
    - Bảo toàn 100% dữ liệu quán trong data/
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền thực thi cập nhật.")

    try:
        from backend.services.updater import apply_update
    except ImportError:
        from services.updater import apply_update
    import asyncio
    return await asyncio.to_thread(apply_update)


@router.post("/system/auto-update-toggle")
async def toggle_auto_update(payload: AutoUpdateTogglePayload, request: Request):
    """
    Bật / Tắt chế độ tự động cập nhật hệ thống (Toggle 'Tự động cập nhật').
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header.split(" ")[1]
    user = get_current_user(token)
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ Chủ quán (Admin) mới có quyền đổi cài đặt cập nhật.")

    try:
        from backend.services.updater import set_auto_update_toggle
    except ImportError:
        from services.updater import set_auto_update_toggle
    return set_auto_update_toggle(payload.enabled)


@router.get("/system/installers-info")
async def get_installers_info():
    """
    Thông tin các gói cài đặt đa nền tảng (macOS, Windows, Mobile PWA).
    """
    return {
        "status": "success",
        "platforms": {
            "mac": {
                "name": "macOS",
                "filename": "run_mac.command",
                "download_url": "/api/v1/cc/system/download-installer/mac",
                "instruction": "Nhấp đúp vào file run_mac.command để khởi động server và mở trình duyệt web tự động.",
                "type": "script"
            },
            "windows": {
                "name": "Windows (POS & PC)",
                "filename": "run_windows.bat",
                "download_url": "/api/v1/cc/system/download-installer/windows",
                "instruction": "Nhấp đúp vào file run_windows.bat để khởi động server và mở trình duyệt web tự động.",
                "type": "batch"
            },
            "mobile": {
                "name": "Điện thoại (iOS / Android)",
                "manifest_url": "/manifest.json",
                "instruction": "Mở trình duyệt trên điện thoại truy cập web -> Chọn 'Thêm vào màn hình chính' (Add to Home Screen) để cài app toàn màn hình.",
                "type": "pwa"
            }
        }
    }


@router.get("/system/download-installer/{target_os}")
async def download_installer(target_os: str):
    """
    Tải file script khởi chạy 1-Click cho máy tính (Mac / Windows).
    """
    from fastapi.responses import FileResponse
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    target = target_os.lower().strip()
    if target in ("mac", "macos", "darwin"):
        file_path = os.path.join(base_dir, "run_mac.command")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File run_mac.command không tồn tại")
        return FileResponse(file_path, filename="run_mac.command", media_type="application/x-sh")
    elif target in ("win", "windows"):
        file_path = os.path.join(base_dir, "run_windows.bat")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File run_windows.bat không tồn tại")
        return FileResponse(file_path, filename="run_windows.bat", media_type="application/x-bat")
    else:
        raise HTTPException(status_code=400, detail=f"Hệ điều hành '{target_os}' không được hỗ trợ (chỉ hỗ trợ 'mac' hoặc 'windows')")
