"""
Comprehensive Data Integrity, Sổ Phụ Anti-Duplication, Account Sync & Security Audit Suite.
Covers all 4 core audit pillars:
1. Anti-duplicate Sổ Phụ: eval_logs.json, data.json SỔ PHỤ, SQLite staff_ledgers.
2. 2-way account synchronization: JSON <-> SQLite staff_accounts + Excel Import auto-sync.
3. Payroll Lock server-side tamper-proof enforcement (HTTP 423 Locked).
4. Security: 3-Tier Progressive Lockout, Cafe WiFi isolation, Inactive Offboarding, Rate Limiting.
"""

import time
import uuid
import json
import pytest
from fastapi.testclient import TestClient

from main import app
from routers.fnb_ops import (
    create_access_token,
    load_staff_auth,
    save_staff_auth,
    check_payroll_lock_status
)
from services.payroll_calc import calculate_staff_payslip_breakdown
from services.db import (
    init_db,
    get_staff_by_username,
    get_db_connection,
    record_failed_attempt_tiered,
    check_login_lockout,
    clear_login_lockout,
    admin_unlock_target,
    check_api_rate_limit,
    clear_all_rate_limits,
    delete_staff_ledger
)
from services.storage import verify_pin
from services.excel_manager import generate_staff_template, import_staff_from_excel, HAS_OPENPYXL


@pytest.fixture(autouse=True)
def ensure_db_ready():
    init_db()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_token():
    return create_access_token(data={"sub": "admin", "role": "ADMIN", "name": "Chủ Hộ (Admin)"})


# ==============================================================================
# PILLAR 1: ANTI-DUPLICATE SỔ PHỤ
# ==============================================================================

def test_01_anti_duplicate_so_phu_calculation():
    """
    Kịch bản kiểm thử: Cùng 1 khoản thưởng, 1 khoản phạt và 1 khoản ứng xuất hiện
    ở cả 3 nguồn: eval_logs.json, data.json SỔ PHỤ và SQLite staff_ledgers.
    Xác minh: calculate_staff_payslip_breakdown() chỉ tính DUY NHẤT 1 LẦN.
    """
    staff_name = "Nguyễn Văn Thiên"
    month = "9"

    # Nguồn 1: eval_logs.json
    evaluations = [
        {
            "id": "EVAL_AUDIT_1",
            "staffName": "Nguyễn Văn Thiên",
            "month": "9",
            "type": "bonus",
            "amount": 200000,
            "reason": "Thưởng chuyên cần tuần 1",
            "status": "APPROVED"
        },
        {
            "id": "EVAL_AUDIT_2",
            "staffName": "Nguyễn Văn Thiên",
            "month": "9",
            "type": "deduction",
            "amount": 50000,
            "reason": "Đi trễ ca tối 15 phút",
            "status": "APPROVED"
        }
    ]

    # Nguồn 2: data.json SỔ PHỤ (dữ liệu mirror từ Google Sheet)
    data_json = {
        "NHÂN VIÊN": [
            ["STT", "Họ và Tên", "Vai trò", "17000"],
            ["", "Nguyễn Văn Thiên", "Phục vụ", "17000"]
        ],
        "DỮ LIỆU": [
            ["STT", "Ngày", "Tên", "Ca làm", "06:00", "11:30", "330", "", "9"]
        ],
        "SỔ PHỤ": [
            ["STT", "Tên nhân viên", "Tháng", "Loại", "Số tiền", "Ngày", "Lý do"],
            ["1", "Nguyễn Văn Thiên", "9", "Thưởng", "200,000", "07/09/2026", "Thưởng chuyên cần tuần 1"],
            ["2", "Nguyễn Văn Thiên", "9", "Phạt", "50,000", "08/09/2026", "Đi trễ ca tối 15 phút"],
            ["3", "Nguyễn Văn Thiên", "9", "Tạm ứng", "100,000", "10/09/2026", "Ứng tiền mặt mua tạp dề"]
        ]
    }

    # Nguồn 3: SQLite staff_ledgers (dữ liệu ghi nhận qua API Sổ Phụ)
    staff_ledgers = [
        {
            "id": "LEDGER_AUDIT_1",
            "staff_name": "Nguyễn Văn Thiên",
            "month": "9",
            "type": "bonus",
            "amount": 200000,
            "reason": "Thưởng chuyên cần tuần 1"
        },
        {
            "id": "LEDGER_AUDIT_2",
            "staff_name": "Nguyễn Văn Thiên",
            "month": "9",
            "type": "deduction",
            "amount": 50000,
            "reason": "Đi trễ ca tối 15 phút"
        },
        {
            "id": "LEDGER_AUDIT_3",
            "staff_name": "Nguyễn Văn Thiên",
            "month": "9",
            "type": "advance",
            "amount": 100000,
            "reason": "Ứng tiền mặt mua tạp dề"
        }
    ]

    breakdown = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=month,
        data_json=data_json,
        evaluations=evaluations,
        staff_ledgers=staff_ledgers
    )

    # Khẳng định: Khoản thưởng 200k chỉ được tính 1 lần (không bị nhân ba thành 600k)
    assert breakdown["eval_bonus"] == 200000, f"Thưởng bị nhân đôi/nhân ba! Thực tế: {breakdown['eval_bonus']}"

    # Khẳng định: Khoản phạt 50k chỉ được tính 1 lần (không bị nhân ba thành 150k)
    assert breakdown["eval_deductions"] == 50000, f"Phạt bị nhân đôi/nhân ba! Thực tế: {breakdown['eval_deductions']}"

    # Khẳng định: Khoản ứng 100k chỉ được tính 1 lần (không bị nhân đôi thành 200k)
    assert breakdown["advance_amount"] == 100000, f"Tạm ứng bị nhân đôi! Thực tế: {breakdown['advance_amount']}"

    # Kiểm tra tính toán lương thực nhận (Net pay)
    standard_pay = breakdown["standard_pay"]
    expected_net = max(0, standard_pay + 200000 - 50000 - 100000)
    assert breakdown["net_pay"] == expected_net


