"""
tests/test_pos_closing_scheduler.py
Unit and Integration Tests for Workstream 3:
1. POS Cash Closing API (/api/v1/cc/pos/daily-closing, /api/v1/cc/pos/daily-closings)
2. FnBOps Mathematical Reconciliation Formulas (total_real, diff, diff_status, is_warning)
3. SQLite (wfm.db) Persistence & JSON Backup (pos_closings.json)
4. BackgroundWorker Lifecycle (asyncio tasks, graceful shutdown, auto-close shift scan, online SQLite snapshot backup)
"""

import os
import sys
import json
import sqlite3
import asyncio
import tempfile
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from main import app
from services.db import init_db, get_db_connection, insert_daily_closing, get_daily_closings
from services.background_worker import BackgroundWorker, get_background_worker
from routers.pos_closing import get_pos_closings_json_path, backup_to_json


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path):
    """
    Isolates SQLite database, JSON backups, and snapshots to a clean temporary directory for each test.
    """
    test_db = str(tmp_path / "test_fnbop.db")
    test_json = str(tmp_path / "pos_closings.json")
    test_backups = str(tmp_path / "backups")
    os.makedirs(test_backups, exist_ok=True)

    old_db = os.environ.get("DATABASE_PATH")
    old_json = os.environ.get("POS_CLOSINGS_FILE")
    old_backups = os.environ.get("BACKUP_DIR")
    old_worker_disable = os.environ.get("DISABLE_BACKGROUND_WORKER")

    os.environ["DATABASE_PATH"] = test_db
    os.environ["POS_CLOSINGS_FILE"] = test_json
    os.environ["BACKUP_DIR"] = test_backups
    os.environ["DISABLE_BACKGROUND_WORKER"] = "true"

    # Initialize SQLite schema
    init_db(test_db)

    yield {
        "db_path": test_db,
        "json_path": test_json,
        "backup_dir": test_backups,
        "tmp_path": tmp_path
    }

    # Teardown
    if old_db is not None:
        os.environ["DATABASE_PATH"] = old_db
    else:
        os.environ.pop("DATABASE_PATH", None)

    if old_json is not None:
        os.environ["POS_CLOSINGS_FILE"] = old_json
    else:
        os.environ.pop("POS_CLOSINGS_FILE", None)

    if old_backups is not None:
        os.environ["BACKUP_DIR"] = old_backups
    else:
        os.environ.pop("BACKUP_DIR", None)

    if old_worker_disable is not None:
        os.environ["DISABLE_BACKGROUND_WORKER"] = old_worker_disable
    else:
        os.environ.pop("DISABLE_BACKGROUND_WORKER", None)


@pytest.fixture
def client():
    """FastAPI TestClient fixture with default admin token for pos closing tests."""
    from routers.fnb_ops import create_access_token
    c = TestClient(app)
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Admin"})
    orig_post = c.post
    orig_get = c.get
    def authed_post(url, *args, **kwargs):
        headers = kwargs.get("headers") or {}
        if "Authorization" not in headers and "authorization" not in headers:
            headers["Authorization"] = f"Bearer {admin_token}"
        kwargs["headers"] = headers
        return orig_post(url, *args, **kwargs)
    def authed_get(url, *args, **kwargs):
        headers = kwargs.get("headers") or {}
        if "Authorization" not in headers and "authorization" not in headers:
            headers["Authorization"] = f"Bearer {admin_token}"
        kwargs["headers"] = headers
        return orig_get(url, *args, **kwargs)
    c.post = authed_post
    c.get = authed_get
    return c


# ==============================================================================
# 1. POS CASH CLOSING API & RECONCILIATION FORMULA TESTS
# ==============================================================================

