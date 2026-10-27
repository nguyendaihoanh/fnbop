// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// LOCALE PATTERNS [EN] — ENGLISH DYNAMIC TEMPLATES & TOKENS
// ==========================================================================

export const TOKENS = {
  roles: {
    'Quản lý': 'Manager',
    'Pha chế': 'Barista',
    'Phục vụ': 'Service',
    'Giữ xe': 'Parking',
    'Giữ Xe': 'Parking',
    'Khác': 'Other'
  },
  shifts: {
    'Ca Sáng': 'Morning Shift',
    'Ca Tối': 'Evening Shift',
    'Ca Chiều': 'Afternoon Shift',
    'Ca sáng': 'Morning',
    'Ca tối': 'Evening',
    'Tối cuối tuần': 'Weekend Evening'
  },
  days: {
    'Thứ Hai': 'Monday',
    'Thứ Ba': 'Tuesday',
    'Thứ Tư': 'Wednesday',
    'Thứ Năm': 'Thursday',
    'Thứ Sáu': 'Friday',
    'Thứ Bảy': 'Saturday',
    'Thứ 2': 'Mon',
    'Thứ 3': 'Tue',
    'Thứ 4': 'Wed',
    'Thứ 5': 'Thu',
    'Thứ 6': 'Fri',
    'Thứ 7': 'Sat',
    'Chủ Nhật': 'Sun',
    'CN': 'Sun',
    'T2': 'Mon',
    'T3': 'Tue',
    'T4': 'Wed',
    'T5': 'Thu',
    'T6': 'Fri',
    'T7': 'Sat'
  }
};

export function translateTokens(str) {
  let out = str;
  for (const [viR, trR] of Object.entries(TOKENS.roles)) {
    out = out.replace(new RegExp(viR, 'g'), trR);
  }
  for (const [viS, trS] of Object.entries(TOKENS.shifts)) {
    out = out.replace(new RegExp(viS, 'g'), trS);
  }
  for (const [viD, trD] of Object.entries(TOKENS.days)) {
    out = out.replace(new RegExp(viD, 'g'), trD);
  }
  return out;
}

