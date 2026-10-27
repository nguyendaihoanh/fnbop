"""
Test Suite: Role-Based Access Control (RBAC) & Security Hardening
File: tests/test_rbac_endpoints.py

Validates:
1. Excel Router RBAC (/export-payroll, /staff-template, /import-staff)
2. Notification Router RBAC (/send-payslip-email, /send-eval-email, /outbox, /preview-payslip-pdf, /outbox/clear)
3. POS Closing Router RBAC (/daily-closing, /reconcile, /daily-closings)
4. Admin Backdoor Removal & PIN 8888 verification
"""

import os
import sys
import io
import json
import pytest
import openpyxl
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
os.environ["ON_PREMISE_MODE"] = "true"

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.join(project_root, "backend")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from routers.fnb_ops import create_access_token, load_staff_auth, save_staff_auth

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_rbac_env(tmp_path):
    old_env = {
        "AUTH_FILE": os.environ.get("AUTH_FILE"),
        "DB_PATH": os.environ.get("DB_PATH"),
        "ADMIN_PASSWORD": os.environ.get("ADMIN_PASSWORD"),
    }
    # Set up test auth file
    test_auth_file = tmp_path / "staff_auth.json"
    auth_data = {
        "payroll_locks": {},
        "staff_accounts": {
            "admin": {
                "full_name": "Chủ Quán (Admin)",
                "sheet_names": ["Admin"],
                "pin": "8888",
                "role": "ADMIN",
                "status": "ACTIVE",
                "aliases": ["admin"]
            },
            "manager1": {
                "full_name": "Nguyễn Quản Lý",
                "sheet_names": ["Quản Lý"],
                "pin": "1234",
                "role": "MANAGER",
                "status": "ACTIVE"
            },
            "staff1": {
                "full_name": "Trần Nhân Viên",
                "sheet_names": ["Trần Nhân Viên"],
                "pin": "1234",
                "role": "STAFF",
                "status": "ACTIVE"
            },
            "staff2": {
                "full_name": "Lê Nhân Viên 2",
                "sheet_names": ["Lê Nhân Viên 2"],
                "pin": "1234",
                "role": "STAFF",
                "status": "ACTIVE"
            }
        }
    }
    with open(test_auth_file, "w", encoding="utf-8") as f:
        json.dump(auth_data, f)
    os.environ["AUTH_FILE"] = str(test_auth_file)
    os.environ["ADMIN_PASSWORD"] = "8888"

    test_db = str(tmp_path / "test_rbac.db")
    os.environ["DB_PATH"] = test_db
    from services.db import init_db
    init_db(test_db)

    yield

    for k, v in old_env.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


# ===========================================================================
# 1. EXCEL ROUTES RBAC TESTS
# ===========================================================================

def test_excel_export_payroll_rbac():
    # 1. Không có token -> 401
    res = client.get("/api/v1/cc/excel/export-payroll?month=9")
    assert res.status_code == 401

    # 2. Token nhân viên (STAFF) -> 403
    staff_token = create_access_token({"sub": "staff1", "role": "STAFF", "name": "Trần Nhân Viên"})
    res = client.get("/api/v1/cc/excel/export-payroll?month=9", headers={"Authorization": f"Bearer {staff_token}"})
    assert res.status_code == 403

    # 3. Token Quản lý (MANAGER) -> 200
    mgr_token = create_access_token({"sub": "manager1", "role": "MANAGER", "name": "Nguyễn Quản Lý"})
    res = client.get("/api/v1/cc/excel/export-payroll?month=9", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # 4. Token Admin qua Query Param ?token= -> 200
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})
    res = client.get(f"/api/v1/cc/excel/export-payroll?month=9&token={admin_token}")
    assert res.status_code == 200


