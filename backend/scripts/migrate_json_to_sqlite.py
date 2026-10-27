# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Data Migration Utility: Flat JSON Files -> SQLite Relational Database (WAL Mode)
FNBOPS.LOCAL / FnBOps
Safe, Idempotent, and Non-destructive Migration.
"""

import os
import sys
import json
import sqlite3

_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_dir = os.path.dirname(_base_dir)
if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

from services.db import init_db, get_db_connection, DEFAULT_TENANT_ID
from services.storage import hash_pin, needs_rehash


def run_migration():
    print("=== BẮT ĐẦU CHUYỂN ĐỔI DỮ LIỆU SANG SQLITE (WAL MODE) ===")
    init_db()
    conn = get_db_connection()

    # 1. Migrate staff_auth.json
    auth_candidates = [
        os.getenv("AUTH_FILE"),
        os.path.join(_base_dir, "staff_auth.json"),
        os.path.join(os.path.dirname(_base_dir), "data", "staff_auth.json"),
    ]
    auth_file = next((f for f in auth_candidates if f and os.path.exists(f)), None)

    if auth_file:
        print(f"Đang đọc dữ liệu nhân sự từ: {auth_file}")
        with open(auth_file, "r", encoding="utf-8") as f:
            auth_data = json.load(f)

        accounts = auth_data.get("staff_accounts", {})
        migrated_accs = 0
        migrated_aliases = 0

        with conn:
            for u_key, acc in accounts.items():
                pin_raw = str(acc.get("pin", "1234")).strip()
                pin_hash = hash_pin(pin_raw) if needs_rehash(pin_raw) else pin_raw
                full_name = acc.get("full_name", u_key)
                role = acc.get("role", "STAFF")
                position = acc.get("position", "SERVICE")
                gender = acc.get("gender", "NAM")
                status = acc.get("status", "ACTIVE")
                last_login = acc.get("last_login")

                conn.execute("""
                    INSERT INTO staff_accounts (username, tenant_id, full_name, pin_hash, role, position, gender, status, last_login)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(username) DO UPDATE SET
                        full_name = excluded.full_name,
                        pin_hash = excluded.pin_hash,
                        role = excluded.role,
                        position = excluded.position,
                        gender = excluded.gender,
                        status = excluded.status,
                        last_login = excluded.last_login
                """, (u_key, DEFAULT_TENANT_ID, full_name, pin_hash, role, position, gender, status, last_login))
                migrated_accs += 1

                # Migrate aliases and sheet_names
                aliases = set(acc.get("aliases", []))
                aliases.update(acc.get("sheet_names", []))
                aliases.add(full_name)
                for al in aliases:
                    if al:
                        conn.execute("""
                            INSERT OR IGNORE INTO staff_aliases (username, alias, tenant_id)
                            VALUES (?, ?, ?)
                        """, (u_key, str(al).strip(), DEFAULT_TENANT_ID))
                        migrated_aliases += 1

            # Migrate payroll_locks
            locks = auth_data.get("payroll_locks", {})
            for m_key, lock_val in locks.items():
                status = lock_val.get("status", "OPEN")
                msg = lock_val.get("message", "")
                conn.execute("""
                    INSERT INTO payroll_locks (month, tenant_id, status, message)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(month, tenant_id) DO UPDATE SET
                        status = excluded.status,
                        message = excluded.message
                """, (str(m_key), DEFAULT_TENANT_ID, status, msg))

        print(f"-> Đã chuyển đổi thành công {migrated_accs} tài khoản nhân sự và {migrated_aliases} bí danh vào SQLite.")

    # 2. Migrate eval_logs.json
    eval_candidates = [
        os.path.join(_base_dir, "eval_logs.json"),
        os.path.join(os.path.dirname(_base_dir), "data", "eval_logs.json"),
    ]
    eval_file = next((f for f in eval_candidates if f and os.path.exists(f)), None)

    if eval_file:
        print(f"Đang đọc dữ liệu đánh giá từ: {eval_file}")
        with open(eval_file, "r", encoding="utf-8") as f:
            eval_list = json.load(f)

        migrated_evals = 0
        with conn:
            for ev in eval_list:
                ev_id = ev.get("id")
                if not ev_id:
                    continue
                conn.execute("""
                    INSERT OR IGNORE INTO evaluations (
                        tenant_id, staff_name, type, amount, reason, date, month,
                        manager, status, shift, notes, created_by, created_at, eval_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    DEFAULT_TENANT_ID,
                    ev.get("staffName", ""),
                    ev.get("type", "Đánh Giá"),
                    int(ev.get("amount", 0)),
                    ev.get("reason", ""),
                    ev.get("date", ""),
                    str(ev.get("month", "9")),
                    ev.get("manager", "Quản Lý"),
                    ev.get("status", "ACTIVE"),
                    ev.get("shift", "Ca Sáng"),
                    ev.get("notes", ""),
                    ev.get("createdBy", ev.get("created_by", "")),
                    ev.get("createdAt", ev.get("created_at", "")),
                    ev_id
                ))
                migrated_evals += 1
        print(f"-> Đã chuyển đổi thành công {migrated_evals} bản ghi đánh giá vào SQLite.")

    conn.close()
    print("=== CHUYỂN ĐỔI HOÀN TẤT THÀNH CÔNG! ===")


if __name__ == "__main__":
    run_migration()
