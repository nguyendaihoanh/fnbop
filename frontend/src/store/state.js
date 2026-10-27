// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// CENTRAL APPLICATION STATE & POLICY
// ==========================================================================

import { isHolidayDate } from "../utils/dateUtils.js";
import { removeAccents } from "../utils/formatters.js";

export const POLICY = {
  STANDARD_SHIFT_MINS: 300,
  OT_BUFFER_MINS: 30, // 10% cua 300p: 301-330p la OT hieu suat
  EXCESS_THRESHOLD_MINS: 331, // Tu 331p la Ngam ca / Can Quan ly duyet
  LATE_THRESHOLD_MINS: 10,
  LATE_THRESHOLD_INSTANT_FINE: 30,
  LATE_INSTANT_FINE_AMOUNT: 50000,
  LATE_PENALTIES: [
    { count: 1, action: "warn", amount: 0 },
    { count: 2, action: "warn", amount: 0 },
    { count: 3, action: "fine", amount: 50000 },
    { count: 4, action: "fine", amount: 150000 },
    { count: 5, action: "terminate", amount: 0 }
  ],
  ROLE_MAP: {}
};

/**
 * Xác định thời lượng chuẩn của ca (phút):
 * - Ca sáng (06:00 - 11:30): chuẩn 330 phút (5.5h).
 * - Ca tối vào từ 17h (17:00 - 23:00): chuẩn 360 phút (6.0h).
 * - Ca tối vào từ 18h (18:00 - 23:00): chuẩn 300 phút (5.0h).
 * - Mặc định: 300 phút.
 */
export function getShiftStandardMins(shiftName, timeIn) {
  const sNorm = removeAccents(shiftName || "").toLowerCase();
  let cinMins = null;
  if (timeIn) {
    try {
      const parts = timeIn.trim().split(":");
      if (parts.length >= 2) {
        cinMins = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
      }
    } catch (e) {}
  }

  // 1. Ca sáng (06:00 - 11:30): chuẩn 330 phút (5.5h)
  if (sNorm.includes("sang") || sNorm.includes("morning")) {
    return 330;
  }
  if (cinMins !== null && cinMins < 12 * 60) {
    return 330;
  }

  // 2. Ca tối
  if (sNorm.includes("17")) {
    return 360;
  }
  if (sNorm.includes("18")) {
    return 300;
  }

  // Dựa vào giờ check-in thực tế
  if (cinMins !== null) {
    if (cinMins < 18 * 60) { // Vào trước 18:00 -> ca tối vào từ 17h: 360 phút (6.0h)
      return 360;
    } else { // Vào từ 18:00 trở đi -> ca tối vào từ 18h: 300 phút (5.0h)
      return 300;
    }
  }

  return POLICY.STANDARD_SHIFT_MINS || 300;
}

export const currentRealtimeMonth = String(new Date().getMonth() + 1);

export const state = {
  rawData: {},
  employeesMap: {},
  records: [],
  monthsAvailable: [],
  currentMonth: currentRealtimeMonth,
  currentAlertIdx: 0,
  allAlerts: [],
  selectedDateStr: "",
  currentWeekPage: 0, // 0 is latest 7 days
  bonusLedger: {},
  advanceLedger: {},
  deductionLedger: {},
  disbursements: {},
  currentDisbursementFilter: "ALL",
  currentRoleFilter: "ALL",
  currentRole: null,
  currentViewingStaff: null,
  currentRatings: { discipline: 5, service: 5, cleanliness: 5 },
  currentBonusVal: 0,
  staffAggMapCache: {},
  currentAggView: "DAILY",
  rosterCountdownInterval: null,
  shiftPrefState: {},
  currentNextWeekRosterData: null,
  currentRosterWeeksCache: {},
  currentStaffRegState: null,
  currentRegWeekMode: "next",
  mgrRegWeekMode: "next",
  currentSwapContext: null,
  currentEditSlotContext: null,
  serverPayrollSummaryCache: {},
  allTabs: ["ops", "roster", "payslip", "attendance"],
  currentTabKey: "ops",
  adminStaffAccountsData: null,
  adminStaffFilter: "ALL",
  simulatedWifiMode: false,
  attendanceClockInterval: null,
  currentActiveAttendance: null,
  checkoutSliderBound: false,
  currentSopShift: "morning"
};

