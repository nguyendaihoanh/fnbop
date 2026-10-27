#!/usr/bin/env python3
"""
Tạo CSDL SQLite trắng chuẩn (data/wfm_blank.db) để bàn giao cho các quán mới.
- Khởi tạo đầy đủ 12 bảng SQLite WAL.
- Tạo sẵn 1 tài khoản Admin mặc định (username: 'admin', PIN: '1234').
- Không chứa dữ liệu rác, nhân viên hay ca trực của quán cũ.
"""

import os
import sys
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from services.db import init_db, get_db_connection
from services.storage import hash_pin

def generate_blank_db(output_path: str = None):
    if output_path is None:
        output_path = str(PROJECT_ROOT / "data" / "wfm_blank.db")

    # Xóa file cũ nếu tồn tại
    if os.path.exists(output_path):
        os.remove(output_path)
    wal_file = output_path + "-wal"
    shm_file = output_path + "-shm"
    if os.path.exists(wal_file):
        os.remove(wal_file)
    if os.path.exists(shm_file):
        os.remove(shm_file)

    print(f"[*] Đang khởi tạo CSDL trắng tại: {output_path}")
    init_db(output_path)

    conn = get_db_connection(output_path)
    cur = conn.cursor()

    # 1. Tạo Tenant mặc định
    cur.execute("""
        INSERT OR REPLACE INTO tenants (id, code, name)
        VALUES ('fnb_starter', 'STARTER', 'F&B Starter Store')
    """)

    # 2. Tạo tài khoản Admin mặc định (PIN: 1234)
    admin_pin_hash = hash_pin("1234")
    cur.execute("""
        INSERT OR REPLACE INTO staff_accounts (
            username, tenant_id, full_name, display_name, role, pin_hash, is_active, hourly_rate
        ) VALUES (
            'admin', 'fnb_starter', 'Chủ Quán (Admin)', 'Chủ Quán', 'ADMIN', ?, 1, 0
        )
    """, (admin_pin_hash,))

    conn.commit()
    conn.close()

    print("[V] Khởi tạo CSDL SQLite trắng THÀNH CÔNG!")
    print(f"    - File: {output_path}")
    print("    - Tài khoản Admin mặc định: 'admin' | Mã PIN: '1234'")
    print("    - Số bản ghi ca trực / nhân viên khác: 0 (Sạch 100%)")

if __name__ == "__main__":
    generate_blank_db()
