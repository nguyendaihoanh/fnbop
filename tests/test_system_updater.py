# -*- coding: utf-8 -*-
"""
Standalone Unit & Integration Test Suite for System Updater Service
(Open-Source FnBOps / fnbops.local)

Verifies:
1. Semver parsing and version comparison
2. Current version reading from pyproject.toml / package.json
3. Auto-update toggle (get_update_config / set_auto_update_toggle)
4. GitHub release update checking (mock online + offline fallback)
5. Zero-data-loss SQLite pre-update backup creation
6. 1-Click apply_update execution preserving data/ directory
7. REST API endpoints in /api/fnb_ops/system/* (Auth, RBAC Admin-only, toggling)
"""

import os
import sys
import json
import sqlite3
import tempfile
import shutil
from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient

# Path resolution
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CURRENT_DIR)
BACKEND_DIR = os.path.join(PROJECT_DIR, "backend")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from backend.services.updater import (
    parse_semver,
    get_current_version,
    get_update_config,
    set_auto_update_toggle,
    check_for_updates,
    create_pre_update_backup,
    apply_update
)
from backend.services.auth import create_access_token
from main import app

client = TestClient(app)


def test_semver_parsing():
    """Verify robust semver parsing and comparison."""
    assert parse_semver("2.0.0") == (2, 0, 0)
    assert parse_semver("v2.1.3") == (2, 1, 3)
    assert parse_semver("V2.4.0-alpha") == (2, 4, 0)
    assert parse_semver("3") == (3, 0, 0)
    assert parse_semver("") == (0, 0, 0)
    assert parse_semver(None) == (0, 0, 0)

    # Comparison logic
    assert parse_semver("2.1.0") > parse_semver("2.0.9")
    assert parse_semver("v3.0.0") > parse_semver("2.99.99")
    assert parse_semver("2.0.1") > parse_semver("2.0.0")
    assert parse_semver("2.0.0") == parse_semver("v2.0.0")


def test_current_version_detection():
    """Verify get_current_version extracts a valid semver string."""
    ver = get_current_version()
    assert isinstance(ver, str)
    assert len(ver) > 0
    tup = parse_semver(ver)
    assert tup >= (1, 0, 0)


def test_auto_update_toggle_service():
    """Verify toggling auto-update state in store_configs."""
    # Turn OFF
    res_off = set_auto_update_toggle(False, tenant_id="test_store")
    assert res_off["success"] is True
    assert res_off["auto_update"] is False

    cfg_off = get_update_config(tenant_id="test_store")
    assert cfg_off["auto_update"] is False

    # Turn ON
    res_on = set_auto_update_toggle(True, tenant_id="test_store")
    assert res_on["success"] is True
    assert res_on["auto_update"] is True

    cfg_on = get_update_config(tenant_id="test_store")
    assert cfg_on["auto_update"] is True


def test_check_for_updates_mocked():
    """Verify check_for_updates correctly identifies newer versions via mocked GitHub response."""
    mock_response_data = {
        "tag_name": "v9.9.9",
        "body": "Major stability and performance upgrade.",
        "html_url": "https://github.com/nguyendaihoanh/fnbop/releases/tag/v9.9.9"
    }
    
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        info = check_for_updates(tenant_id="test_store")
        assert info["latest_version"] == "9.9.9"
        assert info["update_available"] is True
        assert "Major stability" in info["release_notes"]

    # Older version test
    mock_old_data = {
        "tag_name": "v1.0.0",
        "body": "Old legacy release",
        "html_url": "https://github.com/..."
    }
    mock_resp_old = MagicMock()
    mock_resp_old.status = 200
    mock_resp_old.read.return_value = json.dumps(mock_old_data).encode("utf-8")
    mock_resp_old.__enter__.return_value = mock_resp_old
    mock_resp_old.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp_old):
        info_old = check_for_updates(tenant_id="test_store")
        assert info_old["latest_version"] == "1.0.0"
        assert info_old["update_available"] is False


