# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
# -*- coding: utf-8 -*-
"""
==============================================================================
FNBOPS - ZERO-CONFIG DEMO SEED SERVICE
==============================================================================
Tự động nhận diện và khởi tạo cơ sở dữ liệu mẫu chuẩn 100% khi hệ thống được
triển khai lần đầu hoặc cơ sở dữ liệu hoàn toàn rỗng.
- Khởi tạo Tenant mặc định: fnb_starter ('Quán Cà Phê Mẫu (FnBOps Starter)')
- Store Settings: store_name = 'FnBOps Starter', currency = 'VND'
- 4 Tài khoản demo chuẩn:
  1. Admin: admin / 1234 (ADMIN)
  2. Manager: manager / 8888 (MANAGER)
  3. Barista: phache / 2222 (STAFF - BARISTA)
  4. Service: nhanvien / 1111 (STAFF - SERVICE)
- Dữ liệu ca mẫu (attendance logs) của 3 ngày gần nhất.
- Đảm bảo tính Idempotent: Tuyệt đối không ghi đè nếu database/auth đã có dữ liệu.
==============================================================================
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List

logger = logging.getLogger("demo_seed")

try:
    from services.storage import hash_pin, safe_json_read, safe_json_write
    from services.db import init_db, get_db_connection, get_db_path
    from services.auth import get_auth_file
except ImportError:
    from backend.services.storage import hash_pin, safe_json_read, safe_json_write
    from backend.services.db import init_db, get_db_connection, get_db_path
    from backend.services.auth import get_auth_file


DEFAULT_TENANT_ID = "fnb_starter"
DEFAULT_TENANT_CODE = "STARTER"
DEFAULT_TENANT_NAME = "Quán Cà Phê Mẫu (FnBOps Starter)"


def seed_if_empty(db_path: Optional[str] = None, auth_path: Optional[str] = None) -> bool:
    """
    Tự động khởi tạo dữ liệu mẫu nếu SQLite hoặc staff_auth.json chưa có tài khoản nào.
    Idempotent: Nếu đã có tài khoản nhân viên, bỏ qua và trả về False.
    Trả về True nếu đã thực hiện seed thành công.
    """
    target_db = db_path or get_db_path()
    target_auth = auth_path or get_auth_file()

    # 1. Kiểm tra trạng thái dữ liệu hiện tại
    has_sqlite_accounts = False
    if os.path.exists(target_db):
        try:
            conn = get_db_connection(target_db)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='staff_accounts'")
            if cur.fetchone():
                cur.execute("SELECT COUNT(*) FROM staff_accounts")
                cnt = cur.fetchone()[0]
                if cnt and cnt > 0:
                    has_sqlite_accounts = True
            conn.close()
        except Exception as e:
            logger.warning(f"[demo_seed] Lỗi kiểm tra staff_accounts trong SQLite: {e}")

    has_auth_accounts = False
    if os.path.exists(target_auth):
        try:
            auth_data = safe_json_read(target_auth, default={})
            accounts = auth_data.get("staff_accounts", {})
            if isinstance(accounts, dict) and len(accounts) > 0:
                has_auth_accounts = True
        except Exception as e:
            logger.warning(f"[demo_seed] Lỗi kiểm tra staff_auth.json: {e}")

    # Idempotent guard: Nếu CẢ HAI đều đã có tài khoản -> Không can thiệp!
    if has_sqlite_accounts and has_auth_accounts:
        return False

    logger.info(f"[*] [demo_seed] Bắt đầu khởi tạo dữ liệu mẫu cho hệ thống (DB: {target_db}, Auth: {target_auth})")

    # 2. Khởi tạo schema DB
    init_db(target_db)

    # 3. Tạo tenant và cài đặt quán trong SQLite
    conn = get_db_connection(target_db)
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO tenants (id, code, name)
        VALUES (?, ?, ?)
    """, (DEFAULT_TENANT_ID, DEFAULT_TENANT_CODE, DEFAULT_TENANT_NAME))

    cur.execute("""
        INSERT OR REPLACE INTO store_settings (key, value, label, description, updated_at, updated_by)
        VALUES 
        ('store_name', 'FnBOps Starter', 'Tên cửa hàng', 'Tên quán hiển thị trên hệ thống', datetime('now'), 'demo_seed'),
        ('currency', 'VND', 'Đơn vị tiền tệ', 'Đơn vị tiền tệ chính của quán', datetime('now'), 'demo_seed')
    """)

    # 4. Hash mã PIN cho 4 tài khoản demo
    admin_hash = hash_pin("1234")
    manager_hash = hash_pin("8888")
    barista_hash = hash_pin("2222")
    service_hash = hash_pin("1111")

    demo_accounts = [
        {
            "username": "admin",
            "employee_id": "EMP_001",
            "full_name": "Chủ Quán (Admin)",
            "display_name": "Chủ Quán",
            "role": "ADMIN",
            "position": "MANAGER",
            "pin_hash": admin_hash,
            "hourly_rate": 0,
            "salary_type": "FIXED",
            "gender": "NAM",
            "aliases": ["admin", "chu_quan", "Chủ Quán"]
        },
        {
            "username": "manager",
            "employee_id": "EMP_002",
            "full_name": "Quản Lý Ca",
            "display_name": "Quản Lý Ca",
            "role": "MANAGER",
            "position": "MANAGER",
            "pin_hash": manager_hash,
            "hourly_rate": 25000,
            "salary_type": "HOURLY",
            "gender": "NU",
            "aliases": ["manager", "quanly", "Quản Lý Ca"]
        },
        {
            "username": "phache",
            "employee_id": "EMP_003",
            "full_name": "Nhân Viên Pha Chế",
            "display_name": "Pha Chế",
            "role": "STAFF",
            "position": "BARISTA",
            "pin_hash": barista_hash,
            "hourly_rate": 22000,
            "salary_type": "HOURLY",
            "gender": "NAM",
            "aliases": ["phache", "barista", "Pha Chế"]
        },
        {
            "username": "nhanvien",
            "employee_id": "EMP_004",
            "full_name": "Nhân Viên Phục Vụ",
            "display_name": "Nhân Viên",
            "role": "STAFF",
            "position": "SERVICE",
            "pin_hash": service_hash,
            "hourly_rate": 18000,
            "salary_type": "HOURLY",
            "gender": "NU",
            "aliases": ["nhanvien", "service", "Nhân Viên"]
        }
    ]

    for acc in demo_accounts:
        cur.execute("""
            INSERT OR REPLACE INTO staff_accounts (
                username, employee_id, tenant_id, full_name, display_name, pin_hash,
                role, position, gender, status, hourly_rate, is_active, salary_type,
                token_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, 1, ?, 1, datetime('now'))
        """, (
            acc["username"], acc["employee_id"], DEFAULT_TENANT_ID,
            acc["full_name"], acc["display_name"], acc["pin_hash"],
            acc["role"], acc["position"], acc["gender"],
            acc["hourly_rate"], acc["salary_type"]
        ))

        for al in acc["aliases"]:
            cur.execute("""
                INSERT OR IGNORE INTO staff_aliases (username, alias, tenant_id)
                VALUES (?, ?, ?)
            """, (acc["username"], al, DEFAULT_TENANT_ID))

    # 5. Dữ liệu ca mẫu (attendance logs) của 3 ngày gần nhất
    today = date.today()
    days = [today - timedelta(days=2), today - timedelta(days=1), today]

    sample_logs_json = []

    for d in days:
        d_str_slash = d.strftime("%d/%m/%Y")
        d_str_iso = d.strftime("%Y-%m-%d")

        # 3 ca mỗi ngày:
        # Ca sáng: phache (07:00 - 12:00)
        # Ca chiều: nhanvien (12:00 - 17:00)
        # Ca tối: manager (17:00 - 22:00)
        day_shifts = [
            {
                "username": "phache",
                "display_name": "Pha Chế",
                "shift": "Ca Sáng",
                "shift_key": "morning",
                "start": "07:00",
                "end": "12:00",
                "checkin": f"{d_str_iso} 06:55:00",
                "checkout": f"{d_str_iso} 12:05:00",
                "duration_mins": 310,
                "effective_duration_mins": 300,
                "hourly_rate": 22000,
                "note": "Ca sáng pha chế chuẩn bị đầy đủ quầy bar"
            },
            {
                "username": "nhanvien",
                "display_name": "Nhân Viên",
                "shift": "Ca Chiều",
                "shift_key": "afternoon",
                "start": "12:00",
                "end": "17:00",
                "checkin": f"{d_str_iso} 11:58:00",
                "checkout": f"{d_str_iso} 17:02:00",
                "duration_mins": 304,
                "effective_duration_mins": 300,
                "hourly_rate": 18000,
                "note": "Phục vụ khách giờ cao điểm"
            },
            {
                "username": "manager",
                "display_name": "Quản Lý Ca",
                "shift": "Ca Tối",
                "shift_key": "evening",
                "start": "17:00",
                "end": "22:00",
                "checkin": f"{d_str_iso} 16:50:00",
                "checkout": f"{d_str_iso} 22:10:00",
                "duration_mins": 320,
                "effective_duration_mins": 300,
                "hourly_rate": 25000,
                "note": "Quản lý ca tối và kiểm kê POS đóng ca"
            }
        ]

        for s in day_shifts:
            cur.execute("""
                INSERT INTO attendance_logs (
                    tenant_id, username, full_name, date, shift, checkin, checkout,
                    duration_mins, status, note, created_at, hourly_rate_snapshot,
                    scheduled_start, scheduled_end, effective_duration_mins, is_hanging_pending
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ON_TIME', ?, datetime('now'), ?, ?, ?, ?, 0)
            """, (
                DEFAULT_TENANT_ID, s["username"], s["display_name"], d_str_slash,
                s["shift"], s["checkin"], s["checkout"], s["duration_mins"],
                s["note"], s["hourly_rate"], s["start"], s["end"], s["effective_duration_mins"]
            ))

            sample_logs_json.append({
                "id": f"seed_{d_str_iso}_{s['username']}_{s['shift_key']}",
                "username": s["username"],
                "staff_name": s["display_name"],
                "display_name": s["display_name"],
                "date": d_str_slash,
                "shift_key": s["shift_key"],
                "shift_name": s["shift"],
                "checkin_time": s["checkin"],
                "checkout_time": s["checkout"],
                "total_mins": s["duration_mins"],
                "effective_duration_mins": s["effective_duration_mins"],
                "status": "ON_TIME",
                "note": s["note"],
                "created_at": f"{s['checkin'].replace(' ', 'T')}",
                "hourly_rate_snapshot": s["hourly_rate"],
                "scheduled_start": s["start"],
                "scheduled_end": s["end"]
            })

    conn.commit()
    conn.close()

    # 6. Đồng bộ sang staff_auth.json
    auth_data = safe_json_read(target_auth, default={"payroll_locks": {}, "staff_accounts": {}})
    if not isinstance(auth_data, dict):
        auth_data = {"payroll_locks": {}, "staff_accounts": {}}

    if "staff_accounts" not in auth_data or not isinstance(auth_data["staff_accounts"], dict):
        auth_data["staff_accounts"] = {}

    auth_data["admin"] = {
        "full_name": "Chủ Quán (Admin)",
        "display_name": "Chủ Quán",
        "pin": admin_hash,
        "role": "ADMIN",
        "employee_id": "EMP_001",
        "hourly_rate": 0,
        "salary_type": "FIXED"
    }

    for acc in demo_accounts:
        auth_data["staff_accounts"][acc["username"]] = {
            "full_name": acc["full_name"],
            "display_name": acc["display_name"],
            "pin": acc["pin_hash"],
            "role": acc["role"],
            "position": acc["position"],
            "employee_id": acc["employee_id"],
            "hourly_rate": acc["hourly_rate"],
            "salary_type": acc["salary_type"],
            "status": "ACTIVE",
            "token_version": 1,
            "aliases": acc["aliases"],
            "sheet_names": [acc["display_name"], acc["username"]]
        }

    safe_json_write(target_auth, auth_data)

    # 7. Đồng bộ attendance_logs.json nếu file chưa có hoặc rỗng
    auth_dir = os.path.dirname(os.path.abspath(target_auth))
    logs_file = os.path.join(auth_dir, "attendance_logs.json")
    existing_logs = safe_json_read(logs_file, default=[])
    if not existing_logs or len(existing_logs) == 0:
        safe_json_write(logs_file, sample_logs_json)

    logger.info("[✓] [demo_seed] Hoàn tất khởi tạo 4 tài khoản demo và dữ liệu 3 ngày gần nhất.")
    return True
