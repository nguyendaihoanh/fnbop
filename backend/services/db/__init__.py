# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Database Service Package (SQLite WAL Mode)
High-performance modular architecture preserving 100% backward compatibility.
Submodules:
- connection: WAL connection, pragmas, checkpoints, safe online backups
- schema: Table initializations and incremental migrations
- security_repo: Tiered login lockouts, token revocations, rate limits, audit logs
- staff_repo: Accounts, directory mappings, employee ID resolution, auth bootstrapping
- attendance_repo: Shift approvals, open shift marketplace, attendance requests
- payroll_repo: Staff ledgers, so_cai_luong general ledger, monthly confirmations
- ops_repo: Daily closings, evaluations, seed data migrations, store settings
- notification_repo: Web push subscriptions, in-app persistent reminders, dispatch logs
"""

import sys
import os

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from services.db.connection import (
    DEFAULT_DB_PATH,
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    _BASE_DIR,
    _PROJECT_DIR,
    _thread_local,
    logger,
    get_db_path,
    get_db_connection,
    checkpoint_db,
    cleanup_old_backups,
    safe_sqlite_backup,
)

from services.db.schema import (
    _security_tables_lock,
    _security_tables_ensured_dbs,
    _ensure_login_attempts_table,
    _ensure_staff_ledgers_table,
    _ensure_security_tables,
    _ensure_staff_accounts_table,
    _ensure_payroll_confirmations_table,
    _ensure_v2_operational_tables,
    _ensure_so_cai_luong_and_attendance_enhancements,
    _ensure_evaluations_table,
    _ensure_daily_closings_table,
    _ensure_store_configs_table,
    init_db,
)

from services.db.security_repo import (
    record_failed_attempt_tiered,
    check_login_lockout,
    clear_login_lockout,
    get_active_lockouts,
    admin_unlock_target,
    get_login_attempts,
    record_failed_login,
    clear_login_attempts,
    _hash_token,
    revoke_token,
    is_token_revoked,
    cleanup_expired_tokens,
    check_api_rate_limit,
    clear_all_rate_limits,
    parse_user_agent,
    record_access_audit,
    get_access_audit_logs,
    purge_old_access_audit_logs,
)

from services.db.staff_repo import (
    get_staff_by_username,
    list_staff_accounts,
    upsert_staff_account,
    get_staff_directory_map,
    resolve_employee_id,
    bootstrap_sync_staff_auth_to_sqlite,
    get_staff_token_version,
    bump_staff_token_version_db,
    load_staff_auth_from_sqlite,
)

from services.db.attendance_repo import (
    upsert_shift_approval_db,
    delete_shift_approval_db,
    list_shift_approvals_db,
    create_open_shift_db,
    list_open_shifts_db,
    claim_open_shift_db,
    delete_open_shift_db,
    create_attendance_request_db,
    list_attendance_requests_db,
    get_attendance_request_by_id_db,
    review_attendance_request_db,
)

from services.db.payroll_repo import (
    insert_staff_ledger,
    list_staff_ledgers,
    get_staff_ledger_by_id,
    delete_staff_ledger,
    record_so_cai_luong,
    list_so_cai_luong,
    upsert_payroll_confirmation,
    list_payroll_confirmations,
    upsert_payroll_lock_db,
    is_payroll_locked_db,
    get_payroll_locks_db,
    upsert_payroll_disbursement_db,
    get_payroll_disbursements_db,
)

from services.db.ops_repo import (
    insert_evaluation,
    list_evaluations,
    update_evaluation_status_db,
    get_evaluation_by_id_db,
    clear_evaluations_db,
    insert_daily_closing,
    get_daily_closings,
    list_daily_closings,
    get_daily_closing_by_id,
    update_daily_closing,
    migrate_seed_data_from_json,
    get_store_setting_db,
    get_all_store_settings_db,
    update_store_setting_db,
    get_admin_token_version_db,
    increment_admin_token_version_db,
)

from services.db.roster_repo import (
    upsert_roster_schedule_db,
    get_roster_schedule_db,
    list_roster_schedules_db,
    migrate_roster_schedules_from_json,
)

from services.db.notification_repo import (
    save_push_subscription_db,
    list_push_subscriptions_db,
    deactivate_push_subscription_db,
    has_notification_dispatched_db,
    record_notification_dispatch_db,
    save_in_app_reminder_db,
    list_active_in_app_reminders_db,
    ack_in_app_reminder_db,
    ack_all_in_app_reminders_db,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "DEFAULT_TENANT_ID",
    "DEFAULT_TENANT_NAME",
    "_BASE_DIR",
    "_PROJECT_DIR",
    "_thread_local",
    "logger",
    "get_db_path",
    "get_db_connection",
    "checkpoint_db",
    "cleanup_old_backups",
    "safe_sqlite_backup",
    "_security_tables_lock",
    "_security_tables_ensured_dbs",
    "_ensure_login_attempts_table",
    "_ensure_staff_ledgers_table",
    "_ensure_security_tables",
    "_ensure_staff_accounts_table",
    "_ensure_payroll_confirmations_table",
    "_ensure_v2_operational_tables",
    "_ensure_so_cai_luong_and_attendance_enhancements",
    "_ensure_evaluations_table",
    "_ensure_daily_closings_table",
    "_ensure_store_configs_table",
    "init_db",
    "record_failed_attempt_tiered",
    "check_login_lockout",
    "clear_login_lockout",
    "get_active_lockouts",
    "admin_unlock_target",
    "get_login_attempts",
    "record_failed_login",
    "clear_login_attempts",
    "_hash_token",
    "revoke_token",
    "is_token_revoked",
    "cleanup_expired_tokens",
    "check_api_rate_limit",
    "clear_all_rate_limits",
    "parse_user_agent",
    "record_access_audit",
    "get_access_audit_logs",
    "purge_old_access_audit_logs",
    "get_staff_by_username",
    "list_staff_accounts",
    "upsert_staff_account",
    "get_staff_directory_map",
    "resolve_employee_id",
    "bootstrap_sync_staff_auth_to_sqlite",
    "upsert_shift_approval_db",
    "delete_shift_approval_db",
    "list_shift_approvals_db",
    "create_open_shift_db",
    "list_open_shifts_db",
    "claim_open_shift_db",
    "delete_open_shift_db",
    "create_attendance_request_db",
    "list_attendance_requests_db",
    "get_attendance_request_by_id_db",
    "review_attendance_request_db",
    "insert_staff_ledger",
    "list_staff_ledgers",
    "get_staff_ledger_by_id",
    "delete_staff_ledger",
    "record_so_cai_luong",
    "list_so_cai_luong",
    "upsert_payroll_confirmation",
    "list_payroll_confirmations",
    "upsert_payroll_lock_db",
    "is_payroll_locked_db",
    "get_payroll_locks_db",
    "insert_evaluation",
    "list_evaluations",
    "update_evaluation_status_db",
    "get_evaluation_by_id_db",
    "clear_evaluations_db",
    "upsert_roster_schedule_db",
    "get_roster_schedule_db",
    "list_roster_schedules_db",
    "migrate_roster_schedules_from_json",
    "insert_daily_closing",
    "get_daily_closings",
    "list_daily_closings",
    "get_daily_closing_by_id",
    "update_daily_closing",
    "migrate_seed_data_from_json",
    "get_store_setting_db",
    "get_all_store_settings_db",
    "update_store_setting_db",
    "get_staff_token_version",
    "bump_staff_token_version_db",
    "get_admin_token_version_db",
    "increment_admin_token_version_db",
    "save_push_subscription_db",
    "list_push_subscriptions_db",
    "deactivate_push_subscription_db",
    "has_notification_dispatched_db",
    "record_notification_dispatch_db",
    "save_in_app_reminder_db",
    "list_active_in_app_reminders_db",
    "ack_in_app_reminder_db",
    "ack_all_in_app_reminders_db",
]
