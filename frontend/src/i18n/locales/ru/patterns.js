// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// LOCALE PATTERNS [RU] — РУССКИЙ DYNAMIC TEMPLATES & TOKENS
// ==========================================================================

export const TOKENS = {
  roles: {
    'Quản lý': 'Менеджер',
    'Pha chế': 'Бариста',
    'Phục vụ': 'Сервис',
    'Giữ xe': 'Парковка',
    'Giữ Xe': 'Парковка',
    'Khác': 'Прочие'
  },
  shifts: {
    'Ca Sáng': 'Утренняя',
    'Ca Tối': 'Вечерняя',
    'Ca Chiều': 'Дневная',
    'Ca sáng': 'Утро',
    'Ca tối': 'Вечер',
    'Tối cuối tuần': 'Выходной вечер'
  },
  days: {
    'Thứ Hai': 'Понедельник',
    'Thứ Ba': 'Вторник',
    'Thứ Tư': 'Среда',
    'Thứ Năm': 'Четверг',
    'Thứ Sáu': 'Пятница',
    'Thứ Bảy': 'Суббота',
    'Thứ 2': 'Пн',
    'Thứ 3': 'Вт',
    'Thứ 4': 'Ср',
    'Thứ 5': 'Чт',
    'Thứ 6': 'Пт',
    'Thứ 7': 'Сб',
    'Chủ Nhật': 'Вс',
    'CN': 'Вс',
    'T2': 'Пн',
    'T3': 'Вт',
    'T4': 'Ср',
    'T5': 'Чт',
    'T6': 'Пт',
    'T7': 'Сб'
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
  { re: /^WFM\s*•\s*Chào\s+(.+)$/i, replace: 'WFM • Привет, $1' },
  { re: /^T\.(\d+)$/, replace: 'М.$1' },
  { re: /^(\d+)\s*ca\s*•\s*Công gộp$/i, replace: '$1 смен • Брутто' },
  { re: /^Chiếm\s+([\d.,]+|--)%\s*quỹ(?:\s*lương)?$/i, replace: '$1% от фонда' },
  { re: /^(\d+)\s*ca trễ\s*\(>(\d+)p\)$/i, replace: '$1 опозд. (>$2м)' },
  { re: /^([\d.,]+)tr\s*\((\d+)%\)$/i, replace: '$1M ($2%)' },
  { re: /^(\d+)\s*ca\s*(?:OT\s*\(≥\d+p\)|vượt giờ)\s*•\s*(\d+)\s*chờ duyệt$/i, replace: '$1 сверхур. • $2 ожид.' },
  { re: /^(?:⚡\s*)?(?:CA CẦN DUYỆT|Ca Cần Duyệt)\s*\((\d+)\s*ca\)$/i, replace: '⚡ ОЖИДАЮТ ($1 смен)' },
  { re: /^(?:⏳\s*)?\+(\d+)p\s*(?:OT|giờ thêm)\s*•\s*Chờ duyệt$/i, replace: '⏳ +$1м ОТ • Ожид.' },
  { re: /^(?:✓\s*)?Duyệt(?:\s*đủ)?\s*(\d+)p$/i, replace: '✓ Одобрить $1м' },
  { re: /^(?:✕\s*)?Cắt(?:\s*về)?\s*(\d+)p$/i, replace: '✕ Обрезать до $1м' },
  { re: /^Lương:\s*(.+)$/i, replace: 'Оплата: $1' },
  { re: /^Xem lịch sử\s*(\d+)\s*ca đã xử lý$/i, replace: 'История ($1 смен)' },
  { re: /^Chuẩn\s*(\d+)p$/i, replace: 'Норма $1м' },
  { re: /^⚡\s*OT hiệu suất\s*(\d+)p$/i, replace: '⚡ Одобрено $1м' },
  { re: /^OT hiệu suất\s*\(\+(\d+)p\)$/i, replace: 'Одобрено ОТ (+$1м)' },
  { re: /^Chuẩn\s*([\d.]+)h$/i, replace: 'Норма $1ч' },
  { re: /^Trễ\s*(\d+)\s*(?:p|phút)$/i, replace: 'Опозд. $1м' },
  { re: /^\((Thứ Hai|Thứ Ba|Thứ Tư|Thứ Năm|Thứ Sáu|Thứ Bảy|Chủ Nhật)\)$/i, fn: (m) => `(${translateTokens(m[1])})` },
  { re: /^\(?(\d+)p\)?$/, fn: (m, s) => s.startsWith('(') ? `(${m[1]}м)` : `${m[1]}м` },
  { re: /^(\d+)\s*NV$/i, replace: '$1 сотр.' },
  { re: /^(\d+)%\s*Đúng giờ$/i, replace: '$1% вовремя' },
  { re: /^([\d.]+)h\s*làm$/i, replace: '$1ч раб.' },
  { re: /^\((.+?)\s*•\s*([\d.]+)h\s*OT\s*•\s*chiếm\s*(\d+)%\s*OT quán\)$/i, fn: (m) => `(${translateTokens(m[1])} • ${m[2]}ч ОТ • ${m[3]}% по кафе)` },
  { re: /^\((.+?)\s*•\s*(\d+)\s*ca\)$/i, fn: (m) => `(${translateTokens(m[1])} • ${m[2]} смен)` },
  { re: /^\((\d+)\s*ca trễ\s*•\s*(\d+)p\)$/i, replace: '($1 опозд. • $2м)' },
  { re: /^Xem thêm\s*\((\d+)\s*chỉ số hiệu suất\)$/i, replace: 'Показать еще ($1 показывают)' },
  { re: /^Tuần:\s*Tuần Này\s*\(([^)]+)\)\s*•\s*Hiện Tại$/i, replace: 'Неделя: Текущая ($1)' },
  { re: /^Tuần:\s*(.+)$/i, replace: 'Неделя: $1' },
  { re: /^Tuần Này\s*\(([^)]+)\)$/i, replace: 'Эта неделя ($1)' },
  { re: /^Tuần Sau\s*\(([^)]+)\)$/i, replace: 'След. неделя ($1)' },
  { re: /^Hạn chót:\s*Còn$/i, replace: 'До конца записи:' },
  { re: /^\(Đóng\s+([^)]+)\)$/i, fn: (m) => `(Закрытие ${translateTokens(m[1])})` },
  { re: /^Sáng:\s*(\d+)$/i, replace: 'Утро: $1' },
  { re: /^Tối:\s*(\d+)$/i, replace: 'Веч: $1' },
  { re: /^Chi Tiết Ngày:\s*(.+)$/i, replace: 'Детали дня: $1' },
  { re: /^(\d+)\s*Barista\s*•\s*(\d+)\s*Phục vụ$/i, replace: '$1 Бариста • $2 Сервис' },
  { re: /^(\d+|--)(\/\d+)\s*ca(?:\s*chuẩn|\s*đủ)?$/i, replace: '$1$2 смен заполнено' },
  { re: /^(\d+)\s*ca\s*(?:thiếu|trống)$/i, replace: '$1 свобод. смен' },
  { re: /^Xem thêm\s*\((\d+)\s*ca thiếu khác\)$/i, replace: 'Показать еще ($1 смен)' },
  { re: /^(.+?)\s*\(([\d/]+)\)\s*-\s*(.+?):\s*(Chưa xếp ca|Trống ca chấm công)$/i, fn: (m) => `${translateTokens(m[1])} (${m[2]}) - ${translateTokens(m[3])}: ${m[4].includes('Chưa') ? 'Не назначено' : 'Нет отметки'}` },
  { re: /^(\d+)\s*ca làm việc$/i, replace: '$1 раб. смен' },
  { re: /^([\d.,]+)đ\s*giảm trừ$/i, replace: 'Удержано $1đ' },
  { re: /^(\d+)\/(\d+)\s*nhân sự$/i, replace: '$1/$2 сотр.' },
  { re: /^(\d+|--)\s*nhân sự$/i, replace: '$1 сотр.' },
  { re: /^(\d+)\s*Nhân Sự\s*•\s*Cấp Tài Khoản\s*&\s*Gửi Zalo$/i, replace: '$1 сотр. • Выдача аккаунтов' },
  { re: /^(\d+)\s*đã thanh toán$/i, replace: '$1 оплачено' },
  { re: /^(\d+)\s*chưa thanh toán$/i, replace: '$1 ожидает' },
  { re: /^(.+?)\s*•\s*(\d+)\s*ca\s*•\s*([\d.]+)h$/i, fn: (m) => `${translateTokens(m[1])} • ${m[2]} смен • ${m[3]}h` },
  { re: /^([\d/]+)\s*•\s*(Ca Sáng|Ca Tối|Ca Chiều)$/i, fn: (m) => `${m[1]} • ${translateTokens(m[2])}` },
  { re: /^(?:○\s*)?(?:Chưa CK|Chờ Chuyển)$/i, replace: 'Ожидает' },
  { re: /^(?:✓\s*)?(?:Đã CK|Đã Chuyển)$/i, replace: '✓ Оплачено' },
  { re: /^Đổi sang\s*(?:Chưa CK|Chờ Chuyển)$/i, replace: 'Вернуть в неоплач.' },
  { re: /^Tìm(?: kiếm)? nhân sự\.{0,3}$/i, replace: 'Поиск сотрудника...' },
  { re: /^Lịch Ca$/i, replace: 'График' },
  { re: /^Phiếu Lương$/i, replace: 'Зарплата' },
  { re: /^PHIẾU LƯƠNG NHÂN SỰ\s*•\s*THÁNG\s*(.+)$/i, replace: 'РАСЧЕТНЫЙ ЛИСТОК • МЕСЯЦ $1' },
  { re: /^Chi Tiết Chấm Công\s*•\s*Tháng\s*(.+)$/i, replace: 'Детали табеля • Месяц $1' },
  { re: /^Nhân sự:\s*(.+?)\s*•\s*Xem lịch sử Check-in \/ Out từng ngày$/i, replace: 'Сотрудник: $1 • История прихода/ухода' },
  { re: /^Lương tiêu chuẩn\s*\(([\d.,]+)\s*giờ\)$/i, replace: 'Базовая оплата ($1 ч)' },
  { re: /^Lương làm thêm Overtime\s*\(([\d.,]+)\s*giờ\)$/i, replace: 'Сверхурочные ($1 ч)' },
  { re: /^Tạm ứng trong kỳ\s*\((\d+)\s*lần\)$/i, replace: 'Авансы ($1 раз)' },
  { re: /^Khấu trừ vi phạm\s*&\s*Kỷ luật\s*\((\d+)\s*lần trễ(?:\s*•\s*(\d+)\s*phạt vi phạm)?\)$/i, fn: (m) => `Штрафы и опоздания (${m[1]} опозд.${m[2] ? ` • ${m[2]} штр.` : ''})` },
  { re: /^([\d.,]+)\s*phút$/i, replace: '$1 мин' },
  { re: /^\(([\d.,]+)\s*giờ\)$/i, replace: '($1 ч)' },
  { re: /^(.+)\/(?:giờ|h)$/i, replace: '$1/ч' },
  { re: /^(\d+)\s*ca trực$/i, replace: '$1 смен' },
  { re: /^➕\s*Ghi Tạm Ứng Cho\s+(.+)$/i, replace: '➕ Аванс для $1' },
  { re: /^Danh Sách Đang Bị Khóa\s*\(([^)]*)\)$/i, replace: 'Заблокированные ($1)' },
  { re: /^Danh Sách Đang Bị Khóa\s*\($/i, replace: 'Заблокированные (' },
  { re: /^Tháng\s*(\d+\/\d+)$/i, replace: 'Месяц $1' },
  { re: /^(\d+)\s*lần$/i, replace: '$1 раз' },
  { re: /^phút\s*\(dưới 60 phút quy chuẩn\)\.\s*Bạn có chắc chắn muốn kết thúc ca lúc này\?$/i, replace: 'мин (менее 60 мин нормы). Вы уверены, что хотите завершить смену?' },
  { re: /^(\d+)\s*ca$/i, replace: '$1 смен' }
];

export default { TOKENS, translateTokens, PATTERNS };
