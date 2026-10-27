# -*- coding: utf-8 -*-
"""
Standalone Test Suite for Phase 3:
Immutable Shift Configuration Versioning & Authoritative Ledger Safeguards (ADR-007, ADR-011)

Verifies:
1. ShiftConfig Versioning: Preserves historical shift parameters when store edits shifts mid-month.
2. Historical standard duration lookup via get_shift_config_at and get_shift_standard_mins.
3. Immutable Ledger (so_cai_luong) double-entry accounting (POSTING + REVERSAL).
4. Deduction Cap Safeguard (30-50% gross wage cap, no negative net salary, debt carry-forward).
5. Offboarding Gate verification for resigning staff with uncollected debt.
6. REST API security & payload for GET /api/v1/cc/admin/staff-offboarding-status.
"""

import os
import sys
import json
import copy
from datetime import datetime, timedelta

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

from backend.services.store_config import (
    DEFAULT_STORE_CONFIG,
    get_store_config,
    save_store_config,
    get_shift_config_at,
    get_shift_by_alias,
    get_shift_standard_mins as get_store_std_mins
)
from backend.services.payroll_calc import (
    get_shift_standard_mins as get_payroll_std_mins,
    calculate_staff_payslip_breakdown,
    check_staff_offboarding_status
)
from backend.services.auth import create_access_token
from main import app

client = TestClient(app)


def test_1_shift_config_immutable_versioning():
    """Verify that updating shifts mid-month archives previous version into shift_versions."""
    tenant = "test_store_phase3"
    
    # 1. Start with initial config (Ca Tối 17:00 - 23:00, 360 mins)
    init_cfg = copy.deepcopy(DEFAULT_STORE_CONFIG)
    init_cfg["shift_valid_from"] = "2026-01-01T00:00:00"
    init_cfg["shifts"]["toi"]["standard_mins"] = 360
    init_cfg["shifts"]["toi"]["official_start"] = "17:00"
    save_store_config(init_cfg, tenant_id=tenant)

    loaded_1 = get_store_config(tenant_id=tenant)
    assert loaded_1["shifts"]["toi"]["standard_mins"] == 360
    assert len(loaded_1.get("shift_versions", [])) == 0

    # 2. Update shift config on mid-month date (e.g. changing Ca Tối to 300 mins)
    updated_cfg = copy.deepcopy(loaded_1)
    updated_cfg["shifts"]["toi"]["standard_mins"] = 300
    updated_cfg["shifts"]["toi"]["official_start"] = "18:00"
    save_store_config(updated_cfg, tenant_id=tenant)

    loaded_2 = get_store_config(tenant_id=tenant)
    assert loaded_2["version"] == 2
    assert len(loaded_2["shift_versions"]) == 1
    archived_v1 = loaded_2["shift_versions"][0]
    assert archived_v1["version"] == 1
    assert archived_v1["shifts"]["toi"]["standard_mins"] == 360
    assert loaded_2["shifts"]["toi"]["standard_mins"] == 300

    # 3. Lookup past date -> must return archived 360 mins
    past_shift = get_shift_config_at("2026-01-10", shift_key="toi", tenant_id=tenant)
    assert past_shift is not None
    assert past_shift["standard_mins"] == 360

    # 4. Lookup future date -> must return current 300 mins
    future_shift = get_shift_config_at("2026-12-01", shift_key="toi", tenant_id=tenant)
    assert future_shift is not None
    assert future_shift["standard_mins"] == 300


def test_2_payroll_standard_mins_date_awareness():
    """Verify get_shift_standard_mins correctly resolves duration based on shift date."""
    tenant = "test_store_phase3"
    
    # Past date (under version 1)
    mins_past = get_store_std_mins("toi", date_str="2026-01-10", tenant_id=tenant)
    assert mins_past == 360

    # Future date (under version 2)
    mins_future = get_store_std_mins("toi", date_str="2026-12-01", tenant_id=tenant)
    assert mins_future == 300


def test_3_so_cai_luong_reversal_accounting():
    """Verify double-entry posting and reversal in immutable ledger does not drift net pay."""
    staff_name = "Nguyễn Văn Test"
    canonical = "nguyen van test"
    staff_accounts = {
        "nv_test": {
            "full_name": staff_name,
            "hourly_rate": 20000,
            "salary_type": "HOURLY"
        }
    }
    
    data_json = {
        "DỮ LIỆU": [
            ["ID", "Ngày", "Nhân Viên", "Ca", "Vào", "Ra", "Phút", "Tháng", "Tháng", "Trễ"],
            ["1", "10/10/2026", staff_name, "Ca Sáng", "06:00", "11:30", 330, "10", "10", 0]
        ]
    }
    # Baseline: 330 mins * (20000 / 60) = 110,000 VND
    base_res = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month="10",
        data_json=data_json,
        staff_accounts=staff_accounts
    )
    assert base_res["gross_salary"] == 110000
    assert base_res["net_pay"] == 110000

    # Scenario: Manager adds bonus 50,000 then reverses it (-50,000)
    so_cai_with_reversal = [
        {
            "id": "1",
            "staff_name": staff_name,
            "month": "10",
            "loai_su_kien": "THUONG",
            "so_tien_thay_doi": 50000,
            "ly_do": "Chuyên cần"
        },
        {
            "id": "2",
            "staff_name": staff_name,
            "month": "10",
            "loai_su_kien": "REVERSAL",
            "reference_type": "THUONG",
            "so_tien_thay_doi": 50000,
            "ly_do": "Hủy duyệt chuyên cần"
        }
    ]

    rev_res = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month="10",
        data_json=data_json,
        staff_accounts=staff_accounts,
        so_cai_luong=so_cai_with_reversal
    )
    # Total bonus should be 50k - 50k = 0, net pay exactly 110,000
    assert rev_res["eval_bonus"] == 0
    assert rev_res["gross_salary"] == 110000
    assert rev_res["net_pay"] == 110000


