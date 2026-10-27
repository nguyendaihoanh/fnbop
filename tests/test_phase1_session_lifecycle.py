"""
Test Suite for Phase 1: Authentication & Session Lifecycle Security
Validates:
1. PIN update immediately revokes all prior active tokens (token_version bump).
2. Privilege Creep Neutralization: Real-time role override from persistent store.
3. Strict Admin Identity Binding: Rejects spoofed sub claims for ADMIN role.
4. Hard Reset of Legacy Sessions: Immediate 401 for tokens lacking 'ver'.
5. Sliding Session Refresh Endpoint: Cấp token mới với hạn 7 ngày duy trì ver.
6. Admin Global Version Bump: Immediate revocation of all issued admin tokens.
7. Staff Status Deactivation: Immediate session invalidation.
8. Zero PIN leakage in update-pin response.
"""

import os
import sys
import uuid
import datetime
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure backend directory is in path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Load environment or provide test secret
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_backend_dir, ".env"))
    load_dotenv(os.path.join(_project_root, ".env"))
except ImportError:
    pass

if not os.getenv("JWT_SECRET_KEY"):
    os.environ["JWT_SECRET_KEY"] = "phase1_test_jwt_secret_key_strictly_enforced_2026"

from services.auth import (
    create_access_token,
    get_current_user,
    load_staff_auth,
    save_staff_auth,
    get_admin_token_version,
    increment_admin_token_version,
    bump_staff_token_version,
    SECRET_KEY,
    ALGORITHM,
    VALID_ADMIN_SUBS
)
from services.db import (
    init_db,
    upsert_staff_account,
    get_staff_token_version,
    get_admin_token_version_db,
    increment_admin_token_version_db,
)
from routers.fnb_ops import router as cc_router
from routers.staff import router as staff_router

# Build test FastAPI app
test_app = FastAPI()
test_app.include_router(cc_router)
test_app.include_router(staff_router, prefix="/api/v1/cc")
client = TestClient(test_app)


@pytest.fixture(autouse=True)
def setup_teardown_auth_env():
    """Ensure clean auth environment and restore original data after tests."""
    init_db()
    auth = load_staff_auth()
    accounts = auth.setdefault("staff_accounts", {})

    # Seed test accounts
    accounts["staff_phase1_test"] = {
        "full_name": "Nhân Viên Test Phase 1",
        "pin": "1234",
        "role": "STAFF",
        "status": "ACTIVE",
        "token_version": 1,
        "aliases": ["staff_phase1_test"],
        "sheet_names": ["Nhân Viên Test Phase 1"]
    }
    accounts["mgr_phase1_test"] = {
        "full_name": "Quản Lý Test Phase 1",
        "pin": "4321",
        "role": "MANAGER",
        "status": "ACTIVE",
        "token_version": 1,
        "aliases": ["mgr_phase1_test"],
        "sheet_names": ["Quản Lý Test Phase 1"]
    }
    save_staff_auth(auth)
    upsert_staff_account(
        username="staff_phase1_test",
        full_name="Nhân Viên Test Phase 1",
        pin_hash="1234",
        role="STAFF",
        status="ACTIVE",
        token_version=1
    )
    upsert_staff_account(
        username="mgr_phase1_test",
        full_name="Quản Lý Test Phase 1",
        pin_hash="4321",
        role="MANAGER",
        status="ACTIVE",
        token_version=1
    )
    yield
    # Cleanup test accounts
    auth = load_staff_auth()
    accs = auth.get("staff_accounts", {})
    accs.pop("staff_phase1_test", None)
    accs.pop("mgr_phase1_test", None)
    save_staff_auth(auth)


