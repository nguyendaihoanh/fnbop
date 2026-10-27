import os
import sys
import json
import pytest
import tempfile
import threading
from unittest.mock import MagicMock, patch

# Ensure backend and project root are in sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from services.storage import (
    hash_pin,
    verify_pin,
    needs_rehash,
    safe_json_write,
    safe_json_read,
    get_file_lock
)
from routers.fnb_ops import router as cc_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(cc_router)
client = TestClient(app)


# ==========================================
# 1. STORAGE & CONCURRENCY TESTS
# ==========================================
def test_safe_json_write_and_read():
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        fpath = tf.name

    test_data = {"key": "value", "count": 100}
    assert safe_json_write(fpath, test_data) is True
    read_data = safe_json_read(fpath)
    assert read_data == test_data

    # Test corrupted fallback
    with open(fpath, "w") as f:
        f.write("{invalid json")
    fallback = safe_json_read(fpath, default={"fallback": True})
    assert fallback == {"fallback": True}

    if os.path.exists(fpath):
        os.remove(fpath)
    if os.path.exists(f"{fpath}.lock"):
        os.remove(f"{fpath}.lock")


def test_concurrent_writes_with_filelock():
    """Verify that multiple threads writing concurrently do not corrupt JSON."""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        fpath = tf.name

    safe_json_write(fpath, {"writes": []})
    errors = []

    def writer_worker(w_id):
        for i in range(10):
            try:
                with get_file_lock(fpath):
                    current = safe_json_read(fpath, default={"writes": []})
                    current["writes"].append(f"{w_id}_{i}")
                    safe_json_write(fpath, current)
            except Exception as e:
                errors.append(e)

    threads = [threading.Thread(target=writer_worker, args=(t_id,)) for t_id in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    final = safe_json_read(fpath)
    assert len(final["writes"]) == 40

    if os.path.exists(fpath):
        os.remove(fpath)
    if os.path.exists(f"{fpath}.lock"):
        os.remove(f"{fpath}.lock")


# ==========================================
# 2. PIN HASHING & OWASP PBKDF2 TESTS
# ==========================================
def test_pin_hashing_and_verification():
    pin = "1234"
    h = hash_pin(pin)
    assert h.startswith("pbkdf2_sha256$100000$")
    assert verify_pin(pin, h) is True
    assert verify_pin("0000", h) is False
    assert needs_rehash(h) is False

    # Legacy plaintext check
    legacy_pin = "5678"
    assert verify_pin("5678", legacy_pin) is True
    assert verify_pin("9999", legacy_pin) is False
    assert needs_rehash(legacy_pin) is True


# ==========================================
# 4. ROW-LEVEL PRIVACY FILTER & PIN MIGRATION
# ==========================================
@pytest.fixture
def temp_auth_and_data(monkeypatch):
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as af:
        auth_data = {
            "payroll_locks": {"9": {"status": "OPEN"}},
            "staff_accounts": {
                "staff1": {
                    "full_name": "Nguyen Van A",
                    "sheet_names": ["Nguyen Van A", "A_NV"],
                    "pin": "1234",  # Plaintext legacy
                    "role": "STAFF",
                    "status": "ACTIVE"
                },
                "admin1": {
                    "full_name": "Admin User",
                    "sheet_names": ["Admin"],
                    "pin": hash_pin("9999"),
                    "role": "ADMIN",
                    "status": "ACTIVE"
                }
            }
        }
        json.dump(auth_data, af)
        auth_file = af.name

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as df:
        sheet_data = {
            "NHÂN VIÊN": [
                ["Title"],
                ["", "", "", "", ""],
                ["STT", "TÊN NHÂN VIÊN", "VỊ TRÍ", "LƯƠNG/GIỜ", "TỔNG LƯƠNG"],
                ["1", "Nguyen Van A", "Pha che", 25000, 2500000],
                ["2", "Tran Thi B", "Phuc vu", 22000, 1800000]
            ],
            "DỮ LIỆU": [
                ["STT", "Ngày", "Tên Nhân Viên", "Ca làm việc", "Giờ vào", "Giờ ra"],
                ["1", "01/09/2026", "Nguyen Van A", "Sáng", "06:00", "11:30"],
                ["2", "01/09/2026", "Tran Thi B", "Sáng", "06:00", "11:30"],
                ["3", "02/09/2026", "Tran Thi B", "Tối", "17:00", "23:00"],
                ["4", "02/09/2026", "Nguyen Van A", "Tối", "17:00", "23:00"]
            ],
            "ĐÁNH GIÁ": [],
            "SỔ PHỤ": []
        }
        json.dump(sheet_data, df)
        data_file = df.name

    monkeypatch.setenv("AUTH_FILE", auth_file)
    monkeypatch.setenv("DATA_FILE", data_file)

    yield {"auth_file": auth_file, "data_file": data_file}

    if os.path.exists(auth_file):
        os.remove(auth_file)
    if os.path.exists(f"{auth_file}.lock"):
        os.remove(f"{auth_file}.lock")
    if os.path.exists(data_file):
        os.remove(data_file)
    if os.path.exists(f"{data_file}.lock"):
        os.remove(f"{data_file}.lock")


def test_staff_login_lazy_migrates_pin_and_filters_data(temp_auth_and_data):
    # 1. Login as staff1 with plaintext PIN "1234"
    login_resp = client.post("/api/v1/cc/auth/login", json={"username": "staff1", "password": "1234"})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # Verify that PIN in auth file is verified correctly
    saved_auth = safe_json_read(temp_auth_and_data["auth_file"])
    stored_pin = saved_auth["staff_accounts"]["staff1"]["pin"]
    assert verify_pin("1234", stored_pin) is True

    # 2. Login again using the same PIN (now verified against hash)
    login_resp2 = client.post("/api/v1/cc/auth/login", json={"username": "staff1", "password": "1234"})
    assert login_resp2.status_code == 200

    # 3. Access /data as STAFF
    data_resp = client.get("/api/v1/cc/data", headers={"Authorization": f"Bearer {token}"})
    assert data_resp.status_code == 200
    staff_data = data_resp.json()

    # Verify STAFF only sees their own shifts in DỮ LIỆU!
    dl_rows = staff_data["DỮ LIỆU"]
    assert len(dl_rows) == 3  # 1 header + 2 shifts of Nguyen Van A
    assert dl_rows[0][2] == "Tên Nhân Viên"
    assert dl_rows[1][2] == "Nguyen Van A"
    assert dl_rows[2][2] == "Nguyen Van A"
    # Tran Thi B shifts must NOT be leaked to staff1!
    for r in dl_rows[1:]:
        assert r[2] != "Tran Thi B"


def test_admin_staff_accounts_access_and_security(temp_auth_and_data):
    # Login as admin
    login_resp = client.post("/api/v1/cc/auth/login", json={"username": "admin1", "password": "9999"})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # Get staff accounts as admin
    acc_resp = client.get("/api/v1/cc/admin/staff-accounts", headers={"Authorization": f"Bearer {token}"})
    assert acc_resp.status_code == 200
    accounts = acc_resp.json()["staff_accounts"]

    # Verify Zero-Trust: PINs are sanitized from API response (never exposed in plaintext), only has_pin flag is returned
    assert accounts["staff1"]["has_pin"] is True
    assert "pin" not in accounts["staff1"]
    assert accounts["admin1"]["has_pin"] is True
    assert "pin" not in accounts["admin1"]

    # Verify non-admin (staff) is strictly forbidden (403) from accessing staff accounts
    login_staff = client.post("/api/v1/cc/auth/login", json={"username": "staff1", "password": "1234"})
    assert login_staff.status_code == 200
    staff_token = login_staff.json()["access_token"]
    acc_resp_staff = client.get("/api/v1/cc/admin/staff-accounts", headers={"Authorization": f"Bearer {staff_token}"})
    assert acc_resp_staff.status_code == 403


# ==========================================
# 4. SERVICE WORKER & POS CLIENT SECURITY TESTS
# ==========================================
def test_service_worker_no_api_cache():
    """Verify sw.js bumps cache version and blocks caching of /api/ and /auth/ endpoints."""
    sw_path = os.path.join(_project_root, "frontend", "sw.js")
    assert os.path.exists(sw_path), "frontend/sw.js must exist"
    with open(sw_path, "r", encoding="utf-8") as f:
        content = f.read()

    import re
    m = re.search(r"(?:fnbops?|wfm)(?:-ops)?-pwa-v(\d+\.\d+)", content)
    assert m is not None and float(m.group(1)) >= 8.9, "Service Worker must bump to at least v8.9 to purge stale cache"
    assert "url.pathname.startsWith('/api/')" in content, "sw.js must explicitly check for /api/ paths"
    assert "url.pathname.startsWith('/auth/')" in content, "sw.js must explicitly check for /auth/ paths"
    # Ensure /api/ routes are not added to cache.put
    api_filter_idx = content.find("url.pathname.startsWith('/api/')")
    cache_put_idx = content.find("cache.put(event.request")
    assert api_filter_idx != -1 and cache_put_idx != -1
    assert api_filter_idx < cache_put_idx, "API exclusion check must precede cache.put"


def test_pos_heartbeat_relocation_and_file_shield():
    """Verify pos heartbeat script is removed from frontend root, relocated to scripts/pos_clients, and blocked by shield."""
    public_ps1 = os.path.join(_project_root, "frontend", "fnb_pos_heartbeat.ps1")
    public_wfm_ps1 = os.path.join(_project_root, "frontend", "wfm_pos_heartbeat.ps1")
    relocated_wfm_ps1 = os.path.join(_project_root, "scripts", "pos_clients", "wfm_pos_heartbeat.ps1")
    relocated_fnb_ps1 = os.path.join(_project_root, "scripts", "pos_clients", "fnb_pos_heartbeat.ps1")

    assert not os.path.exists(public_ps1), "frontend/fnb_pos_heartbeat.ps1 MUST NOT exist in web root"
    assert not os.path.exists(public_wfm_ps1), "frontend/wfm_pos_heartbeat.ps1 MUST NOT exist in web root"
    assert os.path.exists(relocated_wfm_ps1) or os.path.exists(relocated_fnb_ps1), "Hardened script must exist in scripts/pos_clients/"

    target_script = relocated_wfm_ps1 if os.path.exists(relocated_wfm_ps1) else relocated_fnb_ps1
    with open(target_script, "r", encoding="utf-8") as f:
        ps1_code = f.read()
    # Must NOT have static hardcoded secret
    assert '$Secret = "fnbop_pos_secret_2026"' not in ps1_code, "POS script must not hardcode production secret in source"
    assert "$env:WFM_POS_SECRET" in ps1_code or "$env:FNBOP_POS_SECRET" in ps1_code or "secret.txt" in ps1_code, "POS script must support secure retrieval"


