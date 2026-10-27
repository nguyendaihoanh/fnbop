# ==============================================================================
# FnBOps - Phase 5 Packaging, Multi-Platform Installers & PWA Test Suite
# ==============================================================================
import os
import json
import stat
import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_pwa_manifest_validity():
    """Kiểm tra cấu hình PWA trong frontend/manifest.json."""
    manifest_path = os.path.join(BASE_DIR, "frontend", "manifest.json")
    assert os.path.exists(manifest_path), "frontend/manifest.json phải tồn tại"

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "FnBOps" in data.get("name", "")
    assert data.get("short_name") == "FnBOps"
    assert data.get("display") == "standalone"
    assert "start_url" in data
    assert data.get("theme_color") == "#12141a"
    assert data.get("background_color") == "#12141a"
    assert len(data.get("icons", [])) >= 2


def test_system_installers_info_api():
    """Kiểm tra endpoint /system/installers-info trả về đúng metadata 3 nền tảng."""
    # Test cả prefix /api/v1/cc và root route
    for url in ["/api/v1/cc/system/installers-info", "/system/installers-info"]:
        res = client.get(url)
        assert res.status_code == 200, f"Endpoint {url} phải trả về 200"
        payload = res.json()
        assert payload.get("status") == "success"
        platforms = payload.get("platforms", {})
        assert "mac" in platforms
        assert "windows" in platforms
        assert "mobile" in platforms

        mac_info = platforms["mac"]
        assert mac_info["filename"] == "run_mac.command"
        assert "download_url" in mac_info

        win_info = platforms["windows"]
        assert win_info["filename"] == "run_windows.bat"
        assert "download_url" in win_info

        mob_info = platforms["mobile"]
        assert mob_info["type"] == "pwa"
        assert mob_info["manifest_url"] == "/manifest.json"


def test_download_installer_mac():
    """Kiểm tra endpoint download installer cho macOS."""
    for url in ["/api/v1/cc/system/download-installer/mac", "/system/download-installer/mac"]:
        res = client.get(url)
        assert res.status_code == 200
        assert "run_mac.command" in res.headers.get("content-disposition", "")
        assert b"FnBOps" in res.content
        assert b"uvicorn backend.main:app" in res.content


def test_download_installer_windows():
    """Kiểm tra endpoint download installer cho Windows."""
    for url in ["/api/v1/cc/system/download-installer/windows", "/system/download-installer/windows"]:
        res = client.get(url)
        assert res.status_code == 200
        assert "run_windows.bat" in res.headers.get("content-disposition", "")
        assert b"FnBOps" in res.content
        assert b"uvicorn backend.main:app" in res.content


def test_download_installer_invalid_os():
    """Kiểm tra tải hệ điều hành không hỗ trợ trả về 400."""
    res = client.get("/api/v1/cc/system/download-installer/unknown_os")
    assert res.status_code == 400
    assert "không được hỗ trợ" in res.json().get("detail", "")


def test_mac_run_command_script_integrity():
    """Kiểm tra thuộc tính file và nội dung run_mac.command."""
    file_path = os.path.join(BASE_DIR, "run_mac.command")
    assert os.path.exists(file_path), "run_mac.command phải tồn tại ở thư mục gốc"

    # Kiểm tra quyền thực thi (chmod +x)
    st = os.stat(file_path)
    is_executable = bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    assert is_executable, "run_mac.command phải có cờ thực thi (+x)"

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert content.startswith("#!/usr/bin/env bash") or content.startswith("#!/bin/bash")
    assert "8100" in content
    assert "uvicorn backend.main:app" in content
    assert "open \"http://localhost:" in content


def test_windows_run_bat_script_integrity():
    """Kiểm tra file run_windows.bat."""
    file_path = os.path.join(BASE_DIR, "run_windows.bat")
    assert os.path.exists(file_path), "run_windows.bat phải tồn tại ở thư mục gốc"

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "@echo off" in content
    assert "8100" in content
    assert "uvicorn backend.main:app" in content
    assert "start http://localhost:" in content


def test_macos_packaging_service_files():
    """Kiểm tra các file cấu hình dịch vụ chạy ngầm macOS."""
    install_script = os.path.join(BASE_DIR, "packaging", "macos", "install_mac.sh")
    plist_template = os.path.join(BASE_DIR, "packaging", "macos", "io.fnbops.server.plist")

    assert os.path.exists(install_script), "install_mac.sh phải tồn tại"
    assert os.path.exists(plist_template), "io.fnbops.server.plist phải tồn tại"

    with open(install_script, "r", encoding="utf-8") as f:
        script_content = f.read()
    assert "io.fnbops.server.plist" in script_content
    assert "8100" in script_content

    with open(plist_template, "r", encoding="utf-8") as f:
        plist_content = f.read()
    assert "io.fnbops.server" in plist_content
    assert "8100" in plist_content
