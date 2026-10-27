#!/usr/bin/env python3
"""
PBKDF2 Password/PIN Migration Script (FnBOps Core)
Migrates all plaintext staff PINs in data/staff_auth.json and SQLite fnbop.db to OWASP PBKDF2-HMAC-SHA256.
Preserves existing hashes and generates a pre-migration backup before writing.
"""

import os
import sys
import json
import shutil
import datetime

# Ensure project and backend directories are in python path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(_script_dir)
_backend_dir = os.path.join(_project_dir, "backend")

if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

from services.storage import hash_pin, verify_pin, needs_rehash, safe_json_write, safe_json_read
from services.db import init_db, bootstrap_sync_staff_auth_to_sqlite


def run_pin_migration():
    data_dir = os.environ.get("DATA_DIR") or os.path.join(_project_dir, "data")
    auth_file = os.path.join(data_dir, "staff_auth.json")

    if not os.path.exists(auth_file):
        print(f"[ERROR] Auth file not found: {auth_file}")
        sys.exit(1)

    # 1. Create a safe backup timestamped
    backup_dir = os.path.join(data_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(backup_dir, f"staff_auth_pre_pbkdf2_{ts}.json")
    shutil.copy2(auth_file, backup_file)
    print(f"[1/4] Backup created: {backup_file}")

    # 2. Load auth data
    with open(auth_file, "r", encoding="utf-8") as f:
        auth_data = json.load(f)

    accounts = auth_data.get("staff_accounts", {})
    migrated_count = 0
    skipped_count = 0
    verification_samples = []

    for uname, acc in accounts.items():
        raw_pin = str(acc.get("pin", "")).strip()
        if not raw_pin:
            skipped_count += 1
            continue

        if needs_rehash(raw_pin):
            hashed = hash_pin(raw_pin)
            acc["pin"] = hashed
            migrated_count += 1
            if len(verification_samples) < 5:
                verification_samples.append((uname, raw_pin, hashed))
        else:
            skipped_count += 1

    # 3. Write back atomically
    if not safe_json_write(auth_file, auth_data):
        print("[ERROR] Failed to atomically save updated staff_auth.json")
        sys.exit(1)
    print(f"[2/4] Migrated {migrated_count} accounts to PBKDF2 (Skipped/Already hashed: {skipped_count})")

    # 4. Verify samples
    for uname, plain, hashed in verification_samples:
        if not verify_pin(plain, hashed):
            print(f"[FATAL] Verification failed for {uname}! Restoring backup...")
            shutil.copy2(backup_file, auth_file)
            sys.exit(1)
    print(f"[3/4] Successfully verified {len(verification_samples)} sample accounts with verify_pin()")

    # 5. Sync to SQLite
    res_sync = bootstrap_sync_staff_auth_to_sqlite(auth_file_path=auth_file)
    print(f"[4/4] Synced to SQLite: {res_sync.get('synced_staff', 0)} accounts synced")
    print("MIGRATION COMPLETED SUCCESSFULLY.")


if __name__ == "__main__":
    run_pin_migration()
