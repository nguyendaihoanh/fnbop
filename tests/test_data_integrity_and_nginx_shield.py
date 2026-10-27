# -*- coding: utf-8 -*-
"""
Test Suite: Data Integrity & Nginx Edge Shield
Validates:
1. REA4-03: Deleting a shift cleans both JSON and SQLite attendance_logs (no orphaned shifts).
2. REA4-04: Immutable General Ledger (so_cai_luong) supports accounting reversals (HUY_UNG_LUONG, HUY_THUONG, etc.)
   while strictly preserving engine-level immutability (triggers abort UPDATE and DELETE).
3. REA6-03: Nginx edge configuration enforces strict IP whitelisting and 'deny all' on n8n webhooks (/api/send-payslip, /api/ledger).
"""

import os
import sys
import json
import sqlite3
import tempfile
import pytest
from datetime import datetime
from fastapi.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.main import app
from backend.services.db import (
    init_db,
    get_db_connection,
    record_so_cai_luong,
    list_so_cai_luong,
)
from backend.services.db.payroll_repo import (
    insert_staff_ledger,
    get_staff_ledger_by_id,
    delete_staff_ledger,
    create_reversal_ledger_entry,
)
from backend.routers.fnb_ops import create_access_token
import backend.routers.attendance as att_router
from backend.services.attendance_service import (
    sync_attendance_logs_to_sqlite,
    load_attendance_logs,
    save_attendance_logs,
)