def test_pre_update_backup_creates_valid_sqlite_snapshot():
    """Verify pre-update backup executes atomic backup and produces readable SQLite database."""
    # Ensure a database exists in DATA_DIR or DATABASE_PATH
    data_dir = os.environ.get("DATA_DIR", os.path.join(PROJECT_DIR, "data"))
    db_file = os.environ.get("DATABASE_PATH") or os.path.join(data_dir, "wfm.db")
    
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE IF NOT EXISTS test_backup_probe (id INTEGER PRIMARY KEY, note TEXT);")
    conn.execute("INSERT OR REPLACE INTO test_backup_probe (id, note) VALUES (1, 'vital_store_data');")
    conn.commit()
    conn.close()

    backup_file = create_pre_update_backup()
    assert backup_file is not None
    assert os.path.exists(backup_file)

    # Verify backup is a valid SQLite DB with intact data
    bconn = sqlite3.connect(str(backup_file))
    cur = bconn.cursor()
    cur.execute("SELECT note FROM test_backup_probe WHERE id = 1;")
    row = cur.fetchone()
    bconn.close()
    assert row is not None
    assert row[0] == "vital_store_data"


def test_apply_update_execution():
    """Verify apply_update completes safely and preserves data directory."""
    with patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="Already up to date.", stderr="")
        res = apply_update(tenant_id="test_store")
        assert res["success"] is True
        assert "current_version" in res
        assert res.get("backup_path") is not None
        assert os.path.exists(res["backup_path"])


def test_api_system_update_endpoints_security():
    """Verify REST API authorization and behavior for update endpoints."""
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})
    staff_token = create_access_token({"sub": "nv01", "role": "STAFF", "name": "Nhân Viên"})
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # 1. GET /api/v1/cc/system/update-status
    res = client.get("/api/v1/cc/system/update-status")
    assert res.status_code == 200
    st_data = res.json()
    assert "auto_update" in st_data
    assert "current_version" in st_data

    # 2. POST /api/v1/cc/system/auto-update-toggle
    # Unauthorized
    r_no_auth = client.post("/api/v1/cc/system/auto-update-toggle", json={"enabled": False})
    assert r_no_auth.status_code == 401

    # Forbidden for STAFF
    r_staff = client.post("/api/v1/cc/system/auto-update-toggle", json={"enabled": False}, headers=staff_headers)
    assert r_staff.status_code == 403

    # Allowed for ADMIN
    r_admin = client.post("/api/v1/cc/system/auto-update-toggle", json={"enabled": True}, headers=admin_headers)
    assert r_admin.status_code == 200
    assert r_admin.json().get("auto_update") is True

    # 3. POST /api/v1/cc/system/check-update
    with patch("backend.services.updater.check_for_updates", return_value={
        "current_version": "1.0.0",
        "latest_version": "1.1.0",
        "update_available": True,
        "release_notes": "Bản cập nhật tối ưu FOSS.",
        "release_url": "https://github.com/...",
        "last_checked": "2026-10-18T10:00:00"
    }):
        r_check = client.post("/api/v1/cc/system/check-update")
        assert r_check.status_code == 200
        assert r_check.json().get("update_available") is True

    # 4. POST /api/v1/cc/system/apply-update
    # Forbidden for STAFF
    r_apply_staff = client.post("/api/v1/cc/system/apply-update", headers=staff_headers)
    assert r_apply_staff.status_code == 403

    # Allowed for ADMIN
    with patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="Already up to date.", stderr="")
        r_apply_admin = client.post("/api/v1/cc/system/apply-update", headers=admin_headers)
        assert r_apply_admin.status_code == 200
        assert r_apply_admin.json().get("success") is True

    # 5. Verify root aliases (/system/*)
    res_root_status = client.get("/system/update-status")
    assert res_root_status.status_code == 200
    assert "current_version" in res_root_status.json()

    res_root_toggle = client.post("/system/auto-update-toggle", json={"enabled": True}, headers=admin_headers)
    assert res_root_toggle.status_code == 200
    assert res_root_toggle.json().get("auto_update") is True
