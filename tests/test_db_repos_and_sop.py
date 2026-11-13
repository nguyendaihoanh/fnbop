"""
Unit tests for DB repository transaction atomicity, tiered lockout persistence,
notification/roster repositories, and SOP template loading.
"""

import os
import tempfile
import pytest

from backend.services.db.schema import init_db
from backend.services.db import payroll_repo, security_repo, notification_repo, roster_repo
from backend.services import sop_service


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    init_db(db_path)
    yield db_path

    for ext in ["", "-wal", "-shm"]:
        p = f"{db_path}{ext}"
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_delete_staff_ledger_atomic_rollback_on_reversal_failure(temp_db, monkeypatch):
    entry = {
        "id": "ldg-atomic-01",
        "staff_name": "Nhân Viên Test",
        "month": "2026-11",
        "type": "advance",
        "amount": 500000,
        "payment_method": "cash",
        "reason": "Tạm ứng giữa tháng",
        "created_by": "admin",
    }
    payroll_repo.insert_staff_ledger(entry, tenant_id="default", db_path=temp_db)

    def _boom(*args, **kwargs):
        raise RuntimeError("Simulated so_cai_luong write failure")

    monkeypatch.setattr(payroll_repo, "_record_so_cai_luong_with_cur", _boom)

    with pytest.raises(RuntimeError, match="Simulated so_cai_luong write failure"):
        payroll_repo.delete_staff_ledger(
            "ldg-atomic-01",
            tenant_id="default",
            deleted_by="admin",
            db_path=temp_db,
        )

    # Transaction must have rolled back completely: entry remains active & no reversal row
    persisted = payroll_repo.get_staff_ledger_by_id(
        "ldg-atomic-01", tenant_id="default", db_path=temp_db
    )
    assert persisted is not None
    assert persisted["is_deleted"] == 0
    assert persisted.get("deleted_at") is None
    assert (
        payroll_repo.list_so_cai_luong(
            staff_name="Nhân Viên Test", tenant_id="default", db_path=temp_db
        )
        == []
    )


@pytest.mark.parametrize(
    "ledger_type,amount,expected_event",
    [
        ("advance", 200000, "HUY_UNG_LUONG"),
        ("bonus", 150000, "HUY_THUONG"),
        ("deduction", 50000, "HUY_PHAT"),
    ],
)
def test_delete_staff_ledger_happy_path_records_reversal(
    temp_db, ledger_type, amount, expected_event
):
    ledger_id = f"ldg-{ledger_type}-01"
    payroll_repo.insert_staff_ledger(
        {
            "id": ledger_id,
            "staff_name": "Pha Chế A",
            "month": "2026-11",
            "type": ledger_type,
            "amount": amount,
            "reason": "Test reversal",
            "created_by": "admin",
        },
        tenant_id="default",
        db_path=temp_db,
    )

    ok = payroll_repo.delete_staff_ledger(
        ledger_id, tenant_id="default", deleted_by="admin", db_path=temp_db
    )
    assert ok is True

    deleted = payroll_repo.get_staff_ledger_by_id(
        ledger_id, tenant_id="default", db_path=temp_db
    )
    assert deleted is not None
    assert deleted["is_deleted"] == 1
    assert deleted["deleted_by"] == "admin"

    reversals = payroll_repo.list_so_cai_luong(
        staff_name="Pha Chế A", tenant_id="default", db_path=temp_db
    )
    assert len(reversals) == 1
    assert reversals[0]["loai_su_kien"] == expected_event
    assert reversals[0]["so_tien_thay_doi"] == -amount


def test_security_repo_tiered_lockout_lifecycle(temp_db):
    ip = "203.0.113.42"
    username = "nhanvien_test"

    # Attempts 1..4 stay unlocked; attempt 5 hits Tier 1 lock (60s)
    for i in range(4):
        res = security_repo.record_failed_attempt_tiered(
            ip=ip, username=username, db_path=temp_db
        )
        assert res.get("is_locked") is False, f"unexpected lock on attempt {i + 1}"

    t1 = security_repo.record_failed_attempt_tiered(
        ip=ip, username=username, db_path=temp_db
    )
    assert t1.get("is_locked") is True
    assert t1.get("tier") == 1
    assert security_repo.check_login_lockout(ip, username, db_path=temp_db)["tier"] == 1

    # Attempts 6..10 hit Tier 2 lock (30 mins)
    for _ in range(4):
        security_repo.record_failed_attempt_tiered(
            ip=ip, username=username, db_path=temp_db
        )
    t2 = security_repo.record_failed_attempt_tiered(
        ip=ip, username=username, db_path=temp_db
    )
    assert t2.get("is_locked") is True
    assert t2.get("tier") == 2

    # Attempt 11 triggers Tier 3 admin lock
    t3 = security_repo.record_failed_attempt_tiered(
        ip=ip, username=username, db_path=temp_db
    )
    assert t3.get("is_locked") is True
    assert t3.get("tier") == 3
    assert t3.get("is_admin_locked") == 1

    lockout = security_repo.check_login_lockout(ip, username, db_path=temp_db)
    assert lockout is not None
    assert lockout["is_admin_locked"] == 1
    assert len(security_repo.get_active_lockouts(db_path=temp_db)) >= 1

    # Admin unlock clears lockout state (unlocking target deletes associated rows by ip/username)
    assert security_repo.admin_unlock_target(f"user:{username}", db_path=temp_db) is True
    assert security_repo.check_login_lockout(ip, username, db_path=temp_db) is None


