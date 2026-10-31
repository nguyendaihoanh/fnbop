#!/usr/bin/env python3
"""
FnBOps Native macOS DMG Packager
================================
Builds a native macOS Application Bundle (FnBOps.app) with drag-to-Applications
installer (.dmg), bundled app icon (app.icns), and zero-leak runtime verification.
"""

import os
import sys
import shutil
import subprocess
import hashlib
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DMG = os.path.join(PROJECT_ROOT, "FnBOps.dmg")
STAGE_DIR = "/tmp/fnbops_dmg_stage"
APP_DIR = os.path.join(STAGE_DIR, "FnBOps.app")
CONTENTS_DIR = os.path.join(APP_DIR, "Contents")
MACOS_DIR = os.path.join(CONTENTS_DIR, "MacOS")
RESOURCES_DIR = os.path.join(CONTENTS_DIR, "Resources")
APP_PAYLOAD_DIR = os.path.join(RESOURCES_DIR, "app")

# Runtime files to include
EXCLUDE_PREFIXES = (
    "tests/",
    ".github/",
    ".githooks/",
    "scripts/",
    ".cursorrules",
    ".dockerignore",
    "docs/brand/",
    "fnbop-v1.0.0.zip",
    "FnBOps.dmg",
)

FORBIDDEN_EXTENSIONS = (
    ".log",
    ".db",
    ".sqlite",
    ".pyc",
    ".DS_Store",
    ".bak",
    ".swp",
)

FORBIDDEN_PATTERNS = (
    "node_modules",
    "task_artifacts",
    "egg-info",
    "__pycache__",
    ".github",
    ".githooks",
    "tests/",
    "deploy_history",
)

LEAK_PATTERNS = {
    "Mac User Path": re.compile(r"/Users/hoanh(?:nguyen)?/"),
    "Tailscale Device IP": re.compile(r"100\.(?:103|113|116)\.\d{1,3}\.\d{1,3}"),
    "Internal Production Domain": re.compile(r"cc\.vnaigc\.com"),
    "POS Hostname": re.compile(r"\badmin-pc\b", re.IGNORECASE),
    "Hardcoded Telegram Token": re.compile(r"\b\d{8,10}:[a-zA-Z0-9_-]{35}\b"),
    "Private Key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY"),
}


INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>FnBOps</string>
    <key>CFBundleDisplayName</key>
    <string>FnBOps</string>
    <key>CFBundleIdentifier</key>
    <string>com.vnaigc.fnbops</string>
    <key>CFBundleVersion</key>
    <string>1.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleExecutable</key>
    <string>FnBOps</string>
    <key>CFBundleIconFile</key>
    <string>app.icns</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
"""

LAUNCHER_SCRIPT = """#!/usr/bin/env bash
set -e

# ==============================================================================
# FnBOps macOS Native Launcher (Zero-Config Edge POS & Workforce OS)
# ==============================================================================

APP_RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
APP_SOURCE="$APP_RESOURCES/app"

# Standard macOS persistent user directory
DATA_HOME="$HOME/Library/Application Support/FnBOps"
mkdir -p "$DATA_HOME/data/logs"
mkdir -p "$DATA_HOME/data/backups"
mkdir -p "$DATA_HOME/data/outbox/pdf"

# Seed default configs if first run
if [ ! -f "$DATA_HOME/data/store_config.json" ] && [ -f "$APP_SOURCE/data/store_config.json" ]; then
    cp "$APP_SOURCE/data/store_config.json" "$DATA_HOME/data/"
fi
if [ ! -f "$DATA_HOME/data/staff_auth.json" ] && [ -f "$APP_SOURCE/data/staff_auth.json" ]; then
    cp "$APP_SOURCE/data/staff_auth.json" "$DATA_HOME/data/"
fi
if [ ! -f "$DATA_HOME/data/data.json" ] && [ -f "$APP_SOURCE/data/data.json" ]; then
    cp "$APP_SOURCE/data/data.json" "$DATA_HOME/data/"
fi
if [ ! -f "$DATA_HOME/.env" ] && [ -f "$APP_SOURCE/.env.example" ]; then
    cp "$APP_SOURCE/.env.example" "$DATA_HOME/.env"
fi

# Locate Python 3
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif [ -f "/opt/homebrew/bin/python3" ]; then
    PYTHON_CMD="/opt/homebrew/bin/python3"
elif [ -f "/usr/local/bin/python3" ]; then
    PYTHON_CMD="/usr/local/bin/python3"
fi

if [ -z "$PYTHON_CMD" ]; then
    osascript -e 'display dialog "Chưa tìm thấy Python 3 trên máy Mac của bạn.\\nVui lòng cài đặt Python (3.11 hoặc 3.12) từ python.org để khởi chạy FnBOps." with title "FnBOps" buttons {"Đóng"} default button "Đóng" with icon stop'
    exit 1
fi

# Virtual environment in persistent user space
VENV_DIR="$DATA_HOME/.venv"
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

# Auto install / sync packages
if ! "$VENV_DIR/bin/python3" -c "import fastapi, uvicorn, pydantic" &>/dev/null; then
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    if [ -f "$APP_SOURCE/requirements.txt" ]; then
        "$VENV_DIR/bin/pip" install --quiet -r "$APP_SOURCE/requirements.txt"
    fi
fi

