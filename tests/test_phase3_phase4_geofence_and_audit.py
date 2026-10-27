"""
tests/test_phase3_phase4_geofence_and_audit.py
Unit & Integration Test Suite for:
1. Phase 3: Geofence Spoofing Protection & Replay Attack Shield (attendance.py)
2. Phase 4: Immutable Audit Trail & Soft Delete for Staff Ledgers & POS Closing Overwrite Protection
"""

import os
import sys

os.environ["TESTING"] = "1"
os.environ["JWT_SECRET_KEY"] = "test_jwt_secret_super_secure_key_1234567890"

import time
import json
import sqlite3
import pytest
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

# Ensure backend and project root are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.auth import create_access_token
from services.db.connection import get_db_connection, DEFAULT_TENANT_ID
from services.db.payroll_repo import (
    insert_staff_ledger,
    list_staff_ledgers,
    get_staff_ledger_by_id,
    delete_staff_ledger,
)
from routers.attendance import (
    router as attendance_router,
    get_client_ip,
    is_trusted_proxy,
    _validate_heartbeat_timestamp,
    POS_SECRET,
)
from routers.pos_closing import (
    router as pos_closing_router,
    create_daily_closing,
    reconcile_daily_closing,
)

isolated_app = FastAPI()
isolated_app.include_router(attendance_router)
isolated_app.include_router(pos_closing_router)


@pytest.fixture(scope="module")
def client():
    return TestClient(isolated_app)


@pytest.fixture(scope="module")
def admin_token():
    return create_access_token(data={"sub": "admin", "role": "ADMIN", "name": "Admin System"})


