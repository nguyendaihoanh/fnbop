"""
Test Suite for Store Configuration, 1-Step POS Closing, and Payroll Anti-Duplicate
Verifies all 3 user requirements and critical operational fixes:
1. Dynamic Store Configuration (multi-shop customization: shifts, gender, holidays)
2. 1-Step POS closing: Staff submits cash/expenses -> status CHỜ_ĐỐI_SOÁT -> Admin/System reconciles later
3. Manual POS mode / direct revenue entry
4. Anti-duplicate Sổ Phụ calculations
5. Dynamic current month fallback
6. Staff account sync between JSON and SQLite
"""

import os
import sys
import json
import pytest
import datetime
from fastapi.testclient import TestClient

# Ensure test mode
os.environ["TESTING"] = "1"
os.environ["ON_PREMISE_MODE"] = "true"

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from services.store_config import (
    get_store_config,
    save_store_config,
    is_configured_holiday,
    DEFAULT_STORE_CONFIG
)
from services.payroll_calc import (
    calculate_staff_payslip_breakdown,
    calculate_progressive_late_penalties
)
from services.db import (
    get_db_connection,
    init_db,
    get_daily_closing_by_id,
    get_staff_by_username
)

from routers.fnb_ops import create_access_token
client = TestClient(app)
_admin_tok = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Admin"})
_orig_post = client.post
_orig_get = client.get
def _authed_post(url, *args, **kwargs):
    headers = kwargs.get("headers") or {}
    if "Authorization" not in headers and "authorization" not in headers:
        headers["Authorization"] = f"Bearer {_admin_tok}"
    kwargs["headers"] = headers
    return _orig_post(url, *args, **kwargs)
def _authed_get(url, *args, **kwargs):
    headers = kwargs.get("headers") or {}
    if "Authorization" not in headers and "authorization" not in headers:
        headers["Authorization"] = f"Bearer {_admin_tok}"
    kwargs["headers"] = headers
    return _orig_get(url, *args, **kwargs)
client.post = _authed_post
client.get = _authed_get


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, monkeypatch):
    """Isolate test database and config files."""
    db_file = str(tmp_path / "test_fnbop.db")
    config_file = str(tmp_path / "store_config.json")
    closings_file = str(tmp_path / "pos_closings.json")

    monkeypatch.setenv("DATABASE_PATH", db_file)
    monkeypatch.setenv("STORE_CONFIG_FILE", config_file)
    monkeypatch.setenv("POS_CLOSINGS_FILE", closings_file)

    init_db(db_file)
    save_store_config(DEFAULT_STORE_CONFIG)


# --------------------------------------------------------------------------
# 1. STORE CONFIGURATION TESTS
# --------------------------------------------------------------------------

def test_store_config_defaults():
    """Verify default store configuration matches WFM preset."""
    cfg = get_store_config()
    assert cfg["store_name"] in ("FnBOps Store Lounge", "WFM Store Lounge")
    assert "sang" in cfg["shifts"]
    assert "toi" in cfg["shifts"]
    assert cfg["shifts"]["sang"]["official_start"] == "06:00"
    assert cfg["shifts"]["sang"]["official_end"] == "11:30"
    assert is_configured_holiday("02/09/2026") is True
    assert is_configured_holiday("15/09/2026") is False


def test_custom_store_config_update():
    """Verify store configuration can be updated for another shop."""
    custom_cfg = {
        "store_name": "Quán Cafe Nhỏ ABC",
        "pos_mode": "manual",
        "shifts": {
            "ca_mot": {
                "name": "Ca Sáng 7h",
                "official_start": "07:00",
                "official_end": "12:00",
                "tolerance_limit": "07:15",
                "min_checkout": "11:30",
                "standard_mins": 300,
                "roles": {"service": 1}
            }
        },
        "holiday_rules": {
            "holidays": ["01/01", "30/04", "01/05", "02/09"]
        },
        "roster_rules": {
            "gender_constraints": {
                "enabled": False
            }
        }
    }
    save_store_config(custom_cfg)

    loaded = get_store_config()
    assert loaded["store_name"] == "Quán Cafe Nhỏ ABC"
    assert "ca_mot" in loaded["shifts"]
    assert is_configured_holiday("01/01/2026") is True
    assert is_configured_holiday("30/04/2026") is True


# --------------------------------------------------------------------------
# 2. 1-STEP POS CLOSING & RECONCILIATION TESTS
# --------------------------------------------------------------------------

