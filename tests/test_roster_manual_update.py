import os
import sys
import unittest
import json
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from main import app
from routers import roster as roster_router
from routers.fnb_ops import DEFAULT_AUTH_FILE, create_access_token

class TestRosterManualUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Create tokens
        cls.admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "user_type": "admin"})
        cls.manager_token = create_access_token({"sub": "manager", "role": "MANAGER", "user_type": "staff"})
        cls.staff_token = create_access_token({"sub": "nhanvien", "role": "STAFF", "user_type": "staff"})

    def test_01_staff_cannot_update_shift(self):
        """Nhân viên thường không được phép sửa/fill ca (phải bị 403)"""
        headers = {"Authorization": f"Bearer {self.staff_token}"}
        res = self.client.post("/api/v1/cc/roster/update-shift", headers=headers, json={
            "week_id": "current",
            "date": "2026-09-14",
            "shift_period": "morning",
            "slot_type": "barista",
            "username": "phache"
        })
        self.assertEqual(res.status_code, 403)

    def test_02_manager_can_manually_assign_barista(self):
        """Quản lý có thể gán Barista vào ca sáng thành công"""
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        res = self.client.post("/api/v1/cc/roster/update-shift", headers=headers, json={
            "week_id": "current",
            "date": "2026-09-14",
            "shift_period": "morning",
            "slot_type": "barista",
            "username": "phache"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])

    def test_03_manager_clear_slot(self):
        """Quản lý có thể xóa người khỏi slot (để trống hoặc fill lại)"""
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        res = self.client.post("/api/v1/cc/roster/update-shift", headers=headers, json={
            "week_id": "current",
            "date": "2026-09-14",
            "shift_period": "morning",
            "slot_type": "barista",
            "username": None
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])

    def test_04_inactive_staff_rejected(self):
        """Không cho phép gán nhân sự đã nghỉ việc (INACTIVE) vào ca trực"""
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        res = self.client.post("/api/v1/cc/roster/update-shift", headers=headers, json={
            "week_id": "current",
            "date": "2026-09-14",
            "shift_period": "morning",
            "slot_type": "barista",
            "username": "nhanvien01" # inactive
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("đã nghỉ việc", res.json()["detail"])

    def test_05_update_shift_syncs_days_structure(self):
        """Kiểm tra đồng bộ 2 chiều: Khi update ca trong shifts, cấu trúc days cũng được cập nhật"""
        headers = {"Authorization": f"Bearer {self.manager_token}"}
        res = self.client.post("/api/v1/cc/roster/update-shift", headers=headers, json={
            "week_id": "current",
            "date": "2026-09-14",
            "shift_period": "morning",
            "slot_type": "barista",
            "username": "phache"
        })
        self.assertEqual(res.status_code, 200)

        r_data = roster_router.load_roster_data()
        active_info, _ = roster_router.get_active_and_next_week_ids()
        week_entry = r_data.get("weeks", {}).get(active_info["week_id"], {})
        # 2026-09-14 is a Monday -> key "mon"
        if "days" in week_entry and "mon" in week_entry["days"]:
            mon_bar = week_entry["days"]["mon"]["sang"].get("barista")
            self.assertIn("phache", mon_bar if isinstance(mon_bar, list) else [mon_bar])

    def test_06_pinned_slots_preserved_in_auto_assign(self):
        """Kiểm tra thuật toán auto_assign bảo toàn các slot đã gán tay (pinned slots)"""
        from services.roster_engine import auto_assign_week_schedule
        accounts = {
            "p1": {"full_name": "Pha Che 1", "gender": "NU", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["BAR"]},
            "p2": {"full_name": "Pha Che 2", "gender": "NAM", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["BAR"]},
            "s1": {"full_name": "Phuc Vu 1", "gender": "NAM", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["SERVICE"]},
            "s2": {"full_name": "Phuc Vu 2", "gender": "NU", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["SERVICE"]}
        }
        regs = {u: {"target_shifts": 6, "preferences": {"0": ["MORNING", "EVENING"]}} for u in accounts}
        # Pre-pin p2 into morning barista for day 0
        existing_shifts = {
            "2026-10-26": {
                "morning": {"barista": "p2", "service": ["s1", None]},
                "evening": {"barista": None, "service": [None, None], "service_17": None, "service_18": None}
            }
        }
        res = auto_assign_week_schedule(
            week_key="2026-W44",
            registrations=regs,
            staff_accounts=accounts,
            shifts=existing_shifts,
            save_to_disk=False
        )
        assigned_day0 = res["shifts"].get("2026-10-26", {}).get("morning", {})
        # Pinned barista p2 must be strictly preserved!
        self.assertEqual(assigned_day0.get("barista"), "p2")
        self.assertIn("s1", assigned_day0.get("service", []))

if __name__ == "__main__":
    unittest.main()
