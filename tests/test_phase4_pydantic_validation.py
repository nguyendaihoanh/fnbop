import unittest
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app
from backend.services.auth import create_access_token
from backend.models.staff import (
    CreateStaffAccountData,
    UpdatePinData,
    UpdateStaffProfileData,
    StaffResponse,
)
from backend.models.attendance import (
    CheckinPayload,
    CheckoutPayload,
    HeartbeatPayload,
    AttendanceLog,
)
from backend.models.roster import (
    UpdateShiftSlotRequest,
    PeerSwapRequest,
    ShiftSlot,
    WeekSchedule,
)
from backend.models.payroll import (
    StaffLedgerCreateRequest,
    PayslipBreakdown,
    LedgerEntry,
)
from backend.models.store_config import (
    StoreConfigUpdate,
    UpdateOpsTogglePayload,
)
from backend.models.auth import (
    LoginRequest,
    TokenResponse,
)


class TestPhase4PydanticValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Admin"})
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

    def test_pin_forbidden_0000_or_1234(self):
        """PIN validation must reject predictable pins like 0000 and 1234"""
        for bad_pin in ["0000", "1234", "123"]:
            with self.assertRaises(ValidationError):
                CreateStaffAccountData(
                    username="test_bad_pin",
                    full_name="Bad Pin User",
                    pin=bad_pin
                )

        # Valid pin should pass
        valid_staff = CreateStaffAccountData(
            username="test_good_pin",
            full_name="Good Pin User",
            pin="9876"
        )
        self.assertEqual(valid_staff.pin, "9876")

    def test_update_pin_validation(self):
        """Updating PIN must enforce length and reject 0000/1234"""
        with self.assertRaises(ValidationError):
            UpdatePinData(username="test", new_pin="0000")

        with self.assertRaises(ValidationError):
            UpdatePinData(username="test", new_pin="12")

        valid_update = UpdatePinData(username="test", new_pin="5566")
        self.assertEqual(valid_update.new_pin, "5566")

    def test_phone_validation(self):
        """Phone must match Vietnamese phone regex or be empty"""
        # Invalid phone formats
        for bad_phone in ["01234", "abcdefghij", "00912345678", "1234567890"]:
            with self.assertRaises(ValidationError):
                CreateStaffAccountData(
                    username="test_bad_phone",
                    full_name="Bad Phone User",
                    pin="7890",
                    phone=bad_phone
                )

        # Valid phone formats
        for good_phone in ["0912345678", "84912345678", "", None]:
            model = CreateStaffAccountData(
                username="test_good_phone",
                full_name="Good Phone User",
                pin="7890",
                phone=good_phone
            )
            self.assertIsNotNone(model)

    def test_hourly_rate_range_validation(self):
        """Hourly rate must be between 0 and 500,000"""
        with self.assertRaises(ValidationError):
            CreateStaffAccountData(
                username="test_neg_rate",
                full_name="Negative Rate User",
                pin="7890",
                hourly_rate=-1000
            )

        with self.assertRaises(ValidationError):
            CreateStaffAccountData(
                username="test_high_rate",
                full_name="High Rate User",
                pin="7890",
                hourly_rate=600000
            )

        valid_staff = CreateStaffAccountData(
            username="test_valid_rate",
            full_name="Valid Rate User",
            pin="7890",
            hourly_rate=25000
        )
        self.assertEqual(valid_staff.hourly_rate, 25000)

    def test_api_create_staff_endpoint_422_on_bad_input(self):
        """The FastAPI endpoint /admin/create-staff-account must return 422 when Pydantic validation fails"""
        # 1. Test with bad PIN 0000
        res = self.client.post(
            "/api/v1/cc/admin/create-staff-account",
            headers=self.admin_headers,
            json={
                "username": "badpin_user",
                "full_name": "Bad Pin User",
                "pin": "0000",
            }
        )
        self.assertEqual(res.status_code, 422)

        # 2. Test with invalid hourly rate > 500,000
        res = self.client.post(
            "/api/v1/cc/admin/create-staff-account",
            headers=self.admin_headers,
            json={
                "username": "badrate_user",
                "full_name": "Bad Rate User",
                "pin": "8888",
                "hourly_rate": 99999999
            }
        )
        self.assertEqual(res.status_code, 422)

    def test_store_config_update_model(self):
        """StoreConfigUpdate should validate and accept structured updates"""
        cfg = StoreConfigUpdate(
            store_name="FnBOps Test",
            late_grace_period_mins=20,
            wifi_whitelist=["203.0.113.10"]
        )
        self.assertEqual(cfg.store_name, "FnBOps Test")
        self.assertEqual(cfg.late_grace_period_mins, 20)

        # Update via endpoint
        res = self.client.post(
            "/api/v1/cc/store/config",
            headers=self.admin_headers,
            json={"late_grace_period_mins": 15}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

    def test_attendance_and_roster_schemas(self):
        """Verify attendance and roster model instantiation and attributes"""
        checkin = CheckinPayload(username="nhan_vien_1", dev_override_wifi=True)
        self.assertEqual(checkin.username, "nhan_vien_1")
        self.assertTrue(checkin.dev_override_wifi)

        checkout = CheckoutPayload(username="nhan_vien_1", confirm_early=True)
        self.assertEqual(checkout.username, "nhan_vien_1")

        slot = UpdateShiftSlotRequest(
            week_id="2026-W42",
            date="15/10/2026",
            shift_period="morning",
            slot_type="barista",
            username="barista_1"
        )
        self.assertEqual(slot.slot_type, "barista")


if __name__ == "__main__":
    unittest.main()