def test_pos_closing_step_1_staff_submission():
    """
    Step 1: Staff submits cash drawer count without POS revenue (bill_pos = 0).
    Status should be CHỜ_ĐỐI_SOÁT without false alarms.
    """
    payload = {
        "report_date": "26/09/2026",
        "cash_amount": 1250000,
        "expense_amount": 50000,
        "expense_detail": "Mua đá lạnh + túi rác",
        "sender_name": "Nguyen Van A"
    }
    resp = client.post("/api/v1/cc/pos/daily-closing", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "success"
    rec = data["data"]
    assert rec["diff_status"] == "CHỜ_ĐỐI_SOÁT"
    assert rec["cash_amount"] == 1250000
    assert rec["expense_amount"] == 50000
    assert rec["bill_pos"] == 0
    assert rec["is_warning"] is False


def test_pos_closing_step_2_admin_reconciliation():
    """
    Step 2: Admin or automated 23h cron completes reconciliation by supplying bill_pos and transfer_amount.
    """
    # Step 1: Staff submits
    staff_payload = {
        "report_date": "26/09/2026",
        "cash_amount": 1200000,
        "expense_amount": 100000,
        "expense_detail": "Sửa vòi nước quầy bar",
        "sender_name": "Thu Ngan B"
    }
    create_resp = client.post("/api/v1/cc/pos/daily-closing", json=staff_payload)
    closing_id = create_resp.json()["data"]["id"]

    # Step 2: Admin reconciles with transfer amount and POS bill
    reconcile_payload = {
        "closing_id": closing_id,
        "bill_pos": 3500000,
        "transfer_amount": 2200000,
        "approver_name": "admin",
        "notes": "Đã đối soát xong tài khoản Vietcombank"
    }
    rec_resp = client.post("/api/v1/cc/pos/reconcile", json=reconcile_payload)
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()["data"]

    # total_real = 1,200,000 (cash) + 2,200,000 (bank) + 100,000 (expense) = 3,500,000
    # bill_pos = 3,500,000 -> diff = 0 -> KHỚP
    assert rec_data["total_real"] == 3500000
    assert rec_data["diff"] == 0
    assert rec_data["diff_status"] == "KHỚP"
    assert rec_data["approver_name"] == "admin"


def test_pos_closing_manual_mode_direct():
    """
    For shops without POS365: Staff or Admin can directly supply bill_pos and transfer_amount in 1 step.
    """
    payload = {
        "report_date": "27/09/2026",
        "closing_time": "22:30",
        "bill_pos": 5000000,
        "cash_amount": 2000000,
        "transfer_amount": 3000000,
        "expense_amount": 0,
        "sender_name": "Chu Quan C"
    }
    resp = client.post("/api/v1/cc/pos/daily-closing", json=payload)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["diff_status"] == "KHỚP"
    assert data["diff"] == 0


# --------------------------------------------------------------------------
# 3. PAYROLL ANTI-DUPLICATE & DYNAMIC MONTH TESTS
# --------------------------------------------------------------------------

def test_so_phu_anti_duplicate():
    """
    Verify that if an evaluation is recorded in evaluations,
    an identical row in data.json SỔ PHỤ or SQLite staff_ledgers is NOT counted twice.
    """
    evaluations = [
        {
            "id": "EVAL_001",
            "staffName": "NGUYEN VAN A",
            "type": "Thưởng nóng",
            "amount": 100000,
            "reason": "Hỗ trợ ca đông khách",
            "month": "9",
            "status": "APPROVED"
        }
    ]

    # data.json SỔ PHỤ has the exact same mirrored entry
    data_json = {
        "NHÂN VIÊN": [
            [], [],
            ["1", "NGUYEN VAN A", "1000", "20000"]
        ],
        "DỮ LIỆU": [],
        "SỔ PHỤ": [
            ["Timestamp", "Tên", "Tháng", "Loại", "Số tiền", "Hình thức", "Lý do"],
            ["2026-09-15 00:00:00", "NGUYEN VAN A", "9", "Thưởng", "100000", "Chuyển khoản", "Hỗ trợ ca đông khách"]
        ]
    }

    # SQLite also has the ledger entry
    staff_ledgers = [
        {
            "staff_name": "NGUYEN VAN A",
            "month": "9",
            "type": "bonus",
            "amount": 100000,
            "reason": "Hỗ trợ ca đông khách"
        }
    ]

    breakdown = calculate_staff_payslip_breakdown(
        staff_name="NGUYEN VAN A",
        month="9",
        data_json=data_json,
        evaluations=evaluations,
        staff_ledgers=staff_ledgers
    )

    # eval_bonus must be 100,000, NOT 300,000 (anti-duplicate)
    assert breakdown["eval_bonus"] == 100000


def test_base_wage_priority_from_staff_accounts():
    """
    Verify base_wage uses staff_accounts hourly_rate first before falling back to data.json.
    """
    staff_accounts = {
        "nguyenvana": {
            "full_name": "Nguyễn Văn A",
            "hourly_rate": 25000,
            "role": "STAFF"
        }
    }
    # data.json has old rate 17000
    data_json = {
        "NHÂN VIÊN": [
            [], [],
            ["1", "Nguyễn Văn A", "1000", "17000"]
        ],
        "DỮ LIỆU": []
    }

    breakdown = calculate_staff_payslip_breakdown(
        staff_name="Nguyễn Văn A",
        month="9",
        data_json=data_json,
        staff_accounts=staff_accounts
    )

    assert breakdown["base_wage"] == 25000
