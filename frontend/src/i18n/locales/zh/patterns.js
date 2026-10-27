// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// LOCALE PATTERNS [ZH] — 中文 DYNAMIC TEMPLATES & TOKENS
// ==========================================================================

export const TOKENS = {
  roles: {
    'Quản lý': '店长',
    'Pha chế': '咖啡师',
    'Phục vụ': '服务员',
    'Giữ xe': '泊车',
    'Giữ Xe': '泊车',
    'Khác': '其他'
  },
  shifts: {
    'Ca Sáng': '早班',
    'Ca Tối': '晚班',
    'Ca Chiều': '午班',
    'Ca sáng': '早班',
    'Ca tối': '晚班',
    'Tối cuối tuần': '周末晚班'
  },
  days: {
    'Thứ Hai': '周一',
    'Thứ Ba': '周二',
    'Thứ Tư': '周三',
    'Thứ Năm': '周四',
    'Thứ Sáu': '周五',
    'Thứ Bảy': '周六',
    'Thứ 2': '周一',
    'Thứ 3': '周二',
    'Thứ 4': '周三',
    'Thứ 5': '周四',
    'Thứ 6': '周五',
    'Thứ 7': '周六',
    'Chủ Nhật': '周日',
    'CN': '周日',
    'T2': '周一',
    'T3': '周二',
    'T4': '周三',
    'T5': '周四',
    'T6': '周五',
    'T7': '周六'
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
  { re: /^WFM\s*•\s*Chào\s+(.+)$/i, replace: 'WFM • 你好 $1' },
  { re: /^T\.(\d+)$/, replace: '$1月' },
  { re: /^(\d+)\s*ca\s*•\s*Công gộp$/i, replace: '$1 班次 • 总计' },
  { re: /^Chiếm\s+([\d.,]+|--)%\s*quỹ(?:\s*lương)?$/i, replace: '占薪资池 $1%' },
  { re: /^(\d+)\s*ca trễ\s*\(>(\d+)p\)$/i, replace: '$1 班次迟到 (>$2分)' },
  { re: /^([\d.,]+)tr\s*\((\d+)%\)$/i, replace: '$1M ($2%)' },
  { re: /^(\d+)\s*ca\s*(?:OT\s*\(≥\d+p\)|vượt giờ)\s*•\s*(\d+)\s*chờ duyệt$/i, replace: '$1 加班班次 • $2 待审批' },
  { re: /^(?:⚡\s*)?(?:CA CẦN DUYỆT|Ca Cần Duyệt)\s*\((\d+)\s*ca\)$/i, replace: '⚡ 待审批班次 ($1 班)' },
  { re: /^(?:⏳\s*)?\+(\d+)p\s*(?:OT|giờ thêm)\s*•\s*Chờ duyệt$/i, replace: '⏳ +$1分 加班 • 待批' },
  { re: /^(?:✓\s*)?Duyệt(?:\s*đủ)?\s*(\d+)p$/i, replace: '✓ 批准 $1分' },
  { re: /^(?:✕\s*)?Cắt(?:\s*về)?\s*(\d+)p$/i, replace: '✕ 截断至 $1分' },
  { re: /^Lương:\s*(.+)$/i, replace: '薪资: $1' },
  { re: /^Xem lịch sử\s*(\d+)\s*ca đã xử lý$/i, replace: '查看 $1 个已处理班次' },
  { re: /^Chuẩn\s*(\d+)p$/i, replace: '标准 $1分' },
  { re: /^⚡\s*OT hiệu suất\s*(\d+)p$/i, replace: '⚡ 已批加班 $1分' },
  { re: /^OT hiệu suất\s*\(\+(\d+)p\)$/i, replace: '已批加班 (+$1分)' },
  { re: /^Chuẩn\s*([\d.]+)h$/i, replace: '标准 $1h' },
  { re: /^Trễ\s*(\d+)\s*(?:p|phút)$/i, replace: '迟到 $1分' },
  { re: /^\((Thứ Hai|Thứ Ba|Thứ Tư|Thứ Năm|Thứ Sáu|Thứ Bảy|Chủ Nhật)\)$/i, fn: (m) => `(${translateTokens(m[1])})` },
  { re: /^\(?(\d+)p\)?$/, fn: (m, s) => s.startsWith('(') ? `(${m[1]}分)` : `${m[1]}分` },
  { re: /^(\d+)\s*NV$/i, replace: '$1 人' },
  { re: /^(\d+)%\s*Đúng giờ$/i, replace: '$1% 准时' },
  { re: /^([\d.]+)h\s*làm$/i, replace: '工作 $1h' },
  { re: /^\((.+?)\s*•\s*([\d.]+)h\s*OT\s*•\s*chiếm\s*(\d+)%\s*OT quán\)$/i, fn: (m) => `(${translateTokens(m[1])} • ${m[2]}h 加班 • 占全店 ${m[3]}%)` },
  { re: /^\((.+?)\s*•\s*(\d+)\s*ca\)$/i, fn: (m) => `(${translateTokens(m[1])} • ${m[2]} 班次)` },
  { re: /^\((\d+)\s*ca trễ\s*•\s*(\d+)p\)$/i, replace: '($1 次迟到 • $2分)' },
  { re: /^Xem thêm\s*\((\d+)\s*chỉ số hiệu suất\)$/i, replace: '展开更多 ($1 项绩效指标)' },
  { re: /^Tuần:\s*Tuần Này\s*\(([^)]+)\)\s*•\s*Hiện Tại$/i, replace: '周次: 本周 ($1) • 当前' },
  { re: /^Tuần:\s*(.+)$/i, replace: '周次: $1' },
  { re: /^Tuần Này\s*\(([^)]+)\)$/i, replace: '本周 ($1)' },
  { re: /^Tuần Sau\s*\(([^)]+)\)$/i, replace: '下周 ($1)' },
  { re: /^Hạn chót:\s*Còn$/i, replace: '截止倒计时:' },
  { re: /^\(Đóng\s+([^)]+)\)$/i, fn: (m) => `(${translateTokens(m[1])} 截止)` },
  { re: /^Sáng:\s*(\d+)$/i, replace: '早: $1' },
  { re: /^Tối:\s*(\d+)$/i, replace: '晚: $1' },
  { re: /^Chi Tiết Ngày:\s*(.+)$/i, replace: '当日排班详情: $1' },
  { re: /^(\d+)\s*Barista\s*•\s*(\d+)\s*Phục vụ$/i, replace: '$1 咖啡师 • $2 服务员' },
  { re: /^(\d+|--)(\/\d+)\s*ca(?:\s*chuẩn|\s*đủ)?$/i, replace: '$1$2 班次达标' },
  { re: /^(\d+)\s*ca\s*(?:thiếu|trống)$/i, replace: '缺 $1 个班次' },
  { re: /^Xem thêm\s*\((\d+)\s*ca thiếu khác\)$/i, replace: '展开更多 (其余 $1 个缺人班次)' },
  { re: /^(.+?)\s*\(([\d/]+)\)\s*-\s*(.+?):\s*(Chưa xếp ca|Trống ca chấm công)$/i, fn: (m) => `${translateTokens(m[1])} (${m[2]}) - ${translateTokens(m[3])}: ${m[4].includes('Chưa') ? '未排班' : '无考勤记录'}` },
  { re: /^(\d+)\s*ca làm việc$/i, replace: '$1 个工作班次' },
  { re: /^([\d.,]+)đ\s*giảm trừ$/i, replace: '扣款 $1đ' },
  { re: /^(\d+)\/(\d+)\s*nhân sự$/i, replace: '$1/$2 名员工' },
  { re: /^(\d+|--)\s*nhân sự$/i, replace: '$1 名员工' },
  { re: /^(\d+)\s*Nhân Sự\s*•\s*Cấp Tài Khoản\s*&\s*Gửi Zalo$/i, replace: '$1 名员工 • 分配账号与发送 Zalo' },
  { re: /^(\d+)\s*đã thanh toán$/i, replace: '$1 已付' },
  { re: /^(\d+)\s*chưa thanh toán$/i, replace: '$1 未付' },
  { re: /^(.+?)\s*•\s*(\d+)\s*ca\s*•\s*([\d.]+)h$/i, fn: (m) => `${translateTokens(m[1])} • ${m[2]} 班次 • ${m[3]}h` },
  { re: /^([\d/]+)\s*•\s*(Ca Sáng|Ca Tối|Ca Chiều)$/i, fn: (m) => `${m[1]} • ${translateTokens(m[2])}` },
  { re: /^(?:○\s*)?(?:Chưa CK|Chờ Chuyển)$/i, replace: '未转账' },
  { re: /^(?:✓\s*)?(?:Đã CK|Đã Chuyển)$/i, replace: '✓ 已转账' },
  { re: /^Đổi sang\s*(?:Chưa CK|Chờ Chuyển)$/i, replace: '设为未转账' },
  { re: /^Tìm(?: kiếm)? nhân sự\.{0,3}$/i, replace: '搜索员工...' },
  { re: /^Lịch Ca$/i, replace: '排班' },
  { re: /^Phiếu Lương$/i, replace: '工资条' },
  { re: /^PHIẾU LƯƠNG NHÂN SỰ\s*•\s*THÁNG\s*(.+)$/i, replace: '员工工资单 • $1月' },
  { re: /^Chi Tiết Chấm Công\s*•\s*Tháng\s*(.+)$/i, replace: '考勤明细 • $1月' },
  { re: /^Nhân sự:\s*(.+?)\s*•\s*Xem lịch sử Check-in \/ Out từng ngày$/i, replace: '员工: $1 • 每日签到/签退记录' },
  { re: /^Lương tiêu chuẩn\s*\(([\d.,]+)\s*giờ\)$/i, replace: '标准薪资 ($1 小时)' },
  { re: /^Lương làm thêm Overtime\s*\(([\d.,]+)\s*giờ\)$/i, replace: '加班薪资 ($1 小时)' },
  { re: /^Tạm ứng trong kỳ\s*\((\d+)\s*lần\)$/i, replace: '本期预支 ($1 次)' },
  { re: /^Khấu trừ vi phạm\s*&\s*Kỷ luật\s*\((\d+)\s*lần trễ(?:\s*•\s*(\d+)\s*phạt vi phạm)?\)$/i, fn: (m) => `违纪与迟到扣款 (${m[1]} 次迟到${m[2] ? ` • ${m[2]} 次罚款` : ''})` },
  { re: /^([\d.,]+)\s*phút$/i, replace: '$1 分钟' },
  { re: /^\(([\d.,]+)\s*giờ\)$/i, replace: '($1 小时)' },
  { re: /^(.+)\/(?:giờ|h)$/i, replace: '$1/小时' },
  { re: /^(\d+)\s*ca trực$/i, replace: '$1 班次' },
  { re: /^➕\s*Ghi Tạm Ứng Cho\s+(.+)$/i, replace: '➕ 为 $1 登记预支' },
  { re: /^Danh Sách Đang Bị Khóa\s*\(([^)]*)\)$/i, replace: '当前已锁定列表 ($1)' },
  { re: /^Danh Sách Đang Bị Khóa\s*\($/i, replace: '当前已锁定列表 (' },
  { re: /^Tháng\s*(\d+\/\d+)$/i, replace: '$1月' },
  { re: /^(\d+)\s*lần$/i, replace: '$1 次' },
  { re: /^phút\s*\(dưới 60 phút quy chuẩn\)\.\s*Bạn có chắc chắn muốn kết thúc ca lúc này\?$/i, replace: '分钟 (未满60分钟标准)。确定现在签退下班吗？' },
  { re: /^(\d+)\s*ca$/i, replace: '$1 班次' }
];

export default { TOKENS, translateTokens, PATTERNS };
