import unittest
import json
import os

class TestPayrollLogic(unittest.TestCase):
    def setUp(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.data_json_path = os.path.join(self.project_root, "data", "data.json")
        if not os.path.exists(self.data_json_path):
            self.data_json_path = os.path.join(self.project_root, "data", "data.json")

    def test_01_data_json_validity(self):
        """Kiểm tra data.json tồn tại và có cú pháp JSON hợp lệ"""
        self.assertTrue(os.path.exists(self.data_json_path), "File data/data.json phải tồn tại")
        with open(self.data_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict, "data.json phải là dictionary")
        self.assertTrue(len(data.keys()) > 0, "data.json không được rỗng")

    def test_02_overtime_calculation(self):
        """Kiểm tra logic quy đổi OT: ca tiêu chuẩn vs OT > 300 phút"""
        def calculate_shift_hours(start_min, end_min):
            duration_minutes = end_min - start_min
            if duration_minutes < 0:
                duration_minutes += 24 * 60
            hours = duration_minutes / 60.0
            return hours

        # Ca thường 7h00 - 15h00 (8 tiếng = 480 phút)
        normal_hours = calculate_shift_hours(7 * 60, 15 * 60)
        self.assertEqual(normal_hours, 8.0)

        # Ca gãy hoặc OT 300 phút (5 tiếng)
        ot_hours = calculate_shift_hours(17 * 60, 22 * 60)
        self.assertEqual(ot_hours, 5.0)

    def test_03_holiday_multiplier(self):
        """Kiểm tra hệ số ngày Lễ Quốc Khánh 2/9 nhân x2"""
        def get_pay_multiplier(date_str):
            if "-09-02" in date_str or "/09/02" in date_str or "02/09" in date_str:
                return 2.0
            return 1.0

        self.assertEqual(get_pay_multiplier("2026-09-02"), 2.0)
        self.assertEqual(get_pay_multiplier("2026-09-01"), 1.0)
        self.assertEqual(get_pay_multiplier("02/09/2026"), 2.0)

    def test_04_clean_duplicate_shifts_logic(self):
        """Kiểm tra logic loại bỏ ca trùng lặp (Dedup)"""
        shifts = [
            {"staff": "Nguyen Van A", "date": "2026-09-01", "shift": "Ca Sang", "id": 1},
            {"staff": "Nguyen Van A", "date": "2026-09-01", "shift": "Ca Sang", "id": 2}, # Trùng
            {"staff": "Nguyen Van A", "date": "2026-09-01", "shift": "Ca Toi", "id": 3},  # Khác ca
            {"staff": "Tran Thi B", "date": "2026-09-01", "shift": "Ca Sang", "id": 4}
        ]

        seen = set()
        deduped = []
        for s in shifts:
            key = (s["staff"], s["date"], s["shift"])
            if key not in seen:
                seen.add(key)
                deduped.append(s)

        self.assertEqual(len(deduped), 3)
        self.assertEqual(deduped[0]["id"], 1)
        self.assertEqual(deduped[1]["id"], 3)
        self.assertEqual(deduped[2]["id"], 4)

    def test_05_late_deduction_policy(self):
        """Kiểm tra chính sách khấu trừ đi trễ của FnBOps Lounge"""
        def calculate_late_penalty(minutes_late):
            if minutes_late <= 15:
                return 0
            elif minutes_late <= 30:
                return 20000
            else:
                return 50000

        self.assertEqual(calculate_late_penalty(10), 0)
        self.assertEqual(calculate_late_penalty(15), 0)
        self.assertEqual(calculate_late_penalty(20), 20000)
        self.assertEqual(calculate_late_penalty(30), 20000)
        self.assertEqual(calculate_late_penalty(35), 50000)

    def test_06_roster_headcount_standard(self):
        """Kiểm tra chuẩn định biên tối thiểu theo ca (Roster Minimum Standards)"""
        def validate_roster_headcount(shift_name, staff_count):
            standards = {
                "Sáng": 4, # 2 Barista, 1 Thu ngân, 1 Phục vụ
                "Tối": 5   # 2 Barista, 1 Thu ngân, 2 Phục vụ
            }
            standard = standards.get(shift_name, 3)
            return {
                "required": standard,
                "actual": staff_count,
                "is_sufficient": staff_count >= standard,
                "missing": max(0, standard - staff_count)
            }

        sang_check = validate_roster_headcount("Sáng", 4)
        self.assertTrue(sang_check["is_sufficient"])
        self.assertEqual(sang_check["missing"], 0)

        sang_short = validate_roster_headcount("Sáng", 3)
        self.assertFalse(sang_short["is_sufficient"])
        self.assertEqual(sang_short["missing"], 1)

        toi_check = validate_roster_headcount("Tối", 5)
        self.assertTrue(toi_check["is_sufficient"])

    def test_07_data_json_row_integrity(self):
        """Kiểm tra tính toàn vẹn các hàng chấm công thực tế trong data.json"""
        with open(self.data_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        du_lieu = data.get("DỮ LIỆU", [])
        self.assertTrue(len(du_lieu) > 1, "Tab DỮ LIỆU phải có ít nhất 1 hàng dữ liệu ngoài header")
        
        header = du_lieu[0]
        # Các cột bắt buộc trong sheet DỮ LIỆU
        self.assertTrue(any("Nhân Viên" in str(col) or "Tên" in str(col) for col in header))
        self.assertTrue(any("Ngày" in str(col) for col in header))
        self.assertTrue(any("Ca" in str(col) for col in header))

    def test_08_shift_standard_thresholds(self):
        """Kiểm tra chuẩn ngưỡng ca làm việc mới:
        - Ca sáng (06:00 - 11:30): chuẩn 330 phút (5.5h)
        - Ca tối vào từ 17h (17:00 - 23:00): chuẩn 360 phút (6.0h)
        - Ca tối vào từ 18h (18:00 - 23:00): chuẩn 300 phút (5.0h)
        """
        import sys
        backend_dir = os.path.join(self.project_root, "backend")
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from services.payroll_calc import get_shift_standard_mins

        # 1. Ca sáng
        self.assertEqual(get_shift_standard_mins("Ca Sáng", "06:00"), 330)
        self.assertEqual(get_shift_standard_mins("Sáng", "06:15"), 330)
        self.assertEqual(get_shift_standard_mins("Morning", "07:00"), 330)

        # 2. Ca tối vào từ 17h
        self.assertEqual(get_shift_standard_mins("Ca Tối 17h", "17:00"), 360)
        self.assertEqual(get_shift_standard_mins("Tối", "16:55"), 360)
        self.assertEqual(get_shift_standard_mins("Tối", "17:15"), 360)
        self.assertEqual(get_shift_standard_mins("Tối", "17:30"), 300)

        # 3. Ca tối vào từ 18h
        self.assertEqual(get_shift_standard_mins("Ca Tối 18h", "18:00"), 300)
        self.assertEqual(get_shift_standard_mins("Tối", "18:00"), 300)
        self.assertEqual(get_shift_standard_mins("Tối", "18:15"), 300)
        self.assertEqual(get_shift_standard_mins("Tối", "19:00"), 300)


if __name__ == "__main__":
    unittest.main()
