# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Database Schema & Migrations Layer (SQLite)
Contains table initializations, indices, and incremental schema evolutions.
"""

import sys
import os
import sqlite3
import logging
from typing import Optional

import threading

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from services.db.connection import (
    get_db_connection,
    get_db_path,
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
)

logger = logging.getLogger("db_service")

_security_tables_lock = threading.Lock()
_security_tables_ensured_dbs = set()

def _ensure_login_attempts_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='login_attempts'")
    if cur.fetchone():
        cur.execute("PRAGMA table_info(login_attempts);")
        cols_pk = {r[1]: r[5] for r in cur.fetchall()}
        if cols_pk.get("target_key") != 1:
            # Recreate table cleanly so target_key is PRIMARY KEY and multiple users on same cafe IP are supported
            try:
                conn.execute("DROP TABLE IF EXISTS login_attempts;")
            except Exception:
                pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            target_key TEXT PRIMARY KEY,
            target_type TEXT NOT NULL DEFAULT 'IP',
            identifier TEXT NOT NULL DEFAULT '',
            ip TEXT,
            username TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            tier INTEGER NOT NULL DEFAULT 1,
            lockout_until REAL,
            is_admin_locked INTEGER NOT NULL DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_identifier ON login_attempts(identifier);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_login_lockout ON login_attempts(lockout_until);")

def _ensure_default_tenants(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute(
        "INSERT OR IGNORE INTO tenants (id, code, name) VALUES (?, ?, ?)",
        ("default", "DEFAULT", "FnBOps Store Lounge")
    )
    conn.execute(
        "INSERT OR IGNORE INTO tenants (id, code, name) VALUES (?, ?, ?)",
        ("wfm_central", "WFM", "FnBOps Store Lounge")
    )
    conn.execute(
        "INSERT OR IGNORE INTO tenants (id, code, name) VALUES (?, ?, ?)",
        ("fnbop_main", "DEMO", "FnBOps Demo Store")
    )

def _ensure_staff_ledgers_table(conn: sqlite3.Connection) -> None:
    _ensure_default_tenants(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS staff_ledgers (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            staff_name TEXT NOT NULL,
            month TEXT NOT NULL,
            type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            payment_method TEXT DEFAULT 'cash',
            reason TEXT,
            created_by TEXT,
            is_deleted INTEGER DEFAULT 0,
            deleted_at DATETIME,
            deleted_by TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
        );
    """)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(staff_ledgers);")
    cols = {r[1] for r in cur.fetchall()}
    if "is_deleted" not in cols:
        conn.execute("ALTER TABLE staff_ledgers ADD COLUMN is_deleted INTEGER DEFAULT 0;")
    if "deleted_at" not in cols:
        conn.execute("ALTER TABLE staff_ledgers ADD COLUMN deleted_at DATETIME;")
    if "deleted_by" not in cols:
        conn.execute("ALTER TABLE staff_ledgers ADD COLUMN deleted_by TEXT DEFAULT '';")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_staff_ledgers_month_staff ON staff_ledgers(tenant_id, month, staff_name);")

