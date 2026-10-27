import os
import sys
import json
import pytest
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
os.environ["ON_PREMISE_MODE"] = "true"

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.join(project_root, "backend")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from routers.fnb_ops import create_access_token
from routers.roster import load_roster_data, save_roster_data, get_active_and_next_week_ids

client = TestClient(app)

@pytest.fixture
def admin_token():
    return create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})

@pytest.fixture
def manager_token():
    return create_access_token({"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})

@pytest.fixture
def staff_token():
    return create_access_token({"sub": "nhanvien", "role": "STAFF", "name": "Nhân Viên"})


def test_clone_roster_requires_auth():
    res = client.post("/api/v1/cc/roster/clone-previous-week", json={"target_week_id": "2026-W40"})
    assert res.status_code == 401

def test_clone_roster_forbidden_for_staff(staff_token):
    res = client.post(
        "/api/v1/cc/roster/clone-previous-week",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"target_week_id": "2026-W40"}
    )
    assert res.status_code == 403

def test_clone_roster_source_missing_error(manager_token):
    res = client.post(
        "/api/v1/cc/roster/clone-previous-week",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"target_week_id": "2099-W02", "source_week_id": "2099-W01"}
    )
    assert res.status_code == 400
    assert "Không tìm thấy dữ liệu ca trực của tuần nguồn" in res.json()["detail"]

def test_clone_roster_success(manager_token):
    # Setup test source week
    source_week_id = "2026-W38"
    target_week_id = "2026-W39"

    roster_data = load_roster_data()
    weeks = roster_data.setdefault("weeks", {})

    # Mock source week with distinctive assignments
    weeks[source_week_id] = {
        "week_id": source_week_id,
        "start_date": "2026-09-14",
        "end_date": "2026-09-20",
        "status": "PUBLISHED",
        "shifts": {
            "2026-09-14": {
                "morning": {"time": "06:00 - 11:30", "manager": "manager", "barista": "phache", "service": ["nhanvien", "nhanvien01"]},
                "evening": {"time": "17:00 - 23:00", "manager": "manager", "barista": None, "service_17": "nhanvien02", "service_18": "nhanvien03"}
            },
            "2026-09-15": {
                "morning": {"time": "06:00 - 11:30", "manager": "manager", "barista": "phache", "service": ["nhanvien04", "nhanvien05"]},
                "evening": {"time": "17:00 - 23:00", "manager": "manager", "barista": None, "service_17": "nhanvien06", "service_18": "nhanvien03"}
            }
        }
    }
    # Clear target week if exists
    if target_week_id in weeks:
        del weeks[target_week_id]
    save_roster_data(roster_data)

    # Call clone endpoint
    res = client.post(
        "/api/v1/cc/roster/clone-previous-week",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"target_week_id": target_week_id, "source_week_id": source_week_id}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["target_week_id"] == target_week_id
    assert body["source_week_id"] == source_week_id

    # Verify persisted data in target week
    updated_data = load_roster_data()
    target_week = updated_data["weeks"].get(target_week_id)
    assert target_week is not None
    assert target_week["status"] == "DRAFT"

    # Corresponding days mapped: Monday 2026-09-14 -> Monday 2026-09-21
    mon_target = target_week["shifts"].get("2026-09-21")
    assert mon_target is not None
    assert mon_target["morning"]["barista"] == "phache"
    assert mon_target["morning"]["service"] == ["nhanvien", "nhanvien01"]
    assert mon_target["evening"]["service_17"] == "nhanvien02"

    # Tuesday 2026-09-15 -> Tuesday 2026-09-22
    tue_target = target_week["shifts"].get("2026-09-22")
    assert tue_target is not None
    assert tue_target["morning"]["service"] == ["nhanvien04", "nhanvien05"]
