# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
import os
import sys
import re
import uuid
import datetime
import unicodedata
from typing import Any, Dict, Optional, Union
import jwt
from fastapi import HTTPException

from services.storage import safe_json_read, safe_json_write
from services.db import is_token_revoked

# Dynamic fallback paths for production / container / local
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_dir = os.path.dirname(_base_dir)
_env_path = os.path.join(_root_dir, ".env")
_env_example_path = os.path.join(_root_dir, ".env.example")
_PLACEHOLDER_SECRET = "CHANGE_ME_TO_A_SECURE_RANDOM_STRING_AT_LEAST_32_CHARS"


def ensure_bootstrap_jwt_secret() -> Optional[str]:
    """Auto-bootstrap .env with a 256-bit JWT_SECRET_KEY on first run while preserving fail-closed security."""
    if "JWT_SECRET_KEY" in os.environ and not os.environ["JWT_SECRET_KEY"].strip():
        return ""
    data_dir = os.getenv("DATA_DIR", "").strip()
    data_env_path = os.path.join(data_dir, ".env") if data_dir and os.path.isdir(data_dir) else None
    try:
        from dotenv import load_dotenv
        if data_env_path and os.path.exists(data_env_path):
            load_dotenv(data_env_path, override=False)
        load_dotenv(_env_path, override=False)
        load_dotenv(override=False)
    except ImportError:
        pass
    val = os.getenv("JWT_SECRET_KEY")
    if (val is None and not os.path.exists(_env_path)) or (val and val.strip() == _PLACEHOLDER_SECRET):
        import secrets
        new_secret = secrets.token_hex(32)
        try:
            if os.path.exists(_env_path):
                with open(_env_path, "r", encoding="utf-8") as f:
                    content = f.read()
                content = content.replace(_PLACEHOLDER_SECRET, new_secret)
            elif os.path.exists(_env_example_path):
                with open(_env_example_path, "r", encoding="utf-8") as f:
                    content = f.read()
                content = content.replace(_PLACEHOLDER_SECRET, new_secret)
            else:
                content = f"JWT_SECRET_KEY={new_secret}\nON_PREMISE_MODE=true\n"
            with open(_env_path, "w", encoding="utf-8") as f:
                f.write(content)
            if data_env_path and os.path.abspath(data_dir) != os.path.join(_root_dir, "data"):
                with open(data_env_path, "w", encoding="utf-8") as f:
                    f.write(content)
        except OSError:
            pass
        os.environ["JWT_SECRET_KEY"] = new_secret
        return new_secret
    return val


# Fail-Closed JWT Secret enforcement (with first-run auto-bootstrap)
_env_jwt_secret = ensure_bootstrap_jwt_secret()
if not _env_jwt_secret or not _env_jwt_secret.strip():
    raise RuntimeError("CRITICAL BẢO MẬT: JWT_SECRET_KEY là bắt buộc trong .env. Hệ thống từ chối khởi động ở trạng thái mất an toàn.")
SECRET_KEY = _env_jwt_secret.strip()

ALGORITHM = "HS256"

# Valid Admin Identities for Strict Identity Binding
VALID_ADMIN_SUBS = {"admin", "chu_quan", "wfm_admin"}

DEFAULT_AUTH_FILE = os.path.join(_root_dir, "data", "staff_auth.json")


def _get_root_data_dir() -> str:
    if os.getenv("DATA_DIR"):
        return os.getenv("DATA_DIR")
    if _root_dir and _root_dir != "/" and os.path.exists(os.path.join(_root_dir, "data")):
        return os.path.join(_root_dir, "data")
    return os.path.join(_base_dir, "data")


def get_auth_file() -> str:
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


def normalize_str(s: str) -> str:
    if not s:
        return ""
    s = str(s).strip()
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.replace('đ', 'd').replace('Đ', 'd')
    s = re.sub(r'[^a-zA-Z0-9]', '', s)
    return s.lower()


