# -*- coding: utf-8 -*-
"""
Automated Legal, Open-Source License (AGPL-3.0-only), Attribution & Zalo Gateway Token Forwarding Tests.
"""
import json
import os
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_openapi_metadata_exposes_agpl_and_copyright_contact():
    """Verify FastAPI OpenAPI metadata exposes AGPL-3.0-only license and canonical contact."""
    from backend.main import app

    app.openapi_schema = None
    schema = app.openapi()
    info = schema.get("info", {})

    lic = info.get("license", {})
    assert lic.get("identifier") == "AGPL-3.0-only"
    assert "AGPL-3.0" in lic.get("name", "")

    contact = info.get("contact", {})
    assert contact.get("email") == "hoanh@vnaigc.com"
    assert "Nguyen Dai Hoanh" in contact.get("name", "")


def test_all_manifests_and_notices_pass_legal_audit():
    """Verify scripts/audit_schema_contracts.py legal & attribution audit returns zero issues."""
    from scripts.audit_schema_contracts import audit_license_and_legal_compliance

    assert audit_license_and_legal_compliance() == 0


def test_production_frontend_bundles_preserve_agpl_copyright_banner():
    """Verify compiled production JS bundles carry the AGPL-3.0-only copyright header."""
    for rel_path in ("frontend/dist/mobile.bundle.js", "frontend/dist/app.min.js"):
        full_path = os.path.join(PROJECT_ROOT, rel_path)
        assert os.path.exists(full_path), f"Missing compiled bundle: {rel_path}"
        with open(full_path, "r", encoding="utf-8") as f:
            header = f.read(300)
        assert "AGPL-3.0-only" in header
        assert "Nguyen Dai Hoanh (VNAIGC" in header
        assert "hoanh@vnaigc.com" in header


def test_zalo_dispatch_forwards_gateway_token_header_when_configured(monkeypatch):
    """Verify backend forwards X-Zalo-Gateway-Token to Zalo Gateway when ZALO_GATEWAY_TOKEN is set."""
    from backend.routers.notification_routes import _dispatch_zalo_image

    monkeypatch.setenv("ZALO_GATEWAY_URL", "http://127.0.0.1:8177")
    monkeypatch.setenv("ZALO_GATEWAY_TOKEN", "unit_test_shared_gateway_secret")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "msg_id": "zalo_msg_test"}

    with patch("backend.routers.notification_routes.requests.post", return_value=mock_resp) as mock_post:
        res = _dispatch_zalo_image("0901234567", "Payslip test", b"\x89PNG\r\n\x1a\n")
        assert res["success"] is True
        _, kwargs = mock_post.call_args
        assert kwargs["headers"].get("X-Zalo-Gateway-Token") == "unit_test_shared_gateway_secret"


def test_zero_proprietary_fonts_and_valid_inter_ofl_payslip_rendering():
    """Verify bundled fonts are SIL OFL-1.1 Inter TTFs (zero Monotype/Arial) and render Vietnamese payslips."""
    from backend.services.payslip_card_generator import render_payslip_card_png
    from backend.services.pdf_generator import render_payslip_pdf

    fonts_dir = os.path.join(PROJECT_ROOT, "backend", "assets", "fonts")
    assert not os.path.exists(os.path.join(fonts_dir, "Arial.ttf"))
    assert not os.path.exists(os.path.join(fonts_dir, "Arial-Bold.ttf"))
    assert not os.path.exists(os.path.join(fonts_dir, "Arial-Italic.ttf"))

    for req in ("Inter-Regular.ttf", "Inter-Bold.ttf", "Inter-Italic.ttf", "OFL.txt"):
        assert os.path.exists(os.path.join(fonts_dir, req)), f"Missing {req}"

    png_bytes = render_payslip_card_png(
        staff_name="Nguyễn Đại Hoành",
        month="10/2026",
        breakdown={"net_pay": 6500000, "total_shifts": 24, "total_hours": 192.0, "base_wage": 30000},
    )
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png_bytes) > 20000

    pdf_bytes = render_payslip_pdf(
        "Nguyễn Đại Hoành",
        "10/2026",
        {"net_pay": 6500000, "total_shifts": 24, "total_hours": 192.0, "base_wage": 30000},
    )
    assert pdf_bytes.startswith(b"%PDF-")


def test_zero_external_cdn_and_strict_csp_headers(monkeypatch):
    """Verify frontend uses self-hosted vendor assets and backend enforces strict Zero-CDN CSP."""
    from fastapi.testclient import TestClient
    from backend.main import app

    monkeypatch.setenv("ON_PREMISE_MODE", "true")
    chart_path = os.path.join(PROJECT_ROOT, "frontend", "vendor", "chart.umd.min.js")
    assert os.path.exists(chart_path)
    with open(chart_path, "r", encoding="utf-8") as f:
        head = f.read(250)
    assert "Chart.js" in head and "MIT License" in head

    with TestClient(app) as client:
        for route in ("/", "/desktop.html", "/monthly-report.html"):
            resp = client.get(route, headers={"Host": "localhost"})
            assert resp.status_code == 200
            csp = resp.headers.get("Content-Security-Policy", "")
            assert "default-src 'self'" in csp
            assert "font-src 'self' data:" in csp
            assert "connect-src 'self'" in csp
            assert "AGPL-3.0-only" in resp.headers.get("X-FnBOps-License", "")
            assert "fonts.googleapis.com" not in resp.text
            assert "cdn.jsdelivr.net" not in resp.text

        lic_resp = client.get("/api/v1/license", headers={"Host": "localhost"})
        assert lic_resp.status_code == 200
        lic_data = lic_resp.json()
        assert lic_data["spdx_license"] == "AGPL-3.0-only"
        assert "Nguyen Dai Hoanh" in lic_data["copyright_holder"]
        assert lic_data["commercial_license_contact"] == "hoanh@vnaigc.com"


def test_synced_macair_features_rlock_idempotency_and_my_schedule(tmp_path):
    """Verify synced Mac Air PayrollDashboard improvements: RLock, so_cai_luong idempotency_key, and /my-schedule."""
    import threading
    from backend.services.roster_service import _roster_lock
    from backend.services.db.schema import init_db
    from backend.services.db.payroll_repo import record_so_cai_luong, list_so_cai_luong

    assert isinstance(_roster_lock, type(threading.RLock()))

    test_db = str(tmp_path / "test_idem.db")
    init_db(test_db)
    id1 = record_so_cai_luong(
        tenant_id="default",
        nhan_vien_id="EMP_001",
        staff_name="Nguyễn Văn A",
        loai_su_kien="THUONG",
        so_tien_thay_doi=100000,
        ly_do="Thưởng doanh số",
        idempotency_key="TICKET:999:BONUS",
        db_path=test_db,
    )
    id2 = record_so_cai_luong(
        tenant_id="default",
        nhan_vien_id="EMP_001",
        staff_name="Nguyễn Văn A",
        loai_su_kien="THUONG",
        so_tien_thay_doi=100000,
        ly_do="Thưởng doanh số",
        idempotency_key="TICKET:999:BONUS",
        db_path=test_db,
    )
    assert id1 == id2
    rows = list_so_cai_luong(staff_name="Nguyễn Văn A", db_path=test_db)
    assert len(rows) == 1

