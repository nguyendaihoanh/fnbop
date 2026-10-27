// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// DATE UTILITIES (VIETNAMESE & ISO DATES)
// ==========================================================================

export function isHolidayDate(dStr) {
  if (!dStr) return false;
  const p = dStr.trim().split("/");
  return p.length >= 2 && parseInt(p[0], 10) === 2 && parseInt(p[1], 10) === 9;
}

export function parseVNDate(dStr) {
  if (!dStr) return 0;
  const p = dStr.split("/");
  if (p.length === 3) return new Date(parseInt(p[2]), parseInt(p[1]) - 1, parseInt(p[0])).getTime();
  return new Date(dStr).getTime();
}

export function isoToVNDate(isoStr) {
  if (!isoStr || !isoStr.includes("-")) return isoStr;
  const parts = isoStr.split("-");
  return `${parts[2]}/${parts[1]}/${parts[0]}`;
}

export function vnToISODate(vnStr) {
  if (!vnStr || !vnStr.includes("/")) return vnStr;
  const parts = vnStr.split("/");
  return `${parts[2]}-${parts[1].padStart(2, "0")}-${parts[0].padStart(2, "0")}`;
}

export function getCurrentVNDate() {
  const now = new Date();
  const d = String(now.getDate()).padStart(2, "0");
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const y = now.getFullYear();
  return `${d}/${m}/${y}`;
}

export function getCurrentISOWeekDays(offsetWeeks = 0) {
  const now = new Date();
  const day = now.getDay();
  const diff = now.getDate() - (day === 0 ? 6 : day - 1) + (offsetWeeks * 7);
  const monday = new Date(now.setDate(diff));
  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const yyyy = d.getFullYear();
    days.push(`${dd}/${mm}/${yyyy}`);
  }
  return days;
}

export function getDayOfWeekVN(dateStr) {
  if (!dateStr) return "";
  const parts = dateStr.split("/");
  if (parts.length < 3) return "";
  const d = new Date(parseInt(parts[2]), parseInt(parts[1]) - 1, parseInt(parts[0]));
  const days = ["Chủ Nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];
  return days[d.getDay()] || "";
}