/**
 * [C3-FIX] Reset all in-memory session state on logout or role switch.
 * Prevents financial data from leaking between users on shared devices.
 * Must be called from clearAuth() in authStore.js.
 */
export function resetState() {
  state.rawData = {};
  state.employeesMap = {};
  state.records = [];
  state.monthsAvailable = [];
  state.currentAlertIdx = 0;
  state.allAlerts = [];
  state.selectedDateStr = "";
  state.currentWeekPage = 0;
  state.bonusLedger = {};
  state.advanceLedger = {};
  state.deductionLedger = {};
  state.disbursements = {};
  state.currentDisbursementFilter = "ALL";
  state.currentRoleFilter = "ALL";
  state.currentRole = null;
  state.currentViewingStaff = null;
  state.currentRatings = { discipline: 5, service: 5, cleanliness: 5 };
  state.currentBonusVal = 0;
  state.staffAggMapCache = {};
  state.serverPayrollSummaryCache = {};
  state.adminStaffAccountsData = null;
  state.currentSwapContext = null;
  state.currentEditSlotContext = null;
  state.currentActiveAttendance = null;
  state.checkoutSliderBound = false;
}

export function getStaffRole(name) {
  if (!name) return "Phục vụ";
  const upper = name.trim().toUpperCase();
  const noTone = upper.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/Đ/g, "D");

  // 1. Ưu tiên tra cứu động từ danh bạ nhân sự hệ thống (staff_directory)
  const staffDir = state.rawData && state.rawData._meta && state.rawData._meta.staff_directory;
  if (staffDir && typeof staffDir === "object") {
    for (const [uname, info] of Object.entries(staffDir)) {
      const uUpper = uname.toUpperCase();
      const fnUpper = (info.full_name || "").toUpperCase();
      const fnNoTone = fnUpper.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/Đ/g, "D");
      const aliases = (info.aliases || []).map(a => a.toUpperCase());
      const sheetNames = (info.sheet_names || []).map(s => s.toUpperCase());

      if (upper === uUpper || upper === fnUpper || noTone === fnNoTone || aliases.includes(upper) || sheetNames.includes(upper)) {
        if (info.role === "MANAGER") return "Quản lý";
        if (info.position === "BARISTA") return "Pha chế";
        if (info.position === "SERVICE") return "Phục vụ";
        if (info.position === "SECURITY") return "Giữ Xe";
      }
    }
  }

  // 2. Fallback theo từ khóa chức vụ hoặc POLICY.ROLE_MAP
  if (upper.includes("PHA CHẾ") || upper.includes("PHA CHE") || upper.includes("BARISTA")) return "Pha chế";
  if (upper.includes("QUẢN LÝ") || upper.includes("QUAN LY") || upper.includes("MANAGER")) return "Quản lý";
  if (upper.includes("BẢO VỆ") || upper.includes("GIỮ XE") || upper.includes("SECURITY")) return "Giữ Xe";
  if (POLICY.ROLE_MAP[upper]) return POLICY.ROLE_MAP[upper];
  if (POLICY.ROLE_MAP[noTone]) return POLICY.ROLE_MAP[noTone];
  return "Phục vụ";
}

export function getIdx(headers, possibleNames) {
  if (!headers) return -1;
  for (let i = 0; i < headers.length; i++) {
    if (possibleNames.includes((headers[i] || "").trim())) return i;
  }
  return -1;
}

export function isValidStaffName(rawName) {
  if (!rawName) return false;
  const s = String(rawName).trim();
  if (s.length < 2) return false;
  const upper = s.toUpperCase();
  // Bỏ qua các chuỗi rác nhập nhầm giờ chấm công vào cột tên (ví dụ: IN17H OUT 22H45, 17:00, OUT 22H...)
  if (/\bIN\s*\d+H?/i.test(upper) || /\bOUT\s*\d+H?/i.test(upper)) return false;
  if (/^\d+[:h]\d+/i.test(upper)) return false;
  if (upper === 'TÊN NHÂN VIÊN' || upper === 'NAME' || upper === 'STT') return false;
  return true;
}