def _ensure_security_tables(conn: sqlite3.Connection) -> None:
    """Ensures revoked_tokens and api_rate_limits tables exist (thread-safe, idempotent)."""
    try:
        cur = conn.execute("PRAGMA database_list")
        row = cur.fetchone()
        actual_path = row[2] if row and len(row) > 2 else ""
    except Exception:
        actual_path = ""
    target_key = actual_path or get_db_path()
    if target_key and target_key in _security_tables_ensured_dbs:
        return
    with _security_tables_lock:
        if target_key and target_key in _security_tables_ensured_dbs:
            return
        conn.execute("""
            CREATE TABLE IF NOT EXISTS revoked_tokens (
                token_hash TEXT PRIMARY KEY,
                reason TEXT DEFAULT '',
                revoked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at REAL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_revoked_tokens_exp ON revoked_tokens(expires_at);")
        _ensure_login_attempts_table(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_rate_limits (
                key TEXT PRIMARY KEY,
                count INTEGER NOT NULL DEFAULT 1,
                reset_at REAL NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_rate_limits_reset ON api_rate_limits(reset_at);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT DEFAULT 'STAFF',
                action TEXT NOT NULL,
                client_ip TEXT,
                is_cafe_wifi BOOLEAN DEFAULT 0,
                user_agent TEXT,
                os_name TEXT,
                device_type TEXT,
                details TEXT,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON access_audit_logs(timestamp);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON access_audit_logs(username);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON access_audit_logs(action);")
        if target_key:
            _security_tables_ensured_dbs.add(target_key)

def _ensure_staff_accounts_table(conn: sqlite3.Connection) -> None:
    _ensure_default_tenants(conn)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS staff_accounts (
        username TEXT PRIMARY KEY,
        employee_id TEXT DEFAULT '',
        tenant_id TEXT NOT NULL DEFAULT 'default',
        full_name TEXT NOT NULL DEFAULT '',
        display_name TEXT DEFAULT '',
        role TEXT NOT NULL DEFAULT 'STAFF',
        pin_hash TEXT NOT NULL DEFAULT '',
        email TEXT,
        phone TEXT,
        hourly_rate INTEGER DEFAULT 17000,
        is_active BOOLEAN DEFAULT 1,
        position TEXT DEFAULT 'SERVICE',
        gender TEXT DEFAULT 'NAM',
        status TEXT DEFAULT 'ACTIVE',
        allowed_roles TEXT DEFAULT '[]',
        salary_type TEXT DEFAULT 'HOURLY',
        fixed_salary INTEGER DEFAULT 0,
        token_version INTEGER DEFAULT 1,
        last_login DATETIME,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_staff_tenant ON staff_accounts(tenant_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_staff_role ON staff_accounts(role);")

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(staff_accounts);")
    cols = {r[1] for r in cur.fetchall()}
    if "employee_id" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN employee_id TEXT DEFAULT '';")
    if "display_name" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN display_name TEXT DEFAULT '';")
    if "email" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN email TEXT;")
    if "phone" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN phone TEXT;")
    if "hourly_rate" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN hourly_rate INTEGER DEFAULT 17000;")
    if "is_active" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN is_active BOOLEAN DEFAULT 1;")
    if "allowed_roles" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN allowed_roles TEXT DEFAULT '[]';")
    if "salary_type" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN salary_type TEXT DEFAULT 'HOURLY';")
    if "fixed_salary" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN fixed_salary INTEGER DEFAULT 0;")
    if "token_version" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN token_version INTEGER DEFAULT 1;")
    if "zalo_uid" not in cols:
        conn.execute("ALTER TABLE staff_accounts ADD COLUMN zalo_uid TEXT DEFAULT '';")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_staff_emp_id ON staff_accounts(employee_id);")
    conn.execute("UPDATE staff_accounts SET display_name = full_name WHERE (display_name IS NULL OR display_name = '') AND full_name IS NOT NULL AND full_name != '';")
    conn.execute("UPDATE staff_accounts SET full_name = display_name WHERE (full_name IS NULL OR full_name = '') AND display_name IS NOT NULL AND display_name != '';")
    conn.execute("UPDATE staff_accounts SET is_active = CASE WHEN status = 'INACTIVE' THEN 0 ELSE 1 END WHERE is_active IS NULL;")

    # Auto-assign deterministic employee_id (EMP_001, EMP_002...) for any rows missing it
    cur.execute("SELECT username, employee_id FROM staff_accounts ORDER BY created_at ASC, username ASC;")
    all_rows = cur.fetchall()
    used_nums = set()
    missing_users = []
    for r in all_rows:
        eid = (r["employee_id"] or "").strip()
        if eid.startswith("EMP_") and eid[4:].isdigit():
            used_nums.add(int(eid[4:]))
        elif not eid:
            missing_users.append(r["username"])

    if missing_users:
        next_idx = 1
        for u in missing_users:
            while next_idx in used_nums:
                next_idx += 1
            new_eid = f"EMP_{next_idx:03d}"
            used_nums.add(next_idx)
            conn.execute("UPDATE staff_accounts SET employee_id = ? WHERE username = ?", (new_eid, u))

def _ensure_payroll_confirmations_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS payroll_confirmations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        username TEXT NOT NULL,
        month TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'CONFIRMED',
        note TEXT DEFAULT '',
        timestamp TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
        UNIQUE(tenant_id, username, month)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payroll_conf_month ON payroll_confirmations(tenant_id, month);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payroll_conf_user ON payroll_confirmations(username);")

def _ensure_payroll_locks_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS payroll_locks (
        month TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        status TEXT NOT NULL DEFAULT 'OPEN',
        message TEXT DEFAULT '',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (month, tenant_id),
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS payroll_disbursements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        month TEXT NOT NULL,
        staff_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'UNPAID',
        amount INTEGER DEFAULT 0,
        paid_by TEXT DEFAULT '',
        updated_at TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(tenant_id, month, staff_name),
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_disb_month ON payroll_disbursements(tenant_id, month);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_disb_staff ON payroll_disbursements(staff_name);")

def _ensure_v2_operational_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS shift_approvals (
        shift_key TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        status TEXT NOT NULL DEFAULT 'APPROVE',
        approved_mins INTEGER NOT NULL DEFAULT 300,
        manager TEXT DEFAULT 'QUẢN LÝ',
        note TEXT DEFAULT '',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (shift_key, tenant_id)
    );

    CREATE TABLE IF NOT EXISTS roster_schedules (
        week_key TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        status TEXT NOT NULL DEFAULT 'DRAFT',
        schedule_json TEXT NOT NULL DEFAULT '{}',
        registrations_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (week_key, tenant_id)
    );

    CREATE TABLE IF NOT EXISTS open_shifts (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        week_key TEXT NOT NULL DEFAULT '',
        date TEXT NOT NULL,
        shift_key TEXT NOT NULL,
        slot_type TEXT NOT NULL DEFAULT 'service',
        role_required TEXT NOT NULL DEFAULT 'SERVICE',
        note TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'OPEN',
        claimed_by TEXT DEFAULT '',
        claimed_by_name TEXT DEFAULT '',
        claimed_at TEXT,
        created_by TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_open_shifts_status ON open_shifts(tenant_id, status, date);

    CREATE TABLE IF NOT EXISTS attendance_requests (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        username TEXT NOT NULL,
        employee_id TEXT DEFAULT '',
        display_name TEXT NOT NULL,
        date TEXT NOT NULL,
        shift_key TEXT NOT NULL,
        request_type TEXT NOT NULL DEFAULT 'FORGOT_CHECKOUT',
        requested_checkin TEXT DEFAULT '',
        requested_checkout TEXT DEFAULT '',
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'PENDING',
        reviewed_by TEXT DEFAULT '',
        review_note TEXT DEFAULT '',
        reviewed_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_att_requests_status ON attendance_requests(tenant_id, status, date);
    CREATE INDEX IF NOT EXISTS idx_att_requests_user ON attendance_requests(username);
    """)

