import os
import sys
import tempfile
import sqlite3
import pytest
from unittest.mock import patch

from backend.cli import init_command, seed_command, backup_command, export_json_command
import argparse


def test_cli_init_command():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = f.name

    try:
        args = argparse.Namespace(
            tenant="demo_branch_1",
            store_name="Demo Bistro & Cafe",
            admin_pin="9999",
            wifi_ssid="Demo_WiFi_5G",
            wifi_bssid="AA:BB:CC:DD:EE:FF",
            db_path=temp_db
        )
        ret = init_command(args)
        assert ret == 0

        # Verify DB tables exist
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cursor.fetchall()]
        assert "store_configs" in tables
        assert "staff_accounts" in tables

        # Verify store config
        cursor.execute("SELECT config_json FROM store_configs WHERE tenant_id=?", ("demo_branch_1",))
        row = cursor.fetchone()
        assert row is not None
        import json
        cfg = json.loads(row[0])
        assert cfg["store_name"] == "Demo Bistro & Cafe"
        assert cfg["wifi_ssid"] == "Demo_WiFi_5G"
        conn.close()
    finally:
        if os.path.exists(temp_db):
            os.remove(temp_db)


def test_cli_seed_command():
    args = argparse.Namespace(preset="cafe")
    ret = seed_command(args)
    assert ret == 0


def test_cli_backup_command():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = f.name
    temp_backup_dir = tempfile.mkdtemp()

    try:
        # Seed minimal data
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE test_data (id INT PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO test_data VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        args = argparse.Namespace(db_path=temp_db, dest=temp_backup_dir)
        ret = backup_command(args)
        assert ret == 0

        # Verify backup file
        backups = [f for f in os.listdir(temp_backup_dir) if f.startswith("fnbops_backup_")]
        assert len(backups) == 1
        backup_file = os.path.join(temp_backup_dir, backups[0])
        assert os.path.getsize(backup_file) > 0

        # Verify backup integrity
        b_conn = sqlite3.connect(backup_file)
        b_cur = b_conn.cursor()
        b_cur.execute("SELECT val FROM test_data WHERE id=1")
        assert b_cur.fetchone()[0] == "hello"
        b_conn.close()
    finally:
        if os.path.exists(temp_db):
            os.remove(temp_db)
        import shutil
        shutil.rmtree(temp_backup_dir, ignore_errors=True)


def test_cli_export_json_command():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db = f.name
    temp_export_dir = tempfile.mkdtemp()

    try:
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE staff_accounts (username TEXT, full_name TEXT)")
        conn.execute("INSERT INTO staff_accounts VALUES ('nv01', 'Nguyen Van A')")
        conn.commit()
        conn.close()

        args = argparse.Namespace(db_path=temp_db, dest=temp_export_dir)
        ret = export_json_command(args)
        assert ret == 0

        target_json = os.path.join(temp_export_dir, "staff_accounts.json")
        assert os.path.exists(target_json)

        import json
        with open(target_json, "r", encoding="utf-8") as jf:
            rows = json.load(jf)
        assert len(rows) == 1
        assert rows[0]["username"] == "nv01"
    finally:
        if os.path.exists(temp_db):
            os.remove(temp_db)
        import shutil
        shutil.rmtree(temp_export_dir, ignore_errors=True)

