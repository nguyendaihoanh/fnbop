import os
import sys
import unittest
import json
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from routers import roster

class TestRosterFairAllocationAndGenderRules(unittest.TestCase):
    def setUp(self):
        self.mock_staff_accounts = {
            "nhuy": {"full_name": "Nhân Viên Barista 01", "gender": "NU", "position": "BARISTA", "role": "STAFF", "status": "ACTIVE"},
            "thuydiem": {"full_name": "Nhân Viên Phục Vụ 01", "gender": "NU", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE"},
            "thuan": {"full_name": "Nhân Viên Phục Vụ 02", "gender": "NAM", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE"},
            "vinh": {"full_name": "Nhân Viên Phục Vụ 03", "gender": "NAM", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE"},
            "phuongoanh": {"full_name": "Nhân Viên Phục Vụ 04", "gender": "NU", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE"},
            "bin": {"full_name": "Nhân Viên Phục Vụ 05", "gender": "NAM", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE"},
            "nhanvien02": {"full_name": "Nhân Viên Barista 02", "gender": "NU", "position": "BARISTA", "role": "STAFF", "status": "ACTIVE"},
            "tranminhtri": {"full_name": "Nhân Viên Phục Vụ 06", "gender": "NAM", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE"},
            "nguyen": {"full_name": "Nhân Viên Phục Vụ 07", "gender": "NAM", "position": "SERVICE", "role": "STAFF", "status": "ACTIVE"},
            "phat": {"full_name": "Quản Lý 01", "gender": "NAM", "position": "MANAGER", "role": "MANAGER", "status": "ACTIVE"}
        }

        # 8 nhân sự nộp đơn, 'nguyen' không nộp đơn
        self.w42_regs = {
            "nhuy": {"target_shifts": 3, "preferences": {"5": ["EVENING_18"], "6": ["EVENING_18"]}},
            "thuydiem": {"target_shifts": 5, "preferences": {"0": ["EVENING_18"], "1": ["MORNING", "EVENING_17"], "3": ["EVENING_17"], "5": ["MORNING"], "6": ["EVENING_17"]}},
            "thuan": {"target_shifts": 5, "preferences": {"0": ["MORNING"], "3": ["MORNING"], "4": ["EVENING_17"], "5": ["MORNING", "EVENING_18"], "6": ["MORNING"]}},
            "vinh": {"target_shifts": 5, "preferences": {"0": ["EVENING_18"], "1": ["EVENING_18"], "2": ["MORNING", "EVENING_18"], "3": ["MORNING", "EVENING_17"], "4": ["MORNING", "EVENING_17"]}},
            "phuongoanh": {"target_shifts": 5, "preferences": {"1": ["MORNING"], "2": ["MORNING"], "3": ["MORNING"], "4": ["MORNING"], "5": ["MORNING"]}},
            "bin": {"target_shifts": 5, "preferences": {"0": ["EVENING_17"], "1": ["MORNING"], "2": ["MORNING", "EVENING_18"], "3": ["MORNING"], "4": ["EVENING_17"], "5": ["EVENING_17"], "6": ["EVENING_17"]}},
            "nhanvien02": {"target_shifts": 5, "preferences": {"0": ["MORNING"], "2": ["MORNING"], "3": ["MORNING"], "4": ["MORNING"], "5": ["MORNING"], "6": ["MORNING"]}},
            "tranminhtri": {"target_shifts": 5, "preferences": {"1": ["EVENING_18"], "2": ["EVENING_17"], "3": ["EVENING_18"], "4": ["EVENING_17"], "5": ["EVENING_17"], "6": ["EVENING_17"]}}
        }

    def test_auto_assign_excludes_unregistered_staff(self):
        """Nhân viên không nộp đơn đăng ký (nguyen) tuyệt đối không bị xếp ca"""
        res = roster.auto_assign_week_schedule(
            week_key="2026-W42",
            registrations=self.w42_regs,
            staff_accounts=self.mock_staff_accounts,
            save_to_disk=False
        )
        shifts = res.get("shifts", {})
        shifts_str = json.dumps(shifts)
        self.assertNotIn("nguyen", shifts_str)
        summary = res.get("workload_summary", {})
        self.assertNotIn("Nhân Viên Phục Vụ 07", summary)

    def test_gender_rule_enforced_morning_and_evening(self):
        """Mọi ca phục vụ (sáng và tối) đều phải có ít nhất 1 Nam, không bao giờ 2 Nữ"""
        res = roster.auto_assign_week_schedule(
            week_key="2026-W42",
            registrations=self.w42_regs,
            staff_accounts=self.mock_staff_accounts,
            save_to_disk=False
        )
        shifts = res.get("shifts", {})
        for day_str, s in shifts.items():
            # Ca sáng
            m_srv = s.get("morning", {}).get("service", [])
            m_genders = [self.mock_staff_accounts[u]["gender"] for u in m_srv if u in self.mock_staff_accounts]
            if len(m_srv) >= 2:
                self.assertIn("NAM", m_genders, f"Ca sáng ngày {day_str} thiếu Nam: {m_srv} ({m_genders})")

            # Ca tối
            e_17 = s.get("evening", {}).get("service_17")
            e_18 = s.get("evening", {}).get("service_18")
            e_srv = [u for u in [e_17, e_18] if u]
            e_genders = [self.mock_staff_accounts[u]["gender"] for u in e_srv if u in self.mock_staff_accounts]
            if len(e_srv) >= 2:
                self.assertIn("NAM", e_genders, f"Ca tối ngày {day_str} thiếu Nam: {e_srv} ({e_genders})")

    def test_fair_distribution_min_quota(self):
        """Tất cả nhân sự đăng ký đều đạt tối thiểu sàn (>= 3 ca với ai rảnh >= 3 ngày)"""
        res = roster.auto_assign_week_schedule(
            week_key="2026-W42",
            registrations=self.w42_regs,
            staff_accounts=self.mock_staff_accounts,
            save_to_disk=False
        )
        summary = res.get("workload_summary", {})
        # Các nhân sự đăng ký 5 ngày trở lên đều phải đạt ít nhất 3 ca
        self.assertGreaterEqual(summary.get("Nhân Viên Phục Vụ 04", 0), 3)
        self.assertGreaterEqual(summary.get("Nhân Viên Phục Vụ 01", 0), 3)
        self.assertGreaterEqual(summary.get("Nhân Viên Phục Vụ 02", 0), 3)
        self.assertGreaterEqual(summary.get("Nhân Viên Phục Vụ 05", 0), 3)
        self.assertGreaterEqual(summary.get("Nhân Viên Barista 02", 0), 3)
        self.assertGreaterEqual(summary.get("Nhân Viên Phục Vụ 03", 0), 3)
        self.assertGreaterEqual(summary.get("Nhân Viên Phục Vụ 06", 0), 3)

if __name__ == "__main__":
    unittest.main()