def test_excel_staff_template_and_import_rbac():
    staff_token = create_access_token({"sub": "staff1", "role": "STAFF", "name": "Trần Nhân Viên"})
    mgr_token = create_access_token({"sub": "manager1", "role": "MANAGER", "name": "Nguyễn Quản Lý"})
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})

    # Template: STAFF -> 403, MANAGER -> 200, ADMIN -> 200
    res_staff = client.get("/api/v1/cc/excel/staff-template", headers={"Authorization": f"Bearer {staff_token}"})
    assert res_staff.status_code == 403

    res_mgr = client.get("/api/v1/cc/excel/staff-template", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res_mgr.status_code == 200

    # Import: Chỉ duy nhất ADMIN mới có quyền
    # Create simple dummy excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Mã NV", "Họ và tên", "Chức vụ", "Mã PIN"])
    ws.append(["nv99", "Nguyễn Test", "STAFF", "1234"])
    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    # Import with STAFF -> 403
    res_import_staff = client.post(
        "/api/v1/cc/excel/import-staff",
        headers={"Authorization": f"Bearer {staff_token}"},
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert res_import_staff.status_code == 403

    # Import with MANAGER -> 403
    res_import_mgr = client.post(
        "/api/v1/cc/excel/import-staff",
        headers={"Authorization": f"Bearer {mgr_token}"},
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert res_import_mgr.status_code == 403

    # Import with ADMIN -> 200
    res_import_admin = client.post(
        "/api/v1/cc/excel/import-staff",
        headers={"Authorization": f"Bearer {admin_token}"},
        files={"file": ("test.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    )
    assert res_import_admin.status_code == 200
    assert res_import_admin.json()["success"] is True


# ===========================================================================
# 2. NOTIFICATION & OUTBOX ROUTES RBAC TESTS
# ===========================================================================

def test_notification_routes_rbac():
    staff_token = create_access_token({"sub": "staff1", "role": "STAFF", "name": "Trần Nhân Viên", "sheet_names": ["Trần Nhân Viên"]})
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})

    # 1. Gửi email phiếu lương không có auth -> 401
    res = client.post("/api/v1/cc/notifications/send-payslip-email", json={"staff_name": "Trần Nhân Viên"})
    assert res.status_code == 401

    # 2. Gửi email phiếu lương bởi STAFF -> 403
    res = client.post(
        "/api/v1/cc/notifications/send-payslip-email",
        headers={"Authorization": f"Bearer {staff_token}"},
        json={"staff_name": "Trần Nhân Viên"}
    )
    assert res.status_code == 403

    # 3. Gửi email phiếu lương bởi ADMIN -> 200
    res = client.post(
        "/api/v1/cc/notifications/send-payslip-email",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"staff_name": "Trần Nhân Viên"}
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 4. Xem danh sách outbox: STAFF -> 403, ADMIN -> 200
    res_outbox_staff = client.get("/api/v1/cc/notifications/outbox", headers={"Authorization": f"Bearer {staff_token}"})
    assert res_outbox_staff.status_code == 403

    res_outbox_admin = client.get("/api/v1/cc/notifications/outbox", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_outbox_admin.status_code == 200

    # 5. Preview phiếu lương cá nhân:
    # STAFF1 xem của chính mình (Trần Nhân Viên) -> 200
    res_own = client.get(
        f"/api/v1/cc/notifications/preview-payslip-pdf?staff_name=Trần Nhân Viên&month=9&token={staff_token}"
    )
    assert res_own.status_code == 200
    assert res_own.headers["content-type"] == "application/pdf"

    # STAFF1 xem của nhân viên khác (Lê Nhân Viên 2) -> 403
    res_other = client.get(
        f"/api/v1/cc/notifications/preview-payslip-pdf?staff_name=Lê Nhân Viên 2&month=9&token={staff_token}"
    )
    assert res_other.status_code == 403

    # ADMIN xem của bất kỳ ai -> 200
    res_admin_view = client.get(
        f"/api/v1/cc/notifications/preview-payslip-pdf?staff_name=Lê Nhân Viên 2&month=9&token={admin_token}"
    )
    assert res_admin_view.status_code == 200


def test_outbox_clear_admin_only_rbac():
    staff_token = create_access_token({"sub": "staff1", "role": "STAFF", "name": "Trần Nhân Viên"})
    mgr_token = create_access_token({"sub": "manager1", "role": "MANAGER", "name": "Nguyễn Quản Lý"})
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})

    # Xóa outbox: STAFF -> 403
    res = client.delete("/api/v1/cc/notifications/outbox/clear", headers={"Authorization": f"Bearer {staff_token}"})
    assert res.status_code == 403

    # Xóa outbox: MANAGER -> 403
    res = client.delete("/api/v1/cc/notifications/outbox/clear", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res.status_code == 403

    # Xóa outbox: ADMIN -> 200
    res = client.delete("/api/v1/cc/notifications/outbox/clear", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert res.json()["success"] is True


# ===========================================================================
# 3. POS CLOSING ROUTES RBAC TESTS
# ===========================================================================

def test_pos_closing_rbac():
    staff_token = create_access_token({"sub": "staff1", "role": "STAFF", "name": "Trần Nhân Viên"})
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})

    # 1. Chốt ca không có token -> 401
    closing_payload = {
        "report_date": "27/09/2026",
        "cash_amount": 1500000.0,
        "sender_name": "Trần Nhân Viên"
    }
    res = client.post("/api/v1/cc/pos/daily-closing", json=closing_payload)
    assert res.status_code == 401

    # 2. Nhân viên đăng nhập gửi chốt két ca -> 200
    res = client.post("/api/v1/cc/pos/daily-closing", headers={"Authorization": f"Bearer {staff_token}"}, json=closing_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    closing_id = data["data"]["id"]

    # 3. Đối soát (/reconcile): STAFF -> 403
    reconcile_payload = {
        "closing_id": closing_id,
        "bill_pos": 1500000.0,
        "transfer_amount": 0.0,
        "approver_name": "Admin"
    }
    res = client.post("/api/v1/cc/pos/reconcile", headers={"Authorization": f"Bearer {staff_token}"}, json=reconcile_payload)
    assert res.status_code == 403

    # 4. Đối soát (/reconcile): ADMIN -> 200
    res = client.post("/api/v1/cc/pos/reconcile", headers={"Authorization": f"Bearer {admin_token}"}, json=reconcile_payload)
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # 5. Xem lịch sử (/daily-closings):
    # Unauthenticated -> 401
    res = client.get("/api/v1/cc/pos/daily-closings")
    assert res.status_code == 401

    # STAFF1 gọi -> Chỉ thấy ca của chính mình ("Trần Nhân Viên")
    res_staff = client.get("/api/v1/cc/pos/daily-closings", headers={"Authorization": f"Bearer {staff_token}"})
    assert res_staff.status_code == 200
    records = res_staff.json()["records"]
    assert len(records) >= 1
    for r in records:
        assert r["sender_name"] == "Trần Nhân Viên"

    # ADMIN gọi -> Thấy tất cả các ca
    res_admin = client.get("/api/v1/cc/pos/daily-closings", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_admin.status_code == 200
    assert len(res_admin.json()["records"]) >= 1


# ===========================================================================
# 4. ADMIN LOGIN & BACKDOOR REMOVAL TESTS
# ===========================================================================

def test_admin_login_8888_and_backdoor_eradication():
    # 1. Đăng nhập đúng với 8888 -> 200
    res = client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "8888"})
    assert res.status_code == 200
    assert res.json()["role"] == "ADMIN"
    assert "access_token" in res.json()

    # 2. Đăng nhập với backdoor cũ 1234 -> 401
    res_b1 = client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "1234"})
    assert res_b1.status_code == 401

    # 3. Đăng nhập với backdoor cũ 261109 -> 401
    res_b2 = client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "261109"})
    assert res_b2.status_code == 401