def test_02_distinct_entries_preserved_without_false_dedup():
    """
    Xác minh thuật toán chống đếm trùng KHÔNG gây xóa nhầm các khoản thưởng/phạt
    hợp lệ có cùng số tiền nhưng khác lý do hoặc khác ngày.
    """
    staff_name = "Nguyễn Văn Thiên"
    month = "9"

    evaluations = [
        {"id": "EV1", "staffName": "Nguyễn Văn Thiên", "month": "9", "type": "bonus", "amount": 100000, "reason": "Thưởng ca sáng", "status": "APPROVED"},
        {"id": "EV2", "staffName": "Nguyễn Văn Thiên", "month": "9", "type": "bonus", "amount": 100000, "reason": "Thưởng doanh số tối", "status": "APPROVED"}
    ]

    breakdown = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=month,
        evaluations=evaluations
    )
    # Cả 2 khoản 100k khác lý do phải được cộng dồn thành 200k
    assert breakdown["eval_bonus"] == 200000


# ==============================================================================
# PILLAR 2: 2-WAY ACCOUNT SYNCHRONIZATION
# ==============================================================================

def test_03_bi_directional_account_crud_and_sync(client, admin_token):
    """
    Kiểm tra đồng bộ 2 chiều qua API Admin:
    1. Tạo nhân viên -> cả JSON và SQLite đều có record.
    2. Đổi PIN -> cả JSON (plaintext/hash) và SQLite (bcrypt) đều cập nhật.
    3. Đổi trạng thái -> JSON cập nhật status, SQLite cập nhật status + is_active.
    4. Sửa hồ sơ (gender, position) -> cả 2 nguồn khớp 100%.
    """
    test_u = "auditstaffsync"

    def cleanup():
        auth = load_staff_auth()
        if test_u in auth.get("staff_accounts", {}):
            del auth["staff_accounts"][test_u]
            save_staff_auth(auth)
        conn = get_db_connection()
        with conn:
            conn.execute("DELETE FROM staff_accounts WHERE username = ?", (test_u,))
            conn.execute("DELETE FROM staff_aliases WHERE username = ?", (test_u,))
        conn.close()

    cleanup()
    try:
        # 1. Tạo nhân sự mới
        res_create = client.post(
            "/api/v1/cc/admin/create-staff-account",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "username": test_u,
                "full_name": "Nhân Viên Kiểm Thử Sync",
                "pin": "5566",
                "role": "STAFF",
                "gender": "NAM",
                "position": "BARISTA"
            }
        )
        assert res_create.status_code == 200
        assert res_create.json()["success"] is True

        auth = load_staff_auth()
        assert test_u in auth["staff_accounts"]
        assert verify_pin("5566", auth["staff_accounts"][test_u]["pin"]) is True
        assert auth["staff_accounts"][test_u]["status"] == "ACTIVE"

        acc_db = get_staff_by_username(test_u)
        assert acc_db is not None
        assert acc_db["full_name"] == "Nhân Viên Kiểm Thử Sync"
        assert acc_db["status"] == "ACTIVE"
        assert acc_db["is_active"] in (1, True)
        assert verify_pin("5566", acc_db["pin_hash"]) is True

        # 2. Đổi mã PIN
        res_pin = client.post(
            "/api/v1/cc/admin/update-pin",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"username": test_u, "new_pin": "9988"}
        )
        assert res_pin.status_code == 200
        auth = load_staff_auth()
        assert verify_pin("9988", auth["staff_accounts"][test_u]["pin"]) is True
        acc_db = get_staff_by_username(test_u)
        assert verify_pin("9988", acc_db["pin_hash"]) is True

        # 3. Đổi trạng thái sang INACTIVE
        res_st = client.post(
            "/api/v1/cc/admin/toggle-staff-status",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"username": test_u, "status": "INACTIVE"}
        )
        assert res_st.status_code == 200
        auth = load_staff_auth()
        assert auth["staff_accounts"][test_u]["status"] == "INACTIVE"
        acc_db = get_staff_by_username(test_u)
        assert acc_db["status"] == "INACTIVE"
        assert acc_db["is_active"] in (0, False)

        # 4. Sửa hồ sơ (gender, position)
        res_prof = client.post(
            "/api/v1/cc/admin/update-staff-profile",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"username": test_u, "position": "MANAGER", "gender": "NU", "full_name": "Nhân Viên Đã Thăng Chức"}
        )
        assert res_prof.status_code == 200
        auth = load_staff_auth()
        assert auth["staff_accounts"][test_u]["position"] == "MANAGER"
        assert auth["staff_accounts"][test_u]["gender"] == "NU"
        assert auth["staff_accounts"][test_u]["full_name"] == "Nhân Viên Đã Thăng Chức"

        acc_db = get_staff_by_username(test_u)
        assert acc_db["position"] == "MANAGER"
        assert acc_db["gender"] == "NU"
        assert acc_db["full_name"] == "Nhân Viên Đã Thăng Chức"

    finally:
        cleanup()


@pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl is optional")
def test_04_excel_import_auto_mirrors_to_staff_auth_json():
    """
    Kiểm tra Import Excel vào SQLite có tự động đồng bộ sang staff_auth.json không.
    """
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f_db:
        tmp_db = f_db.name
    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f_auth:
        tmp_auth = f_auth.name
        json.dump({"staff_accounts": {}, "payroll_locks": {}}, f_auth)

    os.environ["AUTH_FILE"] = tmp_auth
    orig_db = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = tmp_db
    init_db(tmp_db)

    try:
        template_bytes = generate_staff_template()
        res = import_staff_from_excel(template_bytes)
        assert res["success"] is True
        assert res["count"] >= 3

        # Đọc staff_auth.json xem đã được cập nhật chưa
        with open(tmp_auth, "r", encoding="utf-8") as f:
            auth_data = json.load(f)

        assert "nhanvien01" in auth_data["staff_accounts"]
        assert "nhanvien02" in auth_data["staff_accounts"]
        assert "nhanvien03" in auth_data["staff_accounts"]

        assert auth_data["staff_accounts"]["nhanvien01"]["role"] == "MANAGER"
        assert auth_data["staff_accounts"]["nhanvien02"]["status"] == "ACTIVE"
    finally:
        os.environ.pop("AUTH_FILE", None)
        if orig_db:
            os.environ["DATABASE_PATH"] = orig_db
        else:
            os.environ.pop("DATABASE_PATH", None)
        for ext in ["", "-wal", "-shm"]:
            p = f"{tmp_db}{ext}"
            if os.path.exists(p): os.remove(p)
        if os.path.exists(tmp_auth): os.remove(tmp_auth)


# ==============================================================================
# PILLAR 3: PAYROLL LOCK SERVER-SIDE ENFORCEMENT
# ==============================================================================