@pytest.fixture(scope="module")
def manager_token():
    return create_access_token(data={"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})


@pytest.fixture(scope="module")
def staff_token():
    return create_access_token(data={"sub": "phache", "role": "STAFF", "name": "Pha Chế"})


# ==============================================================================
# TEST SUITE 1: REPLAY ATTACK SHIELD (attendance.py - pos_heartbeat)
# ==============================================================================
class TestReplayAttackShield:
    def test_pos_heartbeat_expired_timestamp_rejected(self, client):
        """
        Test 1: Gửi gói tin POS Heartbeat có timestamp cũ quá 5 phút (300s > 120s)
        -> Bị từ chối với HTTP 400 Bad Request (Replay Attack Shield kích hoạt).
        """
        expired_ts = time.time() - 300  # 5 minutes ago
        resp = client.post(
            "/api/v1/cc/attendance/pos/heartbeat",
            json={
                "pos_secret": POS_SECRET,
                "timestamp": expired_ts
            }
        )
        assert resp.status_code == 400
        assert "Replay Attack Shield" in resp.json()["detail"] or "lệch thời gian" in resp.json()["detail"]

    def test_pos_heartbeat_future_timestamp_rejected(self, client):
        """
        Gửi gói tin POS Heartbeat có timestamp lệch tương lai quá 120s
        -> Bị từ chối với HTTP 400 Bad Request.
        """
        future_ts = time.time() + 300  # 5 minutes in future
        resp = client.post(
            "/api/v1/cc/attendance/pos/heartbeat",
            json={
                "pos_secret": POS_SECRET,
                "timestamp": future_ts
            }
        )
        assert resp.status_code == 400
        assert "Replay Attack Shield" in resp.json()["detail"]

    def test_pos_heartbeat_valid_recent_timestamp_accepted(self, client):
        """
        Gửi gói tin POS Heartbeat có timestamp hợp lệ trong vòng 120s
        -> Chấp nhận thành công với HTTP 200.
        """
        valid_ts = time.time() - 10  # 10s ago (within 120s threshold)
        resp = client.post(
            "/api/v1/cc/attendance/pos/heartbeat",
            json={
                "pos_secret": POS_SECRET,
                "timestamp": valid_ts
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "cafe_ip" in data

    def test_pos_heartbeat_iso_format_timestamp(self, client):
        """
        Kiểm tra hỗ trợ định dạng ISO-8601 string cho timestamp trong heartbeat.
        """
        # Cũ 10 phút -> Bị từ chối
        old_iso = (datetime.now() - timedelta(minutes=10)).isoformat()
        resp = client.post(
            "/api/v1/cc/attendance/pos/heartbeat",
            json={
                "pos_secret": POS_SECRET,
                "timestamp": old_iso
            }
        )
        assert resp.status_code == 400

        # Mới 15 giây -> Thành công
        recent_iso = (datetime.now() - timedelta(seconds=15)).isoformat()
        resp_ok = client.post(
            "/api/v1/cc/attendance/pos/heartbeat",
            json={
                "pos_secret": POS_SECRET,
                "timestamp": recent_iso
            }
        )
        assert resp_ok.status_code == 200


# ==============================================================================
# TEST SUITE 2: GEOFENCE SPOOFING PROTECTION & CLIENT IP (attendance.py)
# ==============================================================================
class TestGeofenceSpoofingProtection:
    def _create_mock_request(self, client_host: str, headers: dict) -> Request:
        """Helper to construct a mock Starlette Request."""
        raw_headers = [
            (k.lower().encode("latin-1"), v.encode("latin-1"))
            for k, v in headers.items()
        ]
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/cc/attendance/checkin",
            "headers": raw_headers,
            "client": (client_host, 54321),
        }
        return Request(scope)

    def test_untrusted_direct_client_spoofing_x_forwarded_for_fails(self):
        """
        Test 2: Thử mạo danh header X-Forwarded-For với IP quán từ một client trực tiếp ngoài quán
        -> Backend không bị lừa, tuyệt đối không đọc X-Forwarded-For, vẫn lấy đúng client_ip thực.
        """
        cafe_public_ip = "203.0.113.10"
        attacker_real_ip = "203.0.113.195"

        # Attacker sends X-Forwarded-For: 203.0.113.10
        req = self._create_mock_request(
            client_host=attacker_real_ip,
            headers={
                "X-Forwarded-For": cafe_public_ip,
                "User-Agent": "AttackerBrowser/1.0"
            }
        )
        detected_ip = get_client_ip(req)
        # Backend must strictly return attacker_real_ip, NOT cafe_public_ip
        assert detected_ip == attacker_real_ip
        assert detected_ip != cafe_public_ip

    def test_untrusted_direct_client_spoofing_cf_connecting_ip_fails(self):
        """
        Nếu client trực tiếp gửi cf-connecting-ip nhưng không đi qua trusted proxy
        -> get_client_ip vẫn trả về direct client host, không tin cậy header.
        """
        cafe_public_ip = "203.0.113.10"
        attacker_real_ip = "198.51.100.88"

        req = self._create_mock_request(
            client_host=attacker_real_ip,
            headers={
                "CF-Connecting-IP": cafe_public_ip,
                "X-Forwarded-For": cafe_public_ip,
            }
        )
        detected_ip = get_client_ip(req)
        assert detected_ip == attacker_real_ip

    def test_trusted_proxy_never_inspects_x_forwarded_for(self):
        """
        Kể cả khi request đến từ trusted proxy (127.0.0.1), nếu không có cf-connecting-ip
        hay x-real-ip từ reverse proxy, backend TUYỆT ĐỐI không bao giờ đọc X-Forwarded-For.
        """
        cafe_public_ip = "203.0.113.10"
        req = self._create_mock_request(
            client_host="127.0.0.1",
            headers={
                "X-Forwarded-For": cafe_public_ip
            }
        )
        detected_ip = get_client_ip(req)
        # Never returns X-Forwarded-For value!
        assert detected_ip == "127.0.0.1"
        assert detected_ip != cafe_public_ip

    def test_trusted_proxy_accepts_cf_connecting_ip(self):
        """
        Khi request đi qua proxy tin cậy (127.0.0.1/Nginx/Cloudflare), cf-connecting-ip được tin cậy.
        """
        real_user_ip = "42.119.150.20"
        req = self._create_mock_request(
            client_host="127.0.0.1",
            headers={
                "CF-Connecting-IP": real_user_ip
            }
        )
        detected_ip = get_client_ip(req)
        assert detected_ip == real_user_ip


# ==============================================================================
# TEST SUITE 3: IMMUTABLE AUDIT TRAIL & SOFT DELETE (payroll_repo.py)
# ==============================================================================
class TestStaffLedgerSoftDelete:
    def test_soft_delete_preserves_record_in_database(self):
        """
        Test 3: Xóa bản ghi sổ phụ -> Bản ghi được đánh dấu is_deleted = 1,
        deleted_at và deleted_by được lưu vết đầy đủ, bản ghi vẫn còn trong database.
        """
        unique_id = f"LEDGER_TEST_{int(time.time() * 1000)}"
        ledger_entry = {
            "id": unique_id,
            "staff_name": "Nguyen Van Bin",
            "month": "2026-10",
            "type": "bonus",
            "amount": 200000,
            "payment_method": "cash",
            "reason": "Thưởng nóng phục vụ xuất sắc",
            "created_by": "Admin",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # 1. Insert ledger entry
        inserted = insert_staff_ledger(ledger_entry)
        assert inserted["id"] == unique_id

        # 2. Verify record exists and is active
        record_before = get_staff_ledger_by_id(unique_id)
        assert record_before is not None
        assert record_before["amount"] == 200000
        assert record_before.get("is_deleted", 0) in (0, None)

        # 3. Soft delete the ledger entry
        deleted_success = delete_staff_ledger(unique_id, deleted_by="Manager_Admin")
        assert deleted_success is True

        # 4. Check that record is NOT returned in normal list_staff_ledgers (filtered out)
        active_list = list_staff_ledgers(month="2026-10", staff_name="Nguyen Van Bin")
        found_in_active = any(r["id"] == unique_id for r in active_list)
        assert found_in_active is False

        # 5. Check that record IS returned when include_deleted=True
        full_list = list_staff_ledgers(month="2026-10", staff_name="Nguyen Van Bin", include_deleted=True)
        found_in_full = any(r["id"] == unique_id for r in full_list)
        assert found_in_full is True

        # 6. Verify directly in SQLite that audit trail columns are preserved
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, is_deleted, deleted_at, deleted_by FROM staff_ledgers WHERE id = ?", (unique_id,))
        row = cur.fetchone()
        conn.close()

        assert row is not None
        row_dict = dict(row)
        assert row_dict["id"] == unique_id
        assert row_dict["is_deleted"] == 1
        assert row_dict["deleted_by"] == "Manager_Admin"
        assert row_dict["deleted_at"] is not None
        assert len(str(row_dict["deleted_at"])) > 0


# ==============================================================================
# TEST SUITE 4: POS CLOSING OVERWRITE PROTECTION (pos_closing.py)
# ==============================================================================
class TestPosClosingOverwriteProtection:
    def test_cannot_overwrite_approved_closing_unless_admin(self, client, admin_token, manager_token, staff_token):
        """
        Test 4: Chống ghi đè ca đã chốt nếu ca đó đã có Quản lý hoặc Admin ký duyệt (approver_name),
        trừ khi chính Admin yêu cầu.
        """
        report_date = datetime.now().strftime("%d/%m/%Y")
        shift_key = f"ca_test_{int(time.time() * 1000)}"
        closing_time = f"21:{int(time.time()) % 50 + 10:02d}"

        # 1. Admin creates and approves closing
        res_create = client.post(
            "/api/v1/cc/pos/daily-closing",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "report_date": report_date,
                "closing_time": closing_time,
                "shift_key": shift_key,
                "bill_pos": 1500000.0,
                "cash_amount": 1000000.0,
                "transfer_amount": 500000.0,
                "expense_amount": 0.0,
                "sender_name": "Admin",
                "approver_name": "Admin_Approver"
            }
        )
        assert res_create.status_code == 200
        closing_id = res_create.json()["data"]["id"]

        # 2. Staff tries to overwrite the approved shift via daily-closing -> 403 Forbidden
        res_staff_overwrite = client.post(
            "/api/v1/cc/pos/daily-closing",
            headers={"Authorization": f"Bearer {staff_token}"},
            json={
                "report_date": report_date,
                "closing_time": closing_time,
                "shift_key": shift_key,
                "bill_pos": 1000000.0,
                "cash_amount": 500000.0,
                "transfer_amount": 500000.0,
                "expense_amount": 0.0,
                "sender_name": "Pha Chế"
            }
        )
        assert res_staff_overwrite.status_code == 403
        assert "đã được ký duyệt" in res_staff_overwrite.json()["detail"]

        # 3. Manager tries to reconcile / overwrite the approved shift -> 403 Forbidden
        res_mgr_reconcile = client.post(
            "/api/v1/cc/pos/reconcile",
            headers={"Authorization": f"Bearer {manager_token}"},
            json={
                "closing_id": closing_id,
                "bill_pos": 2000000.0,
                "approver_name": "Manager_Phat"
            }
        )
        assert res_mgr_reconcile.status_code == 403
        assert "Chỉ Admin mới có quyền điều chỉnh" in res_mgr_reconcile.json()["detail"]

        # 4. Admin adjusts the approved shift -> 200 OK
        res_admin_reconcile = client.post(
            "/api/v1/cc/pos/reconcile",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "closing_id": closing_id,
                "bill_pos": 1550000.0,
                "approver_name": "Admin_Approver_Updated"
            }
        )
        assert res_admin_reconcile.status_code == 200
        assert res_admin_reconcile.json()["status"] == "success"