def test_manager_cannot_escalate_privileges_on_admin_or_managers():
    manager_token = create_access_token({"sub": "manager1", "username": "manager1", "role": "MANAGER"})

    # 1. Manager cố gắng đổi PIN của Admin -> 403 Forbidden
    res_pin_admin = client.post(
        "/api/v1/cc/admin/update-pin",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"username": "admin", "new_pin": "9999"}
    )
    assert res_pin_admin.status_code == 403
    assert "Quản lý không có quyền đổi PIN" in res_pin_admin.json()["detail"]

    # 2. Manager cố gắng khóa tài khoản của Admin -> 403 Forbidden
    res_toggle_admin = client.post(
        "/api/v1/cc/admin/toggle-staff-status",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"username": "admin", "status": "INACTIVE"}
    )
    assert res_toggle_admin.status_code == 403
    assert "Quản lý không có quyền thay đổi trạng thái" in res_toggle_admin.json()["detail"]

    # 3. Manager đổi PIN cho nhân viên thường staff1 -> 200 OK
    res_pin_staff = client.post(
        "/api/v1/cc/admin/update-pin",
        headers={"Authorization": f"Bearer {manager_token}"},
        json={"username": "staff1", "new_pin": "5678"}
    )
    assert res_pin_staff.status_code == 200
    assert res_pin_staff.json()["success"] is True


