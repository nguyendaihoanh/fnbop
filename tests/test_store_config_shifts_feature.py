"""
Test Suite: Cấu Hình Ca & Quán Động (Store & Shifts Configuration Feature)
File: tests/test_store_config_shifts_feature.py

Covers 6 dedicated test cases:
1. GET /api/v1/cc/store/config: Kiểm tra cấu trúc hiện tại (store_name, shifts, roster_rules, pos_mode, holiday_rules...)
2. POST /api/v1/cc/store/config (Admin token):
   - Thêm ca chiều mới 'chieu' (12:00 - 17:00, 300 phút, 1 pha chế, 2 phục vụ)
   - Đổi giờ ca sáng 'sang' từ 06:00-11:30 sang 07:00-12:00
   - Đổi pos_mode sang 'manual'
   - Đổi gender_constraints.enabled = False
3. Attendance Recognition:
   - Trước khi thêm ca chiều / ngoài giờ ca: 13:00 bị OUTSIDE_SHIFT_HOURS
   - Sau khi cấu hình ca chiều: attendance.py & endpoint /status nhận diện ca chiều 'chieu' tại 13:00
4. Payroll Calculation:
   - payroll_calc.py lấy đúng thời lượng chuẩn 300 phút của ca 'chieu'
   - calculate_staff_payslip_breakdown tính chuẩn ca và trạng thái OT dựa trên 300 phút
5. POST /api/v1/cc/store/config/reset:
   - Khôi phục cấu hình mặc định FnBOps Standard
   - Verify store_name, pos_mode='pos365', shifts ban đầu (sang, toi), không còn 'chieu'
6. Security / RBAC Gate:
   - Nhân viên thường (role STAFF) gọi POST /api/v1/cc/store/config bị chặn HTTP 403 Forbidden
   - Nhân viên thường gọi POST /api/v1/cc/store/config/reset bị chặn HTTP 403 Forbidden
   - Request không có token bị chặn HTTP 401 Unauthorized
"""

import os
import sys
import json
import pytest
import shutil
import datetime
from fastapi.testclient import TestClient

# Ensure testing and on-premise flags
os.environ["TESTING"] = "1"
os.environ["ON_PREMISE_MODE"] = "true"

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.join(project_root, "backend")
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from routers.fnb_ops import create_access_token
from routers.attendance import detect_current_shift
from services.store_config import (
    get_store_config,
    save_store_config,
    DEFAULT_STORE_CONFIG
)
from services.payroll_calc import (
    get_shift_standard_mins,
    calculate_staff_payslip_breakdown
)
from services.db import init_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    """
    Thiết lập môi trường kiểm thử độc lập:
    - Cơ sở dữ liệu SQLite trong tmp_path
    - File cấu hình quán store_config.json trong tmp_path
    - File xác thực staff_auth.json trong tmp_path
    """
    db_file = str(tmp_path / "test_fnbop.db")
    config_file = str(tmp_path / "store_config.json")
    auth_file = str(tmp_path / "staff_auth.json")

    # Sao chép staff_auth.json gốc nếu có để có sẵn danh sách tài khoản active
    orig_auth = os.path.join(project_root, "data", "staff_auth.json")
    if os.path.exists(orig_auth):
        shutil.copy(orig_auth, auth_file)
    else:
        # Fallback tạo tài khoản staff test
        with open(auth_file, "w", encoding="utf-8") as f:
            json.dump({
                "payroll_locks": {},
                "staff_accounts": {
                    "nhuy": {
                        "username": "nhuy",
                        "full_name": "Nhân Viên 01",
                        "role": "STAFF",
                        "status": "ACTIVE",
                        "hourly_rate": 23000
                    }
                }
            }, f)

    monkeypatch.setenv("DATABASE_PATH", db_file)
    monkeypatch.setenv("STORE_CONFIG_FILE", config_file)
    monkeypatch.setenv("AUTH_FILE", auth_file)

    init_db(db_file)
    save_store_config(DEFAULT_STORE_CONFIG)