def test_4_deduction_cap_and_debt_carry_forward():
    """Verify ADR-011 Deduction Cap: gross wage cannot be reduced by more than 50%, remaining debt carried forward."""
    staff_name = "Lê Thị Nợ"
    staff_accounts = {
        "nv_no": {
            "full_name": staff_name,
            "hourly_rate": 20000,
            "salary_type": "HOURLY"
        }
    }
    # Worked 10 shifts * 300 mins = 3000 mins = 50 hours * 20,000 = 1,000,000 VND gross
    du_lieu = [["ID", "Ngày", "Nhân Viên", "Ca", "Vào", "Ra", "Phút", "Tháng", "Tháng", "Trễ"]]
    for i in range(1, 11):
        du_lieu.append([str(i), f"{i:02d}/10/2026", staff_name, "Ca Chiều", "12:00", "17:00", 300, "10", "10", 0])

    data_json = {"DỮ LIỆU": du_lieu}

    # Employee took an advance of 800,000 VND (which is 80% of 1,000,000 gross)
    so_cai = [
        {
            "id": "adv_1",
            "staff_name": staff_name,
            "month": "10",
            "loai_su_kien": "UNG_LUONG",
            "so_tien_thay_doi": 800000,
            "ly_do": "Ứng mua đồ"
        }
    ]

    cfg = copy.deepcopy(DEFAULT_STORE_CONFIG)
    cfg["payroll_rules"]["enable_deduction_cap"] = True
    cfg["payroll_rules"]["deduction_cap_percent"] = 0.50 # Max 50% deduction

    res = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month="10",
        data_json=data_json,
        staff_accounts=staff_accounts,
        so_cai_luong=so_cai,
        store_config=cfg
    )

    assert res["gross_salary"] == 1000000
    assert res["total_deductions"] == 800000
    # Deduction cap at 50% of 1,000,000 = 500,000
    assert res["capped_deductions"] == 500000
    assert res["deduction_cap_applied"] is True
    # Net pay must be 1,000,000 - 500,000 = 500,000 VND (ensuring subsistence wage)
    assert res["net_pay"] == 500000
    # Remaining 300,000 VND carried forward as uncollected debt
    assert res["uncollected_debt"] == 300000


def test_5_offboarding_gate_debt_clearance():
    """Verify Offboarding Gate detects uncollected debt and blocks automatic clearance."""
    staff_name = "Trần Thôi Việc"
    staff_accounts = {
        "nv_thoi_viec": {
            "full_name": staff_name,
            "hourly_rate": 20000
        }
    }
    # 0 hours worked, but 500k advance debt
    data_json = {"DỮ LIỆU": [["ID", "Ngày", "Nhân Viên", "Ca", "Vào", "Ra", "Phút", "Tháng", "Tháng", "Trễ"]]}
    so_cai = [
        {
            "id": "deb_1",
            "staff_name": staff_name,
            "month": "10",
            "loai_su_kien": "UNG_LUONG",
            "so_tien_thay_doi": 500000,
            "ly_do": "Tạm ứng"
        }
    ]

    status = check_staff_offboarding_status(
        staff_name=staff_name,
        target_month="10",
        data_json=data_json,
        staff_accounts=staff_accounts,
        so_cai_luong=so_cai
    )

    assert status["can_offboard"] is False
    assert status["requires_admin_clearance"] is True
    assert status["uncollected_debt"] == 500000
    assert "cần quyết toán" in status["message"]


def test_6_api_offboarding_status_endpoint():
    """Verify REST API authorization and response for GET /api/v1/cc/admin/staff-offboarding-status."""
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})
    staff_token = create_access_token({"sub": "nv01", "role": "STAFF", "name": "Nhân Viên"})
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # Unauthorized
    r_no_auth = client.get("/api/v1/cc/admin/staff-offboarding-status?staff_name=Nguyen%20A")
    assert r_no_auth.status_code == 401

    # Forbidden for regular STAFF
    r_staff = client.get("/api/v1/cc/admin/staff-offboarding-status?staff_name=Nguyen%20A", headers=staff_headers)
    assert r_staff.status_code == 403

    # Allowed for ADMIN
    r_admin = client.get("/api/v1/cc/admin/staff-offboarding-status?staff_name=Nguyen%20A", headers=admin_headers)
    assert r_admin.status_code == 200
    d = r_admin.json()
    assert d.get("success") is True
    assert "can_offboard" in d.get("data", {})