def test_store_config_and_maintenance_strictly_admin_only():
    """
    Xác minh nghiêm ngặt chỉ duy nhất ADMIN mới có quyền thực hiện
    các tác vụ cấu hình quán nhạy cảm: Test Telegram, Zalo Gateway, Safe WAL Backup.
    Nhân viên (STAFF) và Quản lý (MANAGER) đều bị chặn 403 Forbidden.
    """
    staff_token = create_access_token({"sub": "staff1", "role": "STAFF", "name": "Nhân Viên"})
    mgr_token = create_access_token({"sub": "manager1", "role": "MANAGER", "name": "Quản Lý"})
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})

    # 1. POST /store/test-telegram
    res_tg_staff = client.post("/api/v1/cc/store/test-telegram", headers={"Authorization": f"Bearer {staff_token}"}, json={})
    assert res_tg_staff.status_code == 403

    res_tg_mgr = client.post("/api/v1/cc/store/test-telegram", headers={"Authorization": f"Bearer {mgr_token}"}, json={})
    assert res_tg_mgr.status_code == 403

    res_tg_admin = client.post("/api/v1/cc/store/test-telegram", headers={"Authorization": f"Bearer {admin_token}"}, json={"bot_token": "dummy", "chat_id": "123"})
    assert res_tg_admin.status_code == 200

    # 2. GET /store/zalo-status
    res_zalo_staff = client.get("/api/v1/cc/store/zalo-status", headers={"Authorization": f"Bearer {staff_token}"})
    assert res_zalo_staff.status_code == 403

    res_zalo_mgr = client.get("/api/v1/cc/store/zalo-status", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res_zalo_mgr.status_code == 403

    res_zalo_admin = client.get("/api/v1/cc/store/zalo-status", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_zalo_admin.status_code == 200

    # 3. GET /store/zalo-qr
    res_qr_staff = client.get("/api/v1/cc/store/zalo-qr", headers={"Authorization": f"Bearer {staff_token}"})
    assert res_qr_staff.status_code == 403

    res_qr_mgr = client.get("/api/v1/cc/store/zalo-qr", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res_qr_mgr.status_code == 403

    res_qr_admin = client.get("/api/v1/cc/store/zalo-qr", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_qr_admin.status_code == 200

    # 4. POST /admin/safe-backup
    res_bk_staff = client.post("/api/v1/cc/admin/safe-backup", headers={"Authorization": f"Bearer {staff_token}"})
    assert res_bk_staff.status_code == 403

    res_bk_mgr = client.post("/api/v1/cc/admin/safe-backup", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res_bk_mgr.status_code == 403

    res_bk_admin = client.post("/api/v1/cc/admin/safe-backup", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_bk_admin.status_code == 200
    assert res_bk_admin.json()["success"] is True

    # 5. GET /store/config credential masking
    res_cfg_anon = client.get("/api/v1/cc/store/config")
    assert res_cfg_anon.status_code == 200
    anon_cfg = res_cfg_anon.json()["config"]
    assert "bot_token" not in anon_cfg.get("notifications", {}).get("telegram", {})
    assert "chat_id" not in anon_cfg.get("notifications", {}).get("telegram", {})

    res_cfg_staff = client.get("/api/v1/cc/store/config", headers={"Authorization": f"Bearer {staff_token}"})
    assert res_cfg_staff.status_code == 200
    staff_cfg = res_cfg_staff.json()["config"]
    assert "bot_token" not in staff_cfg.get("notifications", {}).get("telegram", {})

    res_cfg_admin = client.get("/api/v1/cc/store/config", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_cfg_admin.status_code == 200
    admin_cfg = res_cfg_admin.json()["config"]
    assert "telegram" in admin_cfg.get("notifications", {})


