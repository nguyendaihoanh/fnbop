"""
Test Suite for Workstream 2: PDF Generator & Email Service
FnBOps On-Premise Standalone System (Zero-n8n & Zero-Docker).
Tests:
- Vietnamese TrueType Font Registration & Diacritics rendering.
- Vietnamese number-to-words currency formatting.
- Thermal invoice payslip PDF generation (A5 & A4).
- Shift evaluation notice PDF generation (Reward & Infraction).
- Email Service Outbox smart queuing (dry-run mode).
- Email Service asynchronous non-blocking dispatch.
- SMTP sending with mocked server and network error fallback.
- FastAPI notification routes (/send-payslip-email, /send-eval-email, /outbox, /preview-pdf).
"""

import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch

# Ensure backend directory is in python search path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "backend"))

from fastapi.testclient import TestClient
from main import app
from services.pdf_generator import (
    register_vietnamese_fonts,
    number_to_vietnamese_words,
    render_payslip_pdf,
    render_eval_notice_pdf,
    A5,
    A4
)
from services.email_service import (
    send_email_with_pdf_sync,
    send_email_with_pdf,
    list_outbox_records,
    get_outbox_pdf_file,
    clear_outbox_data
)


@pytest.fixture(autouse=True)
def clean_outbox_before_test(tmp_path, monkeypatch):
    """Ensures test outbox is completely isolated in tmp_path, protecting production data."""
    test_outbox = str(tmp_path / "outbox")
    test_pdf_dir = str(tmp_path / "outbox" / "pdf")
    test_log_file = str(tmp_path / "outbox" / "email_log.json")
    os.makedirs(test_pdf_dir, exist_ok=True)

    import services.email_service as es
    monkeypatch.setattr(es, "OUTBOX_DIR", test_outbox)
    monkeypatch.setattr(es, "OUTBOX_PDF_DIR", test_pdf_dir)
    monkeypatch.setattr(es, "EMAIL_LOG_FILE", test_log_file)
    monkeypatch.setenv("OUTBOX_DIR", test_outbox)
    monkeypatch.setenv("OUTBOX_PDF_DIR", test_pdf_dir)
    monkeypatch.setenv("EMAIL_LOG_FILE", test_log_file)

    try:
        import backend.services.email_service as bes
        monkeypatch.setattr(bes, "OUTBOX_DIR", test_outbox)
        monkeypatch.setattr(bes, "OUTBOX_PDF_DIR", test_pdf_dir)
        monkeypatch.setattr(bes, "EMAIL_LOG_FILE", test_log_file)
    except ImportError:
        pass

    clear_outbox_data(keep_logs=False)
    yield
    clear_outbox_data(keep_logs=False)



# ---------------------------------------------------------------------------
# 1. Font & Number-to-Words Tests
# ---------------------------------------------------------------------------

def test_font_registration():
    reg, bold, italic = register_vietnamese_fonts()
    assert reg in ("VietFont", "Arial", "Helvetica")
    assert bold in ("VietFont-Bold", "Arial-Bold", "Helvetica-Bold", reg)
    assert italic in ("VietFont-Italic", "Arial-Italic", "Helvetica-Oblique", reg)


def test_vietnamese_number_to_words():
    assert number_to_vietnamese_words(0) == "Không đồng"
    assert number_to_vietnamese_words(50000) == "Năm mươi nghìn đồng chẵn"
    assert number_to_vietnamese_words(105000) == "Một trăm lẻ năm nghìn đồng chẵn"
    assert number_to_vietnamese_words(1250000) == "Một triệu hai trăm năm mươi nghìn đồng chẵn"
    assert number_to_vietnamese_words(3500000) == "Ba triệu năm trăm nghìn đồng chẵn"
    assert "Âm" in number_to_vietnamese_words(-50000)


# ---------------------------------------------------------------------------
# 2. PDF Generator Tests (Payslip & Eval Notice)
# ---------------------------------------------------------------------------

def test_render_payslip_pdf_basic():
    pdf_bytes = render_payslip_pdf("Nguyễn Tấn Phát", "9", {
        "staff_name": "Nguyễn Tấn Phát",
        "role": "Nhân viên Pha chế",
        "base_wage": 17000,
        "total_shifts": 24,
        "total_hours": 120.0,
        "standard_pay": 2040000,
        "eval_bonus": 100000,
        "advance_amount": 500000,
        "eval_deductions": 0,
        "late_penalty_total": 0,
        "violations": [],
        "net_pay": 1640000
    }, pagesize=A5)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 20000  # Substantial PDF with fonts embedded