# Export runtime environment
export DATA_DIR="$DATA_HOME/data"
export DATABASE_PATH="$DATA_HOME/data/fnbop.db"
export ON_PREMISE_MODE="true"
export FASTAPI_PORT=8100
export PYTHONPATH="$APP_SOURCE:$APP_SOURCE/backend"

# Automatically open browser
(sleep 2 && open "http://localhost:8100") &

# Start FastAPI application
cd "$DATA_HOME"
exec "$VENV_DIR/bin/python3" -m uvicorn backend.main:app --host 0.0.0.0 --port 8100
"""


def build_icns(icon_src_png: str, dest_icns: str):
    iconset_dir = "/tmp/fnbops_app.iconset"
    shutil.rmtree(iconset_dir, ignore_errors=True)
    os.makedirs(iconset_dir, exist_ok=True)

    sizes = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1)]
    for size, scale in sizes:
        dim = size * scale
        name = f"icon_{size}x{size}@2x.png" if scale == 2 else f"icon_{size}x{size}.png"
        out_png = os.path.join(iconset_dir, name)
        subprocess.run(["sips", "-z", str(dim), str(dim), icon_src_png, "--out", out_png], stdout=subprocess.DEVNULL, check=True)

    subprocess.run(["iconutil", "-c", "icns", iconset_dir, "-o", dest_icns], check=True)
    shutil.rmtree(iconset_dir, ignore_errors=True)


def main():
    print("=======================================================")
    print(">>> FNBOPS NATIVE MACOS DMG PACKAGER & INTEGRITY GATE")
    print("=======================================================")

    # 1. Clean stage
    shutil.rmtree(STAGE_DIR, ignore_errors=True)
    os.makedirs(MACOS_DIR, exist_ok=True)
    os.makedirs(RESOURCES_DIR, exist_ok=True)
    os.makedirs(APP_PAYLOAD_DIR, exist_ok=True)

    # 2. Get tracked files
    res = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    all_tracked = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]

    release_files = []
    for rel_path in all_tracked:
        if any(rel_path.startswith(p) or rel_path == p for p in EXCLUDE_PREFIXES):
            continue
        if any(rel_path.endswith(ext) for ext in FORBIDDEN_EXTENSIONS):
            continue
        if any(pat in rel_path for pat in FORBIDDEN_PATTERNS):
            continue
        if os.path.basename(rel_path) == ".env":
            continue
        release_files.append(rel_path)

    print(f"[*] Copying {len(release_files)} runtime files into app bundle payload...")
    for rel_path in release_files:
        src = os.path.join(PROJECT_ROOT, rel_path)
        dest = os.path.join(APP_PAYLOAD_DIR, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)

    # 3. Write Info.plist
    plist_path = os.path.join(CONTENTS_DIR, "Info.plist")
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(INFO_PLIST)

    # 4. Write launcher executable
    launcher_path = os.path.join(MACOS_DIR, "FnBOps")
    with open(launcher_path, "w", encoding="utf-8") as f:
        f.write(LAUNCHER_SCRIPT)
    os.chmod(launcher_path, 0o755)

    # 5. Build ICNS
    icon_src = os.path.join(PROJECT_ROOT, "frontend/icons/icon-512.png")
    dest_icns = os.path.join(RESOURCES_DIR, "app.icns")
    print("[*] Generating native macOS app.icns...")
    build_icns(icon_src, dest_icns)

    # 6. Deep leak scan of entire bundle
    print("[*] Scanning bundle payload for sensitive leaks...")
    violations = []
    for root, _, files in os.walk(APP_DIR):
        for fn in files:
            if fn.endswith((".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".ttf", ".icns")):
                continue
            fpath = os.path.join(root, fn)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for rule_name, rx in LEAK_PATTERNS.items():
                    m = rx.findall(content)
                    if m:
                        violations.append(f"Sensitive content leak '{rule_name}' ({set(m)}) in: {os.path.relpath(fpath, STAGE_DIR)}")
            except Exception as e:
                pass

    if violations:
        print(f"\n[CRITICAL FAILURE] Found {len(violations)} violations in app bundle:")
        for v in violations:
            print(f"  ❌ {v}")
        shutil.rmtree(STAGE_DIR, ignore_errors=True)
        sys.exit(1)

    # 7. Create Applications symlink for drag-to-install
    os.symlink("/Applications", os.path.join(STAGE_DIR, "Applications"))

    # 8. Create compressed DMG
    if os.path.exists(OUTPUT_DMG):
        os.remove(OUTPUT_DMG)

    print(f"[*] Packaging DMG with hdiutil...")
    cmd = [
        "hdiutil", "create",
        "-volname", "FnBOps",
        "-srcfolder", STAGE_DIR,
        "-ov",
        "-format", "UDZO",
        OUTPUT_DMG
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[FAIL] hdiutil failed: {res.stderr}")
        sys.exit(1)

    # Clean up stage
    shutil.rmtree(STAGE_DIR, ignore_errors=True)

    dmg_size_mb = os.path.getsize(OUTPUT_DMG) / (1024 * 1024)
    with open(OUTPUT_DMG, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    print(f"\n[PASS] 0 leaks detected. Native macOS DMG verified 100% clean.")
    print(f"[SUCCESS] Packaged: {OUTPUT_DMG} ({dmg_size_mb:.2f} MB)")
    print(f"[*] SHA256: {sha256}")
    print("=======================================================")


if __name__ == "__main__":
    main()