@pytest.fixture
def isolated_db_and_logs(monkeypatch):
    """Creates isolated SQLite DB and temporary JSON logs for data integrity testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
        db_path = db_f.name
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as json_f:
        json_path = json_f.name
        json_f.write(b"[]")

    init_db(db_path)
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)

    # Patch active log file paths in attendance_service and router
    monkeypatch.setattr("backend.services.attendance_service._get_active_logs_file", lambda: json_path)
    monkeypatch.setattr("backend.routers.attendance.LOGS_FILE", json_path)

    yield {"db_path": db_path, "json_path": json_path}

    for path in [db_path, json_path]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
    for ext in ["-wal", "-shm"]:
        if os.path.exists(db_path + ext):
            try:
                os.remove(db_path + ext)
            except Exception:
                pass


def test_delete_shift_removes_from_both_json_and_sqlite(isolated_db_and_logs):
    """
    REA4-03: Deleting an erroneous shift must clean both the JSON store
    AND the SQLite `attendance_logs` table, leaving zero orphaned records.
    """
    db_path = isolated_db_and_logs["db_path"]
    client = TestClient(app)
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "ver": 1})

    now = datetime.now()
    today_str = now.strftime("%d/%m/%Y")
    record_id = f"ATT_TEST_{now.strftime('%Y%m%d%H%M%S')}_hoangnam"

    sample_record = {
        "id": record_id,
        "username": "hoangnam",
        "display_name": "Hoàng Nam",
        "role": "Phục vụ",
        "date": today_str,
        "shift_key": "sang",
        "shift_name": "Ca Sáng",
        "checkin_time": "06:05",
        "checkout_time": "11:30",
        "total_mins": 325,
        "is_late": False,
        "status": "ON_TIME",
        "created_at": now.isoformat(),
        "closed_by": "STAFF"
    }

    # Seed into JSON and sync to SQLite
    save_attendance_logs([sample_record])
    sync_attendance_logs_to_sqlite([sample_record])

    # Verify record exists in SQLite
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM attendance_logs WHERE username = ?", ("hoangnam",))
    count_before = cur.fetchone()[0]
    conn.close()
    assert count_before == 1, "Record must exist in SQLite before deletion"

    # Verify record exists in JSON
    json_logs = load_attendance_logs()
    assert len(json_logs) == 1
    assert json_logs[0]["username"] == "hoangnam"

    # Call delete-shift endpoint
    resp = client.post(
        "/api/v1/cc/attendance/manager/delete-shift",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"record_id": record_id, "username": "hoangnam"}
    )
    assert resp.status_code == 200, f"delete-shift failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "success"

    # 1. Verify record is removed from JSON
    logs_after = load_attendance_logs()
    assert len(logs_after) == 0, "Shift must be purged from JSON logs"

    # 2. Verify record is purged from SQLite (No orphan shift)
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM attendance_logs WHERE username = ?", ("hoangnam",))
    count_after = cur.fetchone()[0]
    conn.close()
    assert count_after == 0, "Shift must be completely deleted from SQLite attendance_logs (REA4-03)"


def test_immutable_ledger_reversal_events_and_triggers(isolated_db_and_logs):
    """
    REA4-04: Validate that so_cai_luong accepts accounting reversals
    (HUY_UNG_LUONG, HUY_THUONG, HUY_PHAT, DIEU_CHINH_GIAM, REVERSAL)
    and that UPDATE/DELETE triggers remain actively enforced.
    """
    db_path = isolated_db_and_logs["db_path"]
    reversal_events = [
        ("HUY_UNG_LUONG", -500000, "Hủy ứng lương nhân viên"),
        ("HUY_THUONG", -200000, "Thu hồi thưởng nhầm ca"),
        ("HUY_PHAT", 100000, "Xóa phạt vi phạm sau khi khiếu nại thành công"),
        ("DIEU_CHINH_GIAM", -150000, "Điều chỉnh giảm trừ kế toán"),
        ("REVERSAL", -50000, "Bút toán đảo ngược tổng quát"),
    ]

    for event_type, amount, reason in reversal_events:
        ledger_id = record_so_cai_luong(
            tenant_id="default",
            nhan_vien_id="EMP_001",
            staff_name="Nguyễn Văn A",
            loai_su_kien=event_type,
            so_tien_thay_doi=amount,
            ly_do=reason,
            nguoi_tao="KeToanTruong",
            db_path=db_path
        )
        assert ledger_id > 0, f"Must successfully record reversal event {event_type}"

    # Verify all records exist in DB
    records = list_so_cai_luong(staff_name="Nguyễn Văn A", db_path=db_path)
    recorded_types = [r["loai_su_kien"] for r in records]
    for event_type, _, _ in reversal_events:
        assert event_type in recorded_types, f"Event {event_type} must be stored in so_cai_luong"

    # Immutability Engine Verification: Attempt UPDATE on so_cai_luong
    conn = get_db_connection(db_path)
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError)) as exc_update:
        conn.execute("UPDATE so_cai_luong SET so_tien_thay_doi = 0 WHERE id = ?", (records[0]["id"],))
    assert "bat bien" in str(exc_update.value).lower(), "UPDATE on so_cai_luong must be blocked by trigger"

    # Immutability Engine Verification: Attempt DELETE on so_cai_luong
    with pytest.raises((sqlite3.OperationalError, sqlite3.IntegrityError)) as exc_delete:
        conn.execute("DELETE FROM so_cai_luong WHERE id = ?", (records[0]["id"],))
    assert "bat bien" in str(exc_delete.value).lower(), "DELETE on so_cai_luong must be blocked by trigger"
    conn.close()


def test_create_reversal_ledger_entry_helper(isolated_db_and_logs):
    """
    REA4-04 Helper: Test create_reversal_ledger_entry helper function and integration
    with soft-deleting staff_ledgers.
    """
    db_path = isolated_db_and_logs["db_path"]

    # 1. Insert a staff ledger advance entry
    ledger_item = {
        "id": "LEDGER_ADV_001",
        "staff_name": "Trần Thị B",
        "month": "2026-10",
        "type": "advance",
        "amount": 500000,
        "payment_method": "cash",
        "reason": "Ứng tiền ca đêm",
        "created_by": "Manager"
    }
    insert_staff_ledger(ledger_item, db_path=db_path)

    # 2. Soft delete the staff ledger entry -> triggers create_reversal_ledger_entry
    deleted = delete_staff_ledger("LEDGER_ADV_001", deleted_by="Manager_Test", db_path=db_path)
    assert deleted is True

    # 3. Check staff_ledgers is soft-deleted
    item = get_staff_ledger_by_id("LEDGER_ADV_001", db_path=db_path)
    assert item["is_deleted"] == 1
    assert item["deleted_by"] == "Manager_Test"

    # 4. Check so_cai_luong has the corresponding reversal entry
    so_cai_entries = list_so_cai_luong(staff_name="Trần Thị B", db_path=db_path)
    assert len(so_cai_entries) >= 1
    rev_entry = so_cai_entries[0]
    assert rev_entry["loai_su_kien"] == "HUY_UNG_LUONG"
    assert rev_entry["so_tien_thay_doi"] == -500000
    assert "LEDGER_ADV_001" in rev_entry["cham_cong_id"]


def test_nginx_edge_shield_config():
    """
    REA6-03: Validate that config/nginx/fnbop.conf.example protects /api/send-payslip
    and /api/ledger with strict access controls (allow internal subnets, deny all).
    """
    nginx_conf_path = os.path.join(BASE_DIR, "config", "nginx", "fnbop.conf.example")
    if not os.path.exists(nginx_conf_path):
        nginx_conf_path = os.path.join(BASE_DIR, "config", "nginx", "fnbops.conf")
    assert os.path.exists(nginx_conf_path), f"Nginx config not found at {nginx_conf_path}"

    with open(nginx_conf_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Helper function to extract a location block from nginx conf
    def extract_location_block(location_prefix: str, text: str) -> str:
        idx = text.find(location_prefix)
        assert idx != -1, f"Location {location_prefix} not found in nginx config"
        brace_start = text.find("{", idx)
        assert brace_start != -1
        depth = 1
        pos = brace_start + 1
        while pos < len(text) and depth > 0:
            if text[pos] == "{":
                depth += 1
            elif text[pos] == "}":
                depth -= 1
            pos += 1
        return text[brace_start:pos]

    # Check /api/send-payslip
    payslip_block = extract_location_block("location /api/send-payslip", content)
    assert "deny all;" in payslip_block, "/api/send-payslip must have 'deny all;'"
    assert "allow 127.0.0.1;" in payslip_block, "/api/send-payslip must allow localhost"
    assert any(x in payslip_block for x in ["proxy_pass http://host.docker.internal:5678/webhook/fnb-send-payslip;"])

    # Check /api/ledger
    ledger_block = extract_location_block("location /api/ledger", content)
    assert "deny all;" in ledger_block, "/api/ledger must have 'deny all;'"
    assert "allow 127.0.0.1;" in ledger_block, "/api/ledger must allow localhost"
    assert "allow 172.16.0.0/12;" in ledger_block, "/api/ledger must allow Docker network"
    assert any(x in ledger_block for x in ["proxy_pass http://host.docker.internal:5678/webhook/fnb-so-phu;"])

    # Check order of directives: 'allow' statements must come BEFORE 'deny all'
    deny_idx_payslip = payslip_block.find("deny all;")
    allow_idx_payslip = payslip_block.find("allow 127.0.0.1;")
    assert allow_idx_payslip < deny_idx_payslip, "Allow directives must precede 'deny all;' in /api/send-payslip"

    deny_idx_ledger = ledger_block.find("deny all;")
    allow_idx_ledger = ledger_block.find("allow 127.0.0.1;")
    assert allow_idx_ledger < deny_idx_ledger, "Allow directives must precede 'deny all;' in /api/ledger"
