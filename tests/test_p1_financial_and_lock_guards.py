# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
"""
Verification tests for P1 Financial Accuracy, POS Closing Deduplication, Reversal Ledger, and Lock Guards.
"""

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from services.db.connection import get_db_connection
from services.db.schema import init_db
from services.db.ops_repo import insert_daily_closing, get_daily_closings
from services.db.payroll_repo import (
    insert_staff_ledger,
    delete_staff_ledger,
    list_so_cai_luong,
    upsert_payroll_lock_db,
)
from services.payroll_calc import calculate_staff_payslip_breakdown
from routers.attendance import check_payroll_lock_status


@pytest.fixture
def test_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["SQLITE_DB_PATH"] = path
    os.environ["DATABASE_PATH"] = path
    init_db(path)
    yield path
    try:
        os.remove(path)
        for ext in ["-wal", "-shm"]:
            if os.path.exists(path + ext):
                os.remove(path + ext)
    except Exception:
        pass


def test_payroll_calc_zero_drift():
    """
    P1-1: 7 Barista shifts x 317 minutes at 19,000 VND/hour.
    Must have 0 VND drift between standard_pay, sum(shift_records), and role_breakdown.
    """
    attendance_logs = [
        {
            "id": f"log_{i}",
            "username": "barista_test",
            "staff_name": "Nguyễn Văn Barista",
            "date": f"0{i}/11/2026",
            "shift_name": "Ca Sáng",
            "shift_key": "sang",
            "slot": "barista",
            "shift_role": "BAR",
            "checkin_time": "07:00",
            "checkout_time": "12:17",
            "duration_mins": 317,
            "total_mins": 317,
            "effective_duration_mins": 317,
            "status": "APPROVED",
            "is_hanging_pending": False,
        }
        for i in range(1, 8)
    ]

    accounts = {
        "barista_test": {
            "full_name": "Nguyễn Văn Barista",
            "hourly_rate": 19000,
            "salary_type": "HOURLY",
            "role": "STAFF",
            "position": "BAR",
            "allowed_roles": ["BAR"],
        }
    }

    store_cfg = {
        "store_name": "FnBOps",
        "standard_shift_mins": 300,
        "ot_buffer_mins": 30,
        "hourly_rates": {"bar": 19000, "service": 17000}
    }

    res = calculate_staff_payslip_breakdown(
        staff_name="Nguyễn Văn Barista",
        month="11",
        attendance_logs=attendance_logs,
        staff_accounts=accounts,
        store_config=store_cfg
    )

    std_pay = res["standard_pay"]
    shifts_sum = sum(s["shift_total_cost"] for s in res["shift_records"])
    role_bar_amount = res["role_breakdown"]["bar"]["amount"]

    # All 3 values must match 100% to the exact VND!
    assert std_pay == shifts_sum, f"Mismatch: standard_pay={std_pay} vs sum(shifts)={shifts_sum}"
    assert std_pay == role_bar_amount, f"Mismatch: standard_pay={std_pay} vs role_breakdown={role_bar_amount}"
    assert std_pay == 702681


def test_concurrent_pos_daily_closing_dedup(test_db):
    """
    P1-1: 20 concurrent threads trying to close the same shift must create
    EXACTLY 1 record in SQLite due to UNIQUE(tenant_id, report_date, shift_key).
    """
    num_threads = 20
    barrier = threading.Barrier(num_threads)
    results = []
    errors = []

    closing_payload = {
        "report_date": "05/11/2026",
        "closing_time": "23:00",
        "shift_key": "toi",
        "bill_pos": 5000000,
        "cash_amount": 3000000,
        "transfer_amount": 2000000,
        "expense_amount": 0,
        "total_real": 5000000,
        "diff": 0,
        "diff_status": "KHỚP",
        "sender_name": "ThuNgan01",
    }

    def _closer(idx):
        try:
            barrier.wait(timeout=5)
            r = insert_daily_closing(closing_payload, db_path=test_db)
            results.append((idx, r))
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_closer, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    assert len(errors) == 0, f"Errors during closing: {errors}"
    assert len(results) == num_threads

    # Verify database has ONLY 1 record
    all_closings = get_daily_closings(limit=50, report_date="05/11/2026", db_path=test_db)
    assert len(all_closings) == 1, f"Expected 1 record in DB, found {len(all_closings)}"


def test_reversal_entry_on_staff_ledger_delete(test_db):
    """
    P1-4: Deleting a staff ledger entry must automatically record a reversal entry
    in the immutable so_cai_luong general ledger.
    """
    ledger_id = "LEDGER_ADV_01"
    insert_staff_ledger({
        "id": ledger_id,
        "staff_name": "nhanvien_01",
        "type": "ADVANCE",
        "amount": 500000,
        "reason": "Tạm ứng mua phụ liệu",
        "month": "11",
        "date": "2026-11-05",
        "created_by": "Admin",
    }, db_path=test_db)

    # Delete the entry
    deleted = delete_staff_ledger(ledger_id, deleted_by="Manager_Test", db_path=test_db)
    assert deleted is True

    # Check so_cai_luong for the reversal entry
    entries = list_so_cai_luong(staff_name="nhanvien_01", db_path=test_db)
    reversals = [e for e in entries if "HUY" in e.get("loai_su_kien", "") or "REVERSAL" in e.get("loai_su_kien", "")]

    assert len(reversals) >= 1, "No reversal entry found in so_cai_luong!"
    rev = reversals[0]
    assert rev["so_tien_thay_doi"] == -500000, f"Expected -500000 but got {rev['so_tien_thay_doi']}"


def test_payroll_lock_guard_in_attendance(test_db):
    """
    P1-4: When a month is LOCKED, check_payroll_lock_status must return (True, msg).
    """
    upsert_payroll_lock_db("10", status="LOCKED", message="Đã chốt lương tháng 10", db_path=test_db)

    # 1. Date in locked month (DD/MM/YYYY)
    is_locked, msg = check_payroll_lock_status("15/10/2026")
    assert is_locked is True
    assert "tháng 10" in msg

    # 2. Date in unlocked month (11)
    is_locked_11, _ = check_payroll_lock_status("05/11/2026")
    assert is_locked_11 is False
