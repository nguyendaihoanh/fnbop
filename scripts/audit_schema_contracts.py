#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CI/CD Schema, OpenAPI Contract, Duplicate Operation ID & Seed Hygiene Gate.
Exits with status code 1 if ANY mismatch, OpenAPI collision warning, or seed leak is detected.
Works identically on a clean `git clone` (GitHub Actions) and local dev environments.
"""
import glob
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import warnings

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
# SHA-256 of the whitespace-normalized official FSF AGPL-3.0 text (SPDX: AGPL-3.0-only).
CANONICAL_AGPL3_SHA256 = "2cd0fb7883a3b3553dedbb0bad171646d46f51e2642951aae7c59cb5cec86c46"
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


def _bootstrap_temp_canonical_db() -> tuple[str, str]:
    """Create an isolated temporary SQLite DB initialized from canonical schema.py."""
    tmp_dir = tempfile.mkdtemp(prefix="fnbops_schema_audit_")
    db_path = os.path.join(tmp_dir, "fnbop.db")
    os.environ["TESTING"] = "1"
    os.environ.setdefault("JWT_SECRET_KEY", "ci_schema_audit_ephemeral_jwt_secret_key_32_chars")
    os.environ["DATA_DIR"] = tmp_dir
    os.environ["DATABASE_PATH"] = db_path

    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)

    from services.db import init_db
    init_db()
    return tmp_dir, db_path


def audit_sql_columns(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]
    table_columns = {}
    for t in tables:
        cursor.execute(f"PRAGMA table_info({t})")
        table_columns[t] = set(row[1] for row in cursor.fetchall())
    conn.close()

    issues = []
    if not tables:
        issues.append(("schema.py", "ALL", "0 tables", "Canonical SQLite schema failed to initialize"))

    update_pat = re.compile(r"UPDATE\s+([a-zA-Z0-9_]+)\s+SET\s+([^WHERE;\n]+)", re.IGNORECASE)
    insert_pat = re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+([a-zA-Z0-9_]+)\s*\(([^)]+)\)", re.IGNORECASE)

    for root, dirs, files in os.walk(BACKEND_DIR):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "__pycache__", ".venv")]
        for f in files:
            if f.endswith(".py"):
                filepath = os.path.join(root, f)
                with open(filepath, "r", encoding="utf-8") as fp:
                    content = fp.read()
                    for m in update_pat.finditer(content):
                        tbl = m.group(1).lower()
                        set_clause = m.group(2)
                        if tbl in table_columns:
                            valid_cols = table_columns[tbl]
                            assignments = [a.strip() for a in set_clause.split(",")]
                            for assign in assignments:
                                if "=" in assign:
                                    col = assign.split("=")[0].strip().strip("`\"' ")
                                    if col and col not in valid_cols and not col.startswith(":"):
                                        issues.append((filepath, tbl, col, "Invalid column in UPDATE SET"))

                    for m in insert_pat.finditer(content):
                        tbl = m.group(1).lower()
                        cols_str = m.group(2)
                        if tbl in table_columns:
                            cols = [c.strip().strip("`\"'\n ") for c in cols_str.split(",")]
                            valid_cols = table_columns[tbl]
                            for c in cols:
                                c_clean = c.split()[0] if c else ""
                                if c_clean and c_clean not in valid_cols:
                                    issues.append((filepath, tbl, c_clean, "Invalid column in INSERT"))

    print("--- 1. SQLITE SCHEMA AUDIT ---")
    print(f"Tables Verified: {len(tables)} | Column Mismatches in SQL: {len(issues)}")
    for iss in issues:
        print(f"  [MISMATCH] {iss[0]} -> Table [{iss[1]}]: column '{iss[2]}' ({iss[3]})")
    return len(issues)


def audit_api_endpoints() -> tuple[int, int]:
    print("\n--- 2. FRONTEND VS BACKEND ROUTE & OPENAPI CONTRACT AUDIT ---")
    os.environ["ENABLE_API_DOCS"] = "true"
    from main import app

    # Force fresh OpenAPI schema generation to capture Duplicate Operation ID warnings
    app.openapi_schema = None
    dup_warnings = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        openapi = app.openapi()
        for w in caught:
            msg = str(w.message)
            if "Duplicate Operation ID" in msg:
                dup_warnings.append(msg)

    backend_routes = openapi.get("paths", {})

    api_patterns = [
        re.compile(r'fetch\([\"\'\`](\/api\/[^\'\"\`\?]+)'),
        re.compile(r'apiFetch\([\"\'\`](\/api\/[^\'\"\`\?]+)'),
        re.compile(r'apiJson\([\"\'\`](\/api\/[^\'\"\`\?]+)'),
    ]

    frontend_calls = set()
    for root, dirs, files in os.walk(FRONTEND_DIR):
        dirs[:] = [d for d in dirs if d not in ("dist", "chunks", "node_modules", "vendor")]
        for f in files:
            if f.endswith(".js") or f.endswith(".html"):
                filepath = os.path.join(root, f)
                with open(filepath, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()
                    for pat in api_patterns:
                        for m in pat.findall(content):
                            norm_path = re.sub(r"\$\{.*?\}", "{var}", m).strip()
                            frontend_calls.add((filepath, norm_path))

    unmatched = []
    matched_count = 0
    for fp, call_path in sorted(frontend_calls):
        matched = False
        for br in backend_routes.keys():
            br_regex = re.sub(r"\{[a-zA-Z0-9_]+\}", "[^/]+", br)
            call_regex = re.sub(r"\{var\}", "[^/]+", call_path)
            if re.match(f"^{br_regex}$", call_path) or re.match(f"^{call_regex}$", br) or call_path == br:
                matched = True
                matched_count += 1
                break
        if not matched:
            unmatched.append((fp, call_path))

    print(f"Total Frontend API Calls Audited: {len(frontend_calls)}")
    print(f"Matched Routes: {matched_count} | Unmatched Routes: {len(unmatched)} | OpenAPI Collisions: {len(dup_warnings)}")
    for fp, call_path in unmatched:
        print(f"  [UNMATCHED] {fp} -> '{call_path}' NOT FOUND IN BACKEND ROUTER!")
    for dw in dup_warnings:
        print(f"  [DUPLICATE_OP_ID] {dw}")
    return len(unmatched), len(dup_warnings)


def audit_seed_and_launcher_hygiene() -> int:
    print("\n--- 3. SEED DATA & LAUNCHER CONTRACT HYGIENE ---")
    issues = []
    secret_pat = re.compile(r"([0-9]{9,10}:[a-zA-Z0-9_-]{35}|\"private_key\"\s*:\s*\"[^\"]+\"|\"vapid_keys\")")
    dirty_test_pat = re.compile(r"ca_test_[0-9]+")

    for json_path in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        fname = os.path.basename(json_path)
        if fname == "vapid_keys.json":
            continue
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                raw = f.read()
            json.loads(raw)
        except Exception as exc:
            issues.append(f"{fname}: Invalid JSON ({exc})")
            continue
        if secret_pat.search(raw):
            issues.append(f"{fname}: Contains forbidden secret/private_key/bot_token pattern")
        if dirty_test_pat.search(raw):
            issues.append(f"{fname}: Contains leftover 'ca_test_' test data")

    mac_launcher = os.path.join(PROJECT_ROOT, "run_mac.command")
    win_launcher = os.path.join(PROJECT_ROOT, "run_windows.bat")

    if not os.path.exists(mac_launcher):
        issues.append("run_mac.command: Missing at repository root")
    else:
        st = os.stat(mac_launcher)
        if not bool(st.st_mode & stat.S_IXUSR):
            issues.append("run_mac.command: Missing executable (+x) permission")
        with open(mac_launcher, "rb") as f:
            mac_bytes = f.read()
        if b"\r\n" in mac_bytes:
            issues.append("run_mac.command: Contains CRLF line endings (must be LF for macOS bash)")
        if b"uvicorn backend.main:app" not in mac_bytes:
            issues.append("run_mac.command: Missing canonical 'uvicorn backend.main:app' command")

    if not os.path.exists(win_launcher):
        issues.append("run_windows.bat: Missing at repository root")
    else:
        with open(win_launcher, "r", encoding="utf-8") as f:
            win_text = f.read()
        if "uvicorn backend.main:app" not in win_text:
            issues.append("run_windows.bat: Missing canonical 'uvicorn backend.main:app' command")

    print(f"Seed & Launcher Issues: {len(issues)}")
    for iss in issues:
        print(f"  [HYGIENE_FAIL] {iss}")
    return len(issues)


def audit_license_and_legal_compliance() -> int:
    print("\n--- 4. OPEN-SOURCE LICENSE, ATTRIBUTION & SECURITY POLICY AUDIT ---")
    issues = []

    license_file = os.path.join(PROJECT_ROOT, "LICENSE")
    commercial_file = os.path.join(PROJECT_ROOT, "COMMERCIAL_LICENSE.md")
    notices_file = os.path.join(PROJECT_ROOT, "THIRD_PARTY_NOTICES.md")
    security_file = os.path.join(PROJECT_ROOT, "SECURITY.md")
    pyproject_file = os.path.join(PROJECT_ROOT, "pyproject.toml")
    solar_bundle = os.path.join(FRONTEND_DIR, "vendor", "solar-icons-bundle.js")

    if not os.path.exists(license_file):
        issues.append("LICENSE: Missing at repository root")
    else:
        with open(license_file, "r", encoding="utf-8") as f:
            lic_text = f.read()
        if "GNU AFFERO GENERAL PUBLIC LICENSE" not in lic_text:
            issues.append("LICENSE: Must contain GNU AFFERO GENERAL PUBLIC LICENSE v3")
        # The FSF license text must stay verbatim ("changing it is not allowed").
        # Project-specific notices belong in NOTICE, never inside LICENSE.
        import hashlib
        normalized = " ".join(lic_text.split())
        if hashlib.sha256(normalized.encode("utf-8")).hexdigest() != CANONICAL_AGPL3_SHA256:
            issues.append("LICENSE: Must be the verbatim FSF AGPL-3.0 text (move project notices to NOTICE)")

    notice_file = os.path.join(PROJECT_ROOT, "NOTICE")
    if not os.path.exists(notice_file):
        issues.append("NOTICE: Missing copyright & Section 7 additional terms file")
    else:
        with open(notice_file, "r", encoding="utf-8") as f:
            notice_text = f.read()
        for req_notice in ("Nguyen Dai Hoanh", "4101699631", "hoanh@vnaigc.com", "Section 7", "AGPL-3.0-only"):
            if req_notice not in notice_text:
                issues.append(f"NOTICE: Missing required legal token '{req_notice}'")

    if not os.path.exists(os.path.join(PROJECT_ROOT, "TRADEMARKS.md")):
        issues.append("TRADEMARKS.md: Missing trademark policy for the FnBOps name and logo")

    if not os.path.exists(commercial_file):
        issues.append("COMMERCIAL_LICENSE.md: Missing dual-licensing & anti-rebranding policy file")
    else:
        with open(commercial_file, "r", encoding="utf-8") as f:
            comm_text = f.read()
        for req_comm in ("AGPL-3.0-only", "Nguyen Dai Hoanh", "4101699631", "hoanh@vnaigc.com"):
            if req_comm not in comm_text:
                issues.append(f"COMMERCIAL_LICENSE.md: Missing required legal token '{req_comm}'")

    if not os.path.exists(notices_file):
        issues.append("THIRD_PARTY_NOTICES.md: Missing third-party attribution file")
    else:
        with open(notices_file, "r", encoding="utf-8") as f:
            nt_text = f.read()
        for req_token in (
            "480 Design",
            "CC BY 4.0",
            "zca-js",
            "VNG Corporation",
            "Inter Project Authors",
            "SIL Open Font License",
            "Chart.js",
        ):
            if req_token not in nt_text:
                issues.append(f"THIRD_PARTY_NOTICES.md: Missing mandatory notice token '{req_token}'")

    if os.path.exists(security_file):
        with open(security_file, "r", encoding="utf-8") as f:
            sec_text = f.read()
        if "fnbops.org" in sec_text:
            issues.append("SECURITY.md: Contains unowned domain 'fnbops.org'")
        if "hoanh@vnaigc.com" not in sec_text:
            issues.append("SECURITY.md: Missing canonical security contact 'hoanh@vnaigc.com'")

    if os.path.exists(pyproject_file):
        with open(pyproject_file, "r", encoding="utf-8") as f:
            py_text = f.read()
        if 'license = "AGPL-3.0-only"' not in py_text:
            issues.append("pyproject.toml: License must be 'AGPL-3.0-only'")

    for pkg_rel in ("package.json", "frontend/package.json", "backend/zalo_gateway/package.json"):
        pkg_path = os.path.join(PROJECT_ROOT, pkg_rel)
        if not os.path.exists(pkg_path):
            issues.append(f"{pkg_rel}: Missing package manifest")
            continue
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg_json = json.load(f)
        if pkg_json.get("license") != "AGPL-3.0-only":
            issues.append(f"{pkg_rel}: Expected license 'AGPL-3.0-only', got '{pkg_json.get('license')}'")

    if os.path.exists(solar_bundle):
        with open(solar_bundle, "r", encoding="utf-8") as f:
            solar_full = f.read()
        solar_head = solar_full[:600]
        if "480 Design" not in solar_head or "CC BY 4.0" not in solar_head:
            issues.append("frontend/vendor/solar-icons-bundle.js: Missing CC BY 4.0 attribution header for 480 Design")
        m_solar = re.search(r"const solarCollection = (\{.*\});", solar_full)
        if m_solar:
            solar_data = json.loads(m_solar.group(1))
            bundled_icons = set(solar_data.get("icons", {}).keys()) | set(solar_data.get("aliases", {}).keys())
            used_icons = set()
            for r_dir, sub_dirs, f_list in os.walk(os.path.join(PROJECT_ROOT, "frontend")):
                sub_dirs[:] = [d for d in sub_dirs if d not in {"node_modules", "vendor", "dist", "chunks"}]
                for fn in f_list:
                    if fn.endswith((".html", ".js")):
                        with open(os.path.join(r_dir, fn), "r", encoding="utf-8", errors="ignore") as sfp:
                            used_icons.update(re.findall(r"solar:([a-z0-9-]+)", sfp.read()))
            missing_icons = sorted(used_icons - bundled_icons)
            if missing_icons:
                issues.append(
                    f"frontend/vendor/solar-icons-bundle.js: Missing {len(missing_icons)} offline icons ({', '.join(missing_icons[:5])})"
                )

    for html_rel in ("frontend/index.html", "frontend/desktop.html"):
        html_path = os.path.join(PROJECT_ROOT, html_rel)
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                html_text = f.read()
            if "https://github.com/nguyendaihoanh/fnbop" not in html_text:
                issues.append(f"{html_rel}: Missing AGPL-3.0 Section 13 Corresponding Source link")

    # 5. Open-Font Binary Audit (block proprietary Monotype/Microsoft TTFs, require SIL OFL-1.1)
    fonts_dir = os.path.join(PROJECT_ROOT, "backend", "assets", "fonts")
    ofl_file = os.path.join(fonts_dir, "OFL.txt")
    if not os.path.exists(ofl_file):
        issues.append("backend/assets/fonts/OFL.txt: Missing SIL Open Font License text for bundled fonts")
    else:
        with open(ofl_file, "r", encoding="utf-8") as f:
            if "SIL OPEN FONT LICENSE Version 1.1" not in f.read():
                issues.append("backend/assets/fonts/OFL.txt: Must contain SIL OPEN FONT LICENSE Version 1.1")

    for req_font in ("Inter-Regular.ttf", "Inter-Bold.ttf", "Inter-Italic.ttf"):
        if not os.path.exists(os.path.join(fonts_dir, req_font)):
            issues.append(f"backend/assets/fonts/{req_font}: Missing required bundled Inter TTF font")

    forbidden_font_markers = (
        b"Monotype",
        b"M\x00o\x00n\x00o\x00t\x00y\x00p\x00e",
        b"Microsoft Corporation",
        b"M\x00i\x00c\x00r\x00o\x00s\x00o\x00f\x00t",
    )
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__"}
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if fname.lower().endswith((".ttf", ".otf", ".woff", ".woff2")):
                fpath = os.path.join(root, fname)
                rel_fpath = os.path.relpath(fpath, PROJECT_ROOT)
                if fname.lower().startswith("arial"):
                    issues.append(f"{rel_fpath}: Proprietary Arial font file is prohibited in repository")
                with open(fpath, "rb") as bf:
                    raw = bf.read()
                for marker in forbidden_font_markers:
                    if marker in raw:
                        issues.append(f"{rel_fpath}: Binary font contains proprietary foundry copyright marker")
                        break

    # 6. Zero-CDN Offline POS Gate (no Google Fonts or external JS CDNs in frontend)
    chart_vendor = os.path.join(PROJECT_ROOT, "frontend", "vendor", "chart.umd.min.js")
    if not os.path.exists(chart_vendor):
        issues.append("frontend/vendor/chart.umd.min.js: Missing self-hosted Chart.js bundle")

    forbidden_cdn_hosts = (
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdn.jsdelivr.net",
        "unpkg.com",
        "cdnjs.cloudflare.com",
    )
    frontend_dir = os.path.join(PROJECT_ROOT, "frontend")
    for root, dirs, files in os.walk(frontend_dir):
        dirs[:] = [d for d in dirs if d not in {"node_modules", "vendor", "dist", "chunks"}]
        for fname in files:
            if fname.lower().endswith((".html", ".css", ".js", ".md")):
                fpath = os.path.join(root, fname)
                rel_fpath = os.path.relpath(fpath, PROJECT_ROOT)
                with open(fpath, "r", encoding="utf-8", errors="ignore") as tf:
                    content = tf.read()
                for cdn_host in forbidden_cdn_hosts:
                    if cdn_host in content:
                        issues.append(f"{rel_fpath}: Contains prohibited external CDN dependency '{cdn_host}'")
                disallowed_domains = os.getenv("FORBIDDEN_DOMAINS", "").split(",")
                for d in disallowed_domains:
                    d_clean = d.strip()
                    if d_clean and d_clean in content:
                        issues.append(f"{rel_fpath}: Contains disallowed internal domain '{d_clean}'")

    print(f"License & Legal Compliance Issues: {len(issues)}")
    for iss in issues:
        print(f"  [LEGAL_FAIL] {iss}")
    return len(issues)


if __name__ == "__main__":
    tmp_dir, temp_db_path = _bootstrap_temp_canonical_db()
    try:
        c_issues = audit_sql_columns(temp_db_path)
        a_issues, dup_issues = audit_api_endpoints()
        h_issues = audit_seed_and_launcher_hygiene()
        l_issues = audit_license_and_legal_compliance()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    total = c_issues + a_issues + dup_issues + h_issues + l_issues
    print("\n========================================================")
    print(
        f"CONTRACT AUDIT SUMMARY: SQL={c_issues}, Routes={a_issues}, "
        f"OpenAPI_Collisions={dup_issues}, Hygiene={h_issues}, Legal={l_issues} (Total={total})"
    )
    print("========================================================")
    sys.exit(1 if total > 0 else 0)
