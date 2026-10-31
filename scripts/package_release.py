#!/usr/bin/env python3
"""
FnBOps Secure Release Packager & Zero-Leak Integrity Gate
=========================================================
Ensures public release ZIPs are built 100% cleanly from Git tracking,
free of development dotfiles, tests, internal scripts, machine logs, and credentials.
"""

import os
import sys
import zipfile
import subprocess
import hashlib
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_ZIP = os.path.join(PROJECT_ROOT, "fnbop-v1.0.0.zip")
STAGE_ZIP = "/tmp/fnbop_stage_verify.zip"

# Prefixes & files strictly excluded from runtime distribution packages
EXCLUDE_PREFIXES = (
    "tests/",
    ".github/",
    ".githooks/",
    "scripts/",
    ".cursorrules",
    ".dockerignore",
    "docs/brand/",
    "fnbop-v1.0.0.zip",
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


def main():
    print("=======================================================")
    print(">>> FNBOPS SECURE RELEASE PACKAGING & ZERO-LEAK GATE")
    print("=======================================================")

    # 1. Query Git tracked files
    res = subprocess.run(["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[FAIL] 'git ls-files' failed: {res.stderr}")
        sys.exit(1)

    all_tracked = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
    print(f"[*] Total tracked files in git: {len(all_tracked)}")

    # 2. Filter out non-runtime files
    release_files = []
    excluded_count = 0
    for rel_path in all_tracked:
        if any(rel_path.startswith(p) or rel_path == p for p in EXCLUDE_PREFIXES):
            excluded_count += 1
            continue
        if any(rel_path.endswith(ext) for ext in FORBIDDEN_EXTENSIONS):
            excluded_count += 1
            continue
        if any(pat in rel_path for pat in FORBIDDEN_PATTERNS):
            excluded_count += 1
            continue
        # Exclude actual .env files except .env.example
        if os.path.basename(rel_path) == ".env":
            excluded_count += 1
            continue
        release_files.append(rel_path)

    print(f"[*] Excluded development/test/internal files: {excluded_count}")
    print(f"[*] Pure runtime files staged for packaging: {len(release_files)}")

    # 3. Content scanning for credentials and internal leaks
    violations = []
    for rel_path in release_files:
        full_path = os.path.join(PROJECT_ROOT, rel_path)
        if not os.path.exists(full_path):
            violations.append(f"Missing file: {rel_path}")
            continue

        # Skip binary files from regex text matching
        if rel_path.endswith((".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".ttf")):
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            violations.append(f"Failed to read file {rel_path}: {e}")
            continue

        for rule_name, rx in LEAK_PATTERNS.items():
            matches = rx.findall(content)
            if matches:
                violations.append(f"Leak '{rule_name}' ({set(matches)}) in file: {rel_path}")

    if violations:
        print(f"\n[CRITICAL FAILURE] Found {len(violations)} security violations in staged release files:")
        for v in violations:
            print(f"  ❌ {v}")
        sys.exit(1)

    # 4. Build ZIP cleanly into STAGE_ZIP
    if os.path.exists(STAGE_ZIP):
        os.remove(STAGE_ZIP)

    prefix = "fnbop-v1.0.0"
    with zipfile.ZipFile(STAGE_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in release_files:
            full_path = os.path.join(PROJECT_ROOT, rel_path)
            arcname = os.path.join(prefix, rel_path)
            zf.write(full_path, arcname=arcname)

    # 5. Verify staged ZIP independently
    verify_zip = zipfile.ZipFile(STAGE_ZIP, "r")
    verify_entries = verify_zip.infolist()
    for entry in verify_entries:
        ename = entry.filename
        for pat in FORBIDDEN_PATTERNS:
            if pat in ename:
                print(f"[CRITICAL FAILURE] Packaged ZIP contains forbidden pattern '{pat}': {ename}")
                os.remove(STAGE_ZIP)
                sys.exit(1)

    # 6. Atomic swap to OUTPUT_ZIP
    if os.path.exists(OUTPUT_ZIP):
        os.remove(OUTPUT_ZIP)
    os.rename(STAGE_ZIP, OUTPUT_ZIP)

    # Calculate SHA256 & Size
    with open(OUTPUT_ZIP, "rb") as f:
        sha256_hash = hashlib.sha256(f.read()).hexdigest()
    zip_size_mb = os.path.getsize(OUTPUT_ZIP) / (1024 * 1024)

    print(f"\n[PASS] 0 leaks detected. Release archive verified 100% clean.")
    print(f"[SUCCESS] Packaged: {OUTPUT_ZIP}")
    print(f"[*] Package Size: {zip_size_mb:.2f} MB ({len(release_files)} runtime files)")
    print(f"[*] SHA256: {sha256_hash}")
    print("=======================================================")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
