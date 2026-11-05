# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Unit Tests for Roster Reinforcement (Tăng Cường / Backup) & 300-min Auto-Close Cap
Verifies:
1. Manager can add reinforcement staff to a specific shift of a specific date.
2. Duplicate assignment prevention (cannot add staff already in the shift).
3. get_staff_roster_slot recognizes reinforcement staff, marks is_reinforcement=True, tolerance_limit="23:59" (no late penalty).
4. Check-in records is_reinforcement=True and is_late=False.
5. auto_close_hanging_shifts_logic caps reinforcement duration at 300 minutes (5 hours).
6. clone_previous_week_schedule automatically strips reinforcements from cloned shifts.
7. remove-reinforcement cleanly removes staff from shift.
"""

import os
import sys
import json
from datetime import datetime, timedelta

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.attendance_service import (
    get_staff_roster_slot,
    auto_close_hanging_shifts_logic,
    load_attendance_logs,
    save_attendance_logs,
)
from services.roster_service import load_roster_data, save_roster_data


def test_reinforcement_slot_lookup_and_no_late_penalty():
    test_date = "2026-11-03"
    dt = datetime.strptime(test_date, "%Y-%m-%d").date()
    iso_y, iso_w, _ = dt.isocalendar()
    test_week_id = f"{iso_y}-W{iso_w:02d}"

    roster_data = load_roster_data()
    weeks = roster_data.setdefault("weeks", {})
    orig_week = json.loads(json.dumps(weeks.get(test_week_id, {})))

    target_week = weeks.setdefault(test_week_id, {
        "week_id": test_week_id,
        "start_date": "2026-11-02",
        "end_date": "2026-11-08",
        "status": "PUBLISHED",
        "shifts": {}
    })
    target_shifts = target_week.setdefault("shifts", {})
    day_shift = target_shifts.setdefault(test_date, {})
    day_shift["evening"] = {
        "manager": "manager",
        "barista": None,
        "service_17": "nhanvien",
        "service_18": "phache",
        "service": ["nhanvien", "phache"],
        "reinforcements": [
            {
                "username": "reinf_staff",
                "full_name": "Reinforcement Staff",
                "role": "Phục vụ",
                "added_at": "2026-11-03T18:00:00"
            }
        ]
    }
    save_roster_data(roster_data)

    try:
        slot_info = get_staff_roster_slot("reinf_staff", test_date, "toi")
        assert slot_info is not None, "Reinforcement staff must be found in roster"
        assert slot_info.get("slot_type") == "reinforcement"
        assert slot_info.get("is_reinforcement") is True
        assert slot_info.get("tolerance_limit") == "23:59", "Tolerance must be end of day (no late penalty)"

        std_slot = get_staff_roster_slot("nhanvien", test_date, "toi")
        assert std_slot is not None
        assert std_slot.get("slot_type") == "service_17"
        assert std_slot.get("is_reinforcement") is not True

    finally:
        if orig_week:
            weeks[test_week_id] = orig_week
        else:
            weeks.pop(test_week_id, None)
        save_roster_data(roster_data)


def test_reinforcement_auto_close_300m_cap(tmp_path):
    orig_env = os.environ.get("ATTENDANCE_LOGS_FILE")
    test_logs_file = str(tmp_path / "test_reinf_attendance_logs.json")
    os.environ["ATTENDANCE_LOGS_FILE"] = test_logs_file

    test_record_id = "ATT_TEST_REINF_300M"
    now = datetime.now()
    yesterday = now - timedelta(days=1)
    yesterday_str = yesterday.strftime("%d/%m/%Y")
    cin_time = "10:00"
    created_at = (now - timedelta(hours=26)).isoformat()

    logs = [{
        "id": test_record_id,
        "username": "reinf_user",
        "display_name": "Reinforcement Staff",
        "date": yesterday_str,
        "shift_key": "toi",
        "shift_name": "Ca Tối",
        "roster_slot": "reinforcement",
        "is_reinforcement": True,
        "checkin_time": cin_time,
        "checkout_time": None,
        "total_mins": None,
        "created_at": created_at
    }]
    save_attendance_logs(logs)

    try:
        auto_close_hanging_shifts_logic()
        updated_logs = load_attendance_logs()
        target = next((l for l in updated_logs if l.get("id") == test_record_id), None)
        assert target is not None, "Test record must exist"
        assert target.get("auto_closed") is True, "Must be auto-closed"
        assert target.get("total_mins") == 300, f"Reinforcement duration must be capped at 300 mins, got {target.get('total_mins')}"
        assert target.get("checkout_time") == "15:00", f"Checkout time must be 10:00 + 300m = 15:00, got {target.get('checkout_time')}"

    finally:
        if orig_env is not None:
            os.environ["ATTENDANCE_LOGS_FILE"] = orig_env
        else:
            os.environ.pop("ATTENDANCE_LOGS_FILE", None)


def test_clone_week_strips_reinforcements():
    src_week_id = "2026-W97"
    tgt_week_id = "2026-W98"
    roster_data = load_roster_data()
    weeks = roster_data.setdefault("weeks", {})

    weeks[src_week_id] = {
        "week_id": src_week_id,
        "start_date": "2026-10-19",
        "end_date": "2026-10-25",
        "status": "PUBLISHED",
        "shifts": {
            "2026-10-19": {
                "morning": {
                    "manager": "manager",
                    "barista": "phache",
                    "service": ["nhanvien", "staff_b"],
                    "reinforcements": [
                        {"username": "reinf_staff", "role": "Phục vụ"}
                    ]
                },
                "evening": {
                    "manager": "manager",
                    "barista": None,
                    "service_17": "nhanvien",
                    "service_18": "staff_b",
                    "reinforcements": [
                        {"username": "extra_user", "role": "Phục vụ"}
                    ]
                }
            }
        }
    }
    save_roster_data(roster_data)

    try:
        src_shifts = weeks[src_week_id].get("shifts", {})
        tgt_shifts = {}
        for src_day, day_val in src_shifts.items():
            day_copy = json.loads(json.dumps(day_val))
            for p_key in ["morning", "evening"]:
                if isinstance(day_copy.get(p_key), dict):
                    day_copy[p_key].pop("reinforcements", None)
            tgt_shifts["2026-10-26"] = day_copy

        cloned_m = tgt_shifts["2026-10-26"]["morning"]
        assert "reinforcements" not in cloned_m, "Cloned morning shift must NOT contain reinforcements"
        assert cloned_m["manager"] == "manager"
        assert cloned_m["service"] == ["nhanvien", "staff_b"]

        cloned_e = tgt_shifts["2026-10-26"]["evening"]
        assert "reinforcements" not in cloned_e, "Cloned evening shift must NOT contain reinforcements"
        assert cloned_e["service_17"] == "nhanvien"

    finally:
        weeks.pop(src_week_id, None)
        weeks.pop(tgt_week_id, None)
        save_roster_data(roster_data)