export function getCanonicalStaffName(rawName, customDir) {
  if (!isValidStaffName(rawName)) return "";
  let str = String(rawName).trim().replace(/:+$/, "").trim();
  let nfc = str.normalize("NFC").toUpperCase();

  const staffDir = customDir ||
    (state.rawData && state.rawData._meta && state.rawData._meta.staff_directory) ||
    (state.adminStaffAccountsData && state.adminStaffAccountsData.staff_accounts) ||
    (typeof window !== "undefined" && (window._staff_directory || (window.rawData && window.rawData._meta && window.rawData._meta.staff_directory)));

  if (staffDir && typeof staffDir === "object") {
    for (const [uname, acc] of Object.entries(staffDir)) {
      if (!acc || typeof acc !== "object") continue;
      const eid = String(acc.employee_id || "").trim().toUpperCase();
      const fn = String(acc.full_name || "").trim().normalize("NFC").toUpperCase();
      const uUpper = uname.trim().toUpperCase();
      const sheetNames = (acc.sheet_names || []).map(sn => String(sn).trim().normalize("NFC").toUpperCase()).filter(Boolean);
      const aliases = (acc.aliases || []).map(al => String(al).trim().normalize("NFC").toUpperCase()).filter(Boolean);
      const canonicalRep = sheetNames[0] || fn || uUpper;

      if (eid && nfc === eid) return canonicalRep;
      if (sheetNames.includes(nfc) || nfc === fn || nfc === uUpper || aliases.includes(nfc)) {
        return canonicalRep;
      }
    }
  }

  return nfc;
}

export function resolveStaffCanonicalKey(meta, empKeys) {
  if (!meta || !empKeys || empKeys.length === 0) return '';
  
  const myUname = (meta.username || localStorage.getItem('vnaigc_username') || '').toLowerCase().trim();
  const myName = (meta.full_name || localStorage.getItem('vnaigc_name') || '').trim();
  const mySheetNames = Array.isArray(meta.sheet_names) ? meta.sheet_names : [];

  // Ưu tiên 1: So khớp chính xác tuyệt đối CÓ DẤU theo sheet_names
  for (const sn of mySheetNames) {
    if (!sn) continue;
    const canonSN = getCanonicalStaffName(sn);
    for (const k of empKeys) {
      if (k === sn || k === canonSN || getCanonicalStaffName(k) === canonSN) {
        return k;
      }
    }
  }

  // Ưu tiên 2: So khớp chính xác tuyệt đối CÓ DẤU theo full_name
  if (myName) {
    const canonMyName = getCanonicalStaffName(myName);
    for (const k of empKeys) {
      if (k === myName || k === canonMyName || getCanonicalStaffName(k) === canonMyName) {
        return k;
      }
    }
  }

  // Ưu tiên 3: So khớp không dấu và bỏ khoảng trắng (để "Nhân Viên 01" luôn khớp "NHANVIEN01")
  for (const sn of mySheetNames) {
    if (!sn) continue;
    // Tuyệt đối không dùng không dấu cho THIỆN / THIÊN để tránh gán nhầm
    const upperSN = sn.toUpperCase();
    if (upperSN === 'THIỆN' || upperSN === 'THIÊN') continue;
    const normSN = removeAccents(sn).toUpperCase();
    const stripSN = normSN.replace(/\s+/g, '');
    for (const k of empKeys) {
      const normK = removeAccents(k).toUpperCase();
      const stripK = normK.replace(/\s+/g, '');
      if (normK === normSN || stripK === stripSN) {
        return k;
      }
    }
  }

  if (myName) {
    const upperMyName = myName.toUpperCase();
    if (upperMyName !== 'THIỆN' && upperMyName !== 'THIÊN') {
      const normMyName = removeAccents(myName).toUpperCase();
      const stripMyName = normMyName.replace(/\s+/g, '');
      for (const k of empKeys) {
        const normK = removeAccents(k).toUpperCase();
        const stripK = normK.replace(/\s+/g, '');
        if (normK === normMyName || stripK === stripMyName) {
          return k;
        }
      }
    }
  }

  // Ưu tiên 4: So khớp chính xác theo username (bỏ khoảng trắng, chữ thường)
  if (myUname) {
    for (const k of empKeys) {
      const normK = removeAccents(k).toLowerCase().replace(/\s+/g, '');
      if (normK === myUname) {
        return k;
      }
    }
  }

  return '';
}

