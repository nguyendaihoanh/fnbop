"""
Test Suite: Admin Manager Role Configuration & RBAC Shields
Verifies:
1. Admin can create staff account with role='MANAGER' or role='STAFF'.
2. Manager creating account cannot grant role='MANAGER' (forced to 'STAFF').
3. Creating accounts with reserved admin usernames is strictly rejected.
4. Admin can update role from 'STAFF' to 'MANAGER' and vice versa.
5. Token version is incremented on role change (preventing privilege creep).
6. Manager cannot modify Admin or other Manager profiles (HTTP 403).
7. Manager cannot grant bonus/advance to themselves (Anti-conflict of interest, HTTP 403).
8. Admin can grant bonus/advance to Manager (HTTP 200).
"""

import os
import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.auth import create_access_token, load_staff_auth, save_staff_auth, get_admin_token_version
from backend.services.db import init_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_auth_env(tmp_path, monkeypatch):
    test_auth_file = str(tmp_path / "staff_auth.json")
    test_db_path = str(tmp_path / "test_fnbop.db")

    init_auth_data = {
        "admin": {
            "pin": "pbkdf2_sha256$100000$testsalt$5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
            "full_name": "Chủ Quán (Admin)"
        },
        "staff_accounts": {
            "staff_alice": {
                "full_name": "Alice Barista",
                "pin": "1111",
                "role": "STAFF",
                "position": "BARISTA",
                "status": "ACTIVE",
                "aliases": ["alice"],
                "token_version": 1
            },
            "manager_bob": {
                "full_name": "Bob Quản Lý",
                "pin": "2222",
                "role": "MANAGER",
                "position": "MANAGER",
                "status": "ACTIVE",
                "aliases": ["bob"],
                "token_version": 1
            },
            "manager_carol": {
                "full_name": "Carol Quản Lý 2",
                "pin": "3333",
                "role": "MANAGER",
                "position": "MANAGER",
                "status": "ACTIVE",
                "aliases": ["carol"],
                "token_version": 1
            }
        }
    }

    with open(test_auth_file, "w", encoding="utf-8") as f:
        json.dump(init_auth_data, f)

    monkeypatch.setenv("AUTH_FILE", test_auth_file)
    monkeypatch.setenv("SQLITE_DB_PATH", test_db_path)
    monkeypatch.setenv("DATABASE_PATH", test_db_path)
    monkeypatch.setenv("JWT_SECRET_KEY", "super-secret-key-for-test-suit-40291")
    monkeypatch.setenv("ENABLE_MASTER_STAFF_PASS", "false")

    init_db(test_db_path)

    yield


def test_admin_create_staff_account_with_manager_role():
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán", "ver": get_admin_token_version()})
    
    # 1. Admin tạo tài khoản có role MANAGER
    payload = {
        "username": "david_mgr",
        "pin": "9999",
        "full_name": "David Quản Lý",
        "position": "MANAGER",
        "role": "MANAGER",
        "gender": "NAM"
    }
    res = client.post(
        "/api/v1/cc/admin/create-staff-account",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=payload
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["account"]["role"] == "MANAGER"

    # Kiểm tra persistence
    auth = load_staff_auth()
    assert auth["staff_accounts"]["davidmgr"]["role"] == "MANAGER"


def test_manager_cannot_create_manager_account():
    manager_token = create_access_token({"sub": "manager_bob", "role": "MANAGER", "name": "Bob Quản Lý", "ver": 1})

    # Manager cố tình tạo tài khoản có role MANAGER
    payload = {
        "username": "eve_staff",
        "pin": "8591",
        "full_name": "Eve Nhân Viên",
        "position": "MANAGER",
        "role": "MANAGER",
        "gender": "NU"
    }
    res = client.post(
        "/api/v1/cc/admin/create-staff-account",
        headers={"Authorization": f"Bearer {manager_token}"},
        json=payload
    )
    assert res.status_code == 200, res.text
    data = res.json()
    # Phải bị ép về STAFF
    assert data["account"]["role"] == "STAFF"

    auth = load_staff_auth()
    assert auth["staff_accounts"]["evestaff"]["role"] == "STAFF"


def test_create_account_reserved_admin_usernames_rejected():
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán", "ver": get_admin_token_version()})

    for bad_u in ["admin", "chu_quan", "root", "system"]:
        payload = {
            "username": bad_u,
            "pin": "7842",
            "full_name": "Fake Admin",
            "position": "BARISTA"
        }
        res = client.post(
            "/api/v1/cc/admin/create-staff-account",
            headers={"Authorization": f"Bearer {admin_token}"},
            json=payload
        )
        assert res.status_code == 400
        assert "dành riêng cho quản trị hệ thống" in res.json()["detail"]


def test_admin_update_staff_to_manager_and_back():
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán", "ver": get_admin_token_version()})

    auth_before = load_staff_auth()
    ver_before = auth_before["staff_accounts"]["staff_alice"]["token_version"]

    # 1. Nâng Alice lên MANAGER
    res = client.post(
        "/api/v1/cc/admin/update-staff-profile",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "staff_alice", "role": "MANAGER"}
    )
    assert res.status_code == 200
    auth_after_1 = load_staff_auth()
    assert auth_after_1["staff_accounts"]["staff_alice"]["role"] == "MANAGER"
    assert auth_after_1["staff_accounts"]["staff_alice"]["token_version"] == ver_before + 1

    # 2. Hạ Alice về STAFF
    res = client.post(
        "/api/v1/cc/admin/update-staff-profile",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "staff_alice", "role": "STAFF"}
    )
    assert res.status_code == 200
    auth_after_2 = load_staff_auth()
    assert auth_after_2["staff_accounts"]["staff_alice"]["role"] == "STAFF"
    assert auth_after_2["staff_accounts"]["staff_alice"]["token_version"] == ver_before + 2