# =========================================================================
# TEST 1: GET /api/v1/cc/store/config
# =========================================================================

def test_1_get_store_config_structure():
    """
    Test 1: GET /api/v1/cc/store/config trả về đúng cấu trúc hiện tại:
    store_name, shifts, roster_rules, pos_mode, holiday_rules, auto_close_rules.
    """
    response = client.get("/api/v1/cc/store/config")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    data = response.json()
    assert data.get("success") is True
    assert "config" in data
    cfg = data["config"]

    # 1. Store basic info
    assert cfg.get("store_id") in ("default", "wfm_central")
    assert cfg.get("store_name") in ("FnBOps Store Lounge", "WFM Store Lounge")
    assert cfg.get("pos_mode") == "pos365"
    assert cfg.get("timezone") == "Asia/Ho_Chi_Minh"

    # 2. Operating shifts
    assert "shifts" in cfg
    shifts = cfg["shifts"]
    assert "sang" in shifts
    assert "toi" in shifts

    sang = shifts["sang"]
    assert sang.get("official_start") == "06:00"
    assert sang.get("official_end") == "11:30"
    assert sang.get("tolerance_limit") == "06:10"
    assert sang.get("min_checkout") == "11:00"
    assert sang.get("standard_mins") == 330
    assert "roles" in sang
    assert sang["roles"].get("barista") == 1
    assert sang["roles"].get("service") == 2

    toi = shifts["toi"]
    assert toi.get("official_start") == "17:00"
    assert toi.get("official_end") == "23:00"
    assert toi.get("standard_mins") == 360

    # 3. Roster rules & gender constraints
    assert "roster_rules" in cfg
    roster_rules = cfg["roster_rules"]
    assert "gender_constraints" in roster_rules
    assert roster_rules["gender_constraints"].get("enabled") is True
    assert "registration_window" in roster_rules
    assert "shifts_per_week" in roster_rules

    # 4. Holiday rules
    assert "holiday_rules" in cfg
    assert "02/09" in cfg["holiday_rules"].get("holidays", [])


# =========================================================================
# TEST 2: POST /api/v1/cc/store/config (Admin Token)
# =========================================================================

def test_2_admin_post_store_config_updates():
    """
    Test 2: POST /api/v1/cc/store/config với token Admin:
    + Thêm ca mới 'chieu': 12:00 - 17:00, chuẩn 300 phút, 1 pha chế, 2 phục vụ.
    + Thay đổi giờ ca sáng 'sang': từ 06:00-11:30 sang 07:00-12:00 (chuẩn 300 phút).
    + Chuyển pos_mode sang 'manual'.
    + Đổi ràng buộc giới tính gender_constraints.enabled = False.
    """
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán (Admin)"})

    # Lấy config hiện tại để chỉnh sửa
    current_cfg = get_store_config()

    # Thêm ca chiều 'chieu'
    current_cfg["shifts"]["chieu"] = {
        "key": "chieu",
        "name": "Ca Chiều",
        "official_start": "12:00",
        "official_end": "17:00",
        "tolerance_limit": "12:10",
        "min_checkout": "16:30",
        "standard_mins": 300,
        "roles": {
            "barista": 1,
            "service": 2
        },
        "window": {
            "start": "11:55",
            "end": "17:05"
        }
    }

    # Đổi giờ ca sáng 'sang' sang 07:00 - 12:00
    current_cfg["shifts"]["sang"]["official_start"] = "07:00"
    current_cfg["shifts"]["sang"]["official_end"] = "12:00"
    current_cfg["shifts"]["sang"]["tolerance_limit"] = "07:10"
    current_cfg["shifts"]["sang"]["min_checkout"] = "11:30"
    current_cfg["shifts"]["sang"]["standard_mins"] = 300
    current_cfg["shifts"]["sang"]["window"] = {
        "start": "06:55",
        "end": "12:15"
    }

    # Chuyển pos_mode sang manual
    current_cfg["pos_mode"] = "manual"

    # Đổi ràng buộc giới tính
    current_cfg["roster_rules"]["gender_constraints"]["enabled"] = False

    # Gửi POST request
    headers = {"Authorization": f"Bearer {admin_token}"}
    response = client.post("/api/v1/cc/store/config", json=current_cfg, headers=headers)
    assert response.status_code == 200, f"Update config failed: {response.text}"

    data = response.json()
    assert data.get("success") is True
    assert "config" in data
    updated = data["config"]

    # Verify kết quả trả về từ API
    assert updated["pos_mode"] == "manual"
    assert updated["roster_rules"]["gender_constraints"]["enabled"] is False
    assert updated["shifts"]["sang"]["official_start"] == "07:00"
    assert updated["shifts"]["sang"]["official_end"] == "12:00"
    assert updated["shifts"]["sang"]["standard_mins"] == 300

    assert "chieu" in updated["shifts"]
    chieu = updated["shifts"]["chieu"]
    assert chieu["name"] == "Ca Chiều"
    assert chieu["official_start"] == "12:00"
    assert chieu["official_end"] == "17:00"
    assert chieu["standard_mins"] == 300
    assert chieu["roles"]["barista"] == 1
    assert chieu["roles"]["service"] == 2

    # Verify persisted dữ liệu đọc lại từ file
    persisted = get_store_config()
    assert persisted["pos_mode"] == "manual"
    assert persisted["roster_rules"]["gender_constraints"]["enabled"] is False
    assert "chieu" in persisted["shifts"]
    assert persisted["shifts"]["chieu"]["standard_mins"] == 300