def _ensure_so_cai_luong_and_attendance_enhancements(conn: sqlite3.Connection) -> None:
    """
    Ensures the existence of the immutable audit ledger table (so_cai_luong)
    and expands attendance_logs with wage snapshot and clamping columns.
    """
    _ensure_default_tenants(conn)

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS so_cai_luong (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        nhan_vien_id TEXT NOT NULL,
        staff_name TEXT NOT NULL,
        cham_cong_id TEXT,
        loai_su_kien TEXT NOT NULL CHECK(loai_su_kien IN ('DIEU_CHINH_GIO', 'THUONG', 'PHAT', 'UNG_LUONG', 'DOI_MUC_LUONG', 'HUY_UNG_LUONG', 'HUY_THUONG', 'HUY_PHAT', 'DIEU_CHINH_GIAM', 'REVERSAL')),
        so_gio_thay_doi REAL DEFAULT 0,
        so_tien_thay_doi INTEGER DEFAULT 0,
        muc_luong_ap_dung INTEGER DEFAULT 17000,
        ly_do TEXT NOT NULL,
        nguoi_tao TEXT NOT NULL,
        idempotency_key TEXT,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_so_cai_staff ON so_cai_luong(tenant_id, staff_name);
    CREATE INDEX IF NOT EXISTS idx_so_cai_cham_cong ON so_cai_luong(cham_cong_id);

    -- Immutability Engine Triggers: Strictly prohibit UPDATE and DELETE on so_cai_luong
    CREATE TRIGGER IF NOT EXISTS trg_so_cai_luong_no_update
    BEFORE UPDATE ON so_cai_luong
    BEGIN
        SELECT RAISE(ABORT, 'Bang so_cai_luong la so cai bat bien, nghiem cam sua ban ghi!');
    END;

    CREATE TRIGGER IF NOT EXISTS trg_so_cai_luong_no_delete
    BEFORE DELETE ON so_cai_luong
    BEGIN
        SELECT RAISE(ABORT, 'Bang so_cai_luong la so cai bat bien, nghiem cam xoa ban ghi!');
    END;
    """)

    # REA4-04 Migration: Kiểm tra và mở rộng CHECK constraint nếu bảng đã tồn tại từ trước mà chưa có reversal types
    try:
        cur = conn.cursor()
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='so_cai_luong';")
        row = cur.fetchone()
        if row and row[0] and "HUY_UNG_LUONG" not in row[0]:
            conn.execute("PRAGMA foreign_keys = OFF;")
            conn.execute("DROP TRIGGER IF EXISTS trg_so_cai_luong_no_update;")
            conn.execute("DROP TRIGGER IF EXISTS trg_so_cai_luong_no_delete;")
            conn.execute("ALTER TABLE so_cai_luong RENAME TO so_cai_luong_old;")
            conn.execute("""
                CREATE TABLE so_cai_luong (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    nhan_vien_id TEXT NOT NULL,
                    staff_name TEXT NOT NULL,
                    cham_cong_id TEXT,
                    loai_su_kien TEXT NOT NULL CHECK(loai_su_kien IN ('DIEU_CHINH_GIO', 'THUONG', 'PHAT', 'UNG_LUONG', 'DOI_MUC_LUONG', 'HUY_UNG_LUONG', 'HUY_THUONG', 'HUY_PHAT', 'DIEU_CHINH_GIAM', 'REVERSAL')),
                    so_gio_thay_doi REAL DEFAULT 0,
                    so_tien_thay_doi INTEGER DEFAULT 0,
                    muc_luong_ap_dung INTEGER DEFAULT 17000,
                    ly_do TEXT NOT NULL,
                    nguoi_tao TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );
            """)
            conn.execute("INSERT INTO so_cai_luong SELECT * FROM so_cai_luong_old;")
            conn.execute("DROP TABLE so_cai_luong_old;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_so_cai_staff ON so_cai_luong(tenant_id, staff_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_so_cai_cham_cong ON so_cai_luong(cham_cong_id);")
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_so_cai_luong_no_update
                BEFORE UPDATE ON so_cai_luong
                BEGIN
                    SELECT RAISE(ABORT, 'Bang so_cai_luong la so cai bat bien, nghiem cam sua ban ghi!');
                END;
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_so_cai_luong_no_delete
                BEFORE DELETE ON so_cai_luong
                BEGIN
                    SELECT RAISE(ABORT, 'Bang so_cai_luong la so cai bat bien, nghiem cam xoa ban ghi!');
                END;
            """)
            conn.execute("PRAGMA foreign_keys = ON;")
    except Exception as e:
        logger.warning(f"Failed to migrate so_cai_luong CHECK constraint: {e}")

    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(so_cai_luong);")
        sc_cols = {r[1] for r in cur.fetchall()}
        if "idempotency_key" not in sc_cols:
            conn.execute("ALTER TABLE so_cai_luong ADD COLUMN idempotency_key TEXT;")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_so_cai_idempotency "
            "ON so_cai_luong(idempotency_key) WHERE idempotency_key IS NOT NULL AND idempotency_key != '';"
        )
    except Exception as e:
        logger.warning(f"Failed to ensure idempotency_key on so_cai_luong: {e}")

    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(attendance_logs);")
        att_cols = {r[1] for r in cur.fetchall()}
        if "hourly_rate_snapshot" not in att_cols:
            conn.execute("ALTER TABLE attendance_logs ADD COLUMN hourly_rate_snapshot INTEGER DEFAULT 17000;")
        if "scheduled_start" not in att_cols:
            conn.execute("ALTER TABLE attendance_logs ADD COLUMN scheduled_start TEXT DEFAULT '';")
        if "scheduled_end" not in att_cols:
            conn.execute("ALTER TABLE attendance_logs ADD COLUMN scheduled_end TEXT DEFAULT '';")
        if "effective_duration_mins" not in att_cols:
            conn.execute("ALTER TABLE attendance_logs ADD COLUMN effective_duration_mins INTEGER DEFAULT 0;")
        if "is_hanging_pending" not in att_cols:
            conn.execute("ALTER TABLE attendance_logs ADD COLUMN is_hanging_pending BOOLEAN DEFAULT 0;")
    except Exception as e:
        logger.warning(f"Failed to evolve attendance_logs schema: {e}")