def test_notification_repo_push_dispatch_and_in_app_reminders(temp_db):
    endpoint = "https://push.example.invalid/sub/abc"
    saved = notification_repo.save_push_subscription_db(
        username="phache",
        endpoint=endpoint,
        p256dh="key_p256dh",
        auth="key_auth",
        user_agent="pytest-agent",
        db_path=temp_db,
    )
    assert saved["status"] == "ok"

    subs = notification_repo.list_push_subscriptions_db(username="phache", db_path=temp_db)
    assert len(subs) == 1
    assert subs[0]["endpoint"] == endpoint

    assert notification_repo.deactivate_push_subscription_db(endpoint, db_path=temp_db) is True
    assert notification_repo.list_push_subscriptions_db(username="phache", db_path=temp_db) == []

    dedup = "SHIFT_REMIND:phache:2026-11-13:CA1"
    assert notification_repo.has_notification_dispatched_db(dedup, db_path=temp_db) is False
    notification_repo.record_notification_dispatch_db(
        dedup_key=dedup,
        notification_type="SHIFT_REMINDER",
        username="phache",
        title="Nhắc vào ca",
        body="Chuẩn bị vào ca",
        status="SENT",
        response_code=201,
        db_path=temp_db,
    )
    assert notification_repo.has_notification_dispatched_db(dedup, db_path=temp_db) is True

    # Deduplicating unread reminder update + acknowledgement
    r1 = notification_repo.save_in_app_reminder_db(
        username="phache",
        remind_type="CHECKIN_SOON",
        title="Nhắc chấm công",
        message="Vui lòng check-in đúng giờ",
        url="/",
        db_path=temp_db,
    )
    r2 = notification_repo.save_in_app_reminder_db(
        username="phache",
        remind_type="CHECKIN_SOON",
        title="Nhắc chấm công cập nhật",
        message="Còn 5 phút tới ca",
        url="/",
        db_path=temp_db,
    )
    assert r1 == r2

    active = notification_repo.list_active_in_app_reminders_db("phache", db_path=temp_db)
    assert len(active) == 1
    assert active[0]["title"] == "Nhắc chấm công cập nhật"

    assert notification_repo.ack_in_app_reminder_db(r1, "phache", db_path=temp_db) is True
    assert notification_repo.list_active_in_app_reminders_db("phache", db_path=temp_db) == []

    notification_repo.save_in_app_reminder_db(
        username="phache",
        remind_type="PAYSLIP_READY",
        title="Phiếu lương tháng 11",
        message="Đã sẵn sàng",
        db_path=temp_db,
    )
    assert notification_repo.ack_all_in_app_reminders_db("phache", db_path=temp_db) == 1
    assert notification_repo.list_active_in_app_reminders_db("phache", db_path=temp_db) == []


def test_roster_repo_upsert_get_and_list(temp_db):
    assert roster_repo.upsert_roster_schedule_db("", {}, db_path=temp_db) is False

    week_data = {
        "status": "published",
        "days": {"2026-11-16": {"CA_SANG": ["phache"]}},
        "registrations": {"phache": ["CA_SANG"]},
    }
    assert (
        roster_repo.upsert_roster_schedule_db("2026-W47", week_data, db_path=temp_db)
        is True
    )

    fetched = roster_repo.get_roster_schedule_db("2026-W47", db_path=temp_db)
    assert fetched is not None
    assert fetched["week_id"] == "2026-W47"
    assert fetched["status"] == "PUBLISHED"
    assert fetched["registrations"] == {"phache": ["CA_SANG"]}

    all_weeks = roster_repo.list_roster_schedules_db(db_path=temp_db)
    assert "2026-W47" in all_weeks
    assert all_weeks["2026-W47"]["days"]["2026-11-16"]["CA_SANG"] == ["phache"]


def test_sop_service_normalization_and_loading(monkeypatch):
    data = sop_service.load_sop_templates()
    roles_map = data.get("roles", {})
    assert "pha_che" in roles_map
    assert sop_service.normalize_sop_role("Pha chế", roles_map) == "pha_che"
    assert sop_service.normalize_sop_role("Thu ngân", roles_map) == "thu_ngan"
    assert sop_service.normalize_sop_role("Trưởng ca", roles_map) == "truong_ca"
    assert sop_service.normalize_sop_role("Sân vườn", roles_map) == "phuc_vu_san_vuon"
    assert sop_service.normalize_sop_role(None, roles_map) == "phuc_vu_trong_nha"

    res = sop_service.get_sop_by_role("Pha chế")
    assert res["status"] == "success"
    assert res["role_key"] == "pha_che"
    assert len(res["available_roles"]) >= 5

    monkeypatch.setattr(sop_service, "load_sop_templates", lambda: {})
    err = sop_service.get_sop_by_role("pha_che")
    assert err["status"] == "error"