# =========================================================================
# TEST 3: ATTENDANCE RECOGNITION AT 13:00 (OUTSIDE vs DETECTED)
# =========================================================================

def test_3_attendance_detects_new_chieu_shift_at_13h():
    """
    Test 3: Kiểm tra attendance.py có nhận diện được ca chiều mới 'chieu' khi giả lập thời gian 13:00:
    - Trước khi có ca chiều (ca sáng 07:00-12:00 kết thúc lúc 12:15):
      Tại 13:00 hệ thống trả về OUTSIDE_SHIFT_HOURS, active_shift is None.
    - Sau khi thêm ca chiều (12:00 - 17:00, window 11:55-17:05):
      Tại 13:00 hệ thống nhận diện ca 'chieu', active_shift['key'] == 'chieu',
      shift_state == 'READY_TO_CHECKIN' (không còn bị OUTSIDE_SHIFT_HOURS).
    """
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN"})
    sim_time_13h = datetime.datetime(2026, 9, 26, 13, 0, 0)

    # 1. Cấu hình ca sáng 07:00-12:00, CHƯA có ca chiều
    cfg_without_chieu = get_store_config()
    cfg_without_chieu["shifts"]["sang"]["official_start"] = "07:00"
    cfg_without_chieu["shifts"]["sang"]["official_end"] = "12:00"
    cfg_without_chieu["shifts"]["sang"]["window"] = {"start": "06:55", "end": "12:15"}
    if "chieu" in cfg_without_chieu["shifts"]:
        del cfg_without_chieu["shifts"]["chieu"]
    save_store_config(cfg_without_chieu)

    # Kiểm tra trực tiếp qua hàm detect_current_shift
    shift_before = detect_current_shift(sim_time_13h)
    assert shift_before is None, "Khi chưa có ca chiều, tại 13:00 không được nhận diện ca"

    # Kiểm tra qua API attendance/status
    res_before = client.get("/api/v1/cc/attendance/status?dev_mode=true&simulated_time=13:00")
    assert res_before.status_code == 200
    data_before = res_before.json()
    assert data_before.get("active_shift") is None
    assert data_before.get("shift_state") == "OUTSIDE_SHIFT_HOURS"

    # 2. Thêm ca chiều 'chieu' qua API POST /api/v1/cc/store/config
    cfg_with_chieu = get_store_config()
    cfg_with_chieu["shifts"]["chieu"] = {
        "key": "chieu",
        "name": "Ca Chiều",
        "official_start": "12:00",
        "official_end": "17:00",
        "tolerance_limit": "12:10",
        "min_checkout": "16:30",
        "standard_mins": 300,
        "roles": {"barista": 1, "service": 2},
        "window": {"start": "11:55", "end": "17:05"}
    }
    post_res = client.post(
        "/api/v1/cc/store/config",
        json=cfg_with_chieu,
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert post_res.status_code == 200

    # 3. Kiểm tra lại tại 13:00 sau khi đã thêm ca chiều
    shift_after = detect_current_shift(sim_time_13h)
    assert shift_after is not None, "Ca chiều phải được nhận diện tại 13:00"
    assert shift_after["key"] == "chieu"
    assert shift_after["name"] == "Ca Chiều"
    assert shift_after["official_start"] == "12:00"
    assert shift_after["official_end"] == "17:00"

    # Kiểm tra lại qua endpoint API attendance/status
    res_after = client.get("/api/v1/cc/attendance/status?dev_mode=true&simulated_time=13:00")
    assert res_after.status_code == 200
    data_after = res_after.json()
    assert data_after.get("active_shift") is not None
    assert data_after["active_shift"]["key"] == "chieu"
    assert data_after["active_shift"]["name"] == "Ca Chiều"
    assert data_after.get("shift_state") == "READY_TO_CHECKIN"
    assert data_after.get("shift_state") != "OUTSIDE_SHIFT_HOURS"


# =========================================================================
# TEST 4: PAYROLL CALCULATION STANDARD MINUTES FOR CA CHIEU
# =========================================================================

def test_4_payroll_calc_standard_mins_for_chieu_shift():
    """
    Test 4: Kiểm tra payroll_calc.py có lấy đúng thời lượng chuẩn 300 phút của ca 'chieu' khi tính lương:
    - get_shift_standard_mins('Ca Chiều', '12:00') trả về 300
    - calculate_staff_payslip_breakdown với ca làm việc Ca Chiều:
      standard_shift_minutes == 300, ot_status == 'STANDARD' khi làm 300 phút
    """
    # Đảm bảo cấu hình có ca chiều 300 phút
    cfg = get_store_config()
    cfg["shifts"]["chieu"] = {
        "key": "chieu",
        "name": "Ca Chiều",
        "official_start": "12:00",
        "official_end": "17:00",
        "tolerance_limit": "12:10",
        "min_checkout": "16:30",
        "standard_mins": 300,
        "roles": {"barista": 1, "service": 2}
    }
    save_store_config(cfg)

    # 1. Kiểm tra hàm get_shift_standard_mins
    std_by_name = get_shift_standard_mins("Ca Chiều", "12:00")
    assert std_by_name == 300, f"Expected 300 standard mins for Ca Chiều, got {std_by_name}"

    std_by_key = get_shift_standard_mins("chieu", "12:00")
    assert std_by_key == 300, f"Expected 300 standard mins for chieu, got {std_by_key}"

    # 2. Kiểm tra tính bảng lương hoàn chỉnh với ca chiều
    mock_attendance_logs = [
        {
            "username": "nhuy",
            "display_name": "Nhân Viên 01",
            "date": "26/09/2026",
            "shift_key": "chieu",
            "shift_name": "Ca Chiều",
            "checkin_time": "12:00",
            "checkout_time": "17:00",
            "total_mins": 300,
            "status": "ON_TIME"
        }
    ]

    staff_accounts = {
        "nhuy": {
            "username": "nhuy",
            "full_name": "Nhân Viên 01",
            "hourly_rate": 23000,
            "role": "SERVICE"
        }
    }

    payslip = calculate_staff_payslip_breakdown(
        staff_name="Nhân Viên 01",
        month="9",
        data_json={"DỮ LIỆU": []},
        attendance_logs=mock_attendance_logs,
        staff_accounts=staff_accounts
    )

    assert payslip["total_shifts"] == 1
    assert payslip["total_worked_minutes"] == 300
    assert len(payslip["shift_records"]) == 1

    rec = payslip["shift_records"][0]
    assert rec["shift"] == "Ca Chiều"
    assert rec["minutes"] == 300.0
    assert rec["standard_shift_minutes"] == 300
    assert rec["ot_status"] == "STANDARD"
    # Lương 300 phút = 5 giờ * 23,000đ = 115,000đ
    assert rec["shift_cost"] == 115000.0
    assert payslip["standard_pay"] == 115000.0


# =========================================================================
# TEST 5: POST /api/v1/cc/store/config/reset (Reset to Default)
# =========================================================================

def test_5_admin_reset_store_config_to_fnbop_default():
    """
    Test 5: POST /api/v1/cc/store/config/reset khôi phục lại cấu hình gốc của FnBOps:
    - Status HTTP 200
    - Verify store_name trở về 'WFM Store Lounge'
    - Verify pos_mode trở về 'pos365'
    - Verify shifts ban đầu (sang 06:00-11:30, toi 17:00-23:00)
    - Verify ca 'chieu' không còn tồn tại
    - Verify gender_constraints.enabled trở về True
    """
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN"})
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Làm biến đổi cấu hình trước
    modified_cfg = get_store_config()
    modified_cfg["store_name"] = "Quán Tạm Thời"
    modified_cfg["pos_mode"] = "manual"
    modified_cfg["shifts"]["chieu"] = {"key": "chieu", "name": "Ca Chiều"}
    modified_cfg["shifts"]["sang"]["official_start"] = "08:00"
    modified_cfg["roster_rules"]["gender_constraints"]["enabled"] = False
    save_store_config(modified_cfg)

    # Đảm bảo cấu hình đang ở trạng thái bị sửa
    assert get_store_config()["store_name"] == "Quán Tạm Thời"
    assert "chieu" in get_store_config()["shifts"]

    # Gọi endpoint Reset
    reset_resp = client.post("/api/v1/cc/store/config/reset", headers=headers)
    assert reset_resp.status_code == 200, f"Reset failed: {reset_resp.text}"

    data = reset_resp.json()
    assert data.get("success") is True
    assert "Đã khôi phục cấu hình mặc định WFM thành công" in data.get("message", "")

    # Đọc lại từ cấu hình đã lưu
    reset_cfg = get_store_config()
    assert reset_cfg["store_name"] in ("FnBOps Store Lounge", "WFM Store Lounge")
    assert reset_cfg["pos_mode"] == "pos365"
    assert reset_cfg["timezone"] == "Asia/Ho_Chi_Minh"

    # Ca chiều không còn tồn tại
    assert "chieu" not in reset_cfg["shifts"]
    assert "sang" in reset_cfg["shifts"]
    assert "toi" in reset_cfg["shifts"]

    # Giờ ca sáng trở về 06:00 - 11:30, chuẩn 330 phút
    assert reset_cfg["shifts"]["sang"]["official_start"] == "06:00"
    assert reset_cfg["shifts"]["sang"]["official_end"] == "11:30"
    assert reset_cfg["shifts"]["sang"]["standard_mins"] == 330

    # Ràng buộc giới tính trở về True
    assert reset_cfg["roster_rules"]["gender_constraints"]["enabled"] is True


# =========================================================================
# TEST 6: SECURITY RBAC (STAFF role gets 403 Forbidden)
# =========================================================================

def test_6_security_staff_forbidden_to_modify_store_config():
    """
    Test 6: Kiểm tra bảo mật:
    - Nhân viên thường (role STAFF) gọi POST /api/v1/cc/store/config bị chặn với HTTP 403 Forbidden.
    - Nhân viên thường gọi POST /api/v1/cc/store/config/reset bị chặn với HTTP 403 Forbidden.
    - Request không có token hoặc token rỗng bị chặn với HTTP 401 Unauthorized.
    """
    staff_token = create_access_token({"sub": "nhanvien", "role": "STAFF", "name": "Nhân Viên"})
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    payload = {
        "store_name": "Quán Trái Phép",
        "pos_mode": "manual"
    }

    # 1. Staff cố gắng update config -> 403 Forbidden
    res_update = client.post("/api/v1/cc/store/config", json=payload, headers=staff_headers)
    assert res_update.status_code == 403, f"Expected 403 for STAFF update, got {res_update.status_code}"
    detail_msg = res_update.json().get("detail", "")
    assert "Chỉ Chủ quán (Admin) mới có quyền" in detail_msg

    # 2. Staff cố gắng reset config -> 403 Forbidden
    res_reset = client.post("/api/v1/cc/store/config/reset", headers=staff_headers)
    assert res_reset.status_code == 403, f"Expected 403 for STAFF reset, got {res_reset.status_code}"
    detail_msg_reset = res_reset.json().get("detail", "")
    assert "Chỉ Chủ quán (Admin) mới có quyền" in detail_msg_reset

    # 3. Anonymous / No token -> 401 Unauthorized
    res_anon_update = client.post("/api/v1/cc/store/config", json=payload)
    assert res_anon_update.status_code == 401, f"Expected 401 for anonymous update, got {res_anon_update.status_code}"

    res_anon_reset = client.post("/api/v1/cc/store/config/reset")
    assert res_anon_reset.status_code == 401, f"Expected 401 for anonymous reset, got {res_anon_reset.status_code}"

    # Đảm bảo cấu hình không hề bị thay đổi
    current = get_store_config()
    assert current["store_name"] in ("FnBOps Store Lounge", "WFM Store Lounge")


# ============================================================================
# TEST 7: NOTIFICATION GATEWAY (TELEGRAM TEST & ZALO QR)
# ============================================================================

def test_7_telegram_and_zalo_notification_gateway(monkeypatch):
    """
    Test 7: Cổng thông báo Notification Gateway:
    - Admin gửi tin nhắn thử nghiệm Telegram thành công (POST /api/v1/cc/store/test-telegram).
    - Nhân viên thường bị chặn 403 Forbidden.
    - Đọc mã QR kết nối Zalo Gateway (GET /api/v1/cc/store/zalo-qr).
    """
    monkeypatch.setenv("MOCK_TELEGRAM", "1")
    monkeypatch.setenv("TESTING", "1")

    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Quản Trị Viên"})
    staff_token = create_access_token({"sub": "phache", "role": "STAFF", "name": "Pha Chế"})

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # 1. Admin test Telegram
    res_tg = client.post(
        "/api/v1/cc/store/test-telegram",
        json={"token": "test_token_123", "chat_id": "123456789"},
        headers=admin_headers
    )
    assert res_tg.status_code == 200, res_tg.text
    data_tg = res_tg.json()
    assert data_tg.get("success") is True
    assert "thành công" in data_tg.get("message", "")

    # 2. Staff cannot test Telegram -> 403
    res_tg_staff = client.post(
        "/api/v1/cc/store/test-telegram",
        json={"token": "test_token_123", "chat_id": "123456789"},
        headers=staff_headers
    )
    assert res_tg_staff.status_code == 403

    # 3. Zalo QR Code endpoint
    res_qr = client.get("/api/v1/cc/store/zalo-qr", headers=admin_headers)
    assert res_qr.status_code == 200
    data_qr = res_qr.json()
    assert data_qr.get("success") is True
    if data_qr.get("connected"):
        assert data_qr.get("status") == "ready"
        assert "Tài khoản Zalo đã được kết nối" in data_qr.get("message", "")
    else:
        assert "qr" in data_qr
        assert len(data_qr["qr"]) > 0

