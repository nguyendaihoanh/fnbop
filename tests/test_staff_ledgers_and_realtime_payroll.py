import os
import sys
import tempfile
import json
import pytest
from fastapi.testclient import TestClient

_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Set test environment
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_key_super_secure_32_bytes_long_123"
os.environ["DATA_FILE"] = os.path.join(_project_root, "data", "data.json")

from main import app
from services.db import init_db, insert_staff_ledger, list_staff_ledgers, delete_staff_ledger
from routers.fnb_ops import create_access_token


@pytest.fixture
def temp_environment():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump([], f)
        att_logs_path = f.name

    orig_db = os.environ.get("DATABASE_PATH")
    orig_att = os.environ.get("ATTENDANCE_LOGS_FILE")
    os.environ["DATABASE_PATH"] = db_path
    os.environ["ATTENDANCE_LOGS_FILE"] = att_logs_path
    init_db(db_path)

    yield {"db_path": db_path, "att_logs_path": att_logs_path}

    for ext in ["", "-wal", "-shm"]:
        p = f"{db_path}{ext}"
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    if os.path.exists(att_logs_path):
        try:
            os.remove(att_logs_path)
        except Exception:
            pass
    if orig_db is not None:
        os.environ["DATABASE_PATH"] = orig_db
    else:
        os.environ.pop("DATABASE_PATH", None)
    if orig_att is not None:
        os.environ["ATTENDANCE_LOGS_FILE"] = orig_att
    else:
        os.environ.pop("ATTENDANCE_LOGS_FILE", None)


def test_staff_ledger_rbac_and_crud(temp_environment):
    client = TestClient(app)

    staff_token = create_access_token(data={"sub": "nhanvien03", "name": "Nhân Viên 03", "role": "STAFF"})
    manager_token = create_access_token(data={"sub": "manager", "name": "Quản Lý Ca", "role": "MANAGER"})

    # 1. STAFF cannot POST /payroll/ledger (Must be 403 Forbidden)
    res = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"staff_name": "Nhân Viên 03", "month": "9", "type": "bonus", "amount": 100000}
    )
    assert res.status_code == 403

    # 2. MANAGER can POST /payroll/ledger
    res = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={
            "staff_name": "Nhân Viên 03",
            "month": "9",
            "type": "bonus",
            "amount": 150000,
            "payment_method": "bank",
            "reason": "Thưởng pha chế xuất sắc tuần 2"
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    ledger_id = data["entry"]["id"]

    # 3. Add advance for another staff
    res2 = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={
            "staff_name": "Nhân Viên 02",
            "month": "9",
            "type": "advance",
            "amount": 200000,
            "payment_method": "cash",
            "reason": "Ứng tiền mặt mua đồng phục"
        }
    )
    assert res2.status_code == 200

    # 4. STAFF can only see their own ledgers
    res_staff = client.get(
        "/api/v1/cc/payroll/ledger?month=9",
        headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert res_staff.status_code == 200
    staff_data = res_staff.json()
    assert staff_data["count"] == 1
    assert staff_data["ledgers"][0]["staff_name"] == "Nhân Viên 03"
    assert staff_data["summary"]["total_bonus"] == 150000
    assert staff_data["summary"]["total_advance"] == 0

    # 5. MANAGER can see all ledgers
    res_mgr = client.get(
        "/api/v1/cc/payroll/ledger?month=9",
        headers={"Authorization": f"Bearer {manager_token}"}
    )
    assert res_mgr.status_code == 200
    mgr_data = res_mgr.json()
    assert mgr_data["count"] == 2
    assert mgr_data["summary"]["total_bonus"] == 150000
    assert mgr_data["summary"]["total_advance"] == 200000

    # 6. MANAGER is blocked from deleting entry (403 Forbidden - only ADMIN can delete)
    res_del_mgr = client.delete(
        f"/api/v1/cc/payroll/ledger/{ledger_id}",
        headers={"Authorization": f"Bearer {manager_token}"}
    )
    assert res_del_mgr.status_code == 403

    # 7. ADMIN deletes entry successfully
    admin_token = create_access_token(data={"sub": "admin", "name": "Admin", "role": "ADMIN"})
    res_del = client.delete(
        f"/api/v1/cc/payroll/ledger/{ledger_id}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert res_del.status_code == 200

    # Verify deletion
    res_after = client.get(
        "/api/v1/cc/payroll/ledger?month=9",
        headers={"Authorization": f"Bearer {manager_token}"}
    )
    assert res_after.json()["count"] == 1
    assert res_after.json()["ledgers"][0]["staff_name"] == "Nhân Viên 02"


def test_realtime_attendance_and_ledger_in_payroll_summary(temp_environment):
    client = TestClient(app)
    manager_token = create_access_token(data={"sub": "manager", "name": "Quản Lý Ca", "role": "MANAGER"})

    # 1. Baseline summary for nhanvien (NHANVIEN)
    res_base = client.get(
        "/api/v1/cc/payroll/summary?month=9&staff_name=NHANVIEN",
        headers={"Authorization": f"Bearer {manager_token}"}
    )
    assert res_base.status_code == 200
    base_b = res_base.json()["breakdown"]
    base_shifts = base_b["total_shifts"]

    # 2. Add an advance of 50,000đ in staff_ledgers
    client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={
            "staff_name": "Nhân Viên Phục Vụ",
            "month": "9",
            "type": "advance",
            "amount": 50000,
            "reason": "Ứng tiền test"
        }
    )

    # 3. Add a completed shift into attendance_logs.json
    new_shift = {
        "id": "ATT_TEST_001",
        "username": "nhanvien",
        "display_name": "Nhân Viên Phục Vụ",
        "role": "Phục vụ",
        "date": "15/09/2026",
        "shift_key": "toi",
        "shift_name": "Ca Tối",
        "checkin_time": "18:00",
        "checkout_time": "23:00",
        "total_mins": 300,
        "hourly_rate_snapshot": 17000,
        "is_late": False,
        "late_mins": 0,
        "status": "ON_TIME"
    }
    with open(temp_environment["att_logs_path"], "w", encoding="utf-8") as f:
        json.dump([new_shift], f)

    # 4. Check updated summary
    res_updated = client.get(
        "/api/v1/cc/payroll/summary?month=9&staff_name=NHANVIEN",
        headers={"Authorization": f"Bearer {manager_token}"}
    )
    assert res_updated.status_code == 200
    up_b = res_updated.json()["breakdown"]

    # Shift count must increase by 1
    assert up_b["total_shifts"] == base_shifts + 1
    # Advance amount must reflect 50,000đ
    assert up_b["advance_amount"] == 50000
    # Additional 300 mins (5 hrs) at snapshot wage 17,000đ/hr = 85,000đ
    # Minus advance of 50,000đ
    assert up_b["standard_pay"] == base_b["standard_pay"] + 85000
    assert up_b["net_pay"] == base_b["net_pay"] + 85000 - 50000
