# -*- coding: utf-8 -*-
"""
==============================================================================
TEST SUITE: ZERO-CONFIG DEMO SEED & PACKAGING PREVIEW
==============================================================================
Kiểm thử bộ module tự động tạo dữ liệu mẫu Zero-Config Starter:
1. Khi khởi tạo trong thư mục trắng tinh -> seed_if_empty tự động tạo đủ 4 tài khoản và dữ liệu mẫu.
2. Thử đăng nhập thành công với cả 3 vai trò: admin/1234 (ADMIN), manager/8888 (MANAGER), phache/2222 (STAFF).
3. Gọi lại seed_if_empty lần 2 khi đã có dữ liệu -> Idempotent, không làm thay đổi hay ghi đè dữ liệu hiện tại.
==============================================================================
"""

import os
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.demo_seed import seed_if_empty
from backend.services.storage import verify_pin, safe_json_read


client = TestClient(app)


def test_zero_config_seed_in_blank_dir(tmp_path, monkeypatch):
    """
    Test 1: Khi khởi tạo trong thư mục tạm trắng tinh -> seed_if_empty tự động tạo đủ
    4 tài khoản và dữ liệu mẫu trong cả SQLite và staff_auth.json.
    """
    test_db = str(tmp_path / "test_fnbop.db")
    test_auth = str(tmp_path / "staff_auth.json")

    assert not os.path.exists(test_db)
    assert not os.path.exists(test_auth)

    # Thực hiện seed
    seeded = seed_if_empty(db_path=test_db, auth_path=test_auth)
    assert seeded is True, "seed_if_empty phải trả về True khi database rỗng"

    assert os.path.exists(test_db), "Database file phải được tạo"
    assert os.path.exists(test_auth), "staff_auth.json file phải được tạo"

    # 1. Kiểm tra SQLite tenants & store_settings
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM tenants WHERE id = 'fnb_starter'")
    tenant = cur.fetchone()
    assert tenant is not None, "Tenant fnb_starter phải tồn tại"
    assert "FnBOps Starter" in tenant["name"]

    cur.execute("SELECT key, value FROM store_settings")
    settings = {r["key"]: r["value"] for r in cur.fetchall()}
    assert settings.get("store_name") == "FnBOps Starter"
    assert settings.get("currency") == "VND"

    # 2. Kiểm tra 4 tài khoản trong staff_accounts
    cur.execute("SELECT username, role, pin_hash, display_name, hourly_rate, salary_type, is_active FROM staff_accounts")
    accounts = {r["username"]: dict(r) for r in cur.fetchall()}
    assert len(accounts) == 4, f"Phải có đúng 4 tài khoản demo, thực tế: {len(accounts)}"

    # Admin: admin / 1234 (ADMIN)
    assert "admin" in accounts
    assert accounts["admin"]["role"] == "ADMIN"
    assert accounts["admin"]["display_name"] == "Chủ Quán"
    assert verify_pin("1234", accounts["admin"]["pin_hash"]) is True

    # Manager: manager / 8888 (MANAGER)
    assert "manager" in accounts
    assert accounts["manager"]["role"] == "MANAGER"
    assert accounts["manager"]["display_name"] == "Quản Lý Ca"
    assert verify_pin("8888", accounts["manager"]["pin_hash"]) is True

    # Barista: phache / 2222 (STAFF - BARISTA)
    assert "phache" in accounts
    assert accounts["phache"]["role"] == "STAFF"
    assert accounts["phache"]["display_name"] == "Pha Chế"
    assert accounts["phache"]["hourly_rate"] == 22000
    assert verify_pin("2222", accounts["phache"]["pin_hash"]) is True

    # Service: nhanvien / 1111 (STAFF - SERVICE)
    assert "nhanvien" in accounts
    assert accounts["nhanvien"]["role"] == "STAFF"
    assert accounts["nhanvien"]["display_name"] == "Nhân Viên"
    assert accounts["nhanvien"]["hourly_rate"] == 18000
    assert verify_pin("1111", accounts["nhanvien"]["pin_hash"]) is True

    # 3. Kiểm tra dữ liệu chấm công 3 ngày gần nhất trong SQLite
    cur.execute("SELECT COUNT(*) FROM attendance_logs")
    att_count = cur.fetchone()[0]
    assert att_count >= 9, f"Phải có ít nhất 9 ca chấm công mẫu của 3 ngày gần nhất, thực tế: {att_count}"

    conn.close()

    # 4. Kiểm tra staff_auth.json
    auth_data = safe_json_read(test_auth)
    assert auth_data is not None
    auth_accounts = auth_data.get("staff_accounts", {})
    assert len(auth_accounts) == 4
    assert "admin" in auth_accounts
    assert "manager" in auth_accounts
    assert "phache" in auth_accounts
    assert "nhanvien" in auth_accounts

    assert verify_pin("1234", auth_accounts["admin"]["pin"]) is True
    assert verify_pin("8888", auth_accounts["manager"]["pin"]) is True
    assert verify_pin("2222", auth_accounts["phache"]["pin"]) is True
    assert verify_pin("1111", auth_accounts["nhanvien"]["pin"]) is True


