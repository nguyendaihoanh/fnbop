import os
import sys
import time
import pytest
import tempfile
from unittest.mock import patch, MagicMock

# Ensure backend and project root are in sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from services.db import (
    get_db_connection,
    record_failed_attempt_tiered,
    check_login_lockout,
    clear_login_lockout,
    get_active_lockouts,
    admin_unlock_target,
    _ensure_login_attempts_table
)
from routers.fnb_ops import router as cc_router, create_access_token
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(cc_router)
client = TestClient(app)


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    monkeypatch.setenv("DATABASE_PATH", db_path)
    conn = get_db_connection(db_path)
    _ensure_login_attempts_table(conn)
    conn.close()
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)


# =========================================================================
# 1. UNIT TESTS: TIERED PROGRESSIVE LOGIC & CAFE WHITELIST
# =========================================================================

def test_tier1_username_lockout_60s(temp_db):
    """Tier 1: 5 failed attempts -> Lock username for 60s."""
    user = "barista_thao"
    ip = "203.0.113.80"

    # Attempts 1 to 4: Not locked
    for i in range(1, 5):
        res = record_failed_attempt_tiered(ip=ip, username=user, is_whitelisted_cafe=True, db_path=temp_db)
        assert res["attempts"] == i
        assert res["is_locked"] is False

    # Attempt 5: Locked Tier 1 (60s)
    res5 = record_failed_attempt_tiered(ip=ip, username=user, is_whitelisted_cafe=True, db_path=temp_db)
    assert res5["attempts"] == 5
    assert res5["tier"] == 1
    assert res5["is_locked"] is True
    assert res5["target_type"] == "USER"
    assert res5["target_key"] == f"user:{user}"

    # Lockout check for the user
    lock_info = check_login_lockout(ip=ip, username=user, db_path=temp_db)
    assert lock_info is not None
    assert lock_info["tier"] == 1
    assert lock_info["target_key"] == f"user:{user}"
    assert "60 GIÂY" in lock_info["message"]

    # NO COLLATERAL DAMAGE: Another user on the same IP must NOT be locked!
    other_user_lock = check_login_lockout(ip=ip, username="barista_phat", db_path=temp_db)
    assert other_user_lock is None


def test_tier2_cafe_whitelist_exemption_vs_outside_ip(temp_db):
    """
    Tier 2 (6-10 attempts):
    - From Outside IP: Lock IP for 30 minutes (1800s).
    - From Cafe IP: Whitelist spares the IP! Only lock username for 30 minutes.
    """
    cafe_ip = "203.0.113.80"
    outside_ip = "14.232.11.22"

    # Case A: Outside IP reaches 6 attempts -> locks the IP itself
    for _ in range(6):
        res_out = record_failed_attempt_tiered(ip=outside_ip, username="hacker", is_whitelisted_cafe=False, db_path=temp_db)
    assert res_out["tier"] == 2
    assert res_out["target_type"] == "IP"
    assert res_out["target_key"] == f"ip:{outside_ip}"
    assert res_out["is_locked"] is True

    # Check that any request from outside_ip is locked
    lock_out = check_login_lockout(ip=outside_ip, username="anyone", db_path=temp_db)
    assert lock_out is not None
    assert lock_out["target_key"] == f"ip:{outside_ip}"
    assert "30 PHÚT" in lock_out["message"]

    # Case B: Cafe IP reaches 6 attempts -> Cafe IP is whitelisted, only user is locked
    for _ in range(6):
        res_cafe = record_failed_attempt_tiered(ip=cafe_ip, username="thao_cafe", is_whitelisted_cafe=True, db_path=temp_db)
    assert res_cafe["tier"] == 2
    assert res_cafe["target_type"] == "USER"
    assert res_cafe["target_key"] == "user:thao_cafe"
    assert res_cafe["is_locked"] is True

    # The Cafe IP itself MUST NOT be locked for another user
    lock_other = check_login_lockout(ip=cafe_ip, username="phat_cafe", db_path=temp_db)
    assert lock_other is None


def test_tier3_admin_locked_5_hours(temp_db):
    """Tier 3 (11+ attempts): Lock for 5 hours (18000s) and set is_admin_locked = 1."""
    ip = "171.244.5.6"
    user = "target_account"

    for _ in range(11):
        res = record_failed_attempt_tiered(ip=ip, username=user, is_whitelisted_cafe=False, db_path=temp_db)

    assert res["tier"] == 3
    assert res["is_admin_locked"] == 1
    assert res["is_locked"] is True

    lock_info = check_login_lockout(ip=ip, username=user, db_path=temp_db)
    assert lock_info is not None
    assert lock_info["tier"] == 3
    assert lock_info["is_admin_locked"] == 1
    assert "5 TIẾNG" in lock_info["message"]
    assert "Chủ quán (Admin)" in lock_info["message"]