class TestPosClosingFormulasAndEndpoints:
    def test_closing_exact_match(self, client, setup_test_environment):
        """
        Total Real = 3,000,000 + 1,800,000 + 200,000 = 5,000,000
        Bill POS = 5,000,000
        Diff = 0 -> diff_status = 'KHỚP', is_warning = False
        """
        payload = {
            "report_date": "25/09/2026",
            "closing_time": "22:30",
            "bill_pos": 5000000.0,
            "cash_amount": 3000000.0,
            "transfer_amount": 1800000.0,
            "expense_amount": 200000.0,
            "expense_detail": "Mua đá lạnh và nước suối quầy bar",
            "sender_name": "Phát",
            "approver_name": "Hoành"
        }
        res = client.post("/api/v1/cc/pos/daily-closing", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        record = data["data"]
        assert record["total_real"] == 5000000.0
        assert record["diff"] == 0.0
        assert record["diff_status"] == "KHỚP"
        assert record["is_warning"] is False
        assert record["sender_name"] == "Phát"
        assert record["approver_name"] == "Hoành"

        # Verify persisted in SQLite
        db_records = get_daily_closings(db_path=setup_test_environment["db_path"])
        assert len(db_records) == 1
        assert db_records[0]["diff_status"] == "KHỚP"

        # Verify backed up in JSON
        with open(setup_test_environment["json_path"], "r", encoding="utf-8") as f:
            json_data = json.load(f)
            assert len(json_data) == 1
            assert json_data[0]["report_date"] == "25/09/2026"

    def test_closing_positive_diff_within_tolerance(self, client):
        """
        Total Real = 1,020,000
        Bill POS = 1,000,000
        Diff = +20,000 -> diff_status = 'DƯƠNG', is_warning = False (<= 50k)
        """
        payload = {
            "report_date": "25/09/2026",
            "closing_time": "14:00",
            "bill_pos": 1000000.0,
            "cash_amount": 600000.0,
            "transfer_amount": 420000.0,
            "expense_amount": 0.0,
            "sender_name": "Nhân Viên 01"
        }
        res = client.post("/api/v1/cc/pos/daily-closing", json=payload)
        assert res.status_code == 200
        record = res.json()["data"]
        assert record["total_real"] == 1020000.0
        assert record["diff"] == 20000.0
        assert record["diff_status"] == "DƯƠNG"
        assert record["is_warning"] is True

    def test_closing_positive_diff_warning_threshold(self, client):
        """
        Total Real = 1,060,000
        Bill POS = 1,000,000
        Diff = +60,000 -> diff_status = 'DƯƠNG', is_warning = True (> 50k)
        """
        payload = {
            "report_date": "25/09/2026",
            "closing_time": "23:00",
            "bill_pos": 1000000.0,
            "cash_amount": 600000.0,
            "transfer_amount": 460000.0,
            "expense_amount": 0.0,
            "sender_name": "Nhân Viên 02"
        }
        res = client.post("/api/v1/cc/pos/daily-closing", json=payload)
        assert res.status_code == 200
        record = res.json()["data"]
        assert record["diff"] == 60000.0
        assert record["diff_status"] == "DƯƠNG"
        assert record["is_warning"] is True
        assert "Cảnh báo lệch két nghiêm trọng" in res.json()["message"]

    def test_closing_negative_diff_within_tolerance(self, client):
        """
        Total Real = 980,000
        Bill POS = 1,000,000
        Diff = -20,000 -> diff_status = 'ÂM', is_warning = False (<= 50k)
        """
        payload = {
            "report_date": "25/09/2026",
            "closing_time": "15:00",
            "bill_pos": 1000000.0,
            "cash_amount": 500000.0,
            "transfer_amount": 480000.0,
            "expense_amount": 0.0,
            "sender_name": "Vinh"
        }
        res = client.post("/api/v1/cc/pos/daily-closing", json=payload)
        assert res.status_code == 200
        record = res.json()["data"]
        assert record["diff"] == -20000.0
        assert record["diff_status"] == "ÂM"
        assert record["is_warning"] is True

    def test_closing_negative_diff_warning_threshold(self, client):
        """
        Total Real = 850,000
        Bill POS = 1,000,000
        Diff = -150,000 -> diff_status = 'ÂM', is_warning = True (abs(-150k) > 50k)
        """
        payload = {
            "report_date": "25/09/2026",
            "closing_time": "23:15",
            "bill_pos": 1000000.0,
            "cash_amount": 500000.0,
            "transfer_amount": 350000.0,
            "expense_amount": 0.0,
            "sender_name": "Thuận"
        }
        res = client.post("/api/v1/cc/pos/daily-closing", json=payload)
        assert res.status_code == 200
        record = res.json()["data"]
        assert record["diff"] == -150000.0
        assert record["diff_status"] == "ÂM"
        assert record["is_warning"] is True

    def test_closing_discrepancy_warnings(self, client):
        """
        Test discrepancy conditions:
        - diff == 0 -> diff_status='KHỚP', is_warning=False
        - diff > 0 -> diff_status='DƯƠNG', is_warning=True (Két thừa tiền)
        - diff < 0 -> diff_status='ÂM', is_warning=True (Két thiếu tiền / mất tiền)
        """
        # 1. Khớp hoàn toàn
        p0 = {
            "report_date": "25/09/2026",
            "closing_time": "11:55",
            "bill_pos": 1000000.0,
            "cash_amount": 1000000.0,
            "transfer_amount": 0.0,
            "sender_name": "Test0"
        }
        r0 = client.post("/api/v1/cc/pos/daily-closing", json=p0).json()["data"]
        assert r0["diff"] == 0.0
        assert r0["diff_status"] == "KHỚP"
        assert r0["is_warning"] is False

        # 2. DƯƠNG (thừa tiền)
        p1 = {
            "report_date": "25/09/2026",
            "closing_time": "12:00",
            "bill_pos": 1000000.0,
            "cash_amount": 1020000.0,
            "transfer_amount": 0.0,
            "sender_name": "Test1"
        }
        r1 = client.post("/api/v1/cc/pos/daily-closing", json=p1).json()["data"]
        assert r1["diff"] == 20000.0
        assert r1["diff_status"] == "DƯƠNG"
        assert r1["is_warning"] is True

        # 3. ÂM (thiếu tiền, bất kể số tiền bao nhiêu)
        p2 = {
            "report_date": "25/09/2026",
            "closing_time": "12:05",
            "bill_pos": 1000000.0,
            "cash_amount": 980000.0,
            "transfer_amount": 0.0,
            "sender_name": "Test2"
        }
        r2 = client.post("/api/v1/cc/pos/daily-closing", json=p2).json()["data"]
        assert r2["diff"] == -20000.0
        assert r2["diff_status"] == "ÂM"
        assert r2["is_warning"] is True

    def test_validation_errors(self, client):
        """Test input validation errors (date, time, negative amount, empty sender)."""
        # 1. Invalid date format
        res = client.post("/api/v1/cc/pos/daily-closing", json={
            "report_date": "invalid-date-format",
            "closing_time": "12:00",
            "bill_pos": 100000.0,
            "cash_amount": 100000.0,
            "transfer_amount": 0.0,
            "sender_name": "Tester"
        })
        assert res.status_code == 422

        # 2. Invalid time format
        res = client.post("/api/v1/cc/pos/daily-closing", json={
            "report_date": "25/09/2026",
            "closing_time": "25:00",
            "bill_pos": 100000.0,
            "cash_amount": 100000.0,
            "transfer_amount": 0.0,
            "sender_name": "Tester"
        })
        assert res.status_code == 422

        # 3. Negative amount
        res = client.post("/api/v1/cc/pos/daily-closing", json={
            "report_date": "25/09/2026",
            "closing_time": "12:00",
            "bill_pos": -50000.0,
            "cash_amount": 100000.0,
            "transfer_amount": 0.0,
            "sender_name": "Tester"
        })
        assert res.status_code == 422

        # 4. Empty sender name
        res = client.post("/api/v1/cc/pos/daily-closing", json={
            "report_date": "25/09/2026",
            "closing_time": "12:00",
            "bill_pos": 100000.0,
            "cash_amount": 100000.0,
            "transfer_amount": 0.0,
            "sender_name": "   "
        })
        assert res.status_code == 422


# ==============================================================================
# 2. POS DAILY CLOSINGS HISTORY RETRIEVAL TESTS
# ==============================================================================

class TestDailyClosingsHistory:
    def test_get_daily_closings_history(self, client):
        # Insert 3 records
        for i in range(1, 4):
            client.post("/api/v1/cc/pos/daily-closing", json={
                "report_date": f"2{i}/09/2026",
                "closing_time": "22:00",
                "bill_pos": 1000000.0 * i,
                "cash_amount": 1000000.0 * i,
                "transfer_amount": 0.0,
                "sender_name": f"Staff {i}"
            })

        # Fetch all
        res = client.get("/api/v1/cc/pos/daily-closings")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "success"
        assert body["total"] == 3
        # Should be ordered descending (latest ID first)
        assert body["records"][0]["sender_name"] == "Staff 3"

    def test_filter_by_date(self, client):
        client.post("/api/v1/cc/pos/daily-closing", json={
            "report_date": "21/09/2026",
            "closing_time": "14:00",
            "bill_pos": 500000.0,
            "cash_amount": 500000.0,
            "transfer_amount": 0.0,
            "sender_name": "Staff Day 1"
        })
        client.post("/api/v1/cc/pos/daily-closing", json={
            "report_date": "22/09/2026",
            "closing_time": "14:00",
            "bill_pos": 600000.0,
            "cash_amount": 600000.0,
            "transfer_amount": 0.0,
            "sender_name": "Staff Day 2"
        })

        res = client.get("/api/v1/cc/pos/daily-closings?date=21/09/2026")
        assert res.status_code == 200
        records = res.json()["records"]
        assert len(records) == 1
        assert records[0]["report_date"] == "21/09/2026"
        assert records[0]["sender_name"] == "Staff Day 1"

    def test_pagination(self, client):
        for i in range(5):
            client.post("/api/v1/cc/pos/daily-closing", json={
                "report_date": "25/09/2026",
                "closing_time": f"1{i}:00",
                "bill_pos": 100000.0,
                "cash_amount": 100000.0,
                "transfer_amount": 0.0,
                "sender_name": f"User {i}"
            })

        res = client.get("/api/v1/cc/pos/daily-closings?limit=2&offset=1")
        assert res.status_code == 200
        records = res.json()["records"]
        assert len(records) == 2


# ==============================================================================
# 3. BACKGROUND WORKER & SCHEDULER TESTS
# ==============================================================================

class TestBackgroundWorkerScheduler:
    @pytest.mark.anyio
    async def test_worker_lifecycle(self, setup_test_environment):
        """Test starting and stopping BackgroundWorker gracefully."""
        worker = BackgroundWorker(
            auto_close_interval_secs=3600,
            backup_check_interval_secs=3600,
            db_path=setup_test_environment["db_path"],
            backup_dir=setup_test_environment["backup_dir"]
        )

        assert worker.is_running is False
        await worker.start()
        assert worker.is_running is True
        assert len(worker._tasks) >= 2

        # Stopping gracefully
        await worker.stop()
        assert worker.is_running is False
        assert len(worker._tasks) == 0

    @pytest.mark.anyio
    async def test_worker_execute_auto_close(self, setup_test_environment):
        """Test that worker executes auto-close without crashing and invokes attendance logic."""
        worker = BackgroundWorker(
            db_path=setup_test_environment["db_path"],
            backup_dir=setup_test_environment["backup_dir"]
        )
        res = worker._execute_auto_close()
        assert res is not None
        assert "status" in res
        assert res["status"] in ("success", "error")

    @pytest.mark.anyio
    async def test_auto_close_background_loop(self, setup_test_environment):
        """Test that auto-close loop executes in the background and increments telemetry counter."""
        worker = BackgroundWorker(
            auto_close_interval_secs=1, # 1 second interval for test
            backup_check_interval_secs=3600,
            db_path=setup_test_environment["db_path"],
            backup_dir=setup_test_environment["backup_dir"]
        )

        await worker.start()
        # Allow the task to run at least one cycle
        await asyncio.sleep(0.15)
        await worker.stop()

        assert worker.auto_close_runs >= 1

    def test_perform_db_snapshot_atomic(self, setup_test_environment):
        """
        Verify SQLite online backup mechanism creates a valid, queryable database snapshot.
        """
        db_path = setup_test_environment["db_path"]
        backup_dir = setup_test_environment["backup_dir"]

        # Insert a record in test DB
        conn = get_db_connection(db_path)
        conn.execute("INSERT INTO tenants (id, code, name) VALUES ('t1', 'TEST', 'Test Tenant')")
        conn.commit()
        conn.close()

        worker = BackgroundWorker(
            db_path=db_path,
            backup_dir=backup_dir
        )

        snapshot_file = worker.perform_db_snapshot()
        assert snapshot_file is not None
        assert os.path.exists(snapshot_file)
        assert snapshot_file.startswith(backup_dir)
        assert "fnbops_backup_" in snapshot_file
        assert snapshot_file.endswith(".db")

        # Open snapshot database and verify content integrity
        snap_conn = sqlite3.connect(snapshot_file)
        cur = snap_conn.cursor()
        cur.execute("SELECT name FROM tenants WHERE id = 't1'")
        row = cur.fetchone()
        snap_conn.close()

        assert row is not None
        assert row[0] == "Test Tenant"

    @pytest.mark.anyio
    async def test_midnight_backup_trigger_condition(self, setup_test_environment):
        """
        Simulate 23:59 time window and ensure midnight snapshot is triggered.
        """
        worker = BackgroundWorker(
            auto_close_interval_secs=3600,
            backup_check_interval_secs=1,
            db_path=setup_test_environment["db_path"],
            backup_dir=setup_test_environment["backup_dir"]
        )

        # Mock datetime.now() to return 23:59:15
        fake_midnight = datetime(2026, 9, 25, 23, 59, 15)
        with patch("services.background_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_midnight
            mock_dt.strftime = datetime.strftime

            await worker.start()
            await asyncio.sleep(0.15)
            await worker.stop()

        assert worker.backup_runs >= 1
        assert worker._last_backup_date == "2026-09-25"

        # Check file in backup directory
        backups = os.listdir(setup_test_environment["backup_dir"])
        assert len(backups) >= 1
        assert any(b.endswith(".db") for b in backups)
