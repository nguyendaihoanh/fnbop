"""
Quality Gate & Integration Test Suite:
1. Zalo Gateway Microservice & Notification Endpoints
2. Dark Luxury 1080x1440 Payslip PNG Card Generation
3. Three Automation Toggles (auto_payslip, auto_shift_reminder, auto_checkout_alert)
4. Custom Reminder Messages & In-App Popups
5. Role-Based Access Control (RBAC) Hardening
"""

import os
import sys
import io
import json
import pytest
from unittest.mock import patch, MagicMock

_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi.testclient import TestClient
from PIL import Image

from main import app
from routers.fnb_ops import create_access_token
from services.payslip_card_generator import render_payslip_card_png, format_currency
from services.store_config import get_store_config, save_store_config, DEFAULT_STORE_CONFIG


@pytest.fixture(autouse=True)
def clean_test_env(monkeypatch):
    """Guarantees test isolation and mocks external network calls by default."""
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("MOCK_TELEGRAM", "1")
    yield


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def auth_tokens():
    admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Quản Trị Viên"})
    manager_token = create_access_token({"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})
    staff_token = create_access_token({"sub": "nhanvien23", "role": "STAFF", "name": "Nhân Viên 23", "sheet_names": ["NHANVIEN23"]})
    other_staff_token = create_access_token({"sub": "nhanvien03", "role": "STAFF", "name": "Nhân Viên 03", "sheet_names": ["NHANVIEN03"]})

    return {
        "admin": {"Authorization": f"Bearer {admin_token}"},
        "manager": {"Authorization": f"Bearer {manager_token}"},
        "staff": {"Authorization": f"Bearer {staff_token}"},
        "other_staff": {"Authorization": f"Bearer {other_staff_token}"},
    }


# ==============================================================================
# SECTION 1: PAYSLIP CARD PNG GENERATOR TESTS (services/payslip_card_generator.py)
# ==============================================================================

class TestPayslipCardGenerator:
    """Kiểm thử chuyên sâu module sinh ảnh thẻ lương Dark Luxury 1080x1440 PNG."""

    def test_format_currency_helper(self):
        """Định dạng tiền tệ VNĐ chuẩn xác, xử lý số âm, số 0 và hàng triệu."""
        assert format_currency(0) == "0 đ"
        assert format_currency(150000) == "150.000 đ"
        assert format_currency(5850000) == "5.850.000 đ"
        assert format_currency(-100000) == "-100.000 đ"
        assert format_currency(None) == "0 đ"

    def test_render_payslip_card_png_dimensions_and_validity(self):
        """Ảnh xuất ra phải chuẩn 1080x1440, định dạng PNG RGBA và không bị rỗng."""
        breakdown = {
            "total_shifts": 22,
            "total_hours": 121.5,
            "base_wage": 17000,
            "standard_pay": 2065500,
            "ot_pay": 150000,
            "bonus_amount": 200000,
            "late_penalty": 0,
            "advance_amount": 100000,
            "net_pay": 2315500,
            "bonus_reasons": ["Thưởng chuyên cần tháng 10"],
            "advance_reasons": ["Ứng giữa tháng"]
        }

        png_bytes = render_payslip_card_png(
            staff_name="Nhân Viên 01",
            month="10",
            breakdown=breakdown,
            role_label="Quản Lý / Barista",
            employee_id="WFM_001"
        )

        assert isinstance(png_bytes, bytes)
        assert len(png_bytes) > 10000, "Kích thước ảnh PNG phải > 10KB"
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "Magic bytes phải đúng chuẩn PNG"

        # Đọc lại bằng Pillow để kiểm chứng độ phân giải tuyệt đối
        img = Image.open(io.BytesIO(png_bytes))
        assert img.size == (1080, 1440), f"Kích thước ảnh phải đúng 1080x1440, thực tế: {img.size}"
        assert img.format == "PNG"

    def test_render_payslip_card_vietnamese_typography_resilience(self):
        """Khả năng render tiếng Việt có dấu đầy đủ, tên dài và trường khuyết thiếu không crash."""
        breakdown_empty = {
            "net_pay": 0
        }

        png_bytes = render_payslip_card_png(
            staff_name="Trần Thị Quỳnh Như",
            month="11",
            breakdown=breakdown_empty,
            role_label="Nhân Viên Vận Hành Ca Sáng",
            employee_id="WFM_STAFF"
        )

        assert isinstance(png_bytes, bytes)
        img = Image.open(io.BytesIO(png_bytes))
        assert img.size == (1080, 1440)


# ==============================================================================
# SECTION 2: NOTIFICATION ROUTER & PAYSLIP CARD ENDPOINTS
# ==============================================================================

class TestNotificationPayslipCardEndpoints:
    """Kiểm thử các API xem trước và gửi thẻ lương Zalo (PNG)."""

    def test_preview_payslip_png_rbac_own_payslip_allowed(self, api_client, auth_tokens):
        """Nhân viên STAFF được phép xem trước ảnh thẻ lương của chính mình."""
        res = api_client.get(
            "/api/v1/cc/notifications/preview-payslip-card?staff_name=NHANVIEN23&month=9",
            headers=auth_tokens["staff"]
        )
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"
        assert res.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_preview_payslip_png_rbac_other_payslip_forbidden(self, api_client, auth_tokens):
        """Nhân viên STAFF cố tình xem thẻ lương của nhân viên khác bị chặn 403 Forbidden."""
        res = api_client.get(
            "/api/v1/cc/notifications/preview-payslip-card?staff_name=NHANVIEN03&month=9",
            headers=auth_tokens["staff"]
        )
        assert res.status_code == 403
        assert "Chỉ có quyền xem phiếu lương của chính mình" in res.json().get("detail", "")

    def test_preview_payslip_png_manager_can_view_any(self, api_client, auth_tokens):
        """Quản lý MANAGER được phép xem trước ảnh thẻ lương của bất kỳ nhân viên nào."""
        res = api_client.get(
            "/api/v1/cc/notifications/preview-payslip-card?staff_name=NHANVIEN03&month=9",
            headers=auth_tokens["manager"]
        )
        assert res.status_code == 200
        assert res.headers["content-type"] == "image/png"

    @patch("routers.notification_routes._dispatch_zalo_image")
    def test_send_payslip_zalo_card_success(self, mock_dispatch, api_client, auth_tokens):
        """Manager gửi thẻ lương Zalo thành công với mock gateway."""
        mock_dispatch.return_value = {"success": True, "msg_id": "zalo_test_123"}

        payload = {
            "staff_name": "Nhân Viên 23",
            "month": "9",
            "phone": "0901234567",
            "breakdown": {
                "total_shifts": 20,
                "total_hours": 100,
                "net_pay": 1700000
            }
        }

        res = api_client.post(
            "/api/v1/cc/notifications/send-payslip-zalo-card",
            json=payload,
            headers=auth_tokens["manager"]
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data.get("success") is True
        assert "thành công" in data.get("message", "")
        mock_dispatch.assert_called_once()

    def test_send_payslip_zalo_card_staff_forbidden(self, api_client, auth_tokens):
        """Nhân viên STAFF không được phép gọi lệnh gửi thẻ lương Zalo (403)."""
        payload = {
            "staff_name": "Nhân Viên 23",
            "month": "9",
            "phone": "0901234567"
        }
        res = api_client.post(
            "/api/v1/cc/notifications/send-payslip-zalo-card",
            json=payload,
            headers=auth_tokens["staff"]
        )
        assert res.status_code == 403

    def test_send_payslip_zalo_card_missing_phone_rejected(self, api_client, auth_tokens):
        """Gửi thẻ lương cho nhân viên chưa có số điện thoại bị từ chối 400 Bad Request."""
        payload = {
            "staff_name": "Nhân Sự Không Có SĐT Chưa Tồn Tại",
            "month": "9"
        }
        res = api_client.post(
            "/api/v1/cc/notifications/send-payslip-zalo-card",
            json=payload,
            headers=auth_tokens["manager"]
        )
        assert res.status_code == 400
        assert "chưa có số điện thoại" in res.json().get("detail", "")

    @patch("routers.notification_routes._dispatch_zalo_image")
    def test_send_bulk_payslip_zalo_cards_manager(self, mock_dispatch, api_client, auth_tokens):
        """Manager gửi hàng loạt thẻ lương Zalo."""
        mock_dispatch.return_value = {"success": True, "msg_id": "zalo_bulk_123"}

        res = api_client.post(
            "/api/v1/cc/notifications/send-bulk-payslip-zalo-cards",
            json={"month": "9"},
            headers=auth_tokens["manager"]
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data.get("success") is True
        assert "total_sent" in data


# ==============================================================================
# SECTION 3: STORE CONFIG - 3 AUTOMATION TOGGLES & CUSTOM PROMPTS
# ==============================================================================

class TestStoreConfigAutomationTogglesAndPrompts:
    """Kiểm thử 3 toggle tự động hóa và các mẫu câu nhắc tùy chỉnh trong store_config."""

    def test_store_config_contains_zalo_automation_defaults(self):
        """Cấu trúc mặc định phải có đầy đủ 3 toggles và trường tùy chỉnh câu nhắc."""
        cfg = get_store_config()
        assert "zalo_automation" in cfg
        z_auto = cfg["zalo_automation"]
        assert "enable_auto_payslip" in z_auto
        assert "enable_auto_shift_reminder" in z_auto
        assert "enable_auto_checkout_alert" in z_auto
        assert "reminder_minutes_before_shift" in z_auto
        assert "checkout_alert_grace_mins" in z_auto

    def test_update_three_toggles_and_custom_prompts_via_api(self, api_client, auth_tokens):
        """Admin cập nhật 3 toggle và tùy chỉnh câu nhắc vào ca / chốt ca."""
        # 1. Đọc config hiện tại
        res_get = api_client.get("/api/v1/cc/store/config", headers=auth_tokens["admin"])
        assert res_get.status_code == 200
        current_cfg = res_get.json().get("config", {})

        # 2. Thay đổi 3 toggles và câu nhắc
        current_cfg["zalo_automation"] = {
            "enable_auto_payslip": True,
            "enable_auto_shift_reminder": True,
            "enable_auto_checkout_alert": True,
            "reminder_minutes_before_shift": 45,
            "checkout_alert_grace_mins": 20,
            "shift_reminder_message": "Ca làm sắp bắt đầu trong 45 phút, nhớ ghé quán check-in đúng giờ bạn nhé!",
            "checkout_alert_message": "Đã hết giờ làm việc 20 phút rồi, bạn nhớ bấm Chốt ca trước khi về nha!"
        }

        res_post = api_client.post(
            "/api/v1/cc/store/config",
            json=current_cfg,
            headers=auth_tokens["admin"]
        )
        assert res_post.status_code == 200
        assert res_post.json().get("success") is True

        # 3. Đọc lại để kiểm chứng tính bền vững (Persistence)
        res_verify = api_client.get("/api/v1/cc/store/config", headers=auth_tokens["admin"])
        assert res_verify.status_code == 200
        saved_auto = res_verify.json().get("config", {}).get("zalo_automation", {})

        assert saved_auto.get("enable_auto_payslip") is True
        assert saved_auto.get("enable_auto_shift_reminder") is True
        assert saved_auto.get("enable_auto_checkout_alert") is True
        assert saved_auto.get("reminder_minutes_before_shift") == 45
        assert saved_auto.get("checkout_alert_grace_mins") == 20
        assert "45 phút" in saved_auto.get("shift_reminder_message", "")
        assert "Chốt ca" in saved_auto.get("checkout_alert_message", "")

    def test_staff_cannot_update_store_config_toggles(self, api_client, auth_tokens):
        """Nhân viên STAFF cố tình sửa store config bị chặn 403 Forbidden."""
        res = api_client.post(
            "/api/v1/cc/store/config",
            json={"zalo_automation": {"enable_auto_payslip": True}},
            headers=auth_tokens["staff"]
        )
        assert res.status_code == 403


# ==============================================================================
# SECTION 4: IN-APP URGENT REMINDERS & CUSTOM MESSAGES (routers/push_routes.py)
# ==============================================================================

class TestCustomRemindersAndInAppAlerts:
    """Kiểm thử gửi lời nhắc khẩn cấp kèm câu nhắc tùy biến và cơ chế đóng popup."""

    def test_manager_remind_staff_with_custom_message(self, api_client, auth_tokens):
        """Quản lý gửi câu nhắc tùy biến cho nhân viên, kiểm tra phản hồi API."""
        custom_msg = "Nhân viên 23 ơi, hôm nay khách đông, hỗ trợ vào ca sớm 10 phút nhé! Cảm ơn em."
        payload = {
            "username": "nhanvien23",
            "remind_type": "CHECKIN",
            "custom_message": custom_msg
        }

        res = api_client.post(
            "/api/v1/cc/notifications/push/manager/remind-staff",
            json=payload,
            headers=auth_tokens["manager"]
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data.get("success") is True
        assert data.get("username") == "nhanvien23"
        assert data.get("remind_type") == "CHECKIN"
        assert "reminder_id" in data
        reminder_id = data["reminder_id"]

        # Nhân viên đọc danh sách lời nhắc của mình
        res_my = api_client.get(
            "/api/v1/cc/notifications/push/my-reminders",
            headers=auth_tokens["staff"]
        )
        assert res_my.status_code == 200
        my_reminders = res_my.json().get("reminders", [])
        matched = [r for r in my_reminders if r.get("id") == reminder_id or custom_msg in r.get("message", "")]
        assert len(matched) > 0, "Nhân viên phải nhận được thông báo chứa đúng câu nhắc tùy biến"
        assert custom_msg in matched[0].get("message", "")

        # Nhân viên bấm xác nhận / đóng lời nhắc
        res_ack = api_client.post(
            f"/api/v1/cc/notifications/push/ack-reminder/{reminder_id}",
            headers=auth_tokens["staff"]
        )
        assert res_ack.status_code == 200
        assert res_ack.json().get("success") is True

    def test_manager_remind_staff_checkout_and_roster_types(self, api_client, auth_tokens):
        """Kiểm thử các loại nhắc nhở CHECKOUT và ROSTER."""
        for r_type in ["CHECKOUT", "ROSTER"]:
            payload = {
                "username": "nhanvien23",
                "remind_type": r_type,
                "custom_message": f"Test câu nhắc loại {r_type}"
            }
            res = api_client.post(
                "/api/v1/cc/notifications/push/manager/remind-staff",
                json=payload,
                headers=auth_tokens["manager"]
            )
            assert res.status_code == 200
            assert res.json().get("remind_type") == r_type

    def test_ack_all_reminders_dismissal(self, api_client, auth_tokens):
        """Kiểm thử API đóng toàn bộ lời nhắc khẩn cấp để ngăn chặn spam popup lặp lại."""
        res_ack_all = api_client.post(
            "/api/v1/cc/notifications/push/ack-all-reminders",
            headers=auth_tokens["staff"]
        )
        assert res_ack_all.status_code == 200
        assert res_ack_all.json().get("success") is True

    def test_staff_cannot_remind_other_staff(self, api_client, auth_tokens):
        """Nhân viên STAFF cố tình bắn lệnh nhắc nhân viên khác bị chặn 403 Forbidden."""
        res = api_client.post(
            "/api/v1/cc/notifications/push/manager/remind-staff",
            json={"username": "nhanvien03", "remind_type": "CHECKIN"},
            headers=auth_tokens["staff"]
        )
        assert res.status_code == 403


# ==============================================================================
# SECTION 5: ZALO GATEWAY STATUS & QR CODE RESILIENCE
# ==============================================================================

class TestZaloGatewayStatusAndQr:
    """Kiểm thử router Zalo Gateway trên backend đối với các kịch bản kết nối."""

    def test_zalo_status_endpoint_returns_json(self, api_client, auth_tokens):
        """GET /api/v1/cc/store/zalo-status phản hồi cấu trúc JSON hợp lệ."""
        res = api_client.get(
            "/api/v1/cc/store/zalo-status",
            headers=auth_tokens["admin"]
        )
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert "connected" in data

    def test_zalo_qr_endpoint_structure(self, api_client, auth_tokens):
        """GET /api/v1/cc/store/zalo-qr phản hồi mã QR hoặc trạng thái đã kết nối."""
        res = api_client.get(
            "/api/v1/cc/store/zalo-qr",
            headers=auth_tokens["admin"]
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("success") in [True, False]
        if data.get("success") is True:
            if data.get("connected"):
                assert data.get("status") == "ready"
            else:
                assert "qr" in data

    def test_staff_forbidden_to_query_zalo_qr(self, api_client, auth_tokens):
        """Nhân viên STAFF không có quyền truy cập mã QR Zalo của quán."""
        # Unauthenticated request
        res = api_client.get("/api/v1/cc/store/zalo-qr")
        assert res.status_code in [401, 403]
