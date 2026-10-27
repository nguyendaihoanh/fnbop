import os
import sys
import unittest
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from services.roster_service import (
    SKILL_BAR,
    SKILL_SERVICE,
    SKILL_CASHIER,
    SKILL_MANAGER,
    SKILL_SECURITY,
    compute_staff_skill_mask,
    check_skill_coverage,
    validate_service_gender_pair
)
from services import roster_engine


class TestPhase4SmallShopRosterBitmask(unittest.TestCase):
    """
    Bộ kiểm thử độc lập Phase 4 theo ADR-008:
    Xếp ca kiêm nhiệm cho quán siêu nhỏ 2 - 5 người bằng Skill-Coverage Bitmask
    và nới lỏng ràng buộc mềm (Soft Constraints Relaxation), triệt tiêu 100% bế tắc/kẹt lịch (Deadlock / UNSAT).
    """

    def test_01_skill_bitmask_computation_and_coverage(self):
        """Kiểm tra tính toán SkillMask 5-bit và hàm kiểm tra độ bao phủ kỹ năng"""
        # 1. Nhân viên đa năng (Bar + Service + Thu ngân)
        acc_multi = {
            "full_name": "Lê Văn Đa Năng",
            "position": "STAFF",
            "allowed_roles": ["BAR", "SERVICE", "CASHIER"]
        }
        mask_multi = compute_staff_skill_mask(acc_multi)
        self.assertEqual(mask_multi, SKILL_BAR | SKILL_SERVICE | SKILL_CASHIER)
        self.assertEqual(mask_multi, 7)

        # 2. Nhân viên Pha chế thuần
        acc_bar = {"full_name": "Trần Pha Chế", "position": "BARISTA", "primary_role": "BAR"}
        mask_bar = compute_staff_skill_mask(acc_bar)
        self.assertTrue(bool(mask_bar & SKILL_BAR))

        # 3. Nhân viên Phục vụ thuần
        acc_svc = {"full_name": "Nguyễn Phục Vụ", "position": "SERVICE", "primary_role": "SERVICE"}
        mask_svc = compute_staff_skill_mask(acc_svc)
        self.assertTrue(bool(mask_svc & SKILL_SERVICE))

        # 4. Kiểm tra độ phủ (check_skill_coverage)
        req_shift = SKILL_BAR | SKILL_SERVICE
        accounts = {"multi": acc_multi, "bar": acc_bar, "svc": acc_svc}

        # Đa năng một mình phủ cả ca
        is_cov, comb_mask, ratio = check_skill_coverage(["multi"], accounts, req_shift)
        self.assertTrue(is_cov)
        self.assertEqual(ratio, 1.0)
        self.assertEqual(comb_mask & req_shift, req_shift)

        # Bar thuần chỉ phủ được 50% ca (thiếu Service)
        is_cov_b, _, ratio_b = check_skill_coverage(["bar"], accounts, req_shift)
        self.assertFalse(is_cov_b)
        self.assertEqual(ratio_b, 0.5)

    def test_02_small_store_2_staff_dual_role_coverage(self):
        """
        Quán cà phê siêu nhỏ 2 nhân sự kiêm nhiệm:
        Nhân sự A nghỉ ốm cả tuần, nhân sự B gánh ca sáng.
        Bảo đảm B được xếp ca kiêm nhiệm (dual_role / solo capable) và ca sáng không bị khuyết.
        """
        accounts = {
            "staff_a": {
                "full_name": "Nguyễn Văn A",
                "gender": "NAM",
                "position": "STAFF",
                "role": "STAFF",
                "status": "ACTIVE",
                "allowed_roles": ["BAR", "SERVICE"]
            },
            "staff_b": {
                "full_name": "Trần Thị B",
                "gender": "NU",
                "position": "STAFF",
                "role": "STAFF",
                "status": "ACTIVE",
                "allowed_roles": ["BAR", "SERVICE"]
            }
        }

        # A nghỉ cả tuần, B đăng ký các ca sáng từ T2 đến T6
        regs = {
            "staff_a": {"target_shifts": 0, "preferences": {"0": ["OFF"], "1": ["OFF"], "2": ["OFF"], "3": ["OFF"], "4": ["OFF"], "5": ["OFF"], "6": ["OFF"]}},
            "staff_b": {"target_shifts": 5, "preferences": {"0": ["MORNING"], "1": ["MORNING"], "2": ["MORNING"], "3": ["MORNING"], "4": ["MORNING"]}}
        }

        res = roster_engine.auto_assign_week_schedule(
            week_key="2026-W43",
            registrations=regs,
            staff_accounts=accounts,
            save_to_disk=False
        )

        self.assertTrue(res["success"])
        solver_meta = res.get("solver_meta", {})
        self.assertTrue(solver_meta.get("small_store_mode"))
        self.assertTrue(solver_meta.get("skill_mask_enabled"))

        # Xác minh các ca sáng thứ 2 (d_key: t2)
        shifts = res["shifts"]
        first_day_iso = list(shifts.keys())[0]
        m_shift = shifts[first_day_iso]["morning"]

        # B được xếp làm Barista kiêm nhiệm Service
        self.assertEqual(m_shift["barista"], "staff_b")
        self.assertIn("staff_b", m_shift["service"])
        self.assertTrue(m_shift.get("dual_role"))
        self.assertFalse(m_shift.get("missing_barista"))
        self.assertTrue(m_shift.get("is_fully_covered"))
        self.assertEqual(m_shift.get("coverage_ratio"), 1.0)

    def test_03_small_store_gender_relaxation_when_all_female(self):
        """
        Quán nhỏ 3 nhân sự đều là Nữ (không có Nam).
        Ràng buộc thể lực được nới lỏng an toàn (Soft Constraint Relaxation)
        để không bị bỏ hoang ca và không rơi vào bế tắc (Deadlock).
        """
        accounts = {
            "lan": {"full_name": "Ngọc Lan", "gender": "NU", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["BAR", "SERVICE"]},
            "mai": {"full_name": "Thanh Mai", "gender": "NU", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["SERVICE"]},
            "cuc": {"full_name": "Kim Cúc", "gender": "NU", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["SERVICE"]}
        }

        # Lan làm Bar sáng, Mai và Cúc cùng đăng ký phục vụ sáng thứ 2
        regs = {
            "lan": {"target_shifts": 5, "preferences": {"0": ["MORNING"]}},
            "mai": {"target_shifts": 5, "preferences": {"0": ["MORNING"]}},
            "cuc": {"target_shifts": 5, "preferences": {"0": ["MORNING"]}}
        }

        res = roster_engine.auto_assign_week_schedule(
            week_key="2026-W43",
            registrations=regs,
            staff_accounts=accounts,
            save_to_disk=False
        )

        shifts = res["shifts"]
        first_day_iso = list(shifts.keys())[0]
        m_shift = shifts[first_day_iso]["morning"]

        # Cả Mai và Cúc (2 Nữ) đều được xếp vào phục vụ mà không bị chặn
        self.assertEqual(len(m_shift["service"]), 2)
        self.assertIn("mai", m_shift["service"])
        self.assertIn("cuc", m_shift["service"])

        # Kiểm tra nhật ký nới lỏng ràng buộc
        solver_meta = res.get("solver_meta", {})
        relaxed = solver_meta.get("relaxed_constraints", [])
        gender_relax_entries = [r for r in relaxed if r.get("type") == "GENDER_RELAXED"]
        self.assertGreater(len(gender_relax_entries), 0)

    def test_04_small_store_weekend_evening_dual_role(self):
        """
        Ca tối cuối tuần (T7, CN) yêu cầu Barista (1) và Service (2).
        Quán nhỏ 2 nhân sự: 1 bạn đa năng kiêm nhiệm cả Bar và Service ca tối.
        """
        accounts = {
            "dung": {"full_name": "Nguyễn Tiến Dũng", "gender": "NAM", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["BAR", "SERVICE"]},
            "hoa": {"full_name": "Lê Thị Hoa", "gender": "NU", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["SERVICE"]}
        }

        # Đăng ký ca tối Thứ Bảy (index 5)
        regs = {
            "dung": {"target_shifts": 3, "preferences": {"5": ["EVENING_17"]}},
            "hoa": {"target_shifts": 3, "preferences": {"5": ["EVENING_18"]}}
        }

        res = roster_engine.auto_assign_week_schedule(
            week_key="2026-W43",
            registrations=regs,
            staff_accounts=accounts,
            save_to_disk=False
        )

        shifts = res["shifts"]
        days = list(shifts.keys())
        sat_iso = days[5]
        sat_ev = shifts[sat_iso]["evening"]

        # Dũng kiêm nhiệm Barista ca tối và Service 17
        self.assertEqual(sat_ev["barista"], "dung")
        self.assertFalse(sat_ev.get("missing_barista"))
        self.assertEqual(sat_ev["service_17"], "dung")
        self.assertEqual(sat_ev["service_18"], "hoa")
        self.assertTrue(sat_ev.get("dual_role"))
        self.assertTrue(sat_ev.get("is_fully_covered"))

    def test_05_anti_clopening_relaxation_for_small_shop_when_no_other_candidate(self):
        """
        Quán nhỏ 2 nhân sự: A nghỉ, B làm tối Thứ Hai (0) và sáng Thứ Ba (1).
        Mặc dù B bị clopening (nghỉ ngắn giữa ca tối và sáng hôm sau),
        thuật toán nới lỏng ràng buộc mềm để xếp B ca sáng, không để quán bị đóng cửa.
        """
        accounts = {
            "staff_b": {"full_name": "Trần B", "gender": "NAM", "position": "STAFF", "role": "STAFF", "status": "ACTIVE", "allowed_roles": ["BAR", "SERVICE"]}
        }

        # B làm tối T2 (0) và sáng T3 (1)
        regs = {
            "staff_b": {"target_shifts": 3, "preferences": {"0": ["EVENING_17"], "1": ["MORNING"]}}
        }

        res = roster_engine.auto_assign_week_schedule(
            week_key="2026-W43",
            registrations=regs,
            staff_accounts=accounts,
            save_to_disk=False
        )

        shifts = res["shifts"]
        days = list(shifts.keys())
        t2_iso = days[0]
        t3_iso = days[1]

        # T2 tối: staff_b được xếp
        self.assertEqual(shifts[t2_iso]["evening"]["service_17"], "staff_b")

        # T3 sáng: staff_b vẫn được xếp dù bị clopening (soft constraint relaxed)
        self.assertEqual(shifts[t3_iso]["morning"]["barista"], "staff_b")
        self.assertFalse(shifts[t3_iso]["morning"].get("missing_barista"))

        # Kiểm tra relaxed_constraints có ghi nhận CLOPENING_RELAXED
        solver_meta = res.get("solver_meta", {})
        relaxed = solver_meta.get("relaxed_constraints", [])
        clopen_entries = [r for r in relaxed if r.get("type") == "CLOPENING_RELAXED"]
        self.assertGreater(len(clopen_entries), 0)


if __name__ == "__main__":
    unittest.main()