def test_render_payslip_pdf_with_overtime_and_violations():
    shift_records = [
        {"ot_minutes": 60, "is_holiday": False, "cost": 17000},
        {"ot_minutes": 30, "is_holiday": True, "cost": 34000}
    ]
    pdf_bytes = render_payslip_pdf("Ngô Tấn Phát", "9", {
        "staff_name": "Ngô Tấn Phát",
        "role": "Quản lý Ca Trực",
        "base_wage": 20000,
        "total_shifts": 28,
        "total_hours": 145.5,
        "standard_pay": 2910000,
        "eval_bonus": 250000,
        "advance_amount": 1000000,
        "eval_deductions": 50000,
        "late_penalty_total": 50000,
        "violations": ["Đi trễ 20 phút ngày 03/09", "Không đeo bảng tên ngày 10/09"],
        "net_pay": 2060000,
        "shift_records": shift_records
    }, pagesize=A4)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 20000


def test_render_payslip_pdf_defaults_and_empty_breakdown():
    pdf_bytes = render_payslip_pdf("Nhân Viên Mới", "9", {})
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")


def test_render_eval_notice_pdf_bonus():
    eval_data = {
        "id": "EV-202609-001",
        "staff_name": "Trương Minh Thuận",
        "role": "Phục vụ Bàn",
        "date": "24/09/2026",
        "shift": "Ca Tối (17:00 - 23:00)",
        "evaluator": "Quản lý Hoành",
        "type": "BONUS",
        "amount": 50000,
        "reason": "Chủ động hỗ trợ khách hàng và vệ sinh khu vực quầy bar sạch sẽ."
    }
    pdf_bytes = render_eval_notice_pdf(eval_data)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 15000


def test_render_eval_notice_pdf_penalty():
    eval_data = {
        "id": "EV-202609-002",
        "staff_name": "Nguyễn Văn Thiện",
        "role": "Nhân viên Phục vụ",
        "date": "24/09/2026",
        "shift": "Ca Sáng (06:30 - 11:30)",
        "evaluator": "Quản lý Ca",
        "type": "PENALTY",
        "amount": 50000,
        "reason": "Đi trễ 35 phút không thông báo trước cho Trưởng ca."
    }
    pdf_bytes = render_eval_notice_pdf(eval_data)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 15000


# ---------------------------------------------------------------------------
# 3. Email Service Tests (Outbox Dry-Run & SMTP)
# ---------------------------------------------------------------------------

def test_email_service_outbox_dry_run_when_smtp_unconfigured(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_PASS", "")

    dummy_pdf = b"%PDF-1.4 test payslip invoice dummy"
    res = send_email_with_pdf_sync(
        to_email="staff01@wfm.local",
        subject="[FNBOP] Phiếu Lương Tháng 9",
        body_text="Kính gửi Nhân Viên 01, gửi bạn phiếu lương.",
        pdf_bytes=dummy_pdf,
        filename="PhieuLuong_Nhan_Vien_01_T9.pdf"
    )

    assert res["status"] == "queued_outbox"
    assert res["to_email"] == "staff01@wfm.local"
    assert os.path.exists(res["path"])
    assert res["size_bytes"] == len(dummy_pdf)

    # Check that outbox log recorded the transaction
    logs = list_outbox_records()
    assert len(logs) == 1
    assert logs[0]["to_email"] == "staff01@wfm.local"
    assert logs[0]["status"] == "queued_outbox"


def test_email_service_async_send(monkeypatch):
    import asyncio
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_PASS", "")

    dummy_pdf = b"%PDF-1.4 async test pdf"
    res = asyncio.run(send_email_with_pdf(
        to_email="staff02@wfm.local",
        subject="[FNBOP] Phiếu Lương Nhân Viên 02",
        body_text="Phiếu lương đính kèm.",
        pdf_bytes=dummy_pdf,
        filename="PhieuLuong_Nhan_Vien_02_T9.pdf"
    ))

    assert res["status"] == "queued_outbox"
    assert res["to_email"] == "staff02@wfm.local"


def test_email_service_smtp_success_mock(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "wfm.local@gmail.com")
    monkeypatch.setenv("SMTP_PASS", "app_secret_pass_123")
    monkeypatch.setenv("SMTP_TLS", "true")

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        dummy_pdf = b"%PDF-1.4 mock smtp content"
        res = send_email_with_pdf_sync(
            to_email="phat@wfm.local",
            subject="[MOCK] Test SMTP Delivery",
            body_text="Mock delivery message",
            pdf_bytes=dummy_pdf,
            filename="Mock_Payslip.pdf"
        )

        assert res["status"] == "sent"
        assert res["to_email"] == "phat@wfm.local"
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_with("wfm.local@gmail.com", "app_secret_pass_123")
        mock_smtp_instance.send_message.assert_called_once()
        mock_smtp_instance.quit.assert_called_once()


def test_email_service_smtp_failure_fallback_to_outbox(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.fail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "wfm.local@gmail.com")
    monkeypatch.setenv("SMTP_PASS", "app_secret_pass_123")

    with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("Connection refused by test mock")):
        dummy_pdf = b"%PDF-1.4 fallback test pdf"
        res = send_email_with_pdf_sync(
            to_email="vinh@wfm.local",
            subject="[FAIL] Test Fallback Outbox",
            body_text="Fallback content",
            pdf_bytes=dummy_pdf,
            filename="Fallback_Payslip.pdf"
        )

        assert res["status"] == "queued_outbox_fallback"
        assert "Connection refused" in res["message"]
        assert os.path.exists(res["path"])


