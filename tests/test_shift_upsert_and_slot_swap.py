# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
"""
Verification tests for Feature 4 & 5:
1. Admin/Manager Direct Shift Upsert (`/api/v1/cc/attendance/admin/upsert-shift`)
2. Flexible OT Approval Lookup (`_lookup_shift_approval`)
3. Evening Shift Slot Auto-Detection (`service_17` <-> `service_18`)
"""

import os
import json
from datetime import datetime
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.auth import create_access_token
from backend.services.payroll_calc import _lookup_shift_approval, calculate_staff_payslip_breakdown


def _admin_headers():
    token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Store Admin"})
    return {"Authorization": f"Bearer {token}"}


def _staff_headers(username="nhanvien", display_name="Nhân Viên"):
    token = create_access_token({"sub": username, "role": "STAFF", "name": display_name})
    return {"Authorization": f"Bearer {token}"}


def test_lookup_shift_approval_flexible_matching():
    approvals = {
        "05/11/2026|NHANVIEN|Ca Sáng|06:00": {
            "status": "APPROVE",
            "approved_mins": 345,
            "manager": "admin"
        },
        "2026-11-06|PHACHE|Tối|17:02": {
            "status": "CUT",
            "approved_mins": 300,
            "manager": "manager"
        }
    }
    staff_accounts = {
        "nhanvien": {"full_name": "Nhân Viên A", "sheet_names": ["NHANVIEN"]},
        "phache": {"full_name": "Pha Chế B", "sheet_names": ["PHACHE"]}
    }

    # 1. Variant shift name ("Sáng" vs "Ca Sáng")
    res1 = _lookup_shift_approval(approvals, "05/11/2026", "NHANVIEN", "Sáng", "06:00", staff_accounts)
    assert res1.get("status") == "APPROVE"
    assert res1.get("approved_mins") == 345

    # 2. Slight checkin drift + ISO date format ("06/11/2026" vs "2026-11-06", "17:05" vs "17:02")
    res2 = _lookup_shift_approval(approvals, "06/11/2026", "PHACHE", "Ca Tối", "17:05", staff_accounts)
    assert res2.get("status") == "CUT"
    assert res2.get("approved_mins") == 300


def test_admin_upsert_shift_creates_and_updates_record(tmp_path):
    att_file = tmp_path / "test_upsert_attendance.json"
    appr_file = tmp_path / "test_upsert_approvals.json"
    att_file.write_text("[]", encoding="utf-8")
    appr_file.write_text("{}", encoding="utf-8")

    os.environ["ATTENDANCE_LOGS_FILE"] = str(att_file)
    os.environ["APPROVALS_FILE"] = str(appr_file)

    client = TestClient(app)

    # 1. Create a brand new shift for staff who forgot both checkin & checkout
    res_create = client.post(
        "/api/v1/cc/attendance/admin/upsert-shift",
        headers=_admin_headers(),
        json={
            "username": "nhanvien",
            "staff_name": "NHANVIEN",
            "date": "05/11/2026",
            "shift_key": "sang",
            "checkin_time": "06:05",
            "checkout_time": "11:35",
            "approved_minutes": 330,
            "clear_late": True,
            "note": "Admin tạo ca bổ sung"
        }
    )
    assert res_create.status_code == 200, res_create.text
    body = res_create.json()
    assert body["success"] is True
    rec = body["record"]
    assert rec["checkin_time"] == "06:05"
    assert rec["checkout_time"] == "11:35"
    assert rec["effective_duration_mins"] == 330
    assert rec["is_late"] is False
    assert rec["late_mins"] == 0

    # 2. Update the same shift with new hours
    res_update = client.post(
        "/api/v1/cc/attendance/admin/upsert-shift",
        headers=_admin_headers(),
        json={
            "record_id": rec["id"],
            "username": "nhanvien",
            "staff_name": "NHANVIEN",
            "date": "05/11/2026",
            "shift_key": "sang",
            "checkin_time": "06:00",
            "checkout_time": "12:00",
            "approved_minutes": 360,
            "clear_late": True,
            "note": "Admin duyệt thêm 30p OT"
        }
    )
    assert res_update.status_code == 200, res_update.text
    rec_updated = res_update.json()["record"]
    assert rec_updated["id"] == rec["id"]
    assert rec_updated["checkout_time"] == "12:00"
    assert rec_updated["effective_duration_mins"] == 360

    # Verify payroll calculation honors the upserted shift and approval
    saved_logs = json.loads(att_file.read_text(encoding="utf-8"))
    saved_approvals = json.loads(appr_file.read_text(encoding="utf-8"))
    payslip = calculate_staff_payslip_breakdown(
        staff_name="NHANVIEN",
        month="11",
        attendance_logs=saved_logs,
        shift_approvals=saved_approvals,
        staff_accounts={"nhanvien": {"full_name": "NHANVIEN", "hourly_rate": 20000}}
    )
    assert payslip["total_worked_minutes"] == 360
    assert payslip["standard_pay"] == 108000


def test_evening_shift_slot_swap_auto_detection(tmp_path):
    att_file = tmp_path / "test_swap_attendance.json"
    roster_file = tmp_path / "test_swap_roster.json"
    now_dt = datetime.now()
    today_iso = now_dt.strftime("%Y-%m-%d")
    today_vn = now_dt.strftime("%d/%m/%Y")
    iso_year, iso_week, _ = now_dt.date().isocalendar()
    week_id = f"{iso_year}-W{iso_week:02d}"

    # Pre-seed an early evening peer ("phache") who checked in at 16:58
    att_file.write_text(
        json.dumps([
            {
                "id": "ATT_PEER_1",
                "username": "phache",
                "display_name": "Pha Chế",
                "date": today_vn,
                "shift_key": "toi",
                "shift_name": "Ca Tối",
                "checkin_time": "16:58",
                "checkout_time": None,
                "status": "ON_TIME"
            }
        ]),
        encoding="utf-8"
    )
    # Schedule "nhanvien" in service_17, but they arrive at 17:55 (swapped with peer to 18:00 slot)
    roster_file.write_text(
        json.dumps({
            "weeks": {
                week_id: {
                    "shifts": {
                        today_iso: {
                            "evening": {
                                "barista": "phache",
                                "service_17": "nhanvien",
                                "service_18": "other_staff"
                            }
                        }
                    }
                }
            }
        }),
        encoding="utf-8"
    )

    os.environ["ATTENDANCE_LOGS_FILE"] = str(att_file)
    os.environ["ROSTER_FILE"] = str(roster_file)
    os.environ["ENABLE_RUNTIME_JSON_SYNC"] = "true"

    client = TestClient(app)
    res = client.post(
        "/api/v1/cc/attendance/checkin",
        headers=_staff_headers("nhanvien", "Nhân Viên"),
        json={
            "username": "nhanvien",
            "display_name": "Nhân Viên",
            "shift_override": "toi",
            "dev_override_wifi": True,
            "custom_time_str": "17:55"
        }
    )
    assert res.status_code == 200, res.text
    rec = res.json()["record"]
    assert rec["roster_slot"] == "service_18"
    assert rec["scheduled_start"] == "18:00"
    assert rec["is_late"] is False
    assert rec["late_mins"] == 0
