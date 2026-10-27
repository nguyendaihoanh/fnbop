import os
import sys
import pytest

_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
_backend_dir = os.path.join(_project_root, "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from services.payroll_calc import calculate_staff_payslip_breakdown


# ==============================================================================
# TEST 1: REA-PAYROLL-01 - Anti Double-Counting between staff_ledgers & so_cai_luong
# ==============================================================================
def test_rea_payroll_01_no_double_counting_advance_and_bonus():
    """
    REA-PAYROLL-01:
    Khi 1 khoản tạm ứng/thưởng/phạt được ghi vào Sổ Phụ (staff_ledgers),
    nó đồng thời ghi vết vào Sổ Cái Bất Biến (so_cai_luong).
    Bộ tính lương calculate_staff_payslip_breakdown PHẢI đối chiếu fingerprint
    và KHÔNG ĐƯỢC tính trùng lặp lần 2.
    """
    staff_name = "Nguyễn Văn A"
    month = "10"

    # 1. Khoản tạm ứng 500k xuất hiện ở cả staff_ledgers và so_cai_luong
    staff_ledgers = [
        {
            "staff_name": staff_name,
            "month": "10",
            "type": "advance",
            "amount": 500000,
            "reason": "Tạm ứng mua đồng phục"
        }
    ]

    so_cai_luong = [
        {
            "staff_name": staff_name,
            "loai_su_kien": "UNG_LUONG",
            "so_tien_thay_doi": 500000,
            "ly_do": "Tạm ứng mua đồng phục",
            "created_at": "2026-10-15 10:00:00"
        }
    ]

    calc = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=month,
        staff_ledgers=staff_ledgers,
        so_cai_luong=so_cai_luong,
        staff_accounts={"nguyen_van_a": {"hourly_rate": 20000}}
    )

    # advance_amount PHẢI bằng đúng 500,000đ, KHÔNG ĐƯỢC bằng 1,000,000đ
    assert calc["advance_amount"] == 500000, (
        f"Lỗi Double-Counting: advance_amount bị nhân đôi! "
        f"Kỳ vọng 500,000đ, thực tế={calc['advance_amount']}"
    )

    # 2. Thêm khoản thưởng 200k xuất hiện ở cả 2 nơi
    staff_ledgers.append({
        "staff_name": staff_name,
        "month": "10",
        "type": "bonus",
        "amount": 200000,
        "reason": "Thưởng chuyên cần tuần 1"
    })
    so_cai_luong.append({
        "staff_name": staff_name,
        "loai_su_kien": "THUONG",
        "so_tien_thay_doi": 200000,
        "ly_do": "Thưởng chuyên cần tuần 1",
        "created_at": "2026-10-15 10:05:00"
    })

    # 3. Thêm khoản phạt 50k xuất hiện ở cả 2 nơi
    staff_ledgers.append({
        "staff_name": staff_name,
        "month": "10",
        "type": "deduction",
        "amount": 500000,
        "reason": "Phạt làm vỡ ly"
    })
    so_cai_luong.append({
        "staff_name": staff_name,
        "loai_su_kien": "PHAT",
        "so_tien_thay_doi": 500000,
        "ly_do": "Phạt làm vỡ ly",
        "created_at": "2026-10-15 10:10:00"
    })

    calc2 = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=month,
        staff_ledgers=staff_ledgers,
        so_cai_luong=so_cai_luong,
        staff_accounts={"nguyen_van_a": {"hourly_rate": 20000}}
    )

    assert calc2["advance_amount"] == 500000
    assert calc2["eval_bonus"] == 200000, (
        f"Lỗi Double-Counting: eval_bonus bị nhân đôi! "
        f"Kỳ vọng 200,000đ, thực tế={calc2['eval_bonus']}"
    )
    assert calc2["eval_deductions"] == 500000, (
        f"Lỗi Double-Counting: eval_deductions bị nhân đôi! "
        f"Kỳ vọng 500,000đ, thực tế={calc2['eval_deductions']}"
    )


