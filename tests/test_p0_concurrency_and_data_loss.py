# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
"""
Verification tests for P0 Concurrency, Data Loss Prevention and Atomic CAS.
"""

import os
import time
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from services.db.connection import get_db_connection, write_transaction
from services.db.schema import init_db
from services.db.security_repo import check_api_rate_limit
from services.db.staff_repo import get_staff_token_version, upsert_staff_account
from services.db.attendance_repo import create_open_shift_db, claim_open_shift_db
from services.attendance_service import sync_attendance_logs_to_sqlite, sync_latest_log_to_sqlite


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


def test_sync_latest_log_does_not_purge_other_logs(test_db):
    """
    CRITICAL P0: sync_latest_log_to_sqlite must NOT purge other existing attendance records.
    """
    # 1. Seed 50 logs
    initial_logs = [
        {
            "id": f"log_{i}",
            "username": f"staff_{i}",
            "staff_name": f"Staff_{i}",
            "shift_name": "morning",
            "shift_key": "morning",
            "checkin_time": f"2026-11-05 07:{i:02d}:00",
            "date": "2026-11-05",
            "status": "APPROVED",
        }
        for i in range(50)
    ]
    sync_attendance_logs_to_sqlite(initial_logs, purge_missing=True)

    conn = get_db_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM attendance_logs")
    count_before = cur.fetchone()[0]
    conn.close()
    assert count_before == 50

    # 2. Sync a single late/hanging log via sync_latest_log_to_sqlite
    single_log = {
        "id": "log_hanging_51",
        "username": "staff_new",
        "staff_name": "Staff_New",
        "shift_name": "evening",
        "shift_key": "evening",
        "checkin_time": "2026-11-05 18:00:00",
        "date": "2026-11-05",
        "status": "APPROVED",
    }
    sync_latest_log_to_sqlite(single_log)

    # 3. Verify: We must have 51 records now (0 records lost!)
    conn = get_db_connection(test_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM attendance_logs")
    count_after = cur.fetchone()[0]
    conn.close()

    assert count_after == 51, f"Expected 51 logs but found {count_after}. Data loss detected!"


def test_concurrent_rate_limit_no_busy_deadlock(test_db):
    """
    P0-2: 30 concurrent threads calling check_api_rate_limit with BEGIN IMMEDIATE
    must NOT hit sqlite3.OperationalError: database is locked.
    """
    num_threads = 25
    barrier = threading.Barrier(num_threads)
    errors = []
    results = []

    def _worker(thread_id):
        try:
            barrier.wait(timeout=5)
            allowed, count, retry_after = check_api_rate_limit(
                "concurrent_test_ip",
                limit=100,
                window_seconds=60,
                db_path=test_db
            )
            results.append((allowed, count))
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    assert len(errors) == 0, f"Encountered concurrency errors: {errors}"
    assert len(results) == num_threads
    # All 25 should be allowed
    assert all(r[0] is True for r in results)
    counts = [r[1] for r in results]
    assert max(counts) == num_threads


def test_pure_read_jwt_token_version(test_db):
    """
    P0-3: Pure read of staff token version must not acquire exclusive write locks or fail.
    """
    upsert_staff_account(
        username="barista_user",
        full_name="Test Barista",
        pin_hash="1234",
        role="STAFF",
        token_version=3,
        db_path=test_db
    )

    num_threads = 20
    barrier = threading.Barrier(num_threads)
    versions = []
    errors = []

    def _reader():
        try:
            barrier.wait(timeout=5)
            v = get_staff_token_version("barista_user", db_path=test_db)
            versions.append(v)
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_reader) for _ in range(num_threads)]
        for f in futures:
            f.result()

    assert len(errors) == 0
    assert len(versions) == num_threads
    assert all(v == 3 for v in versions)


def test_atomic_cas_claim_open_shift(test_db):
    """
    P0-4: When 20 threads simultaneously attempt to claim 1 open shift,
    EXACTLY 1 must succeed, and 19 must receive None.
    """
    shift_id = "SHIFT_RACE_TEST_01"
    create_open_shift_db({
        "id": shift_id,
        "date": "2026-11-06",
        "shift_type": "evening",
        "role_required": "SERVICE",
        "slot_type": "service",
        "status": "OPEN",
    }, db_path=test_db)

    num_threads = 20
    barrier = threading.Barrier(num_threads)
    claimed_results = []
    errors = []

    def _claimant(idx):
        try:
            barrier.wait(timeout=5)
            res = claim_open_shift_db(
                shift_id,
                username=f"staff_{idx}",
                display_name=f"Staff {idx}",
                db_path=test_db
            )
            if res is not None:
                claimed_results.append((idx, res))
        except Exception as e:
            errors.append(str(e))

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(_claimant, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    assert len(errors) == 0, f"Errors during claim: {errors}"
    assert len(claimed_results) == 1, (
        f"Race condition failure! Expected exactly 1 winner, but {len(claimed_results)} threads claimed the shift: "
        f"{[c[0] for c in claimed_results]}"
    )
    winner_idx, shift_data = claimed_results[0]
    assert shift_data["status"] == "CLAIMED"
    assert shift_data["claimed_by"] == f"staff_{winner_idx}"