def test_login_all_three_roles(tmp_path, monkeypatch):
    """
    Test 2: Thử đăng nhập thành công qua API với cả 3 vai trò:
    - admin/1234 (ADMIN)
    - manager/8888 (MANAGER)
    - phache/2222 (STAFF)
    """
    test_db = str(tmp_path / "test_fnbop.db")
    test_auth = str(tmp_path / "staff_auth.json")

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTH_FILE", test_auth)
    monkeypatch.setenv("DATABASE_PATH", test_db)
    monkeypatch.setenv("SQLITE_DB_PATH", test_db)
    monkeypatch.setenv("JWT_SECRET_KEY", "test_jwt_secret_key_1234567890_abcdefghij")
    monkeypatch.setenv("ON_PREMISE_MODE", "1")
    monkeypatch.setenv("ENABLE_MASTER_STAFF_PASS", "false")

    # Seed dữ liệu mẫu
    seed_if_empty(db_path=test_db, auth_path=test_auth)

    # 1. Đăng nhập ADMIN (admin / 1234)
    res_admin = client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "1234"})
    assert res_admin.status_code == 200, f"Đăng nhập Admin thất bại: {res_admin.text}"
    data_admin = res_admin.json()
    assert data_admin["role"] == "ADMIN"
    assert data_admin["username"] == "admin"
    assert "access_token" in data_admin

    # 2. Đăng nhập MANAGER (manager / 8888)
    res_mgr = client.post("/api/v1/cc/auth/login", json={"username": "manager", "password": "8888"})
    assert res_mgr.status_code == 200, f"Đăng nhập Manager thất bại: {res_mgr.text}"
    data_mgr = res_mgr.json()
    assert data_mgr["role"] == "MANAGER"
    assert data_mgr["username"] == "manager"
    assert "access_token" in data_mgr

    # 3. Đăng nhập STAFF (phache / 2222)
    res_staff = client.post("/api/v1/cc/auth/login", json={"username": "phache", "password": "2222"})
    assert res_staff.status_code == 200, f"Đăng nhập Staff thất bại: {res_staff.text}"
    data_staff = res_staff.json()
    assert data_staff["role"] == "STAFF"
    assert data_staff["username"] == "phache"
    assert "access_token" in data_staff

    # 4. Kiểm tra mã PIN sai bị từ chối (HTTP 401)
    res_fail = client.post("/api/v1/cc/auth/login", json={"username": "admin", "password": "wrong_password"})
    assert res_fail.status_code == 401

    res_fail_mgr = client.post("/api/v1/cc/auth/login", json={"username": "manager", "password": "9999"})
    assert res_fail_mgr.status_code == 401


def test_seed_idempotency_no_overwrite(tmp_path, monkeypatch):
    """
    Test 3: Gọi lại seed_if_empty lần 2 khi đã có dữ liệu -> Idempotent,
    không làm thay đổi hay ghi đè dữ liệu hiện tại (trả về False).
    """
    test_db = str(tmp_path / "test_fnbop.db")
    test_auth = str(tmp_path / "staff_auth.json")

    # Lần 1: Seed trên thư mục trống
    first_run = seed_if_empty(db_path=test_db, auth_path=test_auth)
    assert first_run is True

    # Giả lập chủ quán thay đổi cài đặt quán và đổi tên hiển thị
    conn = sqlite3.connect(test_db)
    conn.execute("UPDATE store_settings SET value = 'Cà Phê Quán Gốc Tuỳ Biến' WHERE key = 'store_name'")
    conn.execute("UPDATE staff_accounts SET display_name = 'Chủ Quán VIP' WHERE username = 'admin'")
    conn.commit()
    conn.close()

    # Lần 2: Chạy lại seed_if_empty
    second_run = seed_if_empty(db_path=test_db, auth_path=test_auth)
    assert second_run is False, "Lần chạy thứ hai phải trả về False vì đã có dữ liệu"

    # Xác minh dữ liệu không bị ghi đè về mặc định ban đầu
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT value FROM store_settings WHERE key = 'store_name'")
    setting_val = cur.fetchone()["value"]
    assert setting_val == "Cà Phê Quán Gốc Tuỳ Biến", "store_name không được phép bị ghi đè lại thành 'FnBOps Starter'"

    cur.execute("SELECT display_name FROM staff_accounts WHERE username = 'admin'")
    admin_display = cur.fetchone()["display_name"]
    assert admin_display == "Chủ Quán VIP", "Tài khoản admin không được phép bị ghi đè lại"

    conn.close()
