#!/usr/bin/env python3
"""
FnBOps - Live System E2E Readiness Test Suite
Authoritative end-to-end verification of all running services:
- Docker containers (:8100, :8100, :8177)
- Nginx static assets & modules
- FastAPI Backend & Auth/RBAC
- Attendance, Roster, Ops, Payroll
- Dark Luxury Payslip PNG Card Generation
- Zalo Gateway Live Dispatch (:8177)
- Store Configuration & 3 Zalo Automation Scenarios
"""

# Standalone Live E2E script - excluded from automated unit pytest
__test__ = False

import sys
import os
import requests
import json
import subprocess

BASE_WEB = "http://localhost:8100"
BASE_API = "http://localhost:8100/api/v1/cc"
BASE_ZALO = "http://localhost:8177"

def log_step(name: str):
    print(f"\n[TEST SUITE] >>> {name} ...", flush=True)

def assert_true(cond: bool, msg: str):
    if not cond:
        print(f"FAILED: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"  PASS: {msg}")

def test_docker_containers():
    log_step("1. Kiểm tra trạng thái Docker Containers")
    res = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"], capture_output=True, text=True)
    out = res.stdout
    assert_true(any(name in out and "Up" in out for name in ["fnbops-backend", "fnbops-api", "cc-vnaigc-backend"]), "Container backend đang chạy")
    assert_true(any(name in out and "Up" in out for name in ["fnbops-zalo-gateway", "zalo-gateway", "cc-vnaigc-zalo-gateway"]), "Container zalo-gateway đang chạy")
    assert_true(any(name in out and "Up" in out for name in ["fnbops-web", "gateway", "cc-vnaigc-web"]), "Container web gateway đang chạy")

def test_web_static_assets():
    log_step("2. Kiểm tra tài nguyên Web Nginx (:8100)")
    files = [
        ("/", "text/html"),
        ("/style.css", "text/css"),
        ("/mobile.css", "text/css"),
        ("/src/modules/payslipModule.js", "application/javascript"),
        ("/src/modules/storeConfigModule.js", "application/javascript"),
        ("/src/modules/adminModule.js", "application/javascript"),
        ("/src/modules/rosterModule.js", "application/javascript"),
        ("/src/modules/attendanceModule.js", "application/javascript"),
        ("/src/modules/opsModule.js", "application/javascript")
    ]
    for path, expected_type in files:
        url = f"{BASE_WEB}{path}"
        r = requests.get(url, timeout=5)
        assert_true(r.status_code == 200, f"Tải {path} trả về HTTP 200")
        assert_true(len(r.content) > 100, f"Nội dung {path} có dung lượng {len(r.content)} bytes")

def test_auth_flows():
    log_step("3. Kiểm tra Xác thực & Phân quyền (Auth / RBAC)")
    # 3.1 Login Admin (Admin/Manager)
    r1 = requests.post(f"{BASE_API}/auth/login", json={"username": "admin", "password": "1111"}, timeout=5)
    assert_true(r1.status_code == 200, "Đăng nhập admin/1111 thành công HTTP 200")
    d1 = r1.json()
    assert_true("access_token" in d1, "Sinh access_token JWT thành công")
    assert_true(d1.get("role") in ["ADMIN", "MANAGER"], f"Role là ADMIN/MANAGER: {d1.get('role')}")
    token_admin = d1["access_token"]

    # 3.2 Login Manager
    r2 = requests.post(f"{BASE_API}/auth/login", json={"username": "manager", "password": "8888"}, timeout=5)
    assert_true(r2.status_code == 200, "Đăng nhập manager/8888 thành công HTTP 200")
    d2 = r2.json()
    token_manager = d2["access_token"]

    # 3.3 Login Sai PIN
    r3 = requests.post(f"{BASE_API}/auth/login", json={"username": "admin", "password": "9999_wrong_pin"}, timeout=5)
    assert_true(r3.status_code in [400, 401], f"Sai PIN bị từ chối với HTTP {r3.status_code}")

    return token_admin, token_manager

def test_ops_and_attendance(token: str):
    log_step("4. Kiểm tra Tab Vận hành (Ops) & Chấm công")
    headers = {"Authorization": f"Bearer {token}"}
    
    # Attendance Status
    r = requests.get(f"{BASE_API}/attendance/status", headers=headers, timeout=5)
    assert_true(r.status_code == 200, "API /attendance/status trả về HTTP 200")
    d = r.json()
    assert_true("shift_state" in d, "Phản hồi attendance/status có trường shift_state")

    # Attendance SOP
    r = requests.get(f"{BASE_API}/attendance/sop?role=phuc_vu", headers=headers, timeout=5)
    assert_true(r.status_code == 200, "API /attendance/sop?role=phuc_vu trả về HTTP 200")

    # Manager Pending Shifts
    r = requests.get(f"{BASE_API}/attendance/manager/pending", headers=headers, timeout=5)
    assert_true(r.status_code == 200, "API /attendance/manager/pending trả về HTTP 200")

    # Ops Push Toggles
    r = requests.get(f"{BASE_API}/notifications/push/settings/ops-toggles", headers=headers, timeout=5)
    assert_true(r.status_code == 200, "API /notifications/push/settings/ops-toggles trả về HTTP 200")

def test_roster_and_history(token: str):
    log_step("5. Kiểm tra Tab Lịch ca (Roster) & Lịch sử cá nhân")
    headers = {"Authorization": f"Bearer {token}"}
    
    r = requests.get(f"{BASE_API}/roster/week?week_id=current", headers=headers, timeout=5)
    assert_true(r.status_code == 200, "API /roster/week?week_id=current trả về HTTP 200")
    roster_data = r.json()
    assert_true(isinstance(roster_data, dict) and "week" in roster_data, "Cấu trúc dữ liệu lịch ca là dict hợp lệ")

    r = requests.get(f"{BASE_API}/payroll/ledger", headers=headers, timeout=5)
    assert_true(r.status_code == 200, "API /payroll/ledger trả về HTTP 200")

def test_payslip_and_zalo(token: str):
    log_step("6. Kiểm tra Tab Bảng lương & Zalo Gateway")
    headers = {"Authorization": f"Bearer {token}"}

    # 6.1 Bảng lương summary
    r = requests.get(f"{BASE_API}/payroll/summary?month=9", headers=headers, timeout=5)
    assert_true(r.status_code == 200, "API /payroll/summary?month=9 trả về HTTP 200")

    # 6.2 Render Dark Luxury Payslip PNG Card
    r_img = requests.get(f"{BASE_API}/notifications/preview-payslip-card?staff_name=manager&month=9", headers=headers, timeout=10)
    assert_true(r_img.status_code == 200, "API /notifications/preview-payslip-card trả về HTTP 200")
    assert_true(r_img.headers.get("content-type") == "image/png", "Header Content-Type là image/png")
    assert_true(r_img.content.startswith(b"\x89PNG\r\n\x1a\n"), "Magic bytes chuẩn PNG hợp lệ")
    assert_true(len(r_img.content) > 10000, f"Ảnh thẻ lương nét cao: {len(r_img.content)} bytes")

    # 6.3 Zalo Gateway Health & Status
    r_zalo_health = requests.get(f"{BASE_ZALO}/health", timeout=5)
    assert_true(r_zalo_health.status_code == 200, "Zalo Gateway /health trả về HTTP 200")
    
    r_zalo_status = requests.get(f"{BASE_ZALO}/api/zalo/status", timeout=5)
    assert_true(r_zalo_status.status_code == 200, "Zalo Gateway /api/zalo/status trả về HTTP 200")

    r_zalo_qr = requests.get(f"{BASE_ZALO}/api/zalo/qr", timeout=5)
    assert_true(r_zalo_qr.status_code == 200, "Zalo Gateway /api/zalo/qr trả về HTTP 200")

    # 6.4 Gửi thẻ lương qua Zalo Gateway thực tế
    payload = {
        "staff_name": "manager",
        "month": "9",
        "phone": "0901234567"
    }
    r_send = requests.post(f"{BASE_API}/notifications/send-payslip-zalo-card", headers=headers, json=payload, timeout=15)
    assert_true(r_send.status_code == 200, "API /notifications/send-payslip-zalo-card trả về HTTP 200")
    res_send = r_send.json()
    assert_true(res_send.get("success") is True, "Phản hồi gửi Zalo: success=true")
    assert_true(res_send.get("phone") == "0901234567", "Gửi đúng số mẫu: 0901234567")

def test_store_config(token: str):
    log_step("7. Kiểm tra Modal Cài Đặt Quán & 3 Kịch bản Tự Động Hóa")
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(f"{BASE_API}/store/config", headers=headers, timeout=5)
    assert_true(r.status_code == 200, "API /store/config trả về HTTP 200")
    data = r.json()
    cfg = data.get("config", {})
    assert_true("shifts" in cfg, "Cấu hình ca kíp tồn tại trong store_config")
    assert_true("zalo_automation" in cfg, "Cấu hình zalo_automation tồn tại trong store_config")
    
    zalo_cfg = cfg.get("zalo_automation", {})
    assert_true("enable_auto_payslip" in zalo_cfg, "Có toggle Kịch bản 1: enable_auto_payslip")
    assert_true("enable_auto_shift_reminder" in zalo_cfg, "Có toggle Kịch bản 2: enable_auto_shift_reminder")
    assert_true("enable_auto_checkout_alert" in zalo_cfg, "Có toggle Kịch bản 3: enable_auto_checkout_alert")
    assert_true("shift_reminder_message" in zalo_cfg, "Có cấu hình mẫu câu nhắc vào ca cho chủ quán")
    assert_true("checkout_alert_message" in zalo_cfg, "Có cấu hình mẫu câu nhắc chốt ca cho chủ quán")

def main():
    print("====================================================================")
    print(" BẮT ĐẦU E2E SYSTEM READINESS VERIFICATION CHO FNBOPS")
    print("====================================================================")
    test_docker_containers()
    test_web_static_assets()
    token_admin, token_manager = test_auth_flows()
    test_ops_and_attendance(token_admin)
    test_roster_and_history(token_admin)
    test_payslip_and_zalo(token_admin)
    test_store_config(token_admin)
    print("\n====================================================================")
    print(" TẤT CẢ CÁC ĐIỂM KIỂM THỬ THỰC TẾ ĐỀU PASS 100%! HỆ THỐNG SẴN SÀNG!")
    print("====================================================================")

if __name__ == "__main__":
    main()
