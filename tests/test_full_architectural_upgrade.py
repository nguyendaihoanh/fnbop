import os
import sys
import json
import sqlite3
import tempfile
import asyncio
import inspect
import pytest
from datetime import datetime, date
from fastapi.testclient import TestClient

# Setup environment & paths
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

os.environ["TESTING"] = "1"
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_super_secure_key_1234567890"
os.environ["ADMIN_PASSWORD"] = "test_admin_261109"

from main import app
from routers.fnb_ops import create_access_token
import routers.excel_routes as excel_routes
try:
    from backend.services.excel_manager import HAS_OPENPYXL
except ImportError:
    from services.excel_manager import HAS_OPENPYXL
from services.db import (
    init_db,
    get_db_connection,
    safe_sqlite_backup,
    record_so_cai_luong,
    list_so_cai_luong,
    DEFAULT_TENANT_ID
)
from services.payroll_calc import calculate_staff_payslip_breakdown


@pytest.fixture
def temp_db():
    """Provides a fresh isolated SQLite database with full schema evolution."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    init_db(db_path)
    yield db_path

    for ext in ["", "-wal", "-shm"]:
        p = f"{db_path}{ext}"
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def admin_headers():
    token = create_access_token(data={"sub": "admin", "role": "ADMIN"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def manager_headers():
    token = create_access_token(data={"sub": "mgr_test", "role": "MANAGER"})
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# TEST 1: HOURLY RATE SNAPSHOT PREVENTS HISTORICAL PAYROLL REGRESSION
# ==============================================================================
def test_hourly_rate_snapshot_preserves_historical_pay():
    """
    Test that when an employee's hourly rate changes from 22k to 25k,
    past shifts with an explicit `hourly_rate_snapshot` retain 22k and
    do NOT artificially inflate old payroll figures.
    """
    # Shift 1: Past shift worked at 22,000 VND / hour (duration: 300 mins = 5.0 hrs)
    past_shift = {
        "username": "barista_test",
        "display_name": "Nguyễn Văn Barista",
        "date": "2026-09-10",
        "checkin_time": "07:00:00",
        "checkout_time": "12:00:00",
        "shift_key": "sang",
        "shift_name": "Ca Sáng",
        "total_mins": 300,
        "effective_duration_mins": 300,
        "hourly_rate_snapshot": 22000,
        "is_hanging_pending": False,
        "status": "HOAN_THANH"
    }

    # Shift 2: New shift after wage bump to 25,000 VND / hour (duration: 300 mins = 5.0 hrs)
    new_shift = {
        "username": "barista_test",
        "display_name": "Nguyễn Văn Barista",
        "date": "2026-09-25",
        "checkin_time": "07:00:00",
        "checkout_time": "12:00:00",
        "shift_key": "sang",
        "shift_name": "Ca Sáng",
        "total_mins": 300,
        "effective_duration_mins": 300,
        "hourly_rate_snapshot": 25000,
        "is_hanging_pending": False,
        "status": "HOAN_THANH"
    }

    # Current staff record has new hourly rate = 25000
    staff_record = {
        "full_name": "Nguyễn Văn Barista",
        "hourly_rate": 25000,
        "role": "STAFF",
        "position": "BARISTA"
    }

    # Calculate payslip for past shift only
    past_breakdown = calculate_staff_payslip_breakdown(
        staff_name="Nguyễn Văn Barista",
        month="9",
        attendance_logs=[past_shift],
        staff_accounts={"barista_test": staff_record},
        store_config={}
    )
    # Expected base wage: 5.0 hrs * 22,000 = 110,000 VND (NOT 5 * 25,000 = 125,000)
    assert past_breakdown["standard_pay"] == 110000
    assert past_breakdown["total_hours"] == 5.0

    # Calculate payslip for combined shifts
    combined_breakdown = calculate_staff_payslip_breakdown(
        staff_name="Nguyễn Văn Barista",
        month="9",
        attendance_logs=[past_shift, new_shift],
        staff_accounts={"barista_test": staff_record},
        store_config={}
    )
    # Expected: 110,000 (past) + 125,000 (new) = 235,000 VND
    assert combined_breakdown["standard_pay"] == 235000
    assert combined_breakdown["total_hours"] == 10.0


# ==============================================================================
# TEST 2: ATOMIC SAFE SQLITE BACKUP IN WAL MODE
# ==============================================================================
def test_safe_sqlite_backup_online_wal(temp_db):
    """
    Test that `safe_sqlite_backup` executes an atomic, corruption-free online backup
    using sqlite3.Connection.backup() even while WAL mode is active.
    """
    conn = get_db_connection(temp_db)
    cur = conn.cursor()
    # Ensure WAL mode
    cur.execute("PRAGMA journal_mode=WAL;")
    assert cur.fetchone()[0].lower() == "wal"

    # Insert test data
    cur.execute("""
        INSERT INTO staff_accounts (tenant_id, username, full_name, role, hourly_rate)
        VALUES (?, ?, ?, ?, ?)
    """, (DEFAULT_TENANT_ID, "staff_wal_test", "Staff WAL Test", "STAFF", 22000))
    conn.commit()

    record_so_cai_luong(
        tenant_id=DEFAULT_TENANT_ID,
        nhan_vien_id="staff_wal_test",
        staff_name="Staff WAL Test",
        loai_su_kien="THUONG",
        so_tien_thay_doi=50000,
        ly_do="Thưởng test WAL",
        nguoi_tao="admin",
        db_path=temp_db
    )
    conn.close()

    # Perform online safe backup to temporary file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as bf:
        backup_file_path = bf.name

    try:
        result_path = safe_sqlite_backup(src_db_path=temp_db, backup_db_path=backup_file_path)
        assert os.path.exists(result_path)
        assert os.path.getsize(result_path) > 0

        # Verify integrity of backup database
        b_conn = sqlite3.connect(backup_file_path)
        b_cur = b_conn.cursor()
        b_cur.execute("PRAGMA integrity_check;")
        integrity = b_cur.fetchone()[0]
        assert integrity == "ok"

        # Verify tables and rows exist in backup
        b_cur.execute("SELECT COUNT(*) FROM staff_accounts WHERE username = 'staff_wal_test';")
        assert b_cur.fetchone()[0] == 1

        b_cur.execute("SELECT COUNT(*) FROM so_cai_luong WHERE nhan_vien_id = 'staff_wal_test';")
        assert b_cur.fetchone()[0] == 1
        b_conn.close()
    finally:
        if os.path.exists(backup_file_path):
            try:
                os.remove(backup_file_path)
            except Exception:
                pass


# ==============================================================================
# TEST 3: QUEN_CHECKOUT SUSPENSION & MANAGER REVIEW ENDPOINT
# ==============================================================================
def test_quen_checkout_suspension_and_manager_review(temp_db, test_client, admin_headers):
    """
    Test that an auto-closed or hanging shift is flagged as QUEN_CHECKOUT with 0 payable mins,
    and when a Manager reviews and approves it via API:
    1. is_hanging_pending becomes False
    2. trang_thai becomes DA_DUYET with the approved duration
    3. An immutable audit record is created in so_cai_luong
    """
    # Create isolated attendance logs JSON file
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
        temp_logs_path = f.name
        hanging_log = {
            "id": "rec_hanging_999",
            "username": "le_thi_treo",
            "display_name": "Lê Thị Treo",
            "date": "2026-10-14",
            "shift_key": "sang",
            "shift_name": "Ca Sáng",
            "checkin_time": "07:00:00",
            "checkout_time": "23:00:00",
            "total_mins": 0,
            "effective_duration_mins": 0,
            "is_hanging_pending": True,
            "status": "QUEN_CHECKOUT",
            "hourly_rate_snapshot": 20000
        }
        json.dump([hanging_log], f, ensure_ascii=False)

    os.environ["ATTENDANCE_LOGS_FILE"] = temp_logs_path
    os.environ["SQLITE_DB_PATH"] = temp_db

    # Also insert corresponding row into SQLite attendance_logs
    conn = get_db_connection(temp_db)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO attendance_logs (
            tenant_id, username, full_name, date, shift, checkin, checkout,
            duration_mins, status, note, hourly_rate_snapshot, effective_duration_mins, is_hanging_pending
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        DEFAULT_TENANT_ID, "le_thi_treo", "Lê Thị Treo", "2026-10-14", "Ca Sáng", "07:00:00", "23:00:00",
        0, "QUEN_CHECKOUT", "Hanging test", 20000, 0, 1
    ))
    conn.commit()
    conn.close()

    try:
        # 1. Verify initial breakdown assigns 0 pay
        calc = calculate_staff_payslip_breakdown(
            staff_name="Lê Thị Treo",
            month="10",
            attendance_logs=[hanging_log],
            staff_accounts={"le_thi_treo": {"hourly_rate": 20000}}
        )
        assert calc["standard_pay"] == 0
        assert calc["total_hours"] == 0

        # 2. Call Manager Review Endpoint
        review_payload = {
            "record_id": "rec_hanging_999",
            "approved_checkout_time": "12:30:00",
            "approved_minutes": 330,  # 5.5 hours
            "note": "Xác nhận qua camera làm đúng ca sáng 5.5 tiếng"
        }

        resp = test_client.post(
            "/api/v1/cc/attendance/review-hanging-shift",
            json=review_payload,
            headers=admin_headers
        )
        assert resp.status_code == 200, f"Error: {resp.text}"
        data = resp.json()
        assert data.get("success") is True
        assert data.get("approved_duration_mins") == 330

        # 3. Verify JSON file updated
        with open(temp_logs_path, "r", encoding="utf-8") as f:
            updated_logs = json.load(f)
        assert len(updated_logs) == 1
        assert updated_logs[0]["is_hanging_pending"] is False
        assert updated_logs[0]["effective_duration_mins"] == 330
        assert updated_logs[0]["status"] == "DA_DUYET"

        # 4. Verify SQLite attendance record is updated
        conn = get_db_connection(temp_db)
        cur = conn.cursor()
        cur.execute("""
            SELECT checkout, effective_duration_mins, is_hanging_pending, status
            FROM attendance_logs
            WHERE username = ? AND date = ?
        """, ("le_thi_treo", "2026-10-14"))
        row = cur.fetchone()
        assert row is not None
        assert row["checkout"] == "12:30:00"
        assert row["effective_duration_mins"] == 330
        assert row["is_hanging_pending"] == 0

        # 5. Verify audit ledger record in so_cai_luong
        cur.execute("""
            SELECT loai_su_kien, so_gio_thay_doi, ly_do, nguoi_tao
            FROM so_cai_luong
            WHERE nhan_vien_id = ?
        """, ("le_thi_treo",))
        ledger_row = cur.fetchone()
        assert ledger_row is not None
        assert ledger_row["loai_su_kien"] == "DIEU_CHINH_GIO"
        assert ledger_row["so_gio_thay_doi"] == 5.5
        assert "Xác nhận qua camera" in ledger_row["ly_do"]
        conn.close()
    finally:
        if os.path.exists(temp_logs_path):
            try:
                os.remove(temp_logs_path)
            except Exception:
                pass


# ==============================================================================
# TEST 4: IMMUTABLE AUDIT LEDGER (SO_CAI_LUONG) LOGIC & API
# ==============================================================================
def test_so_cai_luong_immutable_ledger_api(temp_db, test_client, admin_headers):
    """
    Test recording bonuses, penalties, advances, and retrieving them via
    the administrative audit ledger endpoint GET /api/v1/cc/admin/so-cai-luong.
    """
    # 1. Direct recording via service
    id1 = record_so_cai_luong(
        tenant_id=DEFAULT_TENANT_ID,
        nhan_vien_id="nhan_vien_1",
        staff_name="Phạm Văn Pha Chế",
        loai_su_kien="THUONG",
        so_tien_thay_doi=100000,
        ly_do="Thưởng vượt KPI doanh số",
        nguoi_tao="admin",
        db_path=temp_db
    )
    assert id1 > 0

    id2 = record_so_cai_luong(
        tenant_id=DEFAULT_TENANT_ID,
        nhan_vien_id="nhan_vien_1",
        staff_name="Phạm Văn Pha Chế",
        loai_su_kien="PHAT",
        so_tien_thay_doi=-30000,
        ly_do="Trừ phạt làm vỡ dụng cụ",
        nguoi_tao="admin",
        db_path=temp_db
    )
    assert id2 > id1

    # 2. Query via service
    events = list_so_cai_luong(staff_name="Phạm Văn Pha Chế", db_path=temp_db)
    assert len(events) == 2
    assert events[0]["loai_su_kien"] == "PHAT"
    assert events[1]["loai_su_kien"] == "THUONG"

    # 3. Query via Admin API Endpoint
    os.environ["SQLITE_DB_PATH"] = temp_db
    import services.db as db_service
    orig_get_db_path = db_service.get_db_path
    db_service.get_db_path = lambda: temp_db

    try:
        resp = test_client.get(
            "/api/v1/cc/admin/so-cai-luong?staff_name=Phạm Văn Pha Chế",
            headers=admin_headers
        )
        assert resp.status_code == 200
        api_data = resp.json()
        assert api_data["success"] is True
        assert api_data["count"] == 2
        assert len(api_data["events"]) == 2
        assert api_data["events"][0]["staff_name"] == "Phạm Văn Pha Chế"
    finally:
        db_service.get_db_path = orig_get_db_path


# ==============================================================================
# TEST 5: ASYNC NON-BLOCKING EXCEL ENDPOINTS (THREADPOOL OFFLOADING)
# ==============================================================================
@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl is optional")
def test_async_excel_routes_non_blocking(test_client, admin_headers):
    """
    Test that excel route endpoints are declared as async coroutines and
    safely offload CPU/IO bound openpyxl operations to worker threads.
    """
    # 1. Verify route handler functions are async coroutine functions
    assert inspect.iscoroutinefunction(excel_routes.get_payroll_excel)
    assert inspect.iscoroutinefunction(excel_routes.get_staff_excel_template)
    assert inspect.iscoroutinefunction(excel_routes.post_import_staff)

    # 2. Test staff template export endpoint response
    res = test_client.get(
        "/api/v1/cc/excel/staff-template",
        headers=admin_headers
    )
    assert res.status_code == 200
    assert "spreadsheetml.sheet" in res.headers.get("content-type", "")
    assert len(res.content) > 1000  # Valid Excel file bytes returned