def test_get_outbox_pdf_file():
    dummy_pdf = b"%PDF-1.4 retrieval test content"
    res = send_email_with_pdf_sync(
        to_email="staff@wfm.local",
        subject="Retrieval Test",
        body_text="Hello",
        pdf_bytes=dummy_pdf,
        filename="RetrieveMe.pdf"
    )
    found_path = get_outbox_pdf_file(res["filename"])
    assert found_path is not None
    assert os.path.exists(found_path)

    not_found = get_outbox_pdf_file("non_existent_file_999.pdf")
    assert not_found is None


# ---------------------------------------------------------------------------
# 4. FastAPI Notification Routes Tests
# ---------------------------------------------------------------------------

from routers.fnb_ops import create_access_token


@pytest.fixture
def client():
    c = TestClient(app)
    token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán"})
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_api_send_payslip_email(client):
    payload = {
        "staff_name": "Nguyễn Tấn Phát",
        "month": "9",
        "to_email": "phat.nguyen@wfm.local",
        "breakdown": {
            "staff_name": "Nguyễn Tấn Phát",
            "base_wage": 17000,
            "total_shifts": 24,
            "total_hours": 120.0,
            "standard_pay": 2040000,
            "eval_bonus": 100000,
            "advance_amount": 0,
            "eval_deductions": 0,
            "late_penalty_total": 0,
            "net_pay": 2140000
        }
    }
    resp = client.post("/api/v1/cc/notifications/send-payslip-email", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["staff_name"] == "Nguyễn Tấn Phát"
    assert data["month"] == "9"
    assert data["net_pay"] == 2140000
    assert "PhieuLuong" in data["filename"]
    assert "email_delivery" in data


def test_api_send_payslip_email_computes_breakdown_when_missing(client):
    payload = {
        "staff_name": "Phát",
        "month": "9"
    }
    resp = client.post("/api/v1/cc/notifications/send-payslip-email", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "email_delivery" in data


def test_api_send_eval_email(client):
    payload = {
        "eval_id": "EV-TEST-100",
        "staff_name": "Nhân Viên 01",
        "to_email": "staff01@wfm.local",
        "eval_data": {
            "id": "EV-TEST-100",
            "staff_name": "Nhân Viên 01",
            "type": "BONUS",
            "amount": 100000,
            "reason": "Hoàn thành xuất sắc nhiệm vụ pha chế ca sáng"
        }
    }
    resp = client.post("/api/v1/cc/notifications/send-eval-email", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "BienBan_DanhGia" in data["filename"]


def test_api_get_outbox(client):
    # Trigger an outbox item first
    client.post("/api/v1/cc/notifications/send-payslip-email", json={
        "staff_name": "Nhân Viên 02",
        "month": "9"
    })

    resp = client.get("/api/v1/cc/notifications/outbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total_records"] >= 1
    assert len(data["items"]) >= 1


def test_api_preview_payslip_pdf(client):
    resp = client.get("/api/v1/cc/notifications/preview-payslip-pdf?staff_name=Phát&month=9")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")


def test_api_preview_eval_pdf(client):
    resp = client.get("/api/v1/cc/notifications/preview-eval-pdf?staff_name=Phát")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")


def test_api_download_outbox_pdf(client):
    post_resp = client.post("/api/v1/cc/notifications/send-payslip-email", json={
        "staff_name": "Thiện",
        "month": "9"
    })
    filename = post_resp.json()["filename"]

    # Download it
    dl_resp = client.get(f"/api/v1/cc/notifications/outbox/pdf/{filename}")
    assert dl_resp.status_code == 200
    assert dl_resp.headers["content-type"] == "application/pdf"
    assert dl_resp.content.startswith(b"%PDF-")

    # Non-existent file returns 404
    missing_resp = client.get("/api/v1/cc/notifications/outbox/pdf/not_found_file.pdf")
    assert missing_resp.status_code == 404


def test_api_input_validation(client):
    # Empty staff name
    resp = client.post("/api/v1/cc/notifications/send-payslip-email", json={"staff_name": "   "})
    assert resp.status_code == 400

    # Preview missing staff name
    resp_prev = client.get("/api/v1/cc/notifications/preview-payslip-pdf?staff_name=")
    assert resp_prev.status_code == 400