# ==============================================================================
# TEST 2: REA-PAYROLL-03 - Shift Blindness Fix (Ca Chiều + Ca Tối cùng ngày)
# ==============================================================================
def test_rea_payroll_03_shift_blindness_afternoon_and_evening_same_day():
    """
    REA-PAYROLL-03:
    Trước đây hệ thống ép mọi ca không có chữ 'sang' thành 'Tối'.
    Khi nhân viên làm cả Ca Chiều và Ca Tối trong cùng một ngày,
    bộ lọc dedup (date, emp, norm_s) nuốt mất ca thứ 2.
    Fix: Chuẩn hóa ca đầy đủ (Sáng, Chiều, Tối, Gãy) và kèm start_time vào dedup key.
    Nhân viên PHẢI được nhận đủ tiền của CẢ 2 CA.
    """
    staff_name = "Trần Văn B"
    month = "10"
    date_str = "2026-10-15"

    log_chieu = {
        "id": "rec_chieu_1",
        "display_name": staff_name,
        "date": date_str,
        "shift_key": "chieu",
        "shift_name": "Ca Chiều",
        "checkin_time": "12:00:00",
        "checkout_time": "17:00:00",
        "total_mins": 300,
        "effective_duration_mins": 300,
        "hourly_rate_snapshot": 20000
    }

    log_toi = {
        "id": "rec_toi_1",
        "display_name": staff_name,
        "date": date_str,
        "shift_key": "toi",
        "shift_name": "Ca Tối",
        "checkin_time": "17:30:00",
        "checkout_time": "22:30:00",
        "total_mins": 300,
        "effective_duration_mins": 300,
        "hourly_rate_snapshot": 20000
    }

    calc = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=month,
        attendance_logs=[log_chieu, log_toi],
        staff_accounts={"tran_van_b": {"hourly_rate": 20000}}
    )

    # 1. Phải tính đủ cả 2 ca
    assert calc["total_shifts"] == 2, (
        f"Shift Blindness: Bị nuốt mất ca! Kỳ vọng 2 ca, thực tế={calc['total_shifts']}"
    )

    # 2. Tổng giờ làm phải là 10.0h (5h + 5h)
    assert calc["total_hours"] == 10.0, (
        f"Kỳ vọng 10.0h công, thực tế={calc['total_hours']}"
    )

    # 3. Tổng tiền phải là 200,000đ (10h * 20,000đ)
    assert calc["standard_pay"] == 200000, (
        f"Kỳ vọng 200,000đ, thực tế={calc['standard_pay']}"
    )

    # 4. Kiểm tra danh sách ca ghi nhận đầy đủ 2 ca khác nhau
    records = calc.get("shift_records", [])
    assert len(records) == 2
    shift_names = [r["shift"] for r in records]
    assert "Ca Chiều" in shift_names
    assert "Ca Tối" in shift_names


def test_rea_payroll_03_data_json_afternoon_and_evening():
    """
    Kiểm tra chống nuốt ca từ nguồn DỮ LIỆU (Google Sheets / data.json)
    khi nhân viên làm cả Ca Chiều và Ca Tối trong cùng ngày.
    """
    staff_name = "Lê Hoàng Long"
    month = "10"
    date_str = "15/10/2026"

    data_json = {
        "DỮ LIỆU": [
            ["STT", "Ngày", "Họ và tên", "Ca làm việc", "Giờ vào", "Giờ ra", "Tổng thời gian", "Ghi chú", "Tháng"],
            [1, date_str, staff_name, "Ca Chiều", "12:00", "17:00", "300", "", "10"],
            [2, date_str, staff_name, "Ca Tối", "17:30", "22:30", "300", "", "10"],
        ]
    }

    calc = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=month,
        data_json=data_json,
        staff_accounts={"le_hoang_long": {"full_name": "Lê Hoàng Long", "hourly_rate": 22000}}
    )

    assert calc["total_shifts"] == 2, f"Bị nuốt ca trong data_json! total_shifts={calc['total_shifts']}"
    assert calc["total_hours"] == 10.0
    assert calc["standard_pay"] == 220000