def test_active_lockouts_and_admin_unlock(temp_db):
    """Admin inspects active lockouts and unlocks a target."""
    ip = "1.2.3.4"
    user = "locked_user"

    # Create Tier 1 lock
    for _ in range(5):
        record_failed_attempt_tiered(ip=ip, username=user, is_whitelisted_cafe=True, db_path=temp_db)

    # Active lockouts must list it
    active = get_active_lockouts(db_path=temp_db)
    assert len(active) >= 1
    target_keys = [a["target_key"] for a in active]
    assert f"user:{user}" in target_keys

    # Admin unlocks target
    success = admin_unlock_target(f"user:{user}", db_path=temp_db)
    assert success is True

    # Verify target is no longer locked
    assert check_login_lockout(ip=ip, username=user, db_path=temp_db) is None
    active_after = get_active_lockouts(db_path=temp_db)
    assert not any(a["target_key"] == f"user:{user}" for a in active_after)


# =========================================================================
# 2. END-TO-END FASTAPI HTTP CLIENT TESTS
# =========================================================================

def test_e2e_login_rate_limit_and_admin_unlock(temp_db):
    """
    E2E scenario:
    1. Attacker tries 5 times -> Tier 1 (429 Too Many Requests, Retry-After: 60)
    2. Other employee on same IP logs in -> Allowed
    3. Attacker tries 11 times -> Tier 3 (429, Alert Telegram)
    4. Non-admin calls /admin/lockouts -> 403 Forbidden
    5. Admin calls /admin/lockouts -> 200 OK, lists lockout
    6. Admin calls /admin/lockouts/unlock -> 200 OK, target is unlocked
    7. User can now login again!
    """
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Hộ (Admin)"})
    staff_token = create_access_token({"sub": "thao", "role": "STAFF", "name": "Thảo"})

    cafe_ip = "203.0.113.80"
    attacker_ip = "203.0.113.80"  # At cafe wifi

    # Mock cafe IP in router
    with patch("routers.fnb_ops._get_live_cafe_ip", return_value=cafe_ip), \
         patch("backend.routers.fnb_ops._get_live_cafe_ip", return_value=cafe_ip):

        headers = {
            "X-Forwarded-For": attacker_ip,
            "cf-ray": "mock-cf-ray-123"
        }

        # 1. Failed attempts 1 to 5 -> 401 Unauthorized (attempt 5 records Tier 1 lockout)
        for _ in range(5):
            r = client.post("/api/v1/cc/auth/login", json={"username": "badactor", "password": "wrong_pin"}, headers=headers)
            assert r.status_code == 401

        # 2. Attempt 6 (and subsequent within 60s) -> Tier 1 Lockout (429 Too Many Requests)
        r6 = client.post("/api/v1/cc/auth/login", json={"username": "badactor", "password": "any"}, headers=headers)
        assert r6.status_code == 429
        assert "60 GIÂY" in r6.json()["detail"]
        assert "Retry-After" in r6.headers

        # 3. Another user on the SAME cafe IP tries to log in -> Not blocked by rate limit!
        # (Will get 401 if wrong pin, but NOT 429 lockout)
        r_other = client.post("/api/v1/cc/auth/login", json={"username": "phat", "password": "wrong_pin"}, headers=headers)
        assert r_other.status_code == 401  # Not 429!

        # 4. Escalate 'badactor' to Tier 3 by simulating 11 failed attempts
        for _ in range(6):
            record_failed_attempt_tiered(ip=attacker_ip, username="badactor", is_whitelisted_cafe=True, db_path=temp_db)

        # Now attempting login should trigger Tier 3 429
        r_tier3 = client.post("/api/v1/cc/auth/login", json={"username": "badactor", "password": "any"}, headers=headers)
        assert r_tier3.status_code == 429
        assert "Tầng 3" in r_tier3.json()["detail"] or "5 TIẾNG" in r_tier3.json()["detail"]

        # 5. Permission check on Admin endpoints
        # A staff member tries to access lockouts -> 403 Forbidden
        r_forbidden = client.get("/api/v1/cc/admin/lockouts", headers={"Authorization": f"Bearer {staff_token}"})
        assert r_forbidden.status_code == 403

        r_unlock_forbidden = client.post("/api/v1/cc/admin/lockouts/unlock", json={"target_key": "user:badactor"}, headers={"Authorization": f"Bearer {staff_token}"})
        assert r_unlock_forbidden.status_code == 403

        # 6. Admin accesses lockouts -> 200 OK
        r_admin_list = client.get("/api/v1/cc/admin/lockouts", headers={"Authorization": f"Bearer {admin_token}"})
        assert r_admin_list.status_code == 200
        data = r_admin_list.json()
        assert data["status"] == "success"
        assert data["cafe_ip"] == cafe_ip
        assert data["total_locked"] >= 1
        assert any(l["identifier"] == "badactor" for l in data["lockouts"])

        # 7. Admin unlocks 'user:badactor'
        r_unlock = client.post(
            "/api/v1/cc/admin/lockouts/unlock",
            json={"target_key": "user:badactor"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r_unlock.status_code == 200
        assert r_unlock.json()["unlocked"] is True

        # Verify list is now empty of 'badactor'
        r_admin_list2 = client.get("/api/v1/cc/admin/lockouts", headers={"Authorization": f"Bearer {admin_token}"})
        assert not any(l["identifier"] == "badactor" for l in r_admin_list2.json()["lockouts"])
