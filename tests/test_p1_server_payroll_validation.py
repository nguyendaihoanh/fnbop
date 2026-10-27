import os
import sys
import json
import pytest
import tempfile
from fastapi.testclient import TestClient

# Ensure sys.path contains backend and project root
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from services.payroll_calc import (
    calculate_progressive_late_penalties,
    calculate_staff_payslip_breakdown
)
from services.storage import hash_pin
from routers.fnb_ops import router as cc_router
from fastapi import FastAPI

app = FastAPI()
app.include_router(cc_router)
client = TestClient(app)


# ==========================================
# 1. PROGRESSIVE LATE PENALTIES UNIT TESTS
# ==========================================
def test_late_penalties_month_8_exempt():
    late_list = [15, 20, 25, 40]
    total_penalty, details = calculate_progressive_late_penalties(late_list, month="8")
    assert total_penalty == 0
    assert len(details) == 0


def test_late_penalties_month_9_progressive_rules():
    # 2 lates (> 10 mins) -> Warnings only (0 VND)
    p2, d2 = calculate_progressive_late_penalties([15, 12], month="9")
    assert p2 == 0
    assert len(d2) == 0

    # 3 lates (> 10 mins) -> 50,000 VND
    p3, d3 = calculate_progressive_late_penalties([15, 12, 18], month="9")
    assert p3 == 50000
    assert any("50,000" in d for d in d3)

    # 4 lates (> 10 mins) -> 50,000 + 150,000 = 200,000 VND
    p4, d4 = calculate_progressive_late_penalties([15, 12, 18, 20], month="9")
    assert p4 == 200000

    # 1 late > 30 mins -> Instant fine 50,000 + 1 warning = 50,000 VND
    p_inst, d_inst = calculate_progressive_late_penalties([35], month="9")
    assert p_inst == 50000
    assert any("Trễ >30p" in d for d in d_inst)


# ==========================================
# 2. SERVER PAYROLL SUMMARY & DIRECT PAYLOAD VALIDATION
# ==========================================
@pytest.fixture
def payroll_fixture(monkeypatch):
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as af:
        auth_data = {
            "staff_accounts": {
                "staff_test": {
                    "full_name": "Test Staff",
                    "sheet_names": ["Test Staff"],
                    "pin": hash_pin("1122"),
                    "role": "STAFF",
                    "status": "ACTIVE"
                },
                "mgr_test": {
                    "full_name": "Test Manager",
                    "sheet_names": ["Test Manager"],
                    "pin": hash_pin("9999"),
                    "role": "MANAGER",
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
                [""],
                ["STT", "TÊN NHÂN VIÊN", "VỊ TRÍ", "LƯƠNG/GIỜ", "TỔNG LƯƠNG"],
                ["1", "Test Staff", "Phục vụ", "25.000", 2500000]
            ],
            "DỮ LIỆU": [
                ["STT", "Ngày", "Tên Nhân Viên", "Ca làm việc", "Giờ vào", "Giờ ra"],
                ["1", "01/09/2026", "Test Staff", "Ca Sáng", "06:00", "11:00"], # 300 mins (5h)
                ["2", "02/09/2026", "Test Staff", "Ca Sáng", "06:00", "11:00"]  # 300 mins (5h)
            ],
            "ĐÁNH GIÁ": [],
            "SỔ PHỤ": []
        }
        json.dump(sheet_data, df)
        data_file = df.name

    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as ef:
        json.dump([], ef)
        eval_file = ef.name

    monkeypatch.setenv("AUTH_FILE", auth_file)
    monkeypatch.setenv("DATA_FILE", data_file)
    monkeypatch.setenv("EVALUATIONS_FILE", eval_file)

    yield {"auth_file": auth_file, "data_file": data_file, "eval_file": eval_file}

    for f in [auth_file, data_file, eval_file]:
        if os.path.exists(f):
            os.remove(f)
        if os.path.exists(f"{f}.lock"):
            os.remove(f"{f}.lock")


def test_server_side_payroll_summary_tamper_proof(payroll_fixture):
    # Login staff
    login_s = client.post("/api/v1/cc/auth/login", json={"username": "staff_test", "password": "1122"})
    assert login_s.status_code == 200
    token_s = login_s.json()["access_token"]

    # Call /payroll/summary as staff
    res_s = client.get("/api/v1/cc/payroll/summary?month=9", headers={"Authorization": f"Bearer {token_s}"})
    assert res_s.status_code == 200
    bd = res_s.json()["breakdown"]

    assert bd["staff_name"] == "Test Staff"
    assert bd["total_hours"] == 10.0
    assert bd["base_wage"] == 25000
    # 5h ngày thường 01/09 (125.000đ) + 5h ngày Lễ 02/09 (nhân đôi x2.0 = 250.000đ) = 375.000đ
    assert bd["standard_pay"] == 375000
    assert bd["net_pay"] == 375000


def test_direct_payload_evaluation_validation_limits(payroll_fixture):
    # Login manager
    login_m = client.post("/api/v1/cc/auth/login", json={"username": "mgr_test", "password": "9999"})
    assert login_m.status_code == 200
    token_m = login_m.json()["access_token"]
    headers = {"Authorization": f"Bearer {token_m}"}

    # 1. Reject amount exceeding 5,000,000 VND
    bad_res1 = client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json={
        "staff_name": "Test Staff",
        "date": "2026-09-14",
        "type": "Thưởng",
        "amount": 50000000, # 50 million spam!
        "reason": "Spam reward"
    })
    assert bad_res1.status_code == 400
    assert "tối đa 5,000,000đ" in bad_res1.json()["detail"]

    # 2. Reject negative amount
    bad_res2 = client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json={
        "staff_name": "Test Staff",
        "date": "2026-09-14",
        "type": "Phạt",
        "amount": -50000,
        "reason": "Negative amount"
    })
    assert bad_res2.status_code == 400

    # 3. Reject empty reason
    bad_res3 = client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json={
        "staff_name": "Test Staff",
        "date": "2026-09-14",
        "type": "Thưởng",
        "amount": 100000,
        "reason": "  "
    })
    assert bad_res3.status_code == 400
    assert "tối thiểu 3 ký tự" in bad_res3.json()["detail"]

    # 4. Valid evaluation succeeds
    ok_res = client.post("/api/v1/cc/admin/staff-evaluation", headers=headers, json={
        "staff_name": "Test Staff",
        "date": "2026-09-14",
        "type": "Thưởng",
        "amount": 100000,
        "reason": "Chăm chỉ hỗ trợ đông khách"
    })
    assert ok_res.status_code == 200
    assert ok_res.json()["success"] is True
