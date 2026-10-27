import json
import unittest
import unicodedata
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from backend.services.payroll_calc import calculate_staff_payslip_breakdown, get_canonical_name


def remove_accents(input_str):
    if not input_str:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(input_str))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).replace("đ", "d").replace("Đ", "D")


def resolve_staff_key(uname, acc, emp_keys):
    my_uname = uname.lower().strip()
    my_name = acc.get("full_name", "").strip()
    my_sheet_names = acc.get("sheet_names", [])

    # Ưu tiên 1: So khớp chính xác tuyệt đối CÓ DẤU theo sheet_names
    for sn in my_sheet_names:
        if not sn:
            continue
        canon_sn = get_canonical_name(sn)
        for k in emp_keys:
            if k == sn or k == canon_sn or get_canonical_name(k) == canon_sn:
                return k

    # Ưu tiên 2: So khớp chính xác tuyệt đối CÓ DẤU theo full_name
    if my_name:
        canon_name = get_canonical_name(my_name)
        for k in emp_keys:
            if k == my_name or k == canon_name or get_canonical_name(k) == canon_name:
                return k

    # Ưu tiên 3: So khớp không dấu (loại trừ THIỆN / THIÊN)
    for sn in my_sheet_names:
        if not sn:
            continue
        upper_sn = sn.upper()
        if upper_sn in ["THIỆN", "THIÊN"]:
            continue
        norm_sn = remove_accents(sn).upper()
        for k in emp_keys:
            if remove_accents(k).upper() == norm_sn:
                return k

    # Ưu tiên 4: So khớp chính xác username
    if my_uname:
        for k in emp_keys:
            norm_k = remove_accents(k).lower().replace(" ", "")
            if norm_k == my_uname:
                return k
    return None


class TestStaffIdentityMatching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_file = os.getenv("AUTH_FILE") or ("data/staff_auth.json" if os.path.exists("data/staff_auth.json") else "backend/staff_auth.json")
        with open(auth_file, encoding="utf-8") as f:
            cls.auth = json.load(f)
        data_file = os.getenv("DATA_FILE") or "data/data.json"
        with open(data_file, encoding="utf-8") as f:
            cls.data = json.load(f)

    def test_bin_canonical_and_breakdown(self):
        """Kiểm tra tài khoản phache không bị gán nhầm sang nhanvien."""
        staff_accounts = self.auth.get("staff_accounts", {})
        self.assertIn("phache", staff_accounts)
        bin_acc = staff_accounts["phache"]
        self.assertIn(bin_acc.get("full_name"), ["Pha Chế", "Nhân Viên Pha Chế"])
        self.assertIn("PHACHE", [s.upper() for s in bin_acc.get("sheet_names", [])])
        self.assertNotIn("NHANVIEN", [s.upper() for s in bin_acc.get("sheet_names", [])])

        target_name = bin_acc.get("full_name")
        # Mock dataset tháng 9 cho phache và nhanvien để test tính lương và tách ca
        mock_data = {
            "NHÂN VIÊN": [
                ["STT", "TÊN NHÂN VIÊN", "TỔNG PHÚT", "LƯƠNG/GIỜ", "TỔNG LƯƠNG"],
                ["1", target_name, "6900", "22000", "2530000"],
                ["2", "Nhân Viên", "1025", "18000", "307500"]
            ],
            "DỮ LIỆU": [
                ["STT", "Ngày", "Tên", "Ca", "Vào", "Ra", "Phút", "Ghi chú", "Tháng"],
            ] + [
                [str(i), f"{i:02d}/09/2026", "PHACHE", "Ca Tối", "18:00", "23:00", "300", "OK", "9"]
                for i in range(1, 24)
            ] + [
                ["24", "01/09/2026", "NHANVIEN", "Ca Sáng", "06:00", "12:00", "360", "OK", "9"],
                ["25", "02/09/2026", "NHANVIEN", "Ca Sáng", "06:00", "13:20", "440", "OK", "9"],
                ["26", "02/09/2026", "NHANVIEN", "Ca Tối", "17:25", "23:00", "335", "OK", "9"]
            ],
            "ĐÁNH GIÁ": [],
            "SỔ PHỤ": []
        }

        # Tính lương Tháng 9 cho phache
        breakdown_bin = calculate_staff_payslip_breakdown(target_name, "9", mock_data, staff_accounts=staff_accounts)
        self.assertEqual(breakdown_bin.get("staff_name"), target_name)
        self.assertEqual(breakdown_bin.get("total_shifts"), 23)
        self.assertGreater(breakdown_bin.get("total_hours"), 40.0)

    def test_nhanvien02_breakdown(self):
        """Kiểm tra tài khoản nhanvien sở hữu đúng 3 ca làm riêng trong tháng 9."""
        staff_accounts = self.auth.get("staff_accounts", {})
        nv_acc = staff_accounts.get("nhanvien", {})
        target_nv_name = nv_acc.get("full_name") or "Nhân Viên"
        mock_data = {
            "NHÂN VIÊN": [
                ["STT", "TÊN NHÂN VIÊN", "TỔNG PHÚT", "LƯƠNG/GIỜ", "TỔNG LƯƠNG"],
                ["1", target_nv_name, "1025", "18000", "307500"]
            ],
            "DỮ LIỆU": [
                ["STT", "Ngày", "Tên", "Ca", "Vào", "Ra", "Phút", "Ghi chú", "Tháng"],
                ["1", "01/09/2026", "NHANVIEN", "Ca Sáng", "06:00", "12:00", "360", "OK", "9"],
                ["2", "02/09/2026", "NHANVIEN", "Ca Sáng", "06:00", "13:20", "440", "OK", "9"],
                ["3", "02/09/2026", "NHANVIEN", "Ca Tối", "17:25", "23:00", "335", "OK", "9"]
            ],
            "ĐÁNH GIÁ": [],
            "SỔ PHỤ": []
        }
        breakdown_thien = calculate_staff_payslip_breakdown(target_nv_name, "9", mock_data, staff_accounts=staff_accounts)
        self.assertEqual(breakdown_thien.get("staff_name"), target_nv_name)
        self.assertEqual(breakdown_thien.get("total_shifts"), 3)
        # Ca sáng 1/9 (360p <= 330p+30p OT), Ca sáng 2/9 (440p pending -> 330p), Ca tối 2/9 (335p <= 360p) = 1025p = 17.08h
        self.assertEqual(breakdown_thien.get("total_hours"), 17.08)

    def test_strict_matching_all_accounts(self):
        """Kiểm tra toàn bộ danh bạ không tài khoản nào bị dính lỗi substring includes hoặc nhầm dấu."""
        staff_accounts = self.auth.get("staff_accounts", {})
        emp_keys = [k.upper() for k in staff_accounts.keys()]

        for uname, acc in staff_accounts.items():
            matched = resolve_staff_key(uname, acc, emp_keys)

            # Specific assertions
            if uname == "nhanvien03":
                self.assertEqual(matched, "NHANVIEN03")
            elif uname == "nhanvien02":
                self.assertEqual(matched, "NHANVIEN02")
            elif uname == "nhanvien19":
                self.assertEqual(matched, "NHANVIEN19")
            elif uname == "nhanvien22":
                self.assertEqual(matched, "NHANVIEN22")


if __name__ == "__main__":
    unittest.main()
