# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
"""
High-concurrency stress test suite reproducing the 5 scenarios from the 30-thread audit.
Verifies that:
1. sync_latest_log_to_sqlite never drops any of the 50 logs.
2. 30 concurrent claim_open_shift_db calls yield exactly 1 winner and 29 None.
3. 25 concurrent POS closings produce exactly 1 record without duplicates.
4. Concurrent read-modify-write transactions never hit sqlite3.OperationalError: database is locked.
5. Payroll calculations maintain 100% integer VND consistency with zero drift.
"""

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from services.db.connection import get_db_connection, write_transaction
from services.db.schema import init_db
from services.db.security_repo import check_api_rate_limit
from services.db.ops_repo import insert_daily_closing, get_daily_closings
from services.db.attendance_repo import create_open_shift_db, claim_open_shift_db
from services.attendance_service import sync_attendance_logs_to_sqlite, sync_latest_log_to_sqlite
from services.payroll_calc import calculate_staff_payslip_breakdown


@pytest.fixture
def stress_db():
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


def test_stress_attendance_logs_concurrency(stress_db):
    """Scenario 1: 50 existing logs remain intact under concurrent single-log updates."""
    initial_logs = [
        {
            "id": f"seed_log_{i}",
            "username": f"staff_{i}",
            "staff_name": f"Staff {i}",
            "shift_name": "morning",
            "shift_key": "morning",
            "checkin_time": f"2026-11-05 07:{i:02d}:00",
            "date": "2026-11-05",
            "status": "APPROVED",
        }
        for i in range(50)
    ]
    sync_attendance_logs_to_sqlite(initial_logs, purge_missing=True)

    # 10 threads concurrently sync individual hanging logs
    num_threads = 10
    barrier = threading.Barrier(num_threads)
    errors = []

    def _sync_worker(idx):
        try:
            barrier.wait(timeout=5)
            new_log = {
                "id": f"hanging_new_{idx}",
                "username": f"hanging_user_{idx}",
                "staff_name": f"Hanging Staff {idx}",
                "shift_name": "evening",
                "shift_key": "evening",
                "checkin_time": "2026-11-05 18:00:00",
                "checkout_time": "2026-11-05 23:00:00",
                "date": "2026-11-05",
                "status": "APPROVED",
            }
            sync_latest_log_to_sqlite(new_log)
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_sync_worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    assert len(errors) == 0, f"Errors during concurrent log sync: {errors}"

    conn = get_db_connection(stress_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM attendance_logs")
    total_logs = cur.fetchone()[0]
    conn.close()

    assert total_logs == 60, f"Expected 60 logs (50 seeds + 10 updates), but got {total_logs}!"


def test_stress_30_threads_claim_open_shift(stress_db):
    """Scenario 2: 30 threads simultaneously claim 1 open shift -> exactly 1 winner."""
    shift_id = "STRESS_CLAIM_30"
    create_open_shift_db({
        "id": shift_id,
        "date": "2026-11-06",
        "shift_type": "evening",
        "role_required": "SERVICE",
        "slot_type": "service",
        "status": "OPEN",
    }, db_path=stress_db)

    num_threads = 30
    barrier = threading.Barrier(num_threads)
    winners = []
    losers = []
    errors = []

    def _claim_worker(idx):
        try:
            barrier.wait(timeout=5)
            res = claim_open_shift_db(
                shift_id,
                username=f"worker_{idx}",
                display_name=f"Worker {idx}",
                db_path=stress_db
            )
            if res is not None:
                winners.append((idx, res))
            else:
                losers.append(idx)
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_claim_worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    assert len(errors) == 0, f"Errors in 30-thread claim: {errors}"
    assert len(winners) == 1, f"Expected exactly 1 winner, but got {len(winners)}: {[w[0] for w in winners]}"
    assert len(losers) == 29, f"Expected 29 losers, but got {len(losers)}"


def test_stress_25_threads_pos_closings(stress_db):
    """Scenario 3: 25 threads submit the same shift closing -> exactly 1 row in DB."""
    num_threads = 25
    barrier = threading.Barrier(num_threads)
    results = []
    errors = []

    payload = {
        "report_date": "05/11/2026",
        "closing_time": "23:00",
        "shift_key": "toi",
        "bill_pos": 4200000,
        "cash_amount": 2500000,
        "transfer_amount": 1700000,
        "expense_amount": 0,
        "total_real": 4200000,
        "diff": 0,
        "diff_status": "KHỚP",
        "sender_name": "Cashier_HighLoad",
    }

    def _close_worker(idx):
        try:
            barrier.wait(timeout=5)
            r = insert_daily_closing(payload, db_path=stress_db)
            results.append((idx, r))
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_close_worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    assert len(errors) == 0, f"Errors during 25 concurrent closings: {errors}"
    assert len(results) == num_threads

    closings = get_daily_closings(limit=50, report_date="05/11/2026", db_path=stress_db)
    assert len(closings) == 1, f"Expected exactly 1 closing row, found {len(closings)}!"


def test_stress_concurrent_rate_limiting(stress_db):
    """Scenario 4: 25 threads calling check_api_rate_limit without lock deadlocks."""
    num_threads = 25
    barrier = threading.Barrier(num_threads)
    results = []
    errors = []

    def _rate_worker(idx):
        try:
            barrier.wait(timeout=5)
            allowed, count, _ = check_api_rate_limit(
                "stress_rate_limit_ip",
                limit=100,
                window_seconds=60,
                db_path=stress_db
            )
            results.append((allowed, count))
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_rate_worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    assert len(errors) == 0, f"Errors during concurrent rate limits: {errors}"
    assert len(results) == num_threads
    assert all(r[0] is True for r in results)


def test_stress_payroll_vnd_precision():
    """Scenario 5: 7 shifts x 317 mins x 19,000 VND/h -> 100% exact 702,681 VND match."""
    attendance_logs = [
        {
            "id": f"log_{i}",
            "username": "barista_stress",
            "staff_name": "Trần Barista",
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
        "barista_stress": {
            "full_name": "Trần Barista",
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
        staff_name="Trần Barista",
        month="11",
        attendance_logs=attendance_logs,
        staff_accounts=accounts,
        store_config=store_cfg
    )

    assert res["standard_pay"] == 702681
    assert sum(s["shift_total_cost"] for s in res["shift_records"]) == 702681
    assert res["role_breakdown"]["bar"]["amount"] == 702681
