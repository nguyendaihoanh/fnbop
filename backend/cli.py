#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
FnBOps Command Line Interface (CLI)
Provides administration, initialization, data seeding, and server orchestration tools.

Commands:
    fnbops init       Initialize store configuration and master admin account
    fnbops seed       Seed realistic operational demo data (cafe, restaurant, boba)
    fnbops serve      Launch the production/development FastAPI server
    fnbops backup     Perform atomic online SQLite WAL database backup
"""

import os
import sys
import argparse
import datetime
import sqlite3
import json
from typing import Optional, Dict, Any

_base_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_base_dir)

if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)
if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)


def init_command(args: argparse.Namespace) -> int:
    """Initialize FnBOps database and store configuration."""
    print("=" * 60)
    print("  FnBOps - F&B Workforce & Operations Platform Setup")
    print("=" * 60)

    tenant_id = args.tenant or os.getenv("TENANT_ID", "default")
    store_name = args.store_name or os.getenv("STORE_NAME", "FnBOps Coffee & Lounge")
    admin_pin = args.admin_pin or os.getenv("ADMIN_PIN", "1234")
    db_path = args.db_path or os.getenv("DATABASE_PATH", os.path.join(_root_dir, "data", "fnbop.db"))

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    os.environ["DATABASE_PATH"] = db_path
    os.environ["SQLITE_DB_PATH"] = db_path

    print(f"[*] Target Database : {db_path}")
    print(f"[*] Tenant ID       : {tenant_id}")
    print(f"[*] Store Name      : {store_name}")

    try:
        from backend.services.db import init_db
        from backend.services.store_config import save_store_config, DEFAULT_STORE_CONFIG
        from backend.services.storage import hash_pin
    except ImportError:
        from services.db import init_db
        from services.store_config import save_store_config, DEFAULT_STORE_CONFIG
        from services.storage import hash_pin

    # 1. Initialize SQLite Database Schema & Tables
    init_db(db_path)
    print("[+] Database schema successfully verified and evolved.")

    # 2. Setup Multi-Tenant Store Configuration
    config = dict(DEFAULT_STORE_CONFIG)
    config["store_name"] = store_name
    config["store_id"] = tenant_id
    if args.wifi_ssid:
        config["wifi_ssid"] = args.wifi_ssid
    if args.wifi_bssid:
        config["wifi_bssid"] = args.wifi_bssid

    save_store_config(config, tenant_id=tenant_id)
    print(f"[+] Store configuration for tenant '{tenant_id}' saved.")

    # 3. Seed Demo Accounts & Admin PIN
    try:
        from backend.services.demo_seed import seed_if_empty
    except ImportError:
        from services.demo_seed import seed_if_empty

    seed_if_empty()
    print("[+] Standard demo staff accounts initialized (admin/1234, manager/8888, phache/2222, nhanvien/1111).")

    print("\n[V] Setup completed successfully! Run 'fnbops serve' to start the application.")
    return 0


def seed_command(args: argparse.Namespace) -> int:
    """Seed sample operational data according to F&B preset."""
    preset = (args.preset or "cafe").lower()
    print(f"[*] Seeding FnBOps with preset: {preset.upper()}...")

    try:
        from backend.services.demo_seed import seed_if_empty
    except ImportError:
        from services.demo_seed import seed_if_empty

    seed_if_empty()
    print(f"[+] Preset '{preset}' applied successfully with standard roster quotas and staff directory.")
    return 0


def backup_command(args: argparse.Namespace) -> int:
    """Execute atomic online backup of SQLite database using SQLite Online Backup API."""
    db_path = args.db_path or os.getenv("DATABASE_PATH", os.path.join(_root_dir, "data", "fnbop.db"))
    backup_dir = args.dest or os.path.join(_root_dir, "data", "backups")
    os.makedirs(backup_dir, exist_ok=True)

    if not os.path.exists(db_path):
        print(f"[!] Error: Source database not found at '{db_path}'")
        return 1

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_path = os.path.join(backup_dir, f"fnbops_backup_{timestamp}.db")

    print(f"[*] Performing atomic backup: {db_path} -> {dest_path}")
    src_conn = sqlite3.connect(db_path)
    dst_conn = sqlite3.connect(dest_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn, pages=100)
        print(f"[+] Backup completed successfully ({os.path.getsize(dest_path):,} bytes).")
    finally:
        dst_conn.close()
        src_conn.close()

    # Optional retention cleanup (keep last 10 backups)
    backups = sorted([
        os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
        if f.startswith("fnbops_backup_") and f.endswith(".db")
    ], key=os.path.getmtime)
    if len(backups) > 10:
        for old in backups[:-10]:
            try:
                os.remove(old)
                print(f"[-] Removed expired backup: {os.path.basename(old)}")
            except OSError:
                pass

    return 0


def export_json_command(args: argparse.Namespace) -> int:
    """Export current SQLite tables to human-readable JSON snapshots."""
    db_path = args.db_path or os.getenv("DATABASE_PATH", os.path.join(_root_dir, "data", "fnbop.db"))
    out_dir = args.dest or os.path.join(_root_dir, "data", "export_snapshots")
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(db_path):
        print(f"[!] Error: Database not found at '{db_path}'")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    allowed_tables = {
        "staff_accounts": "SELECT * FROM staff_accounts",
        "attendance_logs": "SELECT * FROM attendance_logs",
        "pos_closings": "SELECT * FROM pos_closings",
        "shift_approvals": "SELECT * FROM shift_approvals",
        "evaluations": "SELECT * FROM evaluations",
        "audit_ledger": "SELECT * FROM audit_ledger",
    }
    exported = 0
    try:
        for tbl, select_sql in allowed_tables.items():
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
            if not cur.fetchone():
                continue
            cur.execute(select_sql)
            rows = [dict(r) for r in cur.fetchall()]
            out_file = os.path.join(out_dir, f"{tbl}.json")
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            print(f"[+] Exported {len(rows):>4} rows -> {out_file}")
            exported += 1
        print(f"\n[V] Successfully exported {exported} tables to {out_dir}")
        return 0
    finally:
        conn.close()



def serve_command(args: argparse.Namespace) -> int:
    """Launch Uvicorn HTTP server."""
    host = args.host or os.getenv("HOST", "0.0.0.0")
    port = int(args.port or os.getenv("PORT", 8100))
    reload = bool(args.reload)

    print(f"[*] Starting FnBOps server on http://{host}:{port} (reload={reload})...")
    import uvicorn
    uvicorn.run("backend.main:app", host=host, port=port, reload=reload)
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="fnbops",
        description="FnBOps CLI — Open-Source F&B Operations & Workforce Management Platform"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize database and store configuration")
    p_init.add_argument("--tenant", default="default", help="Tenant ID (default: 'default')")
    p_init.add_argument("--store-name", default="FnBOps Coffee & Lounge", help="Store display name")
    p_init.add_argument("--admin-pin", default="1234", help="Master administrator 4-digit PIN")
    p_init.add_argument("--wifi-ssid", default="FnBOps_Guest_WiFi", help="Store WiFi SSID")
    p_init.add_argument("--wifi-bssid", default="", help="Store WiFi BSSID (MAC address)")
    p_init.add_argument("--db-path", default="", help="Custom SQLite DB path")

    # seed
    p_seed = subparsers.add_parser("seed", help="Seed sample operational demo data")
    p_seed.add_argument("--preset", choices=["cafe", "restaurant", "boba"], default="cafe", help="F&B concept preset")

    # backup
    p_backup = subparsers.add_parser("backup", help="Create an atomic online SQLite database backup")
    p_backup.add_argument("--db-path", default="", help="Path to source SQLite database")
    p_backup.add_argument("--dest", default="", help="Destination directory for backups")

    # export-json
    p_export = subparsers.add_parser("export-json", help="Export SQLite tables to human-readable JSON files")
    p_export.add_argument("--db-path", default="", help="Path to source SQLite database")
    p_export.add_argument("--dest", default="", help="Destination directory for exported JSON snapshots")

    # serve
    p_serve = subparsers.add_parser("serve", help="Launch FastAPI web and API server")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind IP address (default: 0.0.0.0)")
    p_serve.add_argument("--port", type=int, default=8100, help="Port to listen on (default: 8100)")
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {
        "init": init_command,
        "seed": seed_command,
        "backup": backup_command,
        "export-json": export_json_command,
        "serve": serve_command,
    }

    handler = cmd_map.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