def test_05_payroll_lock_strictly_enforced_at_api_server_level(client, admin_token):
    """
    Kiểm thử tính năng Khóa sổ kỳ lương:
    1. Khi Admin khóa kỳ lương tháng 9 (status=LOCKED):
       - Ghi Sổ Phụ -> Bị chặn với HTTP 423 Locked.
       - Xóa Sổ Phụ -> Bị chặn với HTTP 423 Locked.
       - Thêm đánh giá/thưởng phạt -> Bị chặn với HTTP 423 Locked.
       - Duyệt OT ca làm việc -> Bị chặn với HTTP 423 Locked.
    2. Khi Admin mở khóa kỳ lương tháng 9 (status=OPEN):
       - Mọi thao tác thành công bình thường (HTTP 200).
    """
    # 1. Admin Khóa kỳ lương tháng 9
    res_lock = client.post(
        "/api/v1/cc/admin/toggle-lock",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"month": "9", "status": "LOCKED", "message": "Khóa sổ đối soát tháng 9"}
    )
    assert res_lock.status_code == 200
    assert res_lock.json()["payroll_locks"]["9"]["status"] == "LOCKED"

    # Thử 1: Ghi thêm Sổ Phụ khi đã khóa
    res_ledger_block = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "staff_name": "Nguyễn Văn Thiên",
            "month": "9",
            "type": "bonus",
            "amount": 100000,
            "reason": "Ghi thử khi đã khóa"
        }
    )
    assert res_ledger_block.status_code == 423
    assert "KHÓA SỔ" in res_ledger_block.json()["detail"]

    # Thử 2: Thêm đánh giá / thưởng phạt khi đã khóa
    res_eval_block = client.post(
        "/api/v1/cc/admin/staff-evaluation",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "staff_name": "Nguyễn Văn Thiên",
            "date": "2026-09-18",
            "shift": "Ca Tối",
            "type": "Thưởng",
            "amount": 100000,
            "reason": "Đánh giá thử khi đã khóa"
        }
    )
    assert res_eval_block.status_code == 423
    assert "KHÓA SỔ" in res_eval_block.json()["detail"]

    # Thử 3: Duyệt OT ca làm việc trong tháng đã khóa
    res_ot_block = client.post(
        "/api/v1/cc/shifts/confirm-ot",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "shift_key": "18/09/2026|bin|Ca Tối|18:00",
            "action": "APPROVE",
            "approved_mins": 360,
            "manager_note": "Duyệt thử khi đã khóa"
        }
    )
    assert res_ot_block.status_code == 423
    assert "KHÓA SỔ" in res_ot_block.json()["detail"]

    # 2. Mở khóa tháng 9
    res_unlock = client.post(
        "/api/v1/cc/admin/toggle-lock",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"month": "9", "status": "OPEN", "message": ""}
    )
    assert res_unlock.status_code == 200

    # 3. Ghi Sổ Phụ khi đã mở -> Thành công HTTP 200
    res_ledger_ok = client.post(
        "/api/v1/cc/payroll/ledger",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "staff_name": "Nguyễn Văn Thiên",
            "month": "9",
            "type": "bonus",
            "amount": 100000,
            "reason": "Ghi khi đã mở"
        }
    )
    assert res_ledger_ok.status_code == 200
    lid = res_ledger_ok.json()["entry"]["id"]

    # Khóa lại và thử Xóa Sổ Phụ
    client.post(
        "/api/v1/cc/admin/toggle-lock",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"month": "9", "status": "LOCKED", "message": "Khóa lại"}
    )
    res_del_block = client.delete(
        f"/api/v1/cc/payroll/ledger/{lid}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert res_del_block.status_code == 423
    assert "KHÓA SỔ" in res_del_block.json()["detail"]

    # Mở khóa và xóa sạch dữ liệu test
    client.post(
        "/api/v1/cc/admin/toggle-lock",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"month": "9", "status": "OPEN", "message": ""}
    )
    res_del_ok = client.delete(
        f"/api/v1/cc/payroll/ledger/{lid}",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert res_del_ok.status_code == 200


# ==============================================================================
# PILLAR 4: SECURITY & BRUTE-FORCE RATE-LIMITING
# ==============================================================================

def test_06_three_tier_progressive_lockout_and_admin_unlock(client, admin_token):
    """
    Kiểm thử 3 tầng khóa bảo vệ chống dò mã PIN / brute-force:
    - Tier 1: Sai 5 lần -> Tạm khóa 60 giây.
    - Tier 2: Sai 6 lần -> Tạm khóa 30 phút.
    - Tier 3: Sai 11 lần -> Khóa 5 tiếng + is_admin_locked=1.
    - Admin mở khóa: Mở khóa tức thì qua API /admin/lockouts/unlock.
    """
    clear_all_rate_limits()
    ip = "198.51.100.99"
    u = "victim_staff"

    # Lần 1-4: Không bị khóa
    for _ in range(4):
        res = record_failed_attempt_tiered(ip=ip, username=u, is_whitelisted_cafe=False)
        assert res["is_locked"] is False

    # Lần 5: Kích hoạt Tier 1 (60s)
    res5 = record_failed_attempt_tiered(ip=ip, username=u, is_whitelisted_cafe=False)
    assert res5["tier"] == 1
    assert res5["is_locked"] is True
    info5 = check_login_lockout(ip=ip, username=u)
    assert info5 is not None
    assert info5["tier"] == 1
    assert info5["remaining_seconds"] > 0

    # Lần 6: Kích hoạt Tier 2 (30 phút)
    res6 = record_failed_attempt_tiered(ip=ip, username=u, is_whitelisted_cafe=False)
    assert res6["tier"] == 2
    info6 = check_login_lockout(ip=ip, username=u)
    assert info6["tier"] == 2
    assert info6["remaining_seconds"] > 1700

    # Lần 7-11: Kích hoạt Tier 3 (5 tiếng + Admin lock)
    for _ in range(7, 11):
        record_failed_attempt_tiered(ip=ip, username=u, is_whitelisted_cafe=False)

    res11 = record_failed_attempt_tiered(ip=ip, username=u, is_whitelisted_cafe=False)
    assert res11["tier"] == 3
    assert res11["is_admin_locked"] == 1
    info11 = check_login_lockout(ip=ip, username=u)
    assert info11["is_admin_locked"] == 1
    assert info11["remaining_seconds"] > 17000

    # Admin Mở khóa qua API
    res_unlock = client.post(
        "/api/v1/cc/admin/lockouts/unlock",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"target_key": res11["target_key"]}
    )
    assert res_unlock.status_code == 200
    assert res_unlock.json()["unlocked"] is True

    # Trạng thái mở khóa ngay lập tức
    assert check_login_lockout(ip=ip, username=u) is None