def load_staff_auth() -> Dict[str, Any]:
    # 0. Test Override: Only active in TESTING=1 when strict no-json guard is not enforced
    auth_env = os.getenv("AUTH_FILE")
    if (
        os.getenv("TESTING") == "1"
        and os.getenv("ENABLE_RUNTIME_JSON_SYNC") != "false"
        and auth_env
        and os.path.exists(auth_env)
    ):
        data = safe_json_read(auth_env, default={"payroll_locks": {}, "staff_accounts": {}})
        accounts = data.get("staff_accounts", {})
        if isinstance(accounts, dict):
            for idx, (u_key, acc) in enumerate(accounts.items(), start=1):
                if isinstance(acc, dict) and not acc.get("employee_id"):
                    acc["employee_id"] = f"EMP_{idx:03d}"
        return data

    # 1. Primary Source of Truth: Read directly from SQLite relational database (WAL Mode)
    try:
        from services.db import load_staff_auth_from_sqlite
        db_data = load_staff_auth_from_sqlite()
        if db_data and db_data.get("staff_accounts"):
            return db_data
    except Exception:
        pass

    # 2. Seamless Fallback: Read legacy JSON file if SQLite has not been initialized yet
    data = safe_json_read(get_auth_file(), default={"payroll_locks": {}, "staff_accounts": {}})
    accounts = data.get("staff_accounts", {})
    if isinstance(accounts, dict):
        for idx, (u_key, acc) in enumerate(accounts.items(), start=1):
            if isinstance(acc, dict) and not acc.get("employee_id"):
                acc["employee_id"] = f"EMP_{idx:03d}"
    
    # Auto-bootstrap to SQLite if JSON has accounts
    if accounts:
        try:
            from services.db import bootstrap_sync_staff_auth_to_sqlite
            bootstrap_sync_staff_auth_to_sqlite(data)
        except Exception:
            pass

    return data


def save_staff_auth(data: Dict[str, Any]) -> bool:
    accounts = data.get("staff_accounts", {}) if isinstance(data, dict) else {}
    if isinstance(accounts, dict):
        for idx, (u_key, acc) in enumerate(accounts.items(), start=1):
            if isinstance(acc, dict) and not acc.get("employee_id"):
                acc["employee_id"] = f"EMP_{idx:03d}"
    
    # 1. Primary Sync to SQLite ACID relational store (Mandatory Single Source of Truth)
    try:
        from services.db import bootstrap_sync_staff_auth_to_sqlite
        bootstrap_sync_staff_auth_to_sqlite(data)
    except Exception:
        pass

    # 2. Test isolation override (only active in TESTING=1 when strict no-json guard is not enforced)
    _real_data_dir = os.path.join(_root_dir, "data")
    auth_env = os.getenv("AUTH_FILE")
    if (
        os.getenv("TESTING") == "1"
        and os.getenv("ENABLE_RUNTIME_JSON_SYNC") != "false"
        and auth_env
        and not os.path.abspath(auth_env).startswith(_real_data_dir)
    ):
        return safe_json_write(auth_env, data)

    # 3. Decoupled runtime JSON: Tuyệt đối CẤM GHI file trong data/ trừ khi bật cờ rõ ràng ENABLE_RUNTIME_JSON_SYNC=true
    try:
        from services.storage import is_runtime_json_sync_enabled
        if is_runtime_json_sync_enabled():
            return safe_json_write(get_auth_file(), data)
    except Exception:
        pass

    return True


def get_admin_token_version() -> int:
    """Gets current admin_token_version from store_settings."""
    try:
        from services.db import get_admin_token_version_db
        return get_admin_token_version_db()
    except Exception:
        try:
            from services.db import get_store_setting_db
            return int(get_store_setting_db("admin_token_version", "1"))
        except Exception:
            return 1


def increment_admin_token_version() -> int:
    """Atomically increments admin_token_version."""
    try:
        from services.db import increment_admin_token_version_db
        return increment_admin_token_version_db()
    except Exception:
        try:
            from services.db import get_store_setting_db, update_store_setting_db
            curr = int(get_store_setting_db("admin_token_version", "1") or 1)
            nxt = curr + 1
            update_store_setting_db("admin_token_version", str(nxt), updated_by="admin")
            return nxt
        except Exception:
            return 2