export function loadLedgers() {
  try {
    const sB = localStorage.getItem("bonusLedger_v2");
    state.bonusLedger = sB ? JSON.parse(sB) : {};
  } catch(e) { state.bonusLedger = {}; }

  try {
    const sA = localStorage.getItem("advanceLedger_v1");
    state.advanceLedger = sA ? JSON.parse(sA) : {};
  } catch(e) { state.advanceLedger = {}; }

  try {
    const sD = localStorage.getItem("deductionLedger_v1");
    state.deductionLedger = sD ? JSON.parse(sD) : {};
  } catch(e) { state.deductionLedger = {}; }

  // Ensure default seed data for PHÁT Month 8 if not already present
  if (!state.bonusLedger["8"]) state.bonusLedger["8"] = {};
  if (!state.bonusLedger["8"]["PHÁT"]) {
    state.bonusLedger["8"]["PHÁT"] = [{ id: "SEED-B-PHAT", date: "2026-08-28", amount: 200000, type: "bank", reason: "Thưởng quản lý ca" }];
  }

  if (!state.advanceLedger["8"]) state.advanceLedger["8"] = {};
  if (!state.advanceLedger["8"]["PHÁT"]) {
    state.advanceLedger["8"]["PHÁT"] = [{ id: "SEED-A-PHAT", date: "2026-08-16", amount: 200000, type: "cash", reason: "Ứng tiền mặt" }];
  }
}

export async function syncLedgersFromServer(month = "9") {
  try {
    const token = (typeof localStorage !== "undefined") ? localStorage.getItem("vnaigc_jwt") : null;
    if (!token) return;
    const res = await fetch(`/api/v1/cc/payroll/ledger?month=${encodeURIComponent(month)}`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.success || !Array.isArray(data.ledgers)) return;

    data.ledgers.forEach(item => {
      const m = String(item.month || month);
      const name = item.staff_name;
      const t = (item.type || "").toLowerCase();
      const entry = {
        id: item.id,
        date: item.created_at ? item.created_at.split("T")[0] : "",
        amount: item.amount,
        type: item.payment_method || "cash",
        reason: item.reason || "",
        created_by: item.created_by || ""
      };

      if (t.includes("bonus") || t.includes("thuong")) {
        if (!state.bonusLedger[m]) state.bonusLedger[m] = {};
        if (!state.bonusLedger[m][name]) state.bonusLedger[m][name] = [];
        if (!state.bonusLedger[m][name].some(x => x.id === item.id)) {
          state.bonusLedger[m][name].push(entry);
        }
      } else if (t.includes("advance") || t.includes("ung")) {
        if (!state.advanceLedger[m]) state.advanceLedger[m] = {};
        if (!state.advanceLedger[m][name]) state.advanceLedger[m][name] = [];
        if (!state.advanceLedger[m][name].some(x => x.id === item.id)) {
          state.advanceLedger[m][name].push(entry);
        }
      } else if (t.includes("deduction") || t.includes("phat") || t.includes("tru")) {
        if (!state.deductionLedger[m]) state.deductionLedger[m] = {};
        if (!state.deductionLedger[m][name]) state.deductionLedger[m][name] = [];
        if (!state.deductionLedger[m][name].some(x => x.id === item.id)) {
          state.deductionLedger[m][name].push(entry);
        }
      }
    });
  } catch (e) {
    // Offline fallback: keep existing in-memory/localStorage data
  }
}

export function getStaffBonuses(month, staffName) {
  if (!state.bonusLedger[month] || !state.bonusLedger[month][staffName]) return [];
  return state.bonusLedger[month][staffName];
}