def test_manager_cannot_modify_admin_or_other_manager():
    manager_token = create_access_token({"sub": "manager_bob", "role": "MANAGER", "name": "Bob Quản Lý", "ver": 1})

    # 1. Manager cố tình sửa profile của Carol (Manager khác)
    res = client.post(
        "/api/v1/cc/admin/update-staff-profile",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"username": "manager_carol", "pin": "9999"}
    )
    assert res.status_code == 403
    assert "Quản lý không có quyền chỉnh sửa hồ sơ của Quản trị viên hoặc Quản lý khác" in res.json()["detail"]

    # 2. Manager cố tình đổi PIN của Carol
    res = client.post(
        "/api/v1/cc/admin/update-pin",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"username": "manager_carol", "new_pin": "9999"}
    )
    assert res.status_code == 403
    assert "Quản lý không có quyền đổi PIN của Quản trị viên hoặc Quản lý khác" in res.json()["detail"]

    # 3. Manager cố tình đổi status của Carol sang INACTIVE
    res = client.post(
        "/api/v1/cc/admin/toggle-staff-status",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"username": "manager_carol", "status": "INACTIVE"}
    )
    assert res.status_code == 403
    assert "Quản lý không có quyền thay đổi trạng thái của Quản trị viên hoặc Quản lý khác" in res.json()["detail"]


def test_manager_self_ledger_conflict_of_interest():
    manager_token = create_access_token({"sub": "manager_bob", "role": "MANAGER", "name": "Bob Quản Lý", "ver": 1})
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán", "ver": get_admin_token_version()})

    # 1. Manager tự thưởng cho chính mình (theo username hoặc full_name) -> Bị chặn 403
    res = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={
            "staff_name": "Bob Quản Lý",
            "type": "bonus",
            "amount": 500000,
            "reason": "Tự thưởng cho bản thân",
            "month": "10"
        }
    )
    assert res.status_code == 403
    assert "Xung đột lợi ích" in res.json()["detail"]

    # 2. Manager tự ứng lương cho chính mình -> Bị chặn 403
    res = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={
            "staff_name": "manager_bob",
            "type": "advance",
            "amount": 1000000,
            "reason": "Tự ứng tiền",
            "month": "10"
        }
    )
    assert res.status_code == 403
    assert "Xung đột lợi ích" in res.json()["detail"]

    # 3. Manager ghi sổ phụ cho nhân viên Alice -> Thành công 200
    res = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={
            "staff_name": "Alice Barista",
            "type": "bonus",
            "amount": 200000,
            "reason": "Thưởng doanh số",
            "month": "10"
        }
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 4. Admin thưởng cho Manager Bob -> Thành công 200
    res = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "staff_name": "Bob Quản Lý",
            "type": "bonus",
            "amount": 1000000,
            "reason": "Chủ quán thưởng quản lý xuất sắc",
            "month": "10"
        }
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
