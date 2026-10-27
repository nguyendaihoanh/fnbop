"""
Tests for FnBOps_Core v2.0 Architecture Upgrade (4 Phases):
- Phase 1: SQLite wfm.db Unified Storage & Canonical employee_id (EMP_001...)
- Phase 2: Backend Payroll Single Source of Truth (_meta.computed_shifts & employee_id)
- Phase 3: Timefold-Inspired Roster Solver (Anti-Clopening & 1-Step Swap Backtracking) + Open Shifts Marketplace
- Phase 4: Self-Service Attendance Explanation Requests (Frappe-style Workflow)
"""

import os
import sys
import json
import pytest

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
_BACKEND_DIR = os.path.join(_ROOT_DIR, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi.testclient import TestClient

try:
    from main import app
    from routers.fnb_ops import create_access_token
    from services.db import (
        init_db,
        upsert_staff_account,
        get_staff_directory_map,
        resolve_employee_id,
        upsert_shift_approval_db,
        list_shift_approvals_db
    )
    from services.payroll_calc import compute_all_shift_records_server_side
    from routers.roster import auto_assign_week_schedule
except ImportError:
    from backend.main import app
    from backend.routers.fnb_ops import create_access_token
    from backend.services.db import (
        init_db,
        upsert_staff_account,
        get_staff_directory_map,
        resolve_employee_id,
        upsert_shift_approval_db,
        list_shift_approvals_db
    )
    from backend.services.payroll_calc import compute_all_shift_records_server_side
    from backend.routers.roster import auto_assign_week_schedule


client = TestClient(app)


def test_phase1_sqlite_employee_id_and_shift_approvals(tmp_path):
    """Verify SQLite auto-assigns EMP_001, EMP_002 and stores shift_approvals."""
    db_file = str(tmp_path / "test_v2.db")
    init_db(db_file)

    upsert_staff_account(username="phat", full_name="PHÁT", role="MANAGER", position="MANAGER", db_path=db_file)
    upsert_staff_account(username="nhuy", full_name="NHANVIEN01", role="STAFF", position="BARISTA", db_path=db_file)

    directory = get_staff_directory_map(db_path=db_file)
    assert "phat" in directory
    assert "nhuy" in directory
    assert directory["phat"]["employee_id"].startswith("EMP_")
    assert directory["nhuy"]["employee_id"].startswith("EMP_")
    assert directory["phat"]["employee_id"] != directory["nhuy"]["employee_id"]

    resolved = resolve_employee_id(directory["nhuy"]["employee_id"], db_path=db_file)
    assert resolved is not None
    assert resolved["username"] == "nhuy"

    upsert_shift_approval_db(
        shift_key="02/09/2026|NHANVIEN01|Ca Sáng|06:00",
        status="APPROVE",
        approved_mins=390,
        manager="PHÁT",
        note="Đông khách lễ 2/9",
        db_path=db_file
    )
    approvals = list_shift_approvals_db(db_path=db_file)
    assert "02/09/2026|NHANVIEN01|Ca Sáng|06:00" in approvals
    assert approvals["02/09/2026|NHANVIEN01|Ca Sáng|06:00"]["approved_mins"] == 390


def test_phase2_backend_single_source_of_truth_computed_shifts():
    """Verify compute_all_shift_records_server_side and GET /api/v1/cc/data _meta.computed_shifts."""
    sample_data = {
        "NHÂN VIÊN": [
            [],
            ["", "", "", "", ""],
            ["STT", "TÊN NHÂN VIÊN", "CHỨC VỤ", "LƯƠNG/GIỜ"],
            ["1", "NHANVIEN01", "Pha chế", "20000"]
        ],
        "DỮ LIỆU": [
            ["STT", "Ngày", "Tên Nhân Viên", "Ca làm việc", "Giờ vào", "Giờ ra", "Tổng phút (Tự động)", "Ghi chú", "Tháng", "Trễ"],
            ["1", "02/09/2026", "NHANVIEN01", "Ca Sáng", "06:00", "12:30", "390", "", "9", "0"]
        ]
    }
    staff_accounts = {
        "nhuy": {
            "employee_id": "EMP_005",
            "full_name": "NHANVIEN01",
            "hourly_rate": 20000,
            "sheet_names": ["NHANVIEN01"]
        }
    }
    shift_key = "02/09/2026|NHANVIEN01|Ca Sáng|06:00"

    # Without approval: 390 mins (> 330 + 30 buffer) -> PENDING, capped at 330 mins, x2 holiday on 02/09
    computed_pending = compute_all_shift_records_server_side(sample_data, {}, staff_accounts)
    assert shift_key in computed_pending
    rec_p = computed_pending[shift_key]
    assert rec_p["employee_id"] == "EMP_005"
    assert rec_p["otStatus"] == "PENDING"
    assert rec_p["standardShiftMins"] == 330
    assert rec_p["effectiveMins"] == 330
    assert rec_p["isHoliday"] is True
    assert rec_p["holidayMultiplier"] == 2

    # With manager approval: APPROVED -> 390 effectiveMins
    computed_approved = compute_all_shift_records_server_side(
        sample_data,
        {shift_key: {"status": "APPROVE", "approved_mins": 390}},
        staff_accounts
    )
    rec_a = computed_approved[shift_key]
    assert rec_a["otStatus"] == "APPROVED"
    assert rec_a["effectiveMins"] == 390
    assert rec_a["overtimeMins"] == 60

    # Verify /api/v1/cc/data exposes _meta.computed_shifts and _meta.staff_directory
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})
    res = client.get("/api/v1/cc/data", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    body = res.json()
    assert "_meta" in body
    assert "staff_directory" in body["_meta"]
    assert "computed_shifts" in body["_meta"]


def test_phase3_timefold_anti_clopening_and_open_shifts():
    """Verify Anti-Clopening rule in auto_assign_week_schedule and Open Shifts Marketplace API."""
    # Setup 1 Barista and 4 Service staff (sv1, sv2, sv3, sv4).
    # Monday Evening (t2 toi) is worked by sv1 and sv2.
    # For Tuesday Morning (t3 sang), sv1, sv2 (worked Monday night until 23h) and sv3, sv4 (rested) are available.
    # Anti-Clopening must pick sv3 and sv4 (rested) over sv1 and sv2 (clopening) for Tuesday Morning!
    accounts = {
        "bar1": {"full_name": "Barista 1", "position": "BARISTA", "gender": "NAM", "status": "ACTIVE"},
        "sv1": {"full_name": "Service 1", "position": "SERVICE", "gender": "NAM", "status": "ACTIVE"},
        "sv2": {"full_name": "Service 2", "position": "SERVICE", "gender": "NU", "status": "ACTIVE"},
        "sv3": {"full_name": "Service 3", "position": "SERVICE", "gender": "NAM", "status": "ACTIVE"},
        "sv4": {"full_name": "Service 4", "position": "SERVICE", "gender": "NU", "status": "ACTIVE"}
    }
    registrations = {
        "bar1": {"availability": {"t2": {"sang": "PRI"}, "t3": {"sang": "PRI"}}},
        "sv1": {"availability": {"t2": {"sang": "OFF", "toi": "PRI"}, "t3": {"sang": "PRI", "toi": "OFF"}}},
        "sv2": {"availability": {"t2": {"sang": "OFF", "toi": "PRI"}, "t3": {"sang": "PRI", "toi": "OFF"}}},
        "sv3": {"availability": {"t2": {"sang": "OFF", "toi": "OFF"}, "t3": {"sang": "PRI", "toi": "OFF"}}},
        "sv4": {"availability": {"t2": {"sang": "OFF", "toi": "OFF"}, "t3": {"sang": "PRI", "toi": "OFF"}}}
    }

    schedule = auto_assign_week_schedule("2026-10-05", registrations, accounts)
    assert "solver_meta" in schedule
    assert schedule["solver_meta"]["anti_clopening_enabled"] is True

    # Monday evening (t2 toi) service is sv1 and sv2
    t2_toi_sv = schedule["days"]["t2"]["toi"]["service"]
    assert "sv1" in t2_toi_sv
    assert "sv2" in t2_toi_sv

    # Tuesday morning (t3 sang) service MUST be sv3 and sv4 (rested), NOT sv1/sv2 (clopening)
    t3_sang_sv = schedule["days"]["t3"]["sang"]["service"]
    assert "sv3" in t3_sang_sv
    assert "sv4" in t3_sang_sv
    assert "sv1" not in t3_sang_sv
    assert "sv2" not in t3_sang_sv

    # Test Open Shifts Marketplace API (Create -> List -> Claim -> Delete)
    mgr_token = create_access_token({"sub": "phat", "role": "MANAGER", "name": "PHÁT"})
    staff_token = create_access_token({"sub": "vinh", "role": "STAFF", "name": "VINH"})

    create_res = client.post(
        "/api/v1/cc/roster/open-shifts",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={
            "date": "2026-10-08",
            "shift_key": "toi",
            "slot_type": "service_18",
            "role_required": "SERVICE",
            "note": "Cần thêm 1 bạn phục vụ tối thứ 5"
        }
    )
    assert create_res.status_code == 200
    open_shift = create_res.json()["open_shift"]
    shift_id = open_shift["id"]
    assert open_shift["status"] == "OPEN"

    list_res = client.get(
        "/api/v1/cc/roster/open-shifts?status=OPEN",
        headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert list_res.status_code == 200
    assert any(s["id"] == shift_id for s in list_res.json()["open_shifts"])

    claim_res = client.post(
        f"/api/v1/cc/roster/open-shifts/{shift_id}/claim",
        headers={"Authorization": f"Bearer {staff_token}"}
    )
    assert claim_res.status_code == 200
    assert claim_res.json()["open_shift"]["status"] == "CLAIMED"
    assert claim_res.json()["open_shift"]["claimed_by"] == "vinh"

    # Cleanup test open shift
    del_res = client.delete(
        f"/api/v1/cc/roster/open-shifts/{shift_id}",
        headers={"Authorization": f"Bearer {mgr_token}"}
    )
    assert del_res.status_code == 200


def test_phase4_self_service_attendance_explanation_workflow():
    """Verify Staff can submit Attendance Explanation Request and Manager can approve it."""
    staff_token = create_access_token({"sub": "nhanvien", "role": "STAFF", "name": "Nhân Viên"})
    mgr_token = create_access_token({"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})

    # 1. Staff submits explanation for forgotten checkout
    create_res = client.post(
        "/api/v1/cc/attendance/requests",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={
            "date": "2026-09-27",
            "shift_key": "toi",
            "request_type": "FORGOT_CHECKOUT",
            "requested_checkin": "17:00",
            "requested_checkout": "23:05",
            "reason": "Tối qua dọn quầy xong quên bấm kết thúc ca trên điện thoại"
        }
    )
    assert create_res.status_code == 200
    req_obj = create_res.json()["request"]
    req_id = req_obj["id"]
    assert req_obj["status"] == "PENDING"
    assert req_obj["username"] == "nhanvien"

    # 2. Staff cannot approve their own request (403)
    staff_review = client.post(
        f"/api/v1/cc/attendance/requests/{req_id}/review",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"action": "APPROVE", "review_note": "Tự duyệt"}
    )
    assert staff_review.status_code == 403

    # 3. Manager approves the staff request -> updates status to APPROVED
    mgr_review = client.post(
        f"/api/v1/cc/attendance/requests/{req_id}/review",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={"action": "APPROVE", "review_note": "Xác nhận nhân viên có làm tới 23:05"}
    )
    assert mgr_review.status_code == 200
    reviewed = mgr_review.json()["request"]
    assert reviewed["status"] == "APPROVED"

    # 4. Manager submits their own request -> Manager cannot self-approve (Conflict of Interest -> 403), Admin can approve
    mgr_create = client.post(
        "/api/v1/cc/attendance/requests",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={
            "date": "2026-09-27",
            "shift_key": "sang",
            "request_type": "FORGOT_CHECKOUT",
            "requested_checkin": "06:00",
            "requested_checkout": "11:30",
            "reason": "Bận nhận hàng nguyên liệu quên bấm ra ca"
        }
    )
    assert mgr_create.status_code == 200
    mgr_req_id = mgr_create.json()["request"]["id"]

    mgr_self_approve = client.post(
        f"/api/v1/cc/attendance/requests/{mgr_req_id}/review",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={"action": "APPROVE"}
    )
    assert mgr_self_approve.status_code == 403

    admin_approve = client.post(
        f"/api/v1/cc/attendance/requests/{mgr_req_id}/review",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"action": "APPROVE", "review_note": "Admin duyệt cho Quản lý Ca"}
    )
    assert admin_approve.status_code == 200
    assert admin_approve.json()["request"]["status"] == "APPROVED"