export function getStaffBonusSummary(month, staffName) {
  const list = getStaffBonuses(month, staffName);
  let total = 0, cash = 0, bank = 0;
  list.forEach(item => {
    const val = parseInt(item.amount) || 0;
    total += val;
    if (item.type === "cash") cash += val;
    else bank += val;
  });
  return { list, total, cash, bank, count: list.length };
}

export function getStaffAdvances(month, staffName) {
  if (!state.advanceLedger[month] || !state.advanceLedger[month][staffName]) return [];
  const list = state.advanceLedger[month][staffName];
  const seen = new Set();
  const deduped = [];
  list.forEach(item => {
    const cleanDate = (item.date || item.timestamp || '').split('T')[0].split(' ')[0];
    const semKey = `${cleanDate}_${item.amount}_${(item.reason || '').trim().toLowerCase()}`;
    if (!seen.has(semKey)) {
      seen.add(semKey);
      deduped.push(item);
    } else {
      const idx = deduped.findIndex(x => {
        const dDate = (x.date || x.timestamp || '').split('T')[0].split(' ')[0];
        return `${dDate}_${x.amount}_${(x.reason || '').trim().toLowerCase()}` === semKey;
      });
      if (idx !== -1 && item.id && item.id.startsWith('LEDGER_') && (!deduped[idx].id || deduped[idx].id.startsWith('SP-'))) {
        deduped[idx] = item;
      }
    }
  });
  return deduped;
}

export function getStaffAdvanceSummary(month, staffName) {
  const list = getStaffAdvances(month, staffName);
  let total = 0;
  list.forEach(item => { total += parseInt(item.amount) || 0; });
  return total;
}

export function getStaffDeductions(month, staffName) {
  if (!state.deductionLedger[month] || !state.deductionLedger[month][staffName]) return [];
  return state.deductionLedger[month][staffName];
}

export function getStaffDeductionSummary(month, staffName) {
  const list = getStaffDeductions(month, staffName);
  let total = 0;
  list.forEach(item => {
    total += parseInt(item.amount) || 0;
  });
  return { list, total, count: list.length };
}

