// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// NAVIGATION ROLE SCHEMA (SINGLE SOURCE OF TRUTH)
// Định nghĩa tập trung toàn bộ cấu hình điều hướng theo vai trò (Role-Based)
// ==========================================================================

export const NAV_ROLE_SCHEMA = {
  STAFF: {
    tabs: ["roster", "attendance", "payslip"],
    heroTab: "attendance", // Nút Chấm Công là Hero Action Bar 2.5D ở giữa (3 tab đối xứng)
    defaultTab: "attendance",
    rosterLabelKey: "nav.my_roster",
    rosterDefaultLabel: "Ca Trực"
  },
  MANAGER: {
    tabs: ["ops", "roster", "attendance", "payslip"],
    heroTab: null, // 4 tab chia đều 25% phẳng (Pro Control Dock)
    defaultTab: "ops",
    rosterLabelKey: "nav.shift_roster",
    rosterDefaultLabel: "Ca Trực"
  },
  ADMIN: {
    tabs: ["ops", "roster", "attendance", "payslip"],
    heroTab: null, // 4 tab chia đều 25% phẳng (Pro Control Dock)
    defaultTab: "ops",
    rosterLabelKey: "nav.shift_roster",
    rosterDefaultLabel: "Ca Trực"
  }
};

export function getRoleNavConfig(role) {
  const normRole = (role || "").toUpperCase();
  return NAV_ROLE_SCHEMA[normRole] || NAV_ROLE_SCHEMA.STAFF;
}
