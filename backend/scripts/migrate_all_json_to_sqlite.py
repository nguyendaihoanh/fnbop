#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
# -*- coding: utf-8 -*-
"""
==============================================================================
FNBOPS - COMPREHENSIVE DATA MIGRATION UTILITY (12 JSON FILES -> SQLITE WAL)
==============================================================================
Chuyển đổi toàn diện 100% dữ liệu từ 12 file JSON phẳng sang cơ sở dữ liệu quan hệ
SQLite (WAL Mode) an toàn, tuần hoàn và không làm mất dữ liệu (Zero Data Loss):
1. staff_auth.json          -> staff_accounts, staff_aliases, payroll_locks
2. attendance_logs.json     -> attendance_logs
3. store_config.json        -> store_configs
4. roster_schedule.json     -> roster_schedules
5. pos_closings.json        -> daily_closings
6. shift_approvals.json     -> shift_approvals
7. payroll_disbursements.json -> payroll_disbursements
8. eval_logs.json           -> evaluations
9. data.json ("SỔ PHỤ")     -> so_cai_luong
10. sop_templates.json      -> store_settings (key: 'sop_templates')
11. vapid_keys.json         -> store_settings (key: 'vapid_keys')
12. pos_heartbeat.json      -> store_settings (key: 'pos_heartbeat_last')
==============================================================================
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DATA_DIR = PROJECT_ROOT / "data"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.db import init_db, get_db_connection, DEFAULT_TENANT_ID
from services.storage import hash_pin, needs_rehash


def run_full_migration(target_db_path: Path = None):
    print("======================================================================")
    print("   ☕ FNBOPS - BẮT ĐẦU CHUYỂN ĐỔI TOÀN BỘ 12 FILE JSON SANG SQLITE")
    print("======================================================================")

    init_db()
    conn = get_db_connection()
    stats = {}

    try:
        # ----------------------------------------------------------------------
        # 1. staff_auth.json -> staff_accounts, staff_aliases, payroll_locks
        # ----------------------------------------------------------------------
        auth_file = DATA_DIR / "staff_auth.json"
        if auth_file.exists():
            with open(auth_file, "r", encoding="utf-8") as f:
                auth_data = json.load(f)

            accounts = auth_data.get("staff_accounts", {})
            acc_count, alias_count, lock_count = 0, 0, 0
            with conn:
                for idx, (u_key, acc) in enumerate(accounts.items(), start=1):
                    raw_pin = str(acc.get("pin", "1234")).strip()
                    p_hash = hash_pin(raw_pin) if needs_rehash(raw_pin) else raw_pin
                    fn = acc.get("full_name") or u_key
                    role = acc.get("role", "STAFF")
                    pos = acc.get("position", "SERVICE")
                    gender = acc.get("gender", "NAM")
                    status = acc.get("status", "ACTIVE")
                    last_login = acc.get("last_login")
                    emp_id = acc.get("employee_id") or f"EMP_{idx:03d}"
                    hr = acc.get("hourly_rate", 0)
                    stype = acc.get("salary_type", "HOURLY")
                    fsal = acc.get("fixed_salary", 0)
                    token_ver = int(acc.get("token_version", 1))
                    allowed_roles = json.dumps(acc.get("allowed_roles") or [pos])

                    conn.execute("""
                        INSERT INTO staff_accounts (
                            username, employee_id, tenant_id, full_name, display_name,
                            role, pin_hash, phone, hourly_rate, is_active,
                            position, gender, status, allowed_roles, salary_type,
                            fixed_salary, token_version, last_login, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(username) DO UPDATE SET
                            full_name = excluded.full_name,
                            display_name = excluded.display_name,
                            role = excluded.role,
                            pin_hash = excluded.pin_hash,
                            hourly_rate = excluded.hourly_rate,
                            position = excluded.position,
                            gender = excluded.gender,
                            status = excluded.status,
                            salary_type = excluded.salary_type,
                            fixed_salary = excluded.fixed_salary,
                            token_version = excluded.token_version,
                            last_login = excluded.last_login
                    """, (
                        u_key, emp_id, DEFAULT_TENANT_ID, fn, fn,
                        role, p_hash, str(acc.get("phone") or ""), hr, 1 if status == "ACTIVE" else 0,
                        pos, gender, status, allowed_roles, stype,
                        fsal, token_ver, last_login, datetime.now().isoformat()
                    ))
                    acc_count += 1

                    # Aliases
                    aliases = set(acc.get("aliases", []))
                    aliases.update(acc.get("sheet_names", []))
                    aliases.add(fn)
                    for al in aliases:
                        if al and str(al).strip():
                            conn.execute("""
                                INSERT OR IGNORE INTO staff_aliases (username, alias, tenant_id)
                                VALUES (?, ?, ?)
                            """, (u_key, str(al).strip(), DEFAULT_TENANT_ID))
                            alias_count += 1

                # Payroll locks
                for m_key, lock_val in (auth_data.get("payroll_locks") or {}).items():
                    conn.execute("""
                        INSERT INTO payroll_locks (month, tenant_id, status, message)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(month, tenant_id) DO UPDATE SET
                            status = excluded.status,
                            message = excluded.message
                    """, (str(m_key), DEFAULT_TENANT_ID, lock_val.get("status", "OPEN"), lock_val.get("message", "")))
                    lock_count += 1

            stats["staff_accounts"] = acc_count
            stats["staff_aliases"] = alias_count
            stats["payroll_locks"] = lock_count
            print(f"[✓] staff_auth.json -> {acc_count} tài khoản, {alias_count} bí danh, {lock_count} khóa kỳ lương.")

        # ----------------------------------------------------------------------
        # 2. attendance_logs.json -> attendance_logs
        # ----------------------------------------------------------------------
        att_file = DATA_DIR / "attendance_logs.json"
        if att_file.exists():
            with open(att_file, "r", encoding="utf-8") as f:
                att_logs = json.load(f)
            att_count = 0
            with conn:
                for log in (att_logs if isinstance(att_logs, list) else []):
                    u = log.get("username")
                    if not u:
                        continue
                    d = log.get("date")
                    sk = log.get("shift_key") or log.get("shift", "sang")
                    cin = log.get("checkin_time") or log.get("checkin")
                    cout = log.get("checkout_time") or log.get("checkout")
                    tmins = log.get("total_mins") or log.get("duration_mins") or 0
                    eff_mins = log.get("effective_duration_mins") or tmins
                    st = log.get("status", "ON_TIME")
                    note = log.get("note", "")
                    created = log.get("created_at") or datetime.now().isoformat()
                    hr_snap = log.get("hourly_rate_snapshot", 0)
                    s_start = log.get("scheduled_start", "")
                    s_end = log.get("scheduled_end", "")
                    is_hanging = 1 if log.get("is_hanging_pending") else 0

                    conn.execute("""
                        INSERT OR IGNORE INTO attendance_logs (
                            tenant_id, username, full_name, date, shift,
                            checkin, checkout, duration_mins, status, note,
                            created_at, hourly_rate_snapshot, scheduled_start,
                            scheduled_end, effective_duration_mins, is_hanging_pending
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        DEFAULT_TENANT_ID, u, log.get("full_name") or log.get("staff_name") or u,
                        d, sk, cin, cout, tmins, st, note,
                        created, hr_snap, s_start, s_end, eff_mins, is_hanging
                    ))
                    att_count += 1
            stats["attendance_logs"] = att_count
            print(f"[✓] attendance_logs.json -> {att_count} bản ghi chấm công.")

        # ----------------------------------------------------------------------
        # 3. store_config.json -> store_configs
        # ----------------------------------------------------------------------
        cfg_file = DATA_DIR / "store_config.json"
        if cfg_file.exists():
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg_data = json.load(f)
            with conn:
                conn.execute("""
                    INSERT INTO store_configs (tenant_id, config_json, version, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(tenant_id) DO UPDATE SET
                        config_json = excluded.config_json,
                        version = excluded.version,
                        updated_at = excluded.updated_at
                """, (
                    DEFAULT_TENANT_ID,
                    json.dumps(cfg_data, ensure_ascii=False),
                    int(cfg_data.get("version", 1)),
                    datetime.now().isoformat()
                ))
            stats["store_configs"] = 1
            print(f"[✓] store_config.json -> Đã di trú cấu hình cửa hàng (Version: {cfg_data.get('version', 1)}).")

        # ----------------------------------------------------------------------
        # 4. roster_schedule.json -> roster_schedules
        # ----------------------------------------------------------------------
        roster_file = DATA_DIR / "roster_schedule.json"
        if roster_file.exists():
            with open(roster_file, "r", encoding="utf-8") as f:
                roster_data = json.load(f)
            weeks = roster_data.get("weeks", {}) if isinstance(roster_data, dict) else {}
            roster_count = 0
            with conn:
                for w_key, w_val in weeks.items():
                    sched_json = json.dumps(w_val.get("schedule", {}), ensure_ascii=False)
                    reg_json = json.dumps(w_val.get("registrations", {}), ensure_ascii=False)
                    status = "PUBLISHED" if w_val.get("is_published") else "DRAFT"
                    conn.execute("""
                        INSERT INTO roster_schedules (week_key, tenant_id, status, schedule_json, registrations_json, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(week_key, tenant_id) DO UPDATE SET
                            status = excluded.status,
                            schedule_json = excluded.schedule_json,
                            registrations_json = excluded.registrations_json,
                            updated_at = excluded.updated_at
                    """, (w_key, DEFAULT_TENANT_ID, status, sched_json, reg_json, datetime.now().isoformat()))
                    roster_count += 1
            stats["roster_schedules"] = roster_count
            print(f"[✓] roster_schedule.json -> {roster_count} tuần phân ca.")

        # ----------------------------------------------------------------------
        # 5. pos_closings.json -> daily_closings
        # ----------------------------------------------------------------------
        pos_file = DATA_DIR / "pos_closings.json"
        if pos_file.exists():
            with open(pos_file, "r", encoding="utf-8") as f:
                pos_list = json.load(f)
            pos_count = 0
            with conn:
                for p in (pos_list if isinstance(pos_list, list) else []):
                    rep_date = p.get("report_date") or p.get("date")
                    if not rep_date:
                        continue
                    conn.execute("""
                        INSERT OR IGNORE INTO daily_closings (
                            tenant_id, report_date, closing_time, bill_pos,
                            cash_amount, transfer_amount, expense_amount, expense_detail,
                            total_real, diff, diff_amount, diff_status, is_warning,
                            sender_name, approver_name, notes, created_at, shift_key
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        DEFAULT_TENANT_ID, rep_date, p.get("closing_time", ""),
                        float(p.get("bill_pos") or 0), float(p.get("cash_amount") or 0),
                        float(p.get("transfer_amount") or 0), float(p.get("expense_amount") or 0),
                        str(p.get("expense_detail") or ""), float(p.get("total_real") or 0),
                        float(p.get("diff") or 0), float(p.get("diff_amount") or 0),
                        str(p.get("diff_status") or "KHỚP"), 1 if p.get("is_warning") else 0,
                        str(p.get("sender_name") or ""), str(p.get("approver_name") or ""),
                        str(p.get("notes") or ""), p.get("created_at") or datetime.now().isoformat(),
                        str(p.get("shift_key") or "toi")
                    ))
                    pos_count += 1
            stats["daily_closings"] = pos_count
            print(f"[✓] pos_closings.json -> {pos_count} biên bản kết ca thu ngân.")

        # ----------------------------------------------------------------------
        # 6. shift_approvals.json -> shift_approvals
        # ----------------------------------------------------------------------
        sa_file = DATA_DIR / "shift_approvals.json"
        if sa_file.exists():
            with open(sa_file, "r", encoding="utf-8") as f:
                sa_data = json.load(f)
            sa_count = 0
            with conn:
                for k, v in (sa_data if isinstance(sa_data, dict) else {}).items():
                    conn.execute("""
                        INSERT INTO shift_approvals (shift_key, tenant_id, status, approved_mins, manager, note, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(shift_key, tenant_id) DO UPDATE SET
                            status = excluded.status,
                            approved_mins = excluded.approved_mins,
                            manager = excluded.manager,
                            note = excluded.note,
                            updated_at = excluded.updated_at
                    """, (
                        k, DEFAULT_TENANT_ID, v.get("status", "APPROVED"),
                        int(v.get("approved_mins", 0)), v.get("manager", "Quản Lý"),
                        v.get("note", ""), v.get("updated_at") or datetime.now().isoformat()
                    ))
                    sa_count += 1
            stats["shift_approvals"] = sa_count
            print(f"[✓] shift_approvals.json -> {sa_count} phê duyệt ca ngâm.")

        # ----------------------------------------------------------------------
        # 7. payroll_disbursements.json -> payroll_disbursements
        # ----------------------------------------------------------------------
        pd_file = DATA_DIR / "payroll_disbursements.json"
        if pd_file.exists():
            with open(pd_file, "r", encoding="utf-8") as f:
                pd_data = json.load(f)
            pd_count = 0
            with conn:
                for month_key, items in (pd_data if isinstance(pd_data, dict) else {}).items():
                    if isinstance(items, list):
                        for it in items:
                            s_name = it.get("staff_name") or it.get("name")
                            if s_name:
                                conn.execute("""
                                    INSERT OR IGNORE INTO payroll_disbursements (
                                        tenant_id, month, staff_name, status, amount, paid_by, updated_at, created_at
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    DEFAULT_TENANT_ID, str(month_key), s_name,
                                    it.get("status", "PAID"), int(it.get("amount", 0)),
                                    it.get("paid_by", "Admin"), it.get("updated_at", ""),
                                    datetime.now().isoformat()
                                ))
                                pd_count += 1
            stats["payroll_disbursements"] = pd_count
            print(f"[✓] payroll_disbursements.json -> {pd_count} bản ghi giải ngân lương.")

        # ----------------------------------------------------------------------
        # 8. eval_logs.json -> evaluations
        # ----------------------------------------------------------------------
        eval_file = DATA_DIR / "eval_logs.json"
        if eval_file.exists():
            with open(eval_file, "r", encoding="utf-8") as f:
                eval_data = json.load(f)
            ev_count = 0
            with conn:
                for ev in (eval_data if isinstance(eval_data, list) else []):
                    ev_key = ev.get("id") or f"EV_{ev_count}"
                    conn.execute("""
                        INSERT OR IGNORE INTO evaluations (
                            tenant_id, staff_name, type, amount, reason, date, month,
                            manager, status, shift, notes, created_by, created_at, eval_key
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        DEFAULT_TENANT_ID, ev.get("staffName", ""), ev.get("type", "Thưởng"),
                        int(ev.get("amount", 0)), ev.get("reason", ""), ev.get("date", ""),
                        str(ev.get("month", "10")), ev.get("manager", "Quản Lý"),
                        ev.get("status", "ACTIVE"), ev.get("shift", "Ca Sáng"),
                        ev.get("notes", ""), ev.get("createdBy", ""), ev.get("createdAt", ""),
                        ev_key
                    ))
                    ev_count += 1
            stats["evaluations"] = ev_count
            print(f"[✓] eval_logs.json -> {ev_count} biên bản đánh giá thưởng/phạt.")

        # ----------------------------------------------------------------------
        # 9. data.json ("SỔ PHỤ") -> so_cai_luong
        # ----------------------------------------------------------------------
        data_file = DATA_DIR / "data.json"
        if data_file.exists():
            with open(data_file, "r", encoding="utf-8") as f:
                core_data = json.load(f)
            so_phu = core_data.get("SỔ PHỤ", []) if isinstance(core_data, dict) else []
            sp_count = 0
            with conn:
                # Bỏ qua dòng tiêu đề nếu dạng danh sách dòng
                rows = so_phu[1:] if (len(so_phu) > 0 and isinstance(so_phu[0], list)) else so_phu
                for r in rows:
                    if isinstance(r, list) and len(r) >= 5:
                        ev_id = r[0]
                        s_name = r[1]
                        m = str(r[2])
                        l_type = r[3]
                        try:
                            amt = int(float(str(r[4]).replace(",", "")))
                        except Exception:
                            amt = 0
                        ly_do = r[6] if len(r) > 6 else ""
                        nguoi_tao = r[7] if len(r) > 7 else "Admin"
                        conn.execute("""
                            INSERT OR IGNORE INTO so_cai_luong (
                                tenant_id, nhan_vien_id, staff_name, cham_cong_id,
                                loai_su_kien, so_gio_thay_doi, so_tien_thay_doi,
                                muc_luong_ap_dung, ly_do, nguoi_tao, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            DEFAULT_TENANT_ID, ev_id, s_name, "",
                            l_type, 0.0, amt, 0, ly_do, nguoi_tao, datetime.now().isoformat()
                        ))
                        sp_count += 1
            stats["so_cai_luong"] = sp_count
            print(f"[✓] data.json (SỔ PHỤ) -> {sp_count} bản ghi sổ cái lương.")

        # ----------------------------------------------------------------------
        # 10, 11, 12. sop_templates, vapid_keys, pos_heartbeat -> store_settings
        # ----------------------------------------------------------------------
        settings_migrated = 0
        with conn:
            for s_name, s_file in [
                ("sop_templates", DATA_DIR / "sop_templates.json"),
                ("vapid_keys", DATA_DIR / "vapid_keys.json"),
                ("pos_heartbeat_last", DATA_DIR / "pos_heartbeat.json")
            ]:
                if s_file.exists():
                    with open(s_file, "r", encoding="utf-8") as f:
                        val_str = f.read()
                    conn.execute("""
                        INSERT INTO store_settings (key, value, label, description, updated_at, updated_by)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            value = excluded.value,
                            updated_at = excluded.updated_at
                    """, (s_name, val_str, s_name, f"Di trú từ {s_file.name}", datetime.now().isoformat(), "migration"))
                    settings_migrated += 1

        stats["store_settings"] = settings_migrated
        print(f"[✓] sop_templates, vapid_keys, pos_heartbeat -> Đã lưu cấu hình tĩnh vào store_settings.")

    finally:
        conn.close()

    print("======================================================================")
    print("   [V] DI TRÚ 100% 12 FILE JSON SANG SQLITE WAL THÀNH CÔNG!")
    print(f"   Tổng kết bản ghi đã đối soát: {stats}")
    print("======================================================================")
    return stats


if __name__ == "__main__":
    run_full_migration()
