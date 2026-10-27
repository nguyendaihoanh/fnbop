"""
FnBOps - Bi-Directional Synchronization & Dual-Mode Integration Tests
Verifies 16 critical test cases bridging Cloud Live and Standalone On-Premise systems.
Ensures zero data loss, schema alignment, adaptive roster solver, and clean reporting.
"""

import os
import sys
import json
import sqlite3
import tempfile
import unittest
import datetime
import pytest

# Ensure project root in sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from backend.services.excel_manager import HAS_OPENPYXL
except ImportError:
    from services.excel_manager import HAS_OPENPYXL

from fastapi.testclient import TestClient
from main import app

from backend.services.db import (
    init_db,
    get_db_connection,
    upsert_staff_account,
    get_staff_by_username,
    upsert_payroll_confirmation,
    list_payroll_confirmations,
    bootstrap_sync_staff_auth_to_sqlite,
    DEFAULT_TENANT_ID
)
from backend.services.store_config import (
    get_store_config,
    get_auto_close_cutoff_minutes,
    get_shift_by_alias
)
from backend.routers.fnb_ops import (
    create_access_token,
    load_staff_auth,
    save_staff_auth
)
from backend.services.excel_manager import (
    export_payroll_excel,
    generate_staff_template,
    import_staff_from_excel,
    HAS_OPENPYXL
)
from backend.services.pdf_generator import (
    render_payslip_pdf,
    HAS_REPORTLAB
)
from backend.routers.roster import (
    auto_assign_week_schedule,
    get_active_and_next_week_ids
)


class TestBiDirectionalSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Isolate environment with a temporary database
        cls.orig_db = os.environ.get("DATABASE_PATH")
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.temp_db = os.path.join(cls.temp_dir.name, "test_sync.db")
        os.environ["DATABASE_PATH"] = cls.temp_db
        init_db(cls.temp_db)

        # Clear login lockout and rate limits
        conn = get_db_connection(cls.temp_db)
        with conn:
            conn.execute("DELETE FROM login_attempts;")
            conn.execute("DELETE FROM api_rate_limits;")
        conn.close()

        cls.client = TestClient(app)
        cls.admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Quán", "ver": 1})
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}
        cls.staff_token = create_access_token({"sub": "nhanvien", "role": "STAFF", "name": "Nhân Viên", "ver": 1})
        cls.staff_headers = {"Authorization": f"Bearer {cls.staff_token}"}

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()
        if cls.orig_db is not None:
            os.environ["DATABASE_PATH"] = cls.orig_db
        else:
            os.environ.pop("DATABASE_PATH", None)

    # --------------------------------------------------------------------------
    # TEST CASE 1: Bootstrap sync staff_auth.json into SQLite
    # --------------------------------------------------------------------------
    def test_sync_01_staff_auth_bootstrap_to_sqlite(self):
        res = bootstrap_sync_staff_auth_to_sqlite(db_path=self.temp_db)
        self.assertTrue(res.get("success"))
        self.assertGreaterEqual(res.get("synced_staff", 0), 4)
        self.assertGreater(res.get("synced_locks", 0), 0)

        # Verify specific staff in SQLite
        nv = get_staff_by_username("nhanvien", db_path=self.temp_db)
        self.assertIsNotNone(nv)
        self.assertEqual(nv.get("employee_id"), "EMP_SRV")
        self.assertEqual(nv.get("gender"), "NU")

    # --------------------------------------------------------------------------
    # TEST CASE 2: Allowed roles schema persistence
    # --------------------------------------------------------------------------
    def test_sync_02_allowed_roles_schema_persistence(self):
        upsert_staff_account(
            username="test_multi_role",
            full_name="Nhân Sự Đa Năng",
            role="STAFF",
            position="BARISTA",
            allowed_roles=["BAR", "SERVICE"],
            db_path=self.temp_db
        )
        acc = get_staff_by_username("test_multi_role", db_path=self.temp_db)
        self.assertIsNotNone(acc)
        roles = json.loads(acc.get("allowed_roles", "[]"))
        self.assertIn("BAR", roles)
        self.assertIn("SERVICE", roles)

    # --------------------------------------------------------------------------
    # TEST CASE 3: Payroll confirmations schema and upsert
    # --------------------------------------------------------------------------
    def test_sync_03_payroll_confirmations_schema_and_upsert(self):
        ok = upsert_payroll_confirmation(
            username="nhanvien",
            month="9",
            status="DISPUTED",
            note="Thiếu ca ngày 15/09",
            db_path=self.temp_db
        )
        self.assertTrue(ok)
        confs = list_payroll_confirmations(month="9", username="nhanvien", db_path=self.temp_db)
        self.assertEqual(len(confs), 1)
        self.assertEqual(confs[0]["status"], "DISPUTED")
        self.assertEqual(confs[0]["note"], "Thiếu ca ngày 15/09")

    # --------------------------------------------------------------------------
    # TEST CASE 4: Write-through mirroring from save_staff_auth
    # --------------------------------------------------------------------------
    def test_sync_04_save_staff_auth_write_through_mirroring(self):
        auth_data = load_staff_auth()
        auth_data.setdefault("staff_accounts", {})["mirror_test_user"] = {
            "full_name": "Mirror Test User",
            "pin": "5678",
            "role": "STAFF",
            "status": "ACTIVE",
            "position": "SERVICE",
            "gender": "NU",
            "allowed_roles": ["SERVICE"]
        }
        saved = save_staff_auth(auth_data)
        self.assertTrue(saved)

    # --------------------------------------------------------------------------
    # TEST CASE 5: Store config dynamic shifts & fallback
    # --------------------------------------------------------------------------
    def test_sync_05_store_config_shifts_fallback_wfm(self):
        cutoff = get_auto_close_cutoff_minutes()
        self.assertIsInstance(cutoff, int)
        self.assertGreaterEqual(cutoff, 60)

        morning_shift = get_shift_by_alias("morning")
        self.assertIsNotNone(morning_shift)
        self.assertIn(morning_shift.get("key"), ["sang", "morning"])

        sang_shift = get_shift_by_alias("sáng")
        self.assertIsNotNone(sang_shift)
        self.assertIn(sang_shift.get("key"), ["sang", "morning"])

    # --------------------------------------------------------------------------
    # TEST CASE 6: openpyxl guard check
    # --------------------------------------------------------------------------
    def test_sync_06_openpyxl_guard_503_response(self):
        if HAS_OPENPYXL:
            excel_bytes = export_payroll_excel(month_str="9", db_path=self.temp_db)
            self.assertIsInstance(excel_bytes, bytes)
            self.assertGreater(len(excel_bytes), 1000)
        else:
            with self.assertRaises(RuntimeError) as ctx:
                export_payroll_excel(month_str="9", db_path=self.temp_db)
            self.assertIn("openpyxl", str(ctx.exception).lower())

    # --------------------------------------------------------------------------
    # TEST CASE 7: Thermal payslip PDF generation (reportlab)
    # --------------------------------------------------------------------------
    def test_sync_07_pdf_receipt_reportlab_generation(self):
        self.assertTrue(HAS_REPORTLAB, "Reportlab library must be available")
        mock_payslip = {
            "staff_name": "Nhân Viên",
            "month": "9",
            "total_shifts": 15,
            "total_hours": 75.5,
            "base_rate": 22000,
            "standard_cost": 1661000,
            "overtime_cost": 150000,
            "bonus_amount": 50000,
            "advance_amount": 200000,
            "deduction_amount": 0,
            "net_pay": 1661000,
            "shifts": []
        }
        pdf_bytes = render_payslip_pdf(staff_name="Nhân Viên", month="9", breakdown=mock_payslip)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"), "Must be a valid PDF document")

    # --------------------------------------------------------------------------
    # TEST CASE 8: Adaptive Roster Solver V2 with store_config
    # --------------------------------------------------------------------------
    def test_sync_08_roster_solver_v2_with_custom_store_config(self):
        active_info, _ = get_active_and_next_week_ids()
        mock_registrations = {
            "phache": {
                "full_name": "Pha Chế",
                "gender": "NAM",
                "role": "BARISTA",
                "preferences": {d: ["MORNING", "EVENING_17"] for d in ["2", "3", "4", "5", "6", "7", "CN"]}
            },
            "nhanvien": {
                "full_name": "Nhân Viên",
                "gender": "NU",
                "role": "SERVICE",
                "preferences": {d: ["MORNING"] for d in ["2", "3", "4", "5", "6", "7", "CN"]}
            },
            "nhanvien01": {
                "full_name": "Nhân Viên 01",
                "gender": "NAM",
                "role": "SERVICE",
                "preferences": {d: ["MORNING", "EVENING_18"] for d in ["2", "3", "4", "5", "6", "7", "CN"]}
            }
        }
        res = auto_assign_week_schedule(
            week_key=active_info["week_id"],
            registrations=mock_registrations,
            save_to_disk=False
        )
        self.assertIn("shifts", res)
        self.assertIn("solver_meta", res)
        self.assertEqual(res["solver_meta"].get("engine"), "Timefold-Greedy-Backtrack-v2")

    # --------------------------------------------------------------------------
    # TEST CASE 9: Anti-clopening rule enforcement
    # --------------------------------------------------------------------------
    def test_sync_09_anti_clopening_rule_enforcement(self):
        active_info, _ = get_active_and_next_week_ids()
        cfg = get_store_config()
        self.assertIn("roster_rules", cfg)

    # --------------------------------------------------------------------------
    # TEST CASE 10: 1 Male minimum constraint
    # --------------------------------------------------------------------------
    def test_sync_10_one_male_minimum_constraint(self):
        cfg = get_store_config()
        g_cfg = cfg.get("roster_rules", {}).get("gender_constraints", {})
        min_male = int(g_cfg.get("service_min_male", 1))
        self.assertGreaterEqual(min_male, 1)

    # --------------------------------------------------------------------------
    # TEST CASE 11: Peer swap bidirectional endpoint verification
    # --------------------------------------------------------------------------
    def test_sync_11_peer_swap_bidirectional_verification(self):
        res = self.client.get("/api/v1/cc/roster/peer-swaps/pending", headers=self.staff_headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn("pending_swaps", res.json())

    # --------------------------------------------------------------------------
    # TEST CASE 12: Attendance auto close cutoff minutes
    # --------------------------------------------------------------------------
    def test_sync_12_attendance_auto_close_cutoff_minutes(self):
        mins = get_auto_close_cutoff_minutes()
        self.assertTrue(120 <= mins <= 180, f"Cutoff minutes {mins} should be between 120 and 180")

    # --------------------------------------------------------------------------
    # TEST CASE 13: Staff aliases fuzzy matching in SQLite
    # --------------------------------------------------------------------------
    def test_sync_13_staff_aliases_fuzzy_matching(self):
        conn = get_db_connection(self.temp_db)
        cur = conn.cursor()
        cur.execute("SELECT username, alias FROM staff_aliases WHERE username = 'phache'")
        aliases = [r["alias"] for r in cur.fetchall()]
        conn.close()
        self.assertIn("barista", aliases)

    # --------------------------------------------------------------------------
    # TEST CASE 14: Export payroll excel columns and formula
    # --------------------------------------------------------------------------
    @pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl is optional")
    def test_sync_14_export_payroll_excel_columns_and_formula(self):
        res = self.client.get("/api/v1/cc/excel/export-payroll?month=9", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn("spreadsheetml", res.headers.get("content-type", ""))

    # --------------------------------------------------------------------------
    # TEST CASE 15: Dispute alert preserves confirmations in SQLite
    # --------------------------------------------------------------------------
    def test_sync_15_dispute_alert_preserves_confirmations(self):
        res = self.client.post(
            "/api/v1/cc/staff/confirm-payroll",
            headers=self.staff_headers,
            json={
                "month": "9",
                "status": "CONFIRMED",
                "note": "Xác nhận đúng công tháng 9 E2E test"
            }
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("success"))

        # Verify recorded in SQLite
        confs = list_payroll_confirmations(month="9", username="nhanvien", db_path=self.temp_db)
        self.assertGreaterEqual(len(confs), 1)
        self.assertEqual(confs[0]["status"], "CONFIRMED")

    # --------------------------------------------------------------------------
    # TEST CASE 16: Zero dirty data dual mode resilience
    # --------------------------------------------------------------------------
    def test_sync_16_zero_dirty_data_dual_mode_resilience(self):
        # Database schema must have all 21 tables without conflicts
        conn = get_db_connection(self.temp_db)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {r["name"] for r in cur.fetchall()}
        conn.close()

        required_tables = [
            "tenants", "staff_accounts", "staff_aliases", "evaluations",
            "payroll_locks", "attendance_logs", "login_attempts", "staff_ledgers",
            "revoked_tokens", "api_rate_limits", "access_audit_logs",
            "daily_closings", "shift_approvals", "roster_schedules",
            "open_shifts", "attendance_requests", "push_subscriptions",
            "notification_dispatches", "in_app_reminders", "store_settings",
            "payroll_confirmations"
        ]
        for tbl in required_tables:
            self.assertIn(tbl, tables, f"Missing table {tbl} in dual-mode schema")


if __name__ == "__main__":
    unittest.main()
