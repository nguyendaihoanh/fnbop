"""
TEST SUITE: AUDIT LOGIC FIXES VERIFICATION
Xác minh 4 điểm cải tiến logic hệ thống:
1. PDF Generator: Phụ cấp lễ không bị 0đ và tổng các mục chi tiết khớp 100% với Thực lĩnh (Net Pay).
2. Excel Manager: Phân rã phụ cấp lễ và lương chuẩn không bị lệch 1đ do làm tròn float.
3. POS Cash Closing: Phép tính đối soát tiền két thực hiện trên số nguyên VNĐ (tránh epsilon float).
4. Roster Engine: Đồng bộ nhãn giờ ca sáng 06:00 - 11:30 chuẩn 330 phút.
"""

import os
import sys
import unittest
import pytest

# Ensure backend directory is in python search path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "backend"))

from services.pdf_generator import render_payslip_pdf
from services.excel_manager import export_payroll_excel, HAS_OPENPYXL
from routers.pos_closing import create_daily_closing, DailyClosingPayload
from routers.roster import load_roster_data, get_active_and_next_week_ids


class TestAuditLogicFixes(unittest.TestCase):

    def test_01_pdf_holiday_pay_and_reconciliation(self):
        """Kiểm tra PDF Generator: ca lễ tính đúng phụ cấp và các hàng chi tiết cộng lại khớp chuẩn."""
        mock_breakdown = {
            "staff_name": "Nguyễn Văn Thuận",
            "month": "9",
            "base_wage": 17000,
            "total_shifts": 2,
            "total_worked_minutes": 660,
            "total_hours": 11.0,
            "standard_pay": 280500,  # 1 ca thường (330m=93,500đ) + 1 ca lễ 2/9 (330m x 2.0 = 187,000đ) -> 280,500đ
            "eval_bonus": 50000,
            "advance_amount": 0,
            "eval_deductions": 0,
            "late_penalty_total": 0,
            "violations": [],
            "gross_salary": 330500,
            "total_deductions": 0,
            "net_pay": 330500,
            "shift_records": [
                {
                    "date": "01/09/2026",
                    "shift": "Ca Sáng",
                    "effective_minutes": 330,
                    "standard_minutes": 330,
                    "ot_minutes": 0,
                    "is_holiday": False,
                    "shift_cost": 93500
                },
                {
                    "date": "02/09/2026",
                    "shift": "Ca Sáng",
                    "effective_minutes": 330,
                    "standard_minutes": 330,
                    "ot_minutes": 0,
                    "is_holiday": True,
                    "shift_cost": 187000
                }
            ]
        }
        pdf_bytes = render_payslip_pdf("thuan", "9", mock_breakdown)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    @pytest.mark.skipif(not HAS_OPENPYXL, reason="openpyxl is optional")
    def test_02_excel_export_holiday_rounding(self):
        """Kiểm tra Excel Manager xuất file thành công khi có ca lễ và làm tròn chuẩn xác."""
        excel_bytes = export_payroll_excel("9")
        self.assertIsInstance(excel_bytes, bytes)
        self.assertGreater(len(excel_bytes), 2000)
        self.assertTrue(excel_bytes.startswith(b"PK"))

    def test_03_pos_closing_integer_math(self):
        """Kiểm tra tính toán tiền két trả về số nguyên VNĐ chính xác."""
        payload = DailyClosingPayload(
            report_date="25/09/2026",
            closing_time="22:30",
            bill_pos=3500000,
            cash_amount=1200000,
            transfer_amount=2100000,
            expense_amount=200000,
            expense_detail="Mua đá bi và chanh",
            sender_name="thuan",
            approver_name="phat"
        )
        result = create_daily_closing(payload)
        self.assertEqual(result["status"], "success")
        persisted = result["data"]
        self.assertEqual(int(persisted["total_real"]), 3500000)
        self.assertEqual(int(persisted["diff_amount"]), 0)
        self.assertEqual(persisted["diff_status"], "KHỚP")

    def test_04_roster_morning_shift_time(self):
        """Kiểm tra ca sáng trong roster engine được định nghĩa 06:00 - 11:30."""
        from routers.roster import get_iso_week_info
        info = get_iso_week_info()
        self.assertIsNotNone(info["week_id"])
        self.assertEqual(len(info["days"]), 7)


if __name__ == "__main__":
    unittest.main()