export function processData() {
  // 1. Parse Employees
  const nvTab = state.rawData["NHÂN VIÊN"] || [];
  state.employeesMap = {};
  if (nvTab.length > 2) {
    const headersLeft = nvTab[2];
    const headersRight = nvTab[1];
    const idxName = getIdx(headersLeft, ["TÊN NHÂN VIÊN", "Tên Nhân Viên"]);
    const idxWage = getIdx(headersLeft, ["LƯƠNG/GIỜ\n(VNĐ)", "LƯƠNG/GIỜ", "LƯƠNG/GIỜ (VNĐ)"]);
    const idxStatus = getIdx(headersRight, ["TRẠNG THÁI", "Trạng Thái"]);

    for (let i = 3; i < nvTab.length; i++) {
      const row = nvTab[i];
      if (idxName !== -1 && row[idxName]) {
        const rawName = row[idxName].trim();
        const name = getCanonicalStaffName(rawName);
        if (!name) continue;
        let wageStr = (idxWage !== -1 && row[idxWage]) ? row[idxWage] : "0";
        wageStr = wageStr.replace(/[^\d]/g, "");
        let status = (idxStatus !== -1 && row[idxStatus]) ? row[idxStatus].trim().toUpperCase() : "ĐANG LÀM";
        if (!state.employeesMap[name] || state.employeesMap[name].wage <= 17000) {
          state.employeesMap[name] = { name, wage: parseInt(wageStr) || 17000, role: getStaffRole(name), status };
        }
      }
    }
  }

  // 1.1 Sync salary_type, fixed_salary, hourly_rate from staff_directory / staff_accounts
  const staffDir = (state.rawData && state.rawData._meta && state.rawData._meta.staff_directory) ||
                   (state.adminStaffAccountsData && state.adminStaffAccountsData.staff_accounts) ||
                   (typeof window !== "undefined" && (window._staff_directory || (window.rawData && window.rawData._meta && window.rawData._meta.staff_directory)));
  if (staffDir && typeof staffDir === "object") {
    for (const [uname, info] of Object.entries(staffDir)) {
      if (!info || typeof info !== "object") continue;
      const fn = String(info.full_name || uname).trim().toUpperCase();
      const canonName = getCanonicalStaffName(fn);
      const aliases = (info.aliases || []).map(a => String(a).trim().toUpperCase());
      const sheetNames = (info.sheet_names || []).map(s => String(s).trim().toUpperCase());
      const targets = [canonName, fn, uname.toUpperCase(), ...aliases, ...sheetNames].filter(Boolean);

      for (const t of targets) {
        if (!state.employeesMap[t]) {
          state.employeesMap[t] = { name: t, wage: 17000, role: getStaffRole(t), status: "ĐANG LÀM" };
        }
        if (info.salary_type) {
          state.employeesMap[t].salary_type = String(info.salary_type).toUpperCase();
        }
        if (info.fixed_salary != null) {
          state.employeesMap[t].fixed_salary = parseInt(info.fixed_salary, 10) || 0;
        }
        if (info.hourly_rate && parseInt(info.hourly_rate, 10) > 0) {
          state.employeesMap[t].wage = parseInt(info.hourly_rate, 10);
        }
      }
    }
  }

  // 2. Parse Records (Merge local OT approvals first for offline/instant persistence)
  try {
    const localOt = JSON.parse(localStorage.getItem('vnaigc_local_ot_approvals') || '{}');
    if (Object.keys(localOt).length > 0 && state.rawData) {
      if (!state.rawData._meta) state.rawData._meta = {};
      state.rawData._meta.shift_approvals = Object.assign({}, state.rawData._meta.shift_approvals || {}, localOt);
    }
  } catch (_) {}

  const dlTab = state.rawData["DỮ LIỆU"] || [];
  state.records = [];
  state.monthsAvailable = [];

  if (dlTab.length > 0) {
    const headers = dlTab[0];
    const iDate = getIdx(headers, ["Ngày", "Ngày làm việc"]);
    const iName = getIdx(headers, ["Tên Nhân Viên", "Tên", "Nhân Viên"]);
    const iShift = getIdx(headers, ["Ca làm việc", "Ca"]);
    const iIn = getIdx(headers, ["Giờ vào\n(HH:MM)", "Giờ vào", "Bắt đầu"]);
    const iOut = getIdx(headers, ["Giờ ra\n(HH:MM)", "Giờ ra", "Kết thúc"]);
    const iMins = getIdx(headers, ["Tổng phút (Tự động)", "Tổng phút", "Phút"]);
    const iMonth = getIdx(headers, ["Tháng"]);
    const iLate = getIdx(headers, ["Trễ"]);

    let rawList = [];
    for (let i = 1; i < dlTab.length; i++) {
      const r = dlTab[i];
      if (!r || r.length === 0) continue;
      const dateStr = (iDate !== -1 && r[iDate] ? r[iDate] : "").trim();
      let month = (iMonth !== -1 && r[iMonth]) ? r[iMonth].trim() : "";
      if (!month && dateStr) {
        if (dateStr.includes("/")) {
          const parts = dateStr.split("/");
          if (parts.length >= 2) month = String(parseInt(parts[1], 10));
        } else if (dateStr.includes("-")) {
          const parts = dateStr.split("-");
          if (parts.length >= 2) month = String(parseInt(parts[1], 10));
        }
      }
      const rawName = (iName !== -1 && r[iName] ? r[iName] : "").trim();
      const name = getCanonicalStaffName(rawName);
      if (!month || !name || !dateStr) continue;

      if (!state.monthsAvailable.includes(month)) state.monthsAvailable.push(month);

      let mins = parseFloat((r[iMins] || "0").replace(",", ".")) || 0;
      let lateMins = parseFloat((r[iLate] || "0").replace(",", ".")) || 0;
      let timeIn = (r[iIn] || "").trim();
      let timeOut = (r[iOut] || "").trim();
      let shift = (r[iShift] || "").trim();

      const emp = state.employeesMap[name] || { wage: 17000, role: getStaffRole(name) };
      const shiftKey = `${dateStr}|${name}|${shift}|${timeIn}`;
      const shiftApprovals = (state.rawData && state.rawData._meta && state.rawData._meta.shift_approvals) || {};
      let approval = shiftApprovals[shiftKey] || null;
      if (!approval) {
        const canonName = getCanonicalStaffName(name);
        for (const [key, val] of Object.entries(shiftApprovals)) {
          const parts = key.split("|");
          if (parts.length >= 4 && parts[0] === dateStr && parts[2] === shift && parts[3] === timeIn) {
            const keyName = parts[1];
            if (canonName && getCanonicalStaffName(keyName) === canonName) {
              approval = val;
              break;
            }
          }
        }
      }

      let otStatus = "STANDARD";
      let effectiveMins = mins;

      // Tháng < 9 mặc định coi như đã chốt lịch sử (AUTO-APPROVE)
      const isHistoric = (month && parseInt(month) < 9);

      const stdShiftMins = getShiftStandardMins(shift, timeIn);

      if (mins <= stdShiftMins) {
        otStatus = "STANDARD";
        effectiveMins = mins;
      } else if (mins <= (stdShiftMins + POLICY.OT_BUFFER_MINS)) {
        otStatus = "OT_PERF"; // OT hiệu suất tự động tính đủ
        effectiveMins = mins;
      } else {
        // Cần Quản lý duyệt
        if (approval && approval.status === "APPROVE") {
          otStatus = "APPROVED";
          effectiveMins = approval.approved_mins || mins;
        } else if (approval && approval.status === "CUT") {
          otStatus = "CUT";
          effectiveMins = approval.approved_mins || stdShiftMins;
        } else if (isHistoric) {
          otStatus = "APPROVED";
          effectiveMins = mins;
        } else {
          otStatus = "PENDING";
          effectiveMins = stdShiftMins; // Tạm tính theo chuẩn ca, chờ Quản lý duyệt
        }
      }

      let otMins = Math.max(0, effectiveMins - stdShiftMins);
      let stdMins = effectiveMins - otMins;
      let ratePerMin = emp.wage / 60;

      const isHoliday = isHolidayDate(dateStr);
      const holidayMultiplier = isHoliday ? 2 : 1;
      const holidayExtra = isHoliday ? (effectiveMins * ratePerMin) : 0;

      rawList.push({
        rowIdx: i + 1,
        month,
        date: dateStr,
        name,
        shift,
        in: timeIn,
        out: timeOut,
        mins,
        effectiveMins,
        standardMins: stdMins,
        standardShiftMins: stdShiftMins,
        overtimeMins: otMins,
        lateMins,
        standardCost: stdMins * ratePerMin * holidayMultiplier,
        overtimeCost: otMins * ratePerMin * holidayMultiplier,
        totalCost: effectiveMins * ratePerMin * holidayMultiplier,
        projectedCost: mins * ratePerMin * holidayMultiplier,
        empWage: emp.wage || 17000,
        isAbnormalShift: (mins > 720),
        isHoliday,
        holidayMultiplier,
        holidayExtra,
        role: emp.role,
        shiftKey,
        otStatus,
        approval
      });
    }

    // Dedup records
    let dedup = new Map();
    rawList.forEach(item => dedup.set(`${item.date}|${item.name}|${item.shift}`, item));
    state.records = Array.from(dedup.values());

    // Ensure all active staff from records are present in employeesMap
    state.records.forEach(r => {
      if (!state.employeesMap[r.name]) {
        state.employeesMap[r.name] = { name: r.name, wage: 17000, role: getStaffRole(r.name), status: "ĐANG LÀM" };
      }
    });
  }

  // 3. Sổ Phụ
  const soPhuTab = state.rawData["SỔ PHỤ"] || [];
  if (soPhuTab.length > 1) {
    // Reset ledgers to avoid duplicate accumulation (preserve Month 8 default seed)
    state.advanceLedger = { "8": state.advanceLedger["8"] || {} };
    state.bonusLedger = { "8": state.bonusLedger["8"] || {} };
    state.deductionLedger = { "8": state.deductionLedger["8"] || {} };

    const h = soPhuTab[0];
    const iTimestamp = getIdx(h, ["Timestamp"]);
    const iName = getIdx(h, ["Nhân Viên", "Tên Nhân Viên"]);
    const iMonth = getIdx(h, ["Tháng"]);
    const iType = getIdx(h, ["Loại"]);
    const iAmount = getIdx(h, ["Số Tiền"]);
    const iMethod = getIdx(h, ["Hình Thức"]);
    const iReason = getIdx(h, ["Lý Do"]);

    for (let i = 1; i < soPhuTab.length; i++) {
      const r = soPhuTab[i];
      if (!r || r.length < 5) continue;
      const rawName = (r[iName] || "").trim();
      const name = getCanonicalStaffName(rawName);
      const month = (r[iMonth] || "").trim();
      const type = (r[iType] || "").trim();
      const amount = parseInt((r[iAmount] || "0").toString().replace(/[^\d]/g, "")) || 0;
      const timestamp = (r[iTimestamp] || "").trim();
      const method = (r[iMethod] || "").trim().toLowerCase();
      const reason = (r[iReason] || "").trim();
      if (!name || !month || amount <= 0) continue;

      const paymentType = (method.includes("mặt") || method.includes("tm")) ? "cash" : "bank";
      const entry = {
        id: r[8] || `SP-${month}-${name}-${i}`,
        date: timestamp.split(" ")[0] || "",
        amount: amount,
        type: paymentType,
        reason: reason,
        timestamp: timestamp
      };

      if (type === "Thưởng") {
        if (!state.bonusLedger[month]) state.bonusLedger[month] = {};
        if (!state.bonusLedger[month][name]) state.bonusLedger[month][name] = [];
        const exists = state.bonusLedger[month][name].some(b => b.id === entry.id || (b.timestamp === entry.timestamp && b.amount === entry.amount));
        if (!exists) state.bonusLedger[month][name].push(entry);
      } else if (type === "Ứng") {
        if (!state.advanceLedger[month]) state.advanceLedger[month] = {};
        if (!state.advanceLedger[month][name]) state.advanceLedger[month][name] = [];
        const exists = state.advanceLedger[month][name].some(a => a.id === entry.id || (a.timestamp === entry.timestamp && a.amount === entry.amount));
        if (!exists) state.advanceLedger[month][name].push(entry);
      } else if (type === "Phạt" || type === "Trừ" || type.toLowerCase().includes("phạt")) {
        if (!state.deductionLedger[month]) state.deductionLedger[month] = {};
        if (!state.deductionLedger[month][name]) state.deductionLedger[month][name] = [];
        const exists = state.deductionLedger[month][name].some(d => d.id === entry.id || (d.timestamp === entry.timestamp && d.amount === entry.amount));
        if (!exists) state.deductionLedger[month][name].push(entry);
      }
    }
  }

  if (!state.monthsAvailable.includes(currentRealtimeMonth)) {
    state.monthsAvailable.push(currentRealtimeMonth);
  }
  state.monthsAvailable.sort((a, b) => parseInt(a) - parseInt(b));

  const currentMonthValid = state.currentMonth && state.currentMonth !== 'all' && (
    state.monthsAvailable.includes(String(state.currentMonth)) || 
    state.monthsAvailable.includes(Number(state.currentMonth))
  );
  if (!currentMonthValid) {
    state.currentMonth = state.monthsAvailable.includes(currentRealtimeMonth) 
      ? currentRealtimeMonth 
      : (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth);
  }

  // Load disbursements from rawData._meta & merge with local overrides
  if (state.rawData && state.rawData._meta && state.rawData._meta.disbursements) {
    state.disbursements = { ...state.rawData._meta.disbursements };
  } else if (!state.disbursements) {
    state.disbursements = {};
  }
  try {
    const local = JSON.parse(localStorage.getItem('vnaigc_local_disbursements') || '{}');
    for (const [mKey, staffObj] of Object.entries(local)) {
      if (!state.disbursements[mKey]) state.disbursements[mKey] = {};
      Object.assign(state.disbursements[mKey], staffObj);
    }
  } catch (_) {}
}