def _ensure_evaluations_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='evaluations'")
    if cur.fetchone():
        cur.execute("PRAGMA table_info(evaluations);")
        eval_cols = {r[1]: r[2] for r in cur.fetchall()}
        if "id" in eval_cols and "INT" not in eval_cols["id"].upper():
            cur.execute("SELECT COUNT(*) FROM evaluations;")
            if cur.fetchone()[0] == 0:
                conn.execute("DROP TABLE evaluations;")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        staff_name TEXT NOT NULL,
        type TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL,
        date TEXT NOT NULL,
        month TEXT NOT NULL,
        manager TEXT NOT NULL DEFAULT 'Quản Lý',
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        shift TEXT DEFAULT 'Ca Sáng',
        notes TEXT,
        created_by TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        eval_key TEXT DEFAULT '',
        admin_note TEXT DEFAULT '',
        reviewed_by TEXT DEFAULT '',
        reviewed_at TEXT DEFAULT '',
        meta_json TEXT DEFAULT '{}',
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_tenant_month ON evaluations(tenant_id, month);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_staff ON evaluations(staff_name);")
    for col, col_type in [
        ("eval_key", "TEXT DEFAULT ''"),
        ("admin_note", "TEXT DEFAULT ''"),
        ("reviewed_by", "TEXT DEFAULT ''"),
        ("reviewed_at", "TEXT DEFAULT ''"),
        ("meta_json", "TEXT DEFAULT '{}'")
    ]:
        try:
            conn.execute(f"ALTER TABLE evaluations ADD COLUMN {col} {col_type};")
        except Exception:
            pass

