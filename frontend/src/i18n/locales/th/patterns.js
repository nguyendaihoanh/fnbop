// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// LOCALE PATTERNS [TH] — ภาษาไทย DYNAMIC TEMPLATES & TOKENS
// ==========================================================================

export const TOKENS = {
  roles: {
    'Quản lý': 'ผู้จัดการ',
    'Pha chế': 'บาริสต้า',
    'Phục vụ': 'บริการ',
    'Giữ xe': 'รปภ.',
    'Giữ Xe': 'รปภ.',
    'Khác': 'อื่นๆ'
  },
  shifts: {
    'Ca Sáng': 'กะเช้า',
    'Ca Tối': 'กะเย็น',
    'Ca Chiều': 'กะบ่าย',
    'Ca sáng': 'กะเช้า',
    'Ca tối': 'กะเย็น',
    'Tối cuối tuần': 'กะเย็นสุดสัปดาห์'
  },
  days: {
    'Thứ Hai': 'วันจันทร์',
    'Thứ Ba': 'วันอังคาร',
    'Thứ Tư': 'วันพุธ',
    'Thứ Năm': 'วันพฤหัสบดี',
    'Thứ Sáu': 'วันศุกร์',
    'Thứ Bảy': 'วันเสาร์',
    'Thứ 2': 'จ.',
    'Thứ 3': 'อ.',
    'Thứ 4': 'พ.',
    'Thứ 5': 'พฤ.',
    'Thứ 6': 'ศ.',
    'Thứ 7': 'ส.',
    'Chủ Nhật': 'อา.',
    'CN': 'อา.',
    'T2': 'จ.',
    'T3': 'อ.',
    'T4': 'พ.',
    'T5': 'พฤ.',
    'T6': 'ศ.',
    'T7': 'ส.'
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
  { re: /^WFM\s*•\s*Chào\s+(.+)$/i, replace: 'WFM • สวัสดี $1' },
  { re: /^T\.(\d+)$/, replace: 'ด.$1' },
  { re: /^(\d+)\s*ca\s*•\s*Công gộp$/i, replace: '$1 กะ • รวมทั้งหมด' },
  { re: /^Chiếm\s+([\d.,]+|--)%\s*quỹ(?:\s*lương)?$/i, replace: '$1% ของกองทุน' },
  { re: /^(\d+)\s*ca trễ\s*\(>(\d+)p\)$/i, replace: 'สาย $1 กะ (>$2น.)' },
  { re: /^([\d.,]+)tr\s*\((\d+)%\)$/i, replace: '$1M ($2%)' },
  { re: /^(\d+)\s*ca\s*(?:OT\s*\(≥\d+p\)|vượt giờ)\s*•\s*(\d+)\s*chờ duyệt$/i, replace: 'OT $1 กะ • รออนุมัติ $2' },
  { re: /^(?:⚡\s*)?(?:CA CẦN DUYỆT|Ca Cần Duyệt)\s*\((\d+)\s*ca\)$/i, replace: '⚡ รออนุมัติ ($1 กะ)' },
  { re: /^(?:⏳\s*)?\+(\d+)p\s*(?:OT|giờ thêm)\s*•\s*Chờ duyệt$/i, replace: '⏳ +$1น. OT • รออนุมัติ' },
  { re: /^(?:✓\s*)?Duyệt(?:\s*đủ)?\s*(\d+)p$/i, replace: '✓ อนุมัติ $1น.' },
  { re: /^(?:✕\s*)?Cắt(?:\s*về)?\s*(\d+)p$/i, replace: '✕ ตัดเหลือ $1น.' },
  { re: /^Lương:\s*(.+)$/i, replace: 'ค่าแรง: $1' },
  { re: /^Xem lịch sử\s*(\d+)\s*ca đã xử lý$/i, replace: 'ดูประวัติ $1 กะที่จัดการแล้ว' },
  { re: /^Chuẩn\s*(\d+)p$/i, replace: 'มาตรฐาน $1น.' },
  { re: /^⚡\s*OT hiệu suất\s*(\d+)p$/i, replace: '⚡ อนุมัติ OT $1น.' },
  { re: /^OT hiệu suất\s*\(\+(\d+)p\)$/i, replace: 'อนุมัติ OT (+$1น.)' },
  { re: /^Chuẩn\s*([\d.]+)h$/i, replace: 'มาตรฐาน $1ชม.' },
  { re: /^Trễ\s*(\d+)\s*(?:p|phút)$/i, replace: 'สาย $1น.' },
  { re: /^\((Thứ Hai|Thứ Ba|Thứ Tư|Thứ Năm|Thứ Sáu|Thứ Bảy|Chủ Nhật)\)$/i, fn: (m) => `(${translateTokens(m[1])})` },
  { re: /^\(?(\d+)p\)?$/, fn: (m, s) => s.startsWith('(') ? `(${m[1]}น.)` : `${m[1]}น.` },
  { re: /^(\d+)\s*NV$/i, replace: '$1 คน' },
  { re: /^(\d+)%\s*Đúng giờ$/i, replace: 'ตรงเวลา $1%' },
  { re: /^([\d.]+)h\s*làm$/i, replace: 'ทำ $1 ชม.' },
  { re: /^\((.+?)\s*•\s*([\d.]+)h\s*OT\s*•\s*chiếm\s*(\d+)%\s*OT quán\)$/i, fn: (m) => `(${translateTokens(m[1])} • ${m[2]}ชม. OT • ${m[3]}% ของร้าน)` },
  { re: /^\((.+?)\s*•\s*(\d+)\s*ca\)$/i, fn: (m) => `(${translateTokens(m[1])} • ${m[2]} กะ)` },
  { re: /^\((\d+)\s*ca trễ\s*•\s*(\d+)p\)$/i, replace: '(สาย $1 กะ • $2น.)' },
  { re: /^Xem thêm\s*\((\d+)\s*chỉ số hiệu suất\)$/i, replace: 'ดูเพิ่ม ($1 ตัวชี้วัด)' },
  { re: /^Tuần:\s*Tuần Này\s*\(([^)]+)\)\s*•\s*Hiện Tại$/i, replace: 'สัปดาห์: สัปดาห์นี้ ($1) • ปัจจุบัน' },
  { re: /^Tuần:\s*(.+)$/i, replace: 'สัปดาห์: $1' },
  { re: /^Tuần Này\s*\(([^)]+)\)$/i, replace: 'สัปดาห์นี้ ($1)' },
  { re: /^Tuần Sau\s*\(([^)]+)\)$/i, replace: 'สัปดาห์หน้า ($1)' },
  { re: /^Hạn chót:\s*Còn$/i, replace: 'หมดเขต: เหลือเวลา' },
  { re: /^\(Đóng\s+([^)]+)\)$/i, fn: (m) => `(ปิดรับ ${translateTokens(m[1])})` },
  { re: /^Sáng:\s*(\d+)$/i, replace: 'เช้า: $1' },
  { re: /^Tối:\s*(\d+)$/i, replace: 'เย็น: $1' },
  { re: /^Chi Tiết Ngày:\s*(.+)$/i, replace: 'รายละเอียดวันที่: $1' },
  { re: /^(\d+)\s*Barista\s*•\s*(\d+)\s*Phục vụ$/i, replace: 'บาริสต้า $1 • บริการ $2' },
  { re: /^(\d+|--)(\/\d+)\s*ca(?:\s*chuẩn|\s*đủ)?$/i, replace: 'ครบ $1$2 กะ' },
  { re: /^(\d+)\s*ca\s*(?:thiếu|trống)$/i, replace: 'ขาด $1 กะ' },
  { re: /^Xem thêm\s*\((\d+)\s*ca thiếu khác\)$/i, replace: 'ดูเพิ่ม (อีก $1 กะที่ขาด)' },
  { re: /^(.+?)\s*\(([\d/]+)\)\s*-\s*(.+?):\s*(Chưa xếp ca|Trống ca chấm công)$/i, fn: (m) => `${translateTokens(m[1])} (${m[2]}) - ${translateTokens(m[3])}: ${m[4].includes('Chưa') ? 'ยังไม่จัดคน' : 'ไม่มีบันทึกตอกบัตร'}` },
  { re: /^(\d+)\s*ca làm việc$/i, replace: 'ทำงาน $1 กะ' },
  { re: /^([\d.,]+)đ\s*giảm trừ$/i, replace: 'หัก $1đ' },
  { re: /^(\d+)\/(\d+)\s*nhân sự$/i, replace: '$1/$2 พนักงาน' },
  { re: /^(\d+|--)\s*nhân sự$/i, replace: '$1 พนักงาน' },
  { re: /^(\d+)\s*Nhân Sự\s*•\s*Cấp Tài Khoản\s*&\s*Gửi Zalo$/i, replace: 'พนักงาน $1 คน • ออกบัญชีและส่งผ่าน Zalo' },
  { re: /^(\d+)\s*đã thanh toán$/i, replace: 'โอนแล้ว $1' },
  { re: /^(\d+)\s*chưa thanh toán$/i, replace: 'ค้างโอน $1' },
  { re: /^(.+?)\s*•\s*(\d+)\s*ca\s*•\s*([\d.]+)h$/i, fn: (m) => `${translateTokens(m[1])} • ${m[2]} กะ • ${m[3]}h` },
  { re: /^([\d/]+)\s*•\s*(Ca Sáng|Ca Tối|Ca Chiều)$/i, fn: (m) => `${m[1]} • ${translateTokens(m[2])}` },
  { re: /^(?:○\s*)?(?:Chưa CK|Chờ Chuyển)$/i, replace: 'รอโอน' },
  { re: /^(?:✓\s*)?(?:Đã CK|Đã Chuyển)$/i, replace: '✓ โอนแล้ว' },
  { re: /^Đổi sang\s*(?:Chưa CK|Chờ Chuyển)$/i, replace: 'เปลี่ยนเป็นรอโอน' },
  { re: /^Tìm(?: kiếm)? nhân sự\.{0,3}$/i, replace: 'ค้นหาพนักงาน...' },
  { re: /^Lịch Ca$/i, replace: 'ตารางกะ' },
  { re: /^Phiếu Lương$/i, replace: 'สลิปเงินเดือน' },
  { re: /^PHIẾU LƯƠNG NHÂN SỰ\s*•\s*THÁNG\s*(.+)$/i, replace: 'สลิปเงินเดือนพนักงาน • เดือน $1' },
  { re: /^Chi Tiết Chấm Công\s*•\s*Tháng\s*(.+)$/i, replace: 'รายละเอียดเวลาทำงาน • เดือน $1' },
  { re: /^Nhân sự:\s*(.+?)\s*•\s*Xem lịch sử Check-in \/ Out từng ngày$/i, replace: 'พนักงาน: $1 • ประวัติเข้า-ออกงานรายวัน' },
  { re: /^Lương tiêu chuẩn\s*\(([\d.,]+)\s*giờ\)$/i, replace: 'ค่าแรงปกติ ($1 ชม.)' },
  { re: /^Lương làm thêm Overtime\s*\(([\d.,]+)\s*giờ\)$/i, replace: 'ค่าล่วงเวลา OT ($1 ชม.)' },
  { re: /^Tạm ứng trong kỳ\s*\((\d+)\s*lần\)$/i, replace: 'เบิกล่วงหน้า ($1 ครั้ง)' },
  { re: /^Khấu trừ vi phạm\s*&\s*Kỷ luật\s*\((\d+)\s*lần trễ(?:\s*•\s*(\d+)\s*phạt vi phạm)?\)$/i, fn: (m) => `หักมาสาย/วินัย (สาย ${m[1]} ครั้ง${m[2] ? ` • ปรับ ${m[2]}` : ''})` },
  { re: /^([\d.,]+)\s*phút$/i, replace: '$1 นาที' },
  { re: /^\(([\d.,]+)\s*giờ\)$/i, replace: '($1 ชม.)' },
  { re: /^(.+)\/(?:giờ|h)$/i, replace: '$1/ชม.' },
  { re: /^(\d+)\s*ca trực$/i, replace: '$1 กะ' },
  { re: /^➕\s*Ghi Tạm Ứng Cho\s+(.+)$/i, replace: '➕ บันทึกเบิกล่วงหน้าให้ $1' },
  { re: /^Danh Sách Đang Bị Khóa\s*\(([^)]*)\)$/i, replace: 'รายการที่ถูกล็อก ($1)' },
  { re: /^Danh Sách Đang Bị Khóa\s*\($/i, replace: 'รายการที่ถูกล็อก (' },
  { re: /^Tháng\s*(\d+\/\d+)$/i, replace: 'เดือน $1' },
  { re: /^(\d+)\s*lần$/i, replace: '$1 ครั้ง' },
  { re: /^phút\s*\(dưới 60 phút quy chuẩn\)\.\s*Bạn có chắc chắn muốn kết thúc ca lúc này\?$/i, replace: 'นาที (ต่ำกว่าเกณฑ์ 60 นาที) คุณแน่ใจหรือไม่ที่จะเลิกงานตอนนี้?' },
  { re: /^(\d+)\s*ca$/i, replace: '$1 กะ' }
];

export default { TOKENS, translateTokens, PATTERNS };