# =========================================================================
# TEST 1: Đổi PIN nhân viên -> Token cũ bị từ chối 401 ngay lập tức
# =========================================================================
def test_update_pin_immediately_revokes_old_token():
    # 1. Cấp token ban đầu cho nhân viên với token_version = 1
    token_v1 = create_access_token({
        "sub": "staff_phase1_test",
        "role": "STAFF",
        "name": "Nhân Viên Test Phase 1",
        "ver": 1
    })
    # Token ban đầu hợp lệ
    user_data = get_current_user(token_v1)
    assert user_data["sub"] == "staff_phase1_test"
    assert user_data["ver"] == 1

    # 2. Tạo admin token để thực hiện đổi PIN
    admin_token = create_access_token({
        "sub": "admin",
        "role": "ADMIN",
        "name": "Admin Test",
        "ver": get_admin_token_version()
    })

    # 3. Đổi PIN qua endpoint /api/v1/cc/admin/update-pin
    res = client.post(
        "/api/v1/cc/admin/update-pin",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "staff_phase1_test", "new_pin": "9999"}
    )
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["success"] is True
    # Khẳng định 100% không lộ mã PIN trong response trả về!
    assert "pin" not in res_data
    assert "9999" not in res_data.get("message", "")

    # 4. Kiểm tra token cũ (v1) ngay lập tức bị từ chối 401
    with pytest.raises(Exception) as exc_info:
        get_current_user(token_v1)
    assert "401" in str(exc_info.value)
    assert "Phiên đăng nhập đã hết hạn" in str(exc_info.value)

    # 5. Gọi thử một endpoint yêu cầu xác thực bằng token cũ -> Phải nhận HTTP 401
    refresh_res = client.post(
        "/api/v1/cc/auth/refresh",
        headers={"Authorization": f"Bearer {token_v1}"}
    )
    assert refresh_res.status_code == 401


# =========================================================================
# TEST 2: Giáng chức Manager xuống Staff -> Token cũ bị hạ role tức thì
# =========================================================================
def test_demote_manager_neutralizes_privilege_creep():
    # 1. Cấp token vai trò MANAGER
    mgr_token = create_access_token({
        "sub": "mgr_phase1_test",
        "role": "MANAGER",
        "name": "Quản Lý Test Phase 1",
        "ver": 1
    })
    # Ban đầu token có role MANAGER
    decoded = get_current_user(mgr_token)
    assert decoded["role"] == "MANAGER"

    # 2. Admin giáng chức nhân sự này xuống STAFF trong nguồn sự thật
    auth = load_staff_auth()
    auth["staff_accounts"]["mgr_phase1_test"]["role"] = "STAFF"
    save_staff_auth(auth)
    upsert_staff_account(
        username="mgr_phase1_test",
        full_name="Quản Lý Test Phase 1",
        role="STAFF",
        token_version=1
    )

    # 3. Kẻ gian dùng token cũ (vốn ghi role=MANAGER) để gọi xác thực
    # Hệ thống PHẢI khử Privilege Creep: ghi đè lại role từ store là STAFF!
    sanitized_user = get_current_user(mgr_token)
    assert sanitized_user["role"] == "STAFF"

    # 4. Thử dùng token cũ gọi endpoint chỉ dành cho Quản lý/Admin
    # Phải bị chặn với HTTP 403 Forbidden vì role đã bị hạ xuống STAFF
    admin_action_res = client.get(
        "/api/v1/cc/admin/staff-accounts",
        headers={"Authorization": f"Bearer {mgr_token}"}
    )
    assert admin_action_res.status_code == 403