def _ensure_daily_closings_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS daily_closings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        report_date TEXT NOT NULL,
        closing_time TEXT NOT NULL,
        bill_pos REAL NOT NULL DEFAULT 0.0,
        cash_amount REAL NOT NULL DEFAULT 0.0,
        transfer_amount REAL NOT NULL DEFAULT 0.0,
        expense_amount REAL NOT NULL DEFAULT 0.0,
        expense_detail TEXT,
        total_real REAL NOT NULL DEFAULT 0.0,
        diff REAL NOT NULL DEFAULT 0.0,
        diff_amount REAL DEFAULT 0.0,
        diff_status TEXT NOT NULL,
        is_warning INTEGER NOT NULL DEFAULT 0,
        sender_name TEXT NOT NULL,
        approver_name TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_closings_date ON daily_closings(tenant_id, report_date);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_closings_created ON daily_closings(created_at);")

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(daily_closings);")
    cols = {r[1] for r in cur.fetchall()}
    if "diff_amount" not in cols:
        conn.execute("ALTER TABLE daily_closings ADD COLUMN diff_amount REAL DEFAULT 0.0;")
    if "notes" not in cols:
        conn.execute("ALTER TABLE daily_closings ADD COLUMN notes TEXT;")
    if "shift_key" not in cols:
        conn.execute("ALTER TABLE daily_closings ADD COLUMN shift_key TEXT DEFAULT 'daily';")

