// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// LOCALE PATTERNS [VI] — TIẾNG VIỆT (SOURCE LANGUAGE)
// ==========================================================================

export const TOKENS = {
  roles: {
    'Quản lý': 'Quản lý',
    'Pha chế': 'Pha chế',
    'Phục vụ': 'Phục vụ',
    'Giữ xe': 'Giữ xe',
    'Giữ Xe': 'Giữ Xe',
    'Khác': 'Khác'
  },
  shifts: {
    'Ca Sáng': 'Ca Sáng',
    'Ca Tối': 'Ca Tối',
    'Ca Chiều': 'Ca Chiều',
    'Ca sáng': 'Ca sáng',
    'Ca tối': 'Ca tối',
    'Tối cuối tuần': 'Tối cuối tuần'
  },
  days: {
    'Thứ Hai': 'Thứ Hai',
    'Thứ Ba': 'Thứ Ba',
    'Thứ Tư': 'Thứ Tư',
    'Thứ Năm': 'Thứ Năm',
    'Thứ Sáu': 'Thứ Sáu',
    'Thứ Bảy': 'Thứ Bảy',
    'Thứ 2': 'Thứ 2',
    'Thứ 3': 'Thứ 3',
    'Thứ 4': 'Thứ 4',
    'Thứ 5': 'Thứ 5',
    'Thứ 6': 'Thứ 6',
    'Thứ 7': 'Thứ 7',
    'Chủ Nhật': 'Chủ Nhật',
    'CN': 'CN',
    'T2': 'T2',
    'T3': 'T3',
    'T4': 'T4',
    'T5': 'T5',
    'T6': 'T6',
    'T7': 'T7'
  }
};

export function translateTokens(str) {
  return str;
}

export const PATTERNS = [];

export default { TOKENS, translateTokens, PATTERNS };