# =========================================================================
# TEST 3: Token Admin với sub giả mạo -> Bị từ chối 401
# =========================================================================
def test_admin_token_identity_binding_rejects_spoofed_sub():
    admin_ver = get_admin_token_version()

    # 1. Token Admin với sub hợp lệ (admin, chu_quan, wfm_admin)
    valid_admin_token = create_access_token({
        "sub": "admin",
        "role": "ADMIN",
        "name": "Chủ Quán Hợp Lệ",
        "ver": admin_ver
    })
    valid_user = get_current_user(valid_admin_token)
    assert valid_user["role"] == "ADMIN"
    assert valid_user["sub"] == "admin"

    # 2. Token Admin giả mạo sub (ví dụ: attacker, nhanvien, hacker)
    spoofed_admin_token = jwt.encode(
        {
            "sub": "attacker_impersonating_admin",
            "role": "ADMIN",
            "name": "Kẻ Giả Mạo",
            "ver": admin_ver,
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        },
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    with pytest.raises(Exception) as exc_info:
        get_current_user(spoofed_admin_token)
    assert "401" in str(exc_info.value)
    assert "Danh tính Quản trị viên không hợp lệ" in str(exc_info.value)


# =========================================================================
# TEST 4: Token cũ thiếu trường 'ver' -> Bị từ chối 401 (Hard Reset)
# =========================================================================
def test_legacy_token_missing_ver_triggers_hard_reset():
    # Giả lập token được cấp từ phiên bản cũ (chưa có trường ver)
    legacy_payload = {
        "sub": "staff_phase1_test",
        "role": "STAFF",
        "name": "Nhân Viên Test Phase 1",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
    }
    legacy_token = jwt.encode(legacy_payload, SECRET_KEY, algorithm=ALGORITHM)

    # get_current_user bắt buộc phải từ chối 401 với thông báo quy chuẩn
    with pytest.raises(Exception) as exc_info:
        get_current_user(legacy_token)
    assert "401" in str(exc_info.value)
    assert "tiêu chuẩn an ninh mới" in str(exc_info.value)

    # Thử qua HTTP endpoint
    res = client.post(
        "/api/v1/cc/auth/refresh",
        headers={"Authorization": f"Bearer {legacy_token}"}
    )
    assert res.status_code == 401


# =========================================================================
# TEST 5: Endpoint /auth/refresh -> Cấp token mới với hạn 7 ngày
# =========================================================================
def test_sliding_session_refresh_endpoint_success():
    # 1. Đăng nhập hoặc cấp token hợp lệ hiện tại
    active_token = create_access_token({
        "sub": "staff_phase1_test",
        "role": "STAFF",
        "name": "Nhân Viên Test Phase 1",
        "sheet_names": ["Nhân Viên Test Phase 1"],
        "ver": 1
    })

    # 2. Gọi endpoint refresh
    res = client.post(
        "/api/v1/cc/auth/refresh",
        headers={"Authorization": f"Bearer {active_token}"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["ver"] == 1
    assert data["expires_in"] == 7 * 24 * 3600

    # 3. Giải mã token mới để kiểm tra exp và trường an ninh jti, iat
    new_token = data["access_token"]
    decoded = jwt.decode(new_token, SECRET_KEY, algorithms=[ALGORITHM])
    assert decoded["ver"] == 1
    assert "jti" in decoded
    assert "iat" in decoded
    assert decoded["sub"] == "staff_phase1_test"

    # Kiểm tra thời hạn exp xấp xỉ 7 ngày tính từ bây giờ
    now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
    exp_ts = decoded["exp"]
    diff_days = (exp_ts - now_ts) / (24 * 3600)
    assert 6.9 < diff_days <= 7.1


# =========================================================================
# TEST 6: Admin Token Version Bump -> Vô hiệu hóa toàn bộ session Admin cũ
# =========================================================================
def test_admin_token_version_bump_invalidates_old_admin_sessions():
    initial_ver = get_admin_token_version()
    admin_token_v1 = create_access_token({
        "sub": "admin",
        "role": "ADMIN",
        "name": "Admin Session",
        "ver": initial_ver
    })

    # Khẳng định token ban đầu hoạt động
    assert get_current_user(admin_token_v1)["role"] == "ADMIN"

    # Admin kích hoạt tăng version (Global Admin Session Bump)
    new_admin_ver = increment_admin_token_version()
    assert new_admin_ver == initial_ver + 1

    # Token v1 ngay lập tức bị từ chối 401
    with pytest.raises(Exception) as exc_info:
        get_current_user(admin_token_v1)
    assert "401" in str(exc_info.value)
    assert "Phiên đăng nhập Quản trị viên đã hết hạn" in str(exc_info.value)

    # Token mới tạo với new_admin_ver hoạt động bình thường
    admin_token_v2 = create_access_token({
        "sub": "admin",
        "role": "ADMIN",
        "name": "Admin Session Fresh",
        "ver": new_admin_ver
    })
    assert get_current_user(admin_token_v2)["role"] == "ADMIN"


# =========================================================================
# TEST 7: Chuyển nhân viên sang INACTIVE -> Tăng token_version & chặn session
# =========================================================================
def test_toggle_staff_status_to_inactive_revokes_session():
    # 1. Cấp token hợp lệ
    token_before = create_access_token({
        "sub": "staff_phase1_test",
        "role": "STAFF",
        "name": "Nhân Viên Test Phase 1",
        "ver": 1
    })
    assert get_current_user(token_before)["sub"] == "staff_phase1_test"

    # 2. Admin gọi toggle sang INACTIVE
    admin_token = create_access_token({
        "sub": "admin",
        "role": "ADMIN",
        "name": "Admin Test",
        "ver": get_admin_token_version()
    })
    toggle_res = client.post(
        "/api/v1/cc/admin/toggle-staff-status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "staff_phase1_test", "status": "INACTIVE"}
    )
    assert toggle_res.status_code == 200

    # 3. Token cũ bị từ chối ngay lập tức
    with pytest.raises(Exception) as exc_info:
        get_current_user(token_before)
    # Bị từ chối vì token_version đã tăng hoặc tài khoản INACTIVE
    err_msg = str(exc_info.value)
    assert "401" in err_msg or "403" in err_msg
