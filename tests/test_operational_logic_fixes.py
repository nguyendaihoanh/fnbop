"""
TEST SUITE: OPERATIONAL LOGIC FIXES VERIFICATION
Kiểm tra toàn diện 6 giải pháp khắc phục khuyết tật vận hành:
1. Maker-Checker: Đánh giá ca ở trạng thái PENDING hoặc REJECTED không được lọt vào SỔ PHỤ.
2. Chấm công: Tham số custom_time_str bị vô hiệu hóa đối với nhân viên thường (chống gian lận giờ).
3. Ca mồ côi: Tự động đóng ca cũ khi nhân viên vào ca mới mà quên dập thẻ ra.
4. Chốt két POS: Chống gửi trùng lặp bản ghi và kích hoạt cảnh báo Telegram khi lệch > 50.000đ.
5. Duyệt OT: Quản lý bị chặn không thể tự duyệt tăng ca cho chính mình.
6. Sổ phụ: Chỉ Admin mới có quyền xóa các bản ghi trong Sổ Phụ.
"""

import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime

# Ensure backend directory is in python search path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "backend"))

from fastapi import HTTPException
from fastapi.testclient import TestClient
from main import app
from routers.fnb_ops import create_access_token
from routers.pos_closing import create_daily_closing, DailyClosingPayload
from routers.attendance import load_attendance_logs, save_attendance_logs, checkin_attendance, CheckinPayload