def bump_staff_token_version(username: str) -> int:
    """Increments staff token_version in both staff_auth.json and SQLite staff_accounts."""
    auth = load_staff_auth()
    accounts = auth.get("staff_accounts", {})
    u_norm = normalize_str(username)
    target_key = username if username in accounts else u_norm
    if target_key not in accounts:
        for k, a in accounts.items():
            if username.lower() == k.lower() or u_norm == normalize_str(k) or u_norm in [normalize_str(al) for al in a.get("aliases", [])]:
                target_key = k
                break

    new_ver = 2
    if target_key in accounts:
        curr_ver = int(accounts[target_key].get("token_version", 1))
        new_ver = curr_ver + 1
        accounts[target_key]["token_version"] = new_ver
        save_staff_auth(auth)

    try:
        from services.db import bump_staff_token_version_db
        db_ver = bump_staff_token_version_db(target_key)
        if db_ver > new_ver:
            new_ver = db_ver
    except Exception:
        pass
    return new_ver


def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    """
    Creates a JWT access token embedding security fields:
    - ver: Token version for instant revocation & sliding session tracking.
    - jti: Unique random nonce per token.
    - iat: Issue Unix timestamp.
    - exp: Expiration datetime (default 7 days).
    """
    to_encode = data.copy()

    # Resolve token version if not explicitly provided
    if "ver" not in to_encode:
        role = str(to_encode.get("role", "")).strip().upper()
        sub = str(to_encode.get("sub", "")).strip()
        if role == "ADMIN" or sub.lower() in VALID_ADMIN_SUBS:
            to_encode["ver"] = get_admin_token_version()
        elif sub:
            auth = load_staff_auth()
            accounts = auth.get("staff_accounts", {})
            u_norm = normalize_str(sub)
            target_acc = accounts.get(sub) or accounts.get(u_norm)
            if not target_acc:
                for k, a in accounts.items():
                    if sub.lower() == k.lower() or u_norm == normalize_str(k) or u_norm in [normalize_str(al) for al in a.get("aliases", [])]:
                        target_acc = a
                        break
            if target_acc:
                to_encode["ver"] = int(target_acc.get("token_version", 1))
            else:
                to_encode["ver"] = 1
        else:
            to_encode["ver"] = 1
    else:
        try:
            to_encode["ver"] = int(to_encode["ver"])
        except (ValueError, TypeError):
            to_encode["ver"] = 1

    # Inject unique jti and issue timestamp iat
    if "jti" not in to_encode:
        to_encode["jti"] = uuid.uuid4().hex
    if "iat" not in to_encode:
        to_encode["iat"] = int(datetime.datetime.now(datetime.timezone.utc).timestamp())

    # Sliding/default expiration: 7 days
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24*7) # 7 days
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user(token: str) -> Dict[str, Any]:
    if not token or not str(token).strip():
        raise HTTPException(status_code=401, detail="Token không được để trống")
    clean_token = str(token).strip()
    if is_token_revoked(clean_token):
        raise HTTPException(
            status_code=401,
            detail="Token đã bị thu hồi hoặc phiên đăng nhập đã kết thúc.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        payload = jwt.decode(clean_token, SECRET_KEY, algorithms=[ALGORITHM])

        # Bắt buộc kiểm tra trường 'ver' trong payload (Hard Reset cơ chế cũ)
        if "ver" not in payload:
            raise HTTPException(
                status_code=401,
                detail="Phiên đăng nhập đã hết hạn theo tiêu chuẩn an ninh mới. Vui lòng đăng nhập lại.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        try:
            token_ver = int(payload["ver"])
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=401,
                detail="Phiên đăng nhập đã hết hạn theo tiêu chuẩn an ninh mới. Vui lòng đăng nhập lại.",
                headers={"WWW-Authenticate": "Bearer"}
            )

        sub = payload.get("sub")
        token_role = str(payload.get("role", "")).strip().upper()

        auth = load_staff_auth()
        accounts = auth.get("staff_accounts", {})
        u_norm = normalize_str(sub) if sub else ""
        target_acc = (accounts.get(sub) or accounts.get(u_norm)) if sub else None
        if not target_acc and sub:
            for k, a in accounts.items():
                if sub.lower() == k.lower() or u_norm == normalize_str(k) or u_norm in [normalize_str(al) for al in a.get("aliases", [])]:
                    target_acc = a
                    break

        # 1. RÀNG BUỘC DANH TÍNH & PHIÊN BẢN CHO ADMIN
        if token_role == "ADMIN":
            is_valid_admin = False
            if sub and str(sub).strip().lower() in VALID_ADMIN_SUBS:
                is_valid_admin = True
            elif target_acc and str(target_acc.get("role", "")).strip().upper() == "ADMIN":
                is_valid_admin = True

            if not is_valid_admin:
                raise HTTPException(
                    status_code=401,
                    detail="Danh tính Quản trị viên không hợp lệ.",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            admin_ver = get_admin_token_version()
            if target_acc and target_acc.get("token_version"):
                admin_ver = max(admin_ver, int(target_acc.get("token_version", 1)))

            if token_ver < admin_ver:
                raise HTTPException(
                    status_code=401,
                    detail="Phiên đăng nhập Quản trị viên đã hết hạn hoặc đã bị thu hồi. Vui lòng đăng nhập lại.",
                    headers={"WWW-Authenticate": "Bearer"}
                )
            return payload

        # 2. XỬ LÝ NHÂN VIÊN & QUẢN LÝ (KHỬ PRIVILEGE CREEP + TOKEN VERSION CHECK)
        if token_role in ["STAFF", "MANAGER"] and sub:
            if not target_acc:
                if os.environ.get("TESTING") == "1":
                    target_acc = {
                        "role": token_role,
                        "full_name": payload.get("name", sub),
                        "token_version": token_ver,
                        "status": "ACTIVE"
                    }
                else:
                    raise HTTPException(
                        status_code=401,
                        detail="Tài khoản không tồn tại hoặc đã bị thu hồi quyền.",
                        headers={"WWW-Authenticate": "Bearer"}
                    )

            current_staff_ver = int(target_acc.get("token_version", 1))
            if token_ver < current_staff_ver:
                raise HTTPException(
                    status_code=401,
                    detail="Phiên đăng nhập đã hết hạn do mã PIN hoặc quyền hạn tài khoản đã thay đổi. Vui lòng đăng nhập lại.",
                    headers={"WWW-Authenticate": "Bearer"}
                )

            if target_acc.get("status", "ACTIVE").strip().upper() == "INACTIVE":
                raise HTTPException(
                    status_code=403, 
                    detail="Tài khoản này đã bị vô hiệu hóa hoặc nhân viên đã nghỉ việc. Vui lòng liên hệ Quản lý."
                )

            # KHỬ PRIVILEGE CREEP & BẢO VỆ NGUYÊN TẮC LEAST PRIVILEGE:
            # - Nếu tài khoản trong DB là STAFF -> Hạ role xuống STAFF (ngăn Privilege Creep)
            # - Nếu tài khoản trong DB là MANAGER nhưng token xin scope STAFF -> Giữ STAFF (Least Privilege)
            acc_role = str(target_acc.get("role", "STAFF")).strip().upper()
            if acc_role == "STAFF":
                payload["role"] = "STAFF"
            elif acc_role == "MANAGER":
                payload["role"] = "STAFF" if token_role == "STAFF" else "MANAGER"
            else:
                payload["role"] = acc_role

            payload["name"] = target_acc.get("full_name") or payload.get("name")
            token_sheets = payload.get("sheet_names") if isinstance(payload.get("sheet_names"), list) else []
            db_sheets = target_acc.get("sheet_names", [target_acc.get("full_name")])
            payload["sheet_names"] = list(dict.fromkeys(db_sheets + token_sheets))
            payload["aliases"] = target_acc.get("aliases", [])

        return payload
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired", headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token", headers={"WWW-Authenticate": "Bearer"})


def verify_token(token: str) -> Dict[str, Any]:
    """Helper alias for get_current_user"""
    return get_current_user(token)