def _ensure_store_configs_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS store_configs (
        tenant_id TEXT PRIMARY KEY,
        config_json TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

def init_db(db_path: Optional[str] = None) -> None:
    """Initializes the database schema with Multi-Tenancy indexes."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    cur.executescript("""
    -- 1. Tenants Table (Multi-Tenancy Foundation)
    CREATE TABLE IF NOT EXISTS tenants (
        id TEXT PRIMARY KEY,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    -- 2. Staff Accounts Table
    CREATE TABLE IF NOT EXISTS staff_accounts (
        username TEXT PRIMARY KEY,
        employee_id TEXT DEFAULT '',
        tenant_id TEXT NOT NULL DEFAULT 'default',
        full_name TEXT NOT NULL DEFAULT '',
        display_name TEXT DEFAULT '',
        role TEXT NOT NULL DEFAULT 'STAFF',
        pin_hash TEXT NOT NULL DEFAULT '',
        email TEXT,
        phone TEXT,
        hourly_rate INTEGER DEFAULT 17000,
        is_active BOOLEAN DEFAULT 1,
        position TEXT DEFAULT 'SERVICE',
        gender TEXT DEFAULT 'NAM',
        status TEXT DEFAULT 'ACTIVE',
        allowed_roles TEXT DEFAULT '[]',
        salary_type TEXT DEFAULT 'HOURLY',
        fixed_salary INTEGER DEFAULT 0,
        token_version INTEGER DEFAULT 1,
        last_login DATETIME,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_staff_tenant ON staff_accounts(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_staff_role ON staff_accounts(role);

    -- 3. Staff Aliases Table (for fuzzy shift mapping)
    CREATE TABLE IF NOT EXISTS staff_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        alias TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        FOREIGN KEY (username) REFERENCES staff_accounts(username) ON DELETE CASCADE,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
        UNIQUE(username, alias)
    );
    CREATE INDEX IF NOT EXISTS idx_aliases_lookup ON staff_aliases(alias, tenant_id);

    -- 4. Evaluations Table (Disciplinary & Rewards)
    CREATE TABLE IF NOT EXISTS evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        staff_name TEXT NOT NULL,
        type TEXT NOT NULL,
        amount INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL,
        date TEXT NOT NULL,
        month TEXT NOT NULL,
        manager TEXT NOT NULL DEFAULT 'Quản Lý',
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        shift TEXT DEFAULT 'Ca Sáng',
        notes TEXT,
        created_by TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_eval_tenant_month ON evaluations(tenant_id, month);
    CREATE INDEX IF NOT EXISTS idx_eval_staff ON evaluations(staff_name);

    -- 5. Payroll Locks Table
    CREATE TABLE IF NOT EXISTS payroll_locks (
        month TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        message TEXT DEFAULT '',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (month, tenant_id),
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );

    -- 6. Attendance Logs Table
    CREATE TABLE IF NOT EXISTS attendance_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        username TEXT NOT NULL,
        full_name TEXT NOT NULL,
        date TEXT NOT NULL,
        shift TEXT NOT NULL,
        checkin DATETIME,
        checkout DATETIME,
        duration_mins INTEGER DEFAULT 0,
        status TEXT DEFAULT 'ON_TIME',
        note TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_att_tenant_date ON attendance_logs(tenant_id, date);
    CREATE INDEX IF NOT EXISTS idx_att_user ON attendance_logs(username);

    -- 7. Login Attempts Table (Brute-Force Protection & Rate Limiting)
    CREATE TABLE IF NOT EXISTS login_attempts (
        target_key TEXT PRIMARY KEY,
        target_type TEXT NOT NULL DEFAULT 'IP',
        identifier TEXT NOT NULL DEFAULT '',
        ip TEXT,
        username TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        tier INTEGER NOT NULL DEFAULT 1,
        lockout_until REAL,
        is_admin_locked INTEGER NOT NULL DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_login_identifier ON login_attempts(identifier);
    CREATE INDEX IF NOT EXISTS idx_login_lockout ON login_attempts(lockout_until);

    -- 8. Staff Ledgers Table (Sổ Phụ Server-Side: Bonus, Advance, Deduction)
    CREATE TABLE IF NOT EXISTS staff_ledgers (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        staff_name TEXT NOT NULL,
        month TEXT NOT NULL,
        type TEXT NOT NULL,          -- 'bonus', 'advance', 'deduction'
        amount INTEGER NOT NULL,
        payment_method TEXT DEFAULT 'cash', -- 'cash', 'bank'
        reason TEXT,
        created_by TEXT,
        is_deleted INTEGER DEFAULT 0,
        deleted_at DATETIME,
        deleted_by TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_staff_ledgers_month_staff ON staff_ledgers(tenant_id, month, staff_name);

    -- 9. Revoked Tokens Table (JWT Blacklist)
    CREATE TABLE IF NOT EXISTS revoked_tokens (
        token_hash TEXT PRIMARY KEY,
        reason TEXT DEFAULT '',
        revoked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at REAL
    );
    CREATE INDEX IF NOT EXISTS idx_revoked_tokens_exp ON revoked_tokens(expires_at);

    -- 10. API Rate Limits Table (Comprehensive Rate Limiting)
    CREATE TABLE IF NOT EXISTS api_rate_limits (
        key TEXT PRIMARY KEY,
        count INTEGER NOT NULL DEFAULT 1,
        reset_at REAL NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_api_rate_limits_reset ON api_rate_limits(reset_at);

    -- 11. Access Audit Logs Table (Weekly Executive Access Digest)
    CREATE TABLE IF NOT EXISTS access_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        username TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT DEFAULT 'STAFF',
        action TEXT NOT NULL,
        client_ip TEXT,
        is_cafe_wifi BOOLEAN DEFAULT 0,
        user_agent TEXT,
        os_name TEXT,
        device_type TEXT,
        details TEXT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_audit_time ON access_audit_logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_audit_user ON access_audit_logs(username);
    CREATE INDEX IF NOT EXISTS idx_audit_action ON access_audit_logs(action);

    -- 12. Daily Closings Table (POS Cash Closing & Audit)
    CREATE TABLE IF NOT EXISTS daily_closings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        report_date TEXT NOT NULL,
        closing_time TEXT NOT NULL,
        bill_pos REAL NOT NULL DEFAULT 0.0,
        cash_amount REAL NOT NULL DEFAULT 0.0,
        transfer_amount REAL NOT NULL DEFAULT 0.0,
        expense_amount REAL NOT NULL DEFAULT 0.0,
        expense_detail TEXT,
        total_real REAL NOT NULL DEFAULT 0.0,
        diff REAL NOT NULL DEFAULT 0.0,
        diff_amount REAL DEFAULT 0.0,
        diff_status TEXT NOT NULL,
        is_warning INTEGER NOT NULL DEFAULT 0,
        sender_name TEXT NOT NULL,
        approver_name TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_closings_date ON daily_closings(tenant_id, report_date);
    CREATE INDEX IF NOT EXISTS idx_closings_created ON daily_closings(created_at);

    -- 13. Shift Approvals Table (OT / Excess Shift Approvals)
    CREATE TABLE IF NOT EXISTS shift_approvals (
        shift_key TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        status TEXT NOT NULL DEFAULT 'APPROVE',
        approved_mins INTEGER NOT NULL DEFAULT 300,
        manager TEXT DEFAULT 'QUẢN LÝ',
        note TEXT DEFAULT '',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (shift_key, tenant_id),
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );

    -- 14. Roster Schedules Table (Weekly Schedules & Registrations)
    CREATE TABLE IF NOT EXISTS roster_schedules (
        week_key TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        status TEXT NOT NULL DEFAULT 'DRAFT',
        schedule_json TEXT NOT NULL DEFAULT '{}',
        registrations_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (week_key, tenant_id),
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );

    -- 15. Open Shifts Table (Staffjoy-style Open Shift Marketplace)
    CREATE TABLE IF NOT EXISTS open_shifts (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        week_key TEXT NOT NULL DEFAULT '',
        date TEXT NOT NULL,
        shift_key TEXT NOT NULL,
        slot_type TEXT NOT NULL DEFAULT 'service',
        role_required TEXT NOT NULL DEFAULT 'SERVICE',
        note TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'OPEN',
        claimed_by TEXT DEFAULT '',
        claimed_by_name TEXT DEFAULT '',
        claimed_at TEXT,
        created_by TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_open_shifts_status ON open_shifts(tenant_id, status, date);

    -- 16. Attendance Requests Table (Frappe-style Self-Service Attendance Explanation)
    CREATE TABLE IF NOT EXISTS attendance_requests (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        username TEXT NOT NULL,
        employee_id TEXT DEFAULT '',
        display_name TEXT NOT NULL,
        date TEXT NOT NULL,
        shift_key TEXT NOT NULL,
        request_type TEXT NOT NULL DEFAULT 'FORGOT_CHECKOUT',
        requested_checkin TEXT DEFAULT '',
        requested_checkout TEXT DEFAULT '',
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'PENDING',
        reviewed_by TEXT DEFAULT '',
        review_note TEXT DEFAULT '',
        reviewed_at TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_att_requests_status ON attendance_requests(tenant_id, status, date);
    CREATE INDEX IF NOT EXISTS idx_att_requests_user ON attendance_requests(username);

    -- 17. Push Subscriptions Table (Web Push PWA)
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        endpoint TEXT UNIQUE NOT NULL,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        user_agent TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_push_sub_user ON push_subscriptions(tenant_id, username, is_active);

    -- 18. Notification Dispatches Table (Deduplication & Audit Log)
    CREATE TABLE IF NOT EXISTS notification_dispatches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        dedup_key TEXT UNIQUE NOT NULL,
        notification_type TEXT NOT NULL,
        username TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL,
        response_code INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_notif_dedup ON notification_dispatches(tenant_id, dedup_key);

    -- 19. In-App Reminders Table (Pop-up alerts for active staff in app)
    CREATE TABLE IF NOT EXISTS in_app_reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        username TEXT NOT NULL,
        remind_type TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        url TEXT DEFAULT '',
        is_read INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        read_at DATETIME,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
    );
    -- 20. Store Settings Table (Operational Quick Toggles)
    CREATE TABLE IF NOT EXISTS store_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        label TEXT DEFAULT '',
        description TEXT DEFAULT '',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_by TEXT DEFAULT 'system'
    );

    -- 21. Payroll Confirmations Table (Staff Dispute & Acknowledgement Log)
    CREATE TABLE IF NOT EXISTS payroll_confirmations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        username TEXT NOT NULL,
        month TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'CONFIRMED',
        note TEXT DEFAULT '',
        timestamp TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
        UNIQUE(tenant_id, username, month)
    );
    CREATE INDEX IF NOT EXISTS idx_payroll_conf_month ON payroll_confirmations(tenant_id, month);
    CREATE INDEX IF NOT EXISTS idx_payroll_conf_user ON payroll_confirmations(username);

    -- 22. Store Configs Table (Multi-Tenant Store Configuration)
    CREATE TABLE IF NOT EXISTS store_configs (
        tenant_id TEXT PRIMARY KEY,
        config_json TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Run schema evolutions
    _ensure_staff_accounts_table(conn)
    _ensure_login_attempts_table(conn)
    _ensure_staff_ledgers_table(conn)
    _ensure_evaluations_table(conn)
    _ensure_daily_closings_table(conn)
    _ensure_v2_operational_tables(conn)
    _ensure_payroll_confirmations_table(conn)
    _ensure_so_cai_luong_and_attendance_enhancements(conn)
    _ensure_store_configs_table(conn)

    # Seed default tenants if not exists
    _ensure_default_tenants(conn)

    # Seed default store_settings toggles
    default_settings = [
        ("auto_remind_shifts", "1", "Tự động nhắc ca theo mốc giờ vàng", "Tự động gửi thông báo lúc 06:15, 11:15, 17:15, 18:15, 22:30"),
        ("emergency_remote_checkin", "0", "Mở Check-in ngoài quán (Sự cố mạng)", "Cho phép nhân viên check-in không cần WiFi quán khi rớt mạng/cúp điện"),
        ("roster_registration_open", "1", "Mở cổng nộp lịch ca tuần mới", "Cho phép nhân viên nộp và chỉnh sửa lịch đăng ký ca làm tuần mới"),
        ("peer_shift_swap_allowed", "1", "Cho phép nhân viên tự đổi ca", "Cho phép 2 nhân viên tự thương lượng và hoán đổi ca làm việc trực tiếp"),
        ("payroll_verification_open", "1", "Mở kỳ đối soát & xác nhận lương", "Cho phép nhân viên xem chi tiết và ký xác nhận bảng tính công lương tháng"),
        ("admin_token_version", "1", "Admin Session Token Version", "Phiên bản token bảo mật của Admin")
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO store_settings (key, value, label, description)
        VALUES (?, ?, ?, ?)
    """, default_settings)

    conn.commit()
    conn.close()