class TestOperationalLogicFixes(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.admin_token = create_access_token({"sub": "admin", "role": "ADMIN", "name": "Chủ Hộ (Admin)"})
        self.manager_token = create_access_token({"sub": "manager", "role": "MANAGER", "name": "Quản Lý Ca"})
        self.staff_token = create_access_token({"sub": "nhanvien", "role": "STAFF", "name": "Nhân Viên"})

    def test_01_maker_checker_rejected_and_pending_evaluations_not_in_so_phu(self):
        """Xác nhận các đánh giá PENDING hoặc REJECTED tuyệt đối không lọt vào SỔ PHỤ."""
        mock_evals = [
            {"id": "ev_1", "staffName": "nhanvien", "month": "9", "status": "PENDING", "type": "Thưởng", "amount": 100000, "reason": "Test pending"},
            {"id": "ev_2", "staffName": "nhanvien", "month": "9", "status": "REJECTED", "type": "Phạt", "amount": 50000, "reason": "Test rejected"},
            {"id": "ev_3", "staffName": "nhanvien", "month": "9", "status": "APPROVED", "type": "Thưởng", "amount": 200000, "reason": "Test approved"}
        ]
        with patch("routers.fnb_ops.load_evaluations", return_value=mock_evals):
            res = self.client.get(
                "/api/v1/cc/data?month=9",
                headers={"Authorization": f"Bearer {self.staff_token}"}
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            so_phu = data.get("SỔ PHỤ", [])
            # Tìm các dòng sinh tự động từ đánh giá
            auto_eval_reasons = [str(r[6]) for r in so_phu[1:] if len(r) > 6]
            self.assertNotIn("Test pending", auto_eval_reasons, "PENDING eval không được vào SỔ PHỤ")
            self.assertNotIn("Test rejected", auto_eval_reasons, "REJECTED eval không được vào SỔ PHỤ")
            self.assertIn("Test approved", auto_eval_reasons, "APPROVED eval phải vào SỔ PHỤ")

    def test_02_custom_time_str_ignored_for_regular_staff(self):
        """Xác nhận nhân viên thường không thể dùng custom_time_str để gian lận giờ vào ca."""
        # Gọi checkin với staff token và custom_time_str="06:00"
        # Với IP không phải cafe wifi và không dev_override, nhân viên không được can thiệp
        mock_payload = CheckinPayload(
            username="nhanvien",
            custom_time_str="06:00",
            dev_override_wifi=False
        )
        mock_request = MagicMock()
        mock_request.headers = {"authorization": f"Bearer {self.staff_token}"}
        mock_request.client.host = "192.168.1.100"

        with patch("routers.attendance.get_client_ip", return_value="203.0.113.10"), \
             patch("routers.attendance.get_current_cafe_ip", return_value="203.0.113.10"), \
             patch("routers.attendance.is_matching_cafe_wifi", return_value=True), \
             patch("routers.attendance.load_attendance_logs", return_value=[]), \
             patch("routers.attendance.safe_json_write", return_value=True), \
             patch("routers.attendance.record_access_audit"), \
             patch("routers.fnb_ops.load_staff_auth", return_value={"staff_accounts": {"nhanvien": {"role": "STAFF", "status": "ACTIVE"}}}):
            # Giả lập thời gian thực tế hiện tại là 07:30 (đi trễ)
            with patch("routers.attendance.datetime") as mock_dt:
                real_late_time = datetime(2026, 9, 25, 7, 30, 0)
                mock_dt.now.return_value = real_late_time
                mock_dt.strptime = datetime.strptime
                mock_dt.fromisoformat = datetime.fromisoformat
                
                # Gọi hàm checkin_attendance
                result = checkin_attendance(mock_request, mock_payload)
                self.assertEqual(result["status"], "success")
                record = result["record"]
                # Giờ checkin ghi nhận phải là giờ thực tế 07:30 (trễ 90p), KHÔNG PHẢI 06:00
                self.assertEqual(record["checkin_time"], "07:30")
                self.assertTrue(record["is_late"])
                self.assertEqual(record["late_mins"], 90)

    def test_03_orphan_shift_auto_resolved_on_next_shift_checkin(self):
        """Xác nhận ca cũ bị quên check-out được tự động chốt khi vào ca mới."""
        mock_logs = [
            {
                "id": "ATT_OLD_001",
                "username": "nhanvien",
                "date": "25/09/2026",
                "shift_key": "sang",
                "shift_name": "Ca Sáng",
                "scheduled_start": "06:00",
                "scheduled_end": "11:30",
                "checkin_time": "06:00",
                "checkout_time": None,
                "total_mins": None
            }
        ]
        mock_payload = CheckinPayload(
            username="nhanvien",
            shift_override="toi",
            dev_override_wifi=True
        )
        mock_request = MagicMock()
        mock_request.headers = {"authorization": f"Bearer {self.staff_token}"}
        mock_request.client.host = "127.0.0.1"

        with patch("routers.attendance.get_client_ip", return_value="127.0.0.1"), \
             patch("routers.attendance.load_attendance_logs", return_value=mock_logs), \
             patch("routers.fnb_ops.load_staff_auth", return_value={"staff_accounts": {"nhanvien": {"role": "STAFF", "status": "ACTIVE"}}}), \
             patch("routers.attendance.safe_json_write", return_value=True), \
             patch("routers.attendance.record_access_audit"):
            with patch("routers.attendance.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 9, 25, 17, 0, 0)
                mock_dt.strptime = datetime.strptime
                mock_dt.fromisoformat = datetime.fromisoformat
                
                result = checkin_attendance(mock_request, mock_payload)
                self.assertEqual(result["status"], "success")
                
                # Ca cũ phải được tự động chốt ra lúc 11:30 với 330 phút
                old_shift = mock_logs[0]
                self.assertEqual(old_shift["checkout_time"], "11:30")
                self.assertEqual(old_shift["total_mins"], 330)
                self.assertEqual(old_shift["closed_by"], "AUTO_RESOLVE_NEXT_SHIFT")

    def test_04_pos_closing_telegram_alert_and_duplicate_prevention(self):
        """Xác nhận chốt két gửi cảnh báo Telegram khi lệch két > 50k và chặn trùng lặp."""
        try:
            from services.db import get_db_connection
            conn = get_db_connection()
            with conn:
                conn.execute("DELETE FROM pos_closings WHERE report_date = '29/09/2026';")
                conn.execute("DELETE FROM daily_closings WHERE report_date = '29/09/2026';")
            conn.close()
        except Exception:
            pass
        try:
            from routers.pos_closing import get_pos_closings_json_path, safe_json_read, safe_json_write
            jpath = get_pos_closings_json_path()
            c_data = safe_json_read(jpath, default=[])
            if isinstance(c_data, list):
                c_data = [x for x in c_data if x.get("report_date") != "29/09/2026"]
                safe_json_write(jpath, c_data)
        except Exception:
            pass

        import random
        test_year = random.randint(2085, 2099)
        test_date = f"29/09/{test_year}"
        unique_min = random.randint(10, 59)
        payload = DailyClosingPayload(
            report_date=test_date,
            closing_time=f"23:{unique_min}",
            bill_pos=5000000,
            cash_amount=1500000,
            transfer_amount=3000000,
            expense_amount=200000,
            expense_detail="Mua nguyên liệu khẩn cấp",
            sender_name="nhanvien",
            approver_name="manager"
        )
        # total_real = 1.5m + 3.0m + 200k = 4.7m -> lệch -300k (vượt ngưỡng 50k)
        with patch("services.send_telegram.send_telegram_alert") as mock_tg:
            res1 = create_daily_closing(payload)
            self.assertEqual(res1["status"], "success")
            self.assertIn("Cảnh báo lệch két nghiêm trọng", res1["message"])
            # Telegram alert phải được gọi
            mock_tg.assert_called_once()
            tg_text = mock_tg.call_args[0][0]
            self.assertIn("CẢNH BÁO LỆCH KÉT POS365", tg_text)
            self.assertIn("300,000đ", tg_text)

            # Lần gọi thứ 2 với cùng thông tin -> chống gửi trùng
            res2 = create_daily_closing(payload)
            self.assertEqual(res2["status"], "success")
            self.assertIn("chống gửi trùng", res2["message"])

    def test_05_manager_cannot_approve_own_ot(self):
        """Xác nhận Quản lý bị chặn 403 khi tự duyệt OT cho chính mình."""
        shift_key_manager = "25/09/2026|manager|Ca Sáng|06:00"
        res = self.client.post(
            "/api/v1/cc/shifts/confirm-ot",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={
                "shift_key": shift_key_manager,
                "action": "APPROVE",
                "approved_mins": 400,
                "manager_note": "Tự duyệt tăng ca"
            }
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("Xung đột lợi ích", res.json()["detail"])

    def test_06_manager_cannot_delete_staff_ledger(self):
        """Xác nhận chỉ Admin mới có quyền xóa khoản Sổ Phụ, Manager bị chặn 403."""
        res_mgr = self.client.delete(
            "/api/v1/cc/payroll/ledger/LEDGER_123456",
            headers={"Authorization": f"Bearer {self.manager_token}"}
        )
        self.assertEqual(res_mgr.status_code, 403)
        self.assertIn("Chức năng xóa khoản Sổ Phụ chỉ dành riêng cho Quản trị viên (Admin)", res_mgr.json()["detail"])


if __name__ == "__main__":
    unittest.main()