# ==============================================================================
# TEST 3: REA-PAYROLL-04 - Missing Checkout Standard Hours Preservation
# ==============================================================================
def test_rea_payroll_04_missing_checkout_preserves_standard_shift_hours():
    """
    REA-PAYROLL-04:
    Khi nhân viên có check-in nhưng quên check-out (cout rỗng/None, ca có cờ
    is_hanging_pending hoặc status == 'QUEN_CHECKOUT' hoặc auto-closed):
    Hệ thống PHẢI bảo lưu giờ công chuẩn ca (300p = 5.0h hoặc 330p = 5.5h)
    để bảo vệ quyền lợi người lao động, KHÔNG ĐƯỢC để lương bị về 0đ.
    """
    staff_name = "Phạm Thị Cúc"
    month = "10"

    # Ca Sáng: checkin 07:00:00, quên check-out (checkout_time = None)
    log_hanging_sang = {
        "id": "rec_missing_cout_1",
        "display_name": staff_name,
        "date": "2026-10-14",
        "shift_key": "sang",
        "shift_name": "Ca Sáng",
        "checkin_time": "07:00:00",
        "checkout_time": None,
        "total_mins": 0,
        "is_hanging_pending": True,
        "status": "QUEN_CHECKOUT",
        "hourly_rate_snapshot": 20000
    }

    calc = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=month,
        attendance_logs=[log_hanging_sang],
        staff_accounts={"pham_thi_cuc": {"hourly_rate": 20000}}
    )

    # 1. Ca phải được ghi nhận (không bị nuốt bởi `if not cin or not cout: continue`)
    assert calc["total_shifts"] == 1, (
        f"Ca quên check-out bị loại bỏ hoàn toàn! total_shifts={calc['total_shifts']}"
    )

    # 2. Giờ công chuẩn ca sáng được bảo lưu: 330 phút = 5.5 giờ
    assert calc["total_hours"] == 5.5, (
        f"Giờ công không được bảo lưu chuẩn ca! total_hours={calc['total_hours']}"
    )

    # 3. Lương không bị về 0: 5.5h * 20,000đ = 110,000đ
    assert calc["standard_pay"] == 110000, (
        f"Lương bị về 0 do quên check-out! standard_pay={calc['standard_pay']}"
    )

    # 4. Trạng thái trong shift_records phản ánh đúng QUEN_CHECKOUT
    rec = calc["shift_records"][0]
    assert rec["ot_status"] == "QUEN_CHECKOUT"
    assert rec["checkout"] == "--:--"


def test_rea_payroll_04_auto_closed_missing_checkout_evening_shift():
    """
    Kiểm tra ca tối tự động đóng (AUTO_CLOSED) khi thiếu checkout_time:
    Bảo lưu giờ công chuẩn ca tối 300 phút = 5.0 giờ.
    """
    staff_name = "Vũ Đình Duy"
    month = "10"

    log_auto_closed_toi = {
        "id": "rec_auto_closed_2",
        "display_name": staff_name,
        "date": "2026-10-15",
        "shift_key": "toi",
        "shift_name": "Ca Tối",
        "checkin_time": "18:00:00",
        "checkout_time": "",
        "total_mins": 0,
        "status": "AUTO_CLOSED",
        "hourly_rate_snapshot": 20000
    }

    calc = calculate_staff_payslip_breakdown(
        staff_name=staff_name,
        month=month,
        attendance_logs=[log_auto_closed_toi],
        staff_accounts={"vu_dinh_duy": {"hourly_rate": 20000}}
    )

    assert calc["total_shifts"] == 1
    assert calc["total_hours"] == 5.0, f"Kỳ vọng 5.0h cho ca tối 18h, thực tế={calc['total_hours']}"
    assert calc["standard_pay"] == 100000, f"Kỳ vọng 100,000đ, thực tế={calc['standard_pay']}"
    assert calc["shift_records"][0]["ot_status"] == "QUEN_CHECKOUT"