export const PATTERNS = [
  { re: /^WFM\s*•\s*Chào\s+(.+)$/i, replace: 'WFM • Hi $1' },
  { re: /^T\.(\d+)$/, replace: 'M.$1' },
  { re: /^(\d+)\s*ca\s*•\s*Công gộp$/i, replace: '$1 shifts • Gross' },
  { re: /^Chiếm\s+([\d.,]+|--)%\s*quỹ(?:\s*lương)?$/i, replace: '$1% of payroll' },
  { re: /^(\d+)\s*ca trễ\s*\(>(\d+)p\)$/i, replace: '$1 late shifts (>$2m)' },
  { re: /^([\d.,]+)tr\s*\((\d+)%\)$/i, replace: '$1M ($2%)' },
  { re: /^(\d+)\s*ca\s*(?:OT\s*\(≥\d+p\)|vượt giờ)\s*•\s*(\d+)\s*chờ duyệt$/i, replace: '$1 OT shifts • $2 pending' },
  { re: /^(?:⚡\s*)?(?:CA CẦN DUYỆT|Ca Cần Duyệt)\s*\((\d+)\s*ca\)$/i, replace: '⚡ PENDING APPROVAL ($1 shifts)' },
  { re: /^(?:⏳\s*)?\+(\d+)p\s*(?:OT|giờ thêm)\s*•\s*Chờ duyệt$/i, replace: '⏳ +$1m OT • Pending' },
  { re: /^(?:✓\s*)?Duyệt(?:\s*đủ)?\s*(\d+)p$/i, replace: '✓ Approve $1m' },
  { re: /^(?:✕\s*)?Cắt(?:\s*về)?\s*(\d+)p$/i, replace: '✕ Cap at $1m' },
  { re: /^Lương:\s*(.+)$/i, replace: 'Pay: $1' },
  { re: /^Xem lịch sử\s*(\d+)\s*ca đã xử lý$/i, replace: 'View $1 processed shifts' },
  { re: /^Chuẩn\s*(\d+)p$/i, replace: 'Standard $1m' },
  { re: /^⚡\s*OT hiệu suất\s*(\d+)p$/i, replace: '⚡ Approved OT $1m' },
  { re: /^OT hiệu suất\s*\(\+(\d+)p\)$/i, replace: 'Approved OT (+$1m)' },
  { re: /^Chuẩn\s*([\d.]+)h$/i, replace: 'Standard $1h' },
  { re: /^Trễ\s*(\d+)\s*(?:p|phút)$/i, replace: 'Late $1m' },
  { re: /^\((Thứ Hai|Thứ Ba|Thứ Tư|Thứ Năm|Thứ Sáu|Thứ Bảy|Chủ Nhật)\)$/i, fn: (m) => `(${translateTokens(m[1])})` },
  { re: /^\(?(\d+)p\)?$/, fn: (m, s) => s.startsWith('(') ? `(${m[1]}m)` : `${m[1]}m` },
  { re: /^(\d+)\s*NV$/i, replace: '$1 Staff' },
  { re: /^(\d+)%\s*Đúng giờ$/i, replace: '$1% On-Time' },
  { re: /^([\d.]+)h\s*làm$/i, replace: '$1h worked' },
  { re: /^\((.+?)\s*•\s*([\d.]+)h\s*OT\s*•\s*chiếm\s*(\d+)%\s*OT quán\)$/i, fn: (m) => `(${translateTokens(m[1])} • ${m[2]}h OT • ${m[3]}% of store OT)` },
  { re: /^\((.+?)\s*•\s*(\d+)\s*ca\)$/i, fn: (m) => `(${translateTokens(m[1])} • ${m[2]} shifts)` },
  { re: /^\((\d+)\s*ca trễ\s*•\s*(\d+)p\)$/i, replace: '($1 late shifts • $2m)' },
  { re: /^Xem thêm\s*\((\d+)\s*chỉ số hiệu suất\)$/i, replace: 'Show more ($1 performance metrics)' },
  { re: /^Tuần:\s*Tuần Này\s*\(([^)]+)\)\s*•\s*Hiện Tại$/i, replace: 'Week: This Week ($1) • Current' },
  { re: /^Tuần:\s*(.+)$/i, replace: 'Week: $1' },
  { re: /^Tuần Này\s*\(([^)]+)\)$/i, replace: 'This Week ($1)' },
  { re: /^Tuần Sau\s*\(([^)]+)\)$/i, replace: 'Next Week ($1)' },
  { re: /^Hạn chót:\s*Còn$/i, replace: 'Deadline: Remaining' },
  { re: /^\(Đóng\s+([^)]+)\)$/i, fn: (m) => `(Closes ${translateTokens(m[1])})` },
  { re: /^Sáng:\s*(\d+)$/i, replace: 'AM: $1' },
  { re: /^Tối:\s*(\d+)$/i, replace: 'PM: $1' },
  { re: /^Chi Tiết Ngày:\s*(.+)$/i, replace: 'Day Details: $1' },
  { re: /^(\d+)\s*Barista\s*•\s*(\d+)\s*Phục vụ$/i, replace: '$1 Barista • $2 Service' },
  { re: /^(\d+|--)(\/\d+)\s*ca(?:\s*chuẩn|\s*đủ)?$/i, replace: '$1$2 shifts filled' },
  { re: /^(\d+)\s*ca\s*(?:thiếu|trống)$/i, replace: '$1 open shifts' },
  { re: /^Xem thêm\s*\((\d+)\s*ca thiếu khác\)$/i, replace: 'Show more ($1 other open shifts)' },
  { re: /^(.+?)\s*\(([\d/]+)\)\s*-\s*(.+?):\s*(Chưa xếp ca|Trống ca chấm công)$/i, fn: (m) => `${translateTokens(m[1])} (${m[2]}) - ${translateTokens(m[3])}: ${m[4].includes('Chưa') ? 'Unassigned' : 'No attendance logged'}` },
  { re: /^(\d+)\s*ca làm việc$/i, replace: '$1 work shifts' },
  { re: /^([\d.,]+)đ\s*giảm trừ$/i, replace: '$1đ deducted' },
  { re: /^(\d+)\/(\d+)\s*nhân sự$/i, replace: '$1/$2 staff' },
  { re: /^(\d+|--)\s*nhân sự$/i, replace: '$1 staff' },
  { re: /^(\d+)\s*Nhân Sự\s*•\s*Cấp Tài Khoản\s*&\s*Gửi Zalo$/i, replace: '$1 Staff • Provision Accounts & Share via Zalo' },
  { re: /^(\d+)\s*đã thanh toán$/i, replace: '$1 paid' },
  { re: /^(\d+)\s*chưa thanh toán$/i, replace: '$1 unpaid' },
  { re: /^(.+?)\s*•\s*(\d+)\s*ca\s*•\s*([\d.]+)h$/i, fn: (m) => `${translateTokens(m[1])} • ${m[2]} shifts • ${m[3]}h` },
  { re: /^([\d/]+)\s*•\s*(Ca Sáng|Ca Tối|Ca Chiều)$/i, fn: (m) => `${m[1]} • ${translateTokens(m[2])}` },
  { re: /^(?:○\s*)?(?:Chưa CK|Chờ Chuyển)$/i, replace: 'Unpaid' },
  { re: /^(?:✓\s*)?(?:Đã CK|Đã Chuyển)$/i, replace: '✓ Paid' },
  { re: /^Đổi sang\s*(?:Chưa CK|Chờ Chuyển)$/i, replace: 'Mark as Unpaid' },
  { re: /^Tìm(?: kiếm)? nhân sự\.{0,3}$/i, replace: 'Search staff...' },
  { re: /^Lịch Ca$/i, replace: 'Roster' },
  { re: /^Phiếu Lương$/i, replace: 'Payslip' },
  { re: /^PHIẾU LƯƠNG NHÂN SỰ\s*•\s*THÁNG\s*(.+)$/i, replace: 'STAFF PAYSLIP • MONTH $1' },
  { re: /^Chi Tiết Chấm Công\s*•\s*Tháng\s*(.+)$/i, replace: 'Attendance Log • Month $1' },
  { re: /^Nhân sự:\s*(.+?)\s*•\s*Xem lịch sử Check-in \/ Out từng ngày$/i, replace: 'Staff: $1 • Daily Check-in / Out History' },
  { re: /^Lương tiêu chuẩn\s*\(([\d.,]+)\s*giờ\)$/i, replace: 'Standard Pay ($1 hrs)' },
  { re: /^Lương làm thêm Overtime\s*\(([\d.,]+)\s*giờ\)$/i, replace: 'Overtime Pay ($1 hrs)' },
  { re: /^Tạm ứng trong kỳ\s*\((\d+)\s*lần\)$/i, replace: 'Salary Advances ($1x)' },
  { re: /^Khấu trừ vi phạm\s*&\s*Kỷ luật\s*\((\d+)\s*lần trễ(?:\s*•\s*(\d+)\s*phạt vi phạm)?\)$/i, fn: (m) => `Discipline Deductions (${m[1]} late${m[2] ? ` • ${m[2]} fines` : ''})` },
  { re: /^([\d.,]+)\s*phút$/i, replace: '$1 mins' },
  { re: /^\(([\d.,]+)\s*giờ\)$/i, replace: '($1 hrs)' },
  { re: /^(.+)\/(?:giờ|h)$/i, replace: '$1/hr' },
  { re: /^(\d+)\s*ca trực$/i, replace: '$1 shifts' },
  { re: /^➕\s*Ghi Tạm Ứng Cho\s+(.+)$/i, replace: '➕ Record Advance for $1' },
  { re: /^Danh Sách Đang Bị Khóa\s*\(([^)]*)\)$/i, replace: 'Currently Locked List ($1)' },
  { re: /^Danh Sách Đang Bị Khóa\s*\($/i, replace: 'Currently Locked List (' },
  { re: /^Tháng\s*(\d+\/\d+)$/i, replace: 'Month $1' },
  { re: /^(\d+)\s*lần$/i, replace: '$1x' },
  { re: /^phút\s*\(dưới 60 phút quy chuẩn\)\.\s*Bạn có chắc chắn muốn kết thúc ca lúc này\?$/i, replace: 'mins (under 60m standard). Are you sure you want to clock out now?' },
  { re: /^(\d+)\s*ca$/i, replace: '$1 shifts' }
];

export default { TOKENS, translateTokens, PATTERNS };
