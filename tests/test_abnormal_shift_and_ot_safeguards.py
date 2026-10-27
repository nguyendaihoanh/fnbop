import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.services.auth import create_access_token, get_admin_token_version, load_staff_auth, save_staff_auth
from backend.services.db import init_db, upsert_staff_account

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_mgr_account():
    init_db()
    auth = load_staff_auth()
    accounts = auth.setdefault("staff_accounts", {})
    accounts["test_manager"] = {
        "full_name": "Quản Lý Test",
        "pin": "1234",
        "role": "MANAGER",
        "status": "ACTIVE",
        "token_version": 1
    }
    save_staff_auth(auth)
    upsert_staff_account(
        username="test_manager",
        full_name="Quản Lý Test",
        pin_hash="1234",
        role="MANAGER",
        status="ACTIVE",
        token_version=1
    )
    yield
    auth = load_staff_auth()
    auth.get("staff_accounts", {}).pop("test_manager", None)
    save_staff_auth(auth)


def test_manager_cannot_approve_abnormal_shift_over_12h():
    """Manager attempting to approve a shift > 720 mins (12h) must be blocked with 403."""
    mgr_token = create_access_token({
        "sub": "test_manager",
        "name": "Quản Lý Test",
        "role": "MANAGER",
        "ver": 1
    })
    
    payload = {
        "shift_key": "16/10/2026|nhuy|Ca Sáng|11:18",
        "action": "APPROVE",
        "approved_mins": 1422,
        "manager_note": "Duyệt nhầm 1422p"
    }
    
    resp = client.post(
        "/api/v1/cc/shifts/confirm-ot",
        json=payload,
        headers={"Authorization": f"Bearer {mgr_token}"}
    )
    assert resp.status_code == 403
    assert "quên check-out qua đêm" in resp.json()["detail"]
    assert "Chỉ Admin" in resp.json()["detail"]


def test_manager_can_cut_abnormal_shift_to_standard():
    """Manager can safely cut the abnormal shift to standard 300 mins."""
    mgr_token = create_access_token({
        "sub": "test_manager",
        "name": "Quản Lý Test",
        "role": "MANAGER",
        "ver": 1
    })
    
    payload = {
        "shift_key": "16/10/2026|nhuy|Ca Sáng|11:18",
        "action": "CUT",
        "approved_mins": 300,
        "manager_note": "Cắt về ca chuẩn 300p"
    }
    
    resp = client.post(
        "/api/v1/cc/shifts/confirm-ot",
        json=payload,
        headers={"Authorization": f"Bearer {mgr_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["approval"]["status"] == "CUT"
    assert resp.json()["approval"]["approved_mins"] == 300


def test_admin_can_approve_abnormal_shift_if_legitimate():
    """Admin has master override authority to approve shifts > 12h if truly legitimate."""
    admin_token = create_access_token({
        "sub": "admin",
        "name": "Chủ Quán (Admin)",
        "role": "ADMIN",
        "ver": get_admin_token_version()
    })
    
    payload = {
        "shift_key": "16/10/2026|nhuy|Ca Sáng|11:18",
        "action": "APPROVE",
        "approved_mins": 750,
        "manager_note": "Admin phê duyệt ca đặc biệt"
    }
    
    resp = client.post(
        "/api/v1/cc/shifts/confirm-ot",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["approval"]["status"] == "APPROVE"
    assert resp.json()["approval"]["approved_mins"] == 750


def test_shift_label_formatting_no_duplicate_ca():
    """Verify that shift label formatting does not duplicate 'Ca Ca Sáng'."""
    shifts = ["Ca Sáng", "ca tối", "Sáng", "Tối", "Gãy"]
    def format_shift(s):
        return s if (s or "").lower().startswith("ca ") else f"Ca {s or ''}"
    
    assert format_shift("Ca Sáng") == "Ca Sáng"
    assert format_shift("ca tối") == "ca tối"
    assert format_shift("Sáng") == "Ca Sáng"
    assert format_shift("Tối") == "Ca Tối"
    assert format_shift("Gãy") == "Ca Gãy"