def test_07_cafe_wifi_targeting_isolation():
    """
    Xác minh phân lập bảo vệ WiFi Quán:
    - Khi ở trên WiFi quán (is_whitelisted_cafe=True), hệ thống chỉ khóa đích danh username vi phạm,
      tuyệt đối KHÔNG khóa IP của quán để tránh gây DoS máy POS hoặc các nhân viên khác.
    """
    cafe_ip = "192.168.1.100"
    user_attacker = "bad_user"

    for _ in range(5):
        res = record_failed_attempt_tiered(ip=cafe_ip, username=user_attacker, is_whitelisted_cafe=True)

    assert res["target_type"] == "USER"
    assert res["target_key"] == f"user:{user_attacker}"

    # Nhân viên khác đăng nhập trên cùng IP quán vẫn hoàn toàn hợp lệ
    other_lock = check_login_lockout(ip=cafe_ip, username="good_barista")
    assert other_lock is None

    clear_login_lockout(ip=cafe_ip, username=user_attacker)


def test_08_inactive_staff_offboarding_rejection(client):
    """
    Xác minh nhân viên đã offboard (status=INACTIVE) bị từ chối đăng nhập với HTTP 403 Forbidden.
    """
    auth = load_staff_auth()
    auth["staff_accounts"]["dummy_inactive_user"] = {
        "full_name": "Nhân Viên Đã Nghỉ",
        "pin": "1234",
        "status": "INACTIVE",
        "role": "STAFF"
    }
    save_staff_auth(auth)

    try:
        res = client.post(
            "/api/v1/cc/auth/login",
            headers={"X-Forwarded-For": "10.0.0.1"},
            json={"username": "dummy_inactive_user", "password": "1234"}
        )
        assert res.status_code == 403
        assert "đã bị vô hiệu hóa hoặc nhân viên đã nghỉ việc" in res.json()["detail"]
    finally:
        del auth["staff_accounts"]["dummy_inactive_user"]
        save_staff_auth(auth)


def test_09_sliding_window_api_rate_limiting():
    """
    Xác minh cơ chế giới hạn tần suất API (Rate-limiting) theo sliding window.
    """
    test_key = f"rate_test:{uuid.uuid4().hex}"
    # Giới hạn 5 requests trong 60 giây
    for i in range(5):
        allowed, count, retry = check_api_rate_limit(test_key, limit=5, window_seconds=60)
        assert allowed is True
        assert count == i + 1

    # Request thứ 6 bị chặn ngay lập tức
    allowed_6, count_6, retry_6 = check_api_rate_limit(test_key, limit=5, window_seconds=60)
    assert allowed_6 is False
    assert count_6 == 5
    assert retry_6 > 0
