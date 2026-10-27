// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// PAYSLIP MODULE: RECEIPT RENDERING, EVALUATION, STAFF PORTAL & DISPUTES
// ==========================================================================

import { showToast, safeErrorDetail } from "../utils/toast.js";
import { showConfirmDialog } from "../utils/dialog.js";
import { getDayOfWeekVN } from "../utils/dateUtils.js";
import { removeAccents, fmtMoney, fmtNum, escapeHtml } from "../utils/formatters.js";
import { updateSheetScrollLock } from "../store/authStore.js";
import {
  state,
  currentRealtimeMonth,
  POLICY,
  getStaffRole,
  getCanonicalStaffName,
  resolveStaffCanonicalKey,
  getStaffBonusSummary,
  getStaffAdvances,
  getStaffAdvanceSummary,
  getStaffDeductionSummary
} from "../store/state.js";
import {
  fetchServerPayrollSummaryApi,
  sendPayslipTelegramApi,
  submitStaffEvaluationApi,
  pushEvaluationWebhookApi,
  confirmStaffPayrollApi,
  deleteStaffLedgerApi,
  getExportPayrollUrl
} from "../api/payrollApi.js";

export function getStaffDisbursementRecord(month, staffName) {
  if (!staffName) return null;
  const mStr = String(month || state.currentMonth || currentRealtimeMonth);
  const mNum = Number(month || state.currentMonth || currentRealtimeMonth);
  
  const disbs = state.disbursements || {};
  const monthMap = disbs[mStr] || disbs[mNum] || {};
  
  if (monthMap[staffName]) return monthMap[staffName];

  const canon = getCanonicalStaffName(staffName);
  const norm = removeAccents(staffName).toUpperCase().trim();
  for (const [k, v] of Object.entries(monthMap)) {
    if (k === staffName || getCanonicalStaffName(k) === canon || removeAccents(k).toUpperCase().trim() === norm) {
      return v;
    }
  }

  try {
    const local = JSON.parse(localStorage.getItem('vnaigc_local_disbursements') || '{}');
    const localMonthMap = local[mStr] || local[mNum] || {};
    if (localMonthMap[staffName]) return localMonthMap[staffName];
    for (const [k, v] of Object.entries(localMonthMap)) {
      if (k === staffName || getCanonicalStaffName(k) === canon || removeAccents(k).toUpperCase().trim() === norm) {
        return v;
      }
    }
  } catch (_) {}

  return null;
}

export function checkStaffIsPaid(month, staffName) {
  const rec = getStaffDisbursementRecord(month, staffName);
  return !!(rec && String(rec.status).toUpperCase() === 'PAID');
}

export function renderTabPayslip() {
  const filtered = state.currentMonth === 'all' ? state.records : state.records.filter(r => r.month === state.currentMonth);
  let staffAgg = {};

  filtered.forEach(r => {
    if (!staffAgg[r.name]) {
      const emp = state.employeesMap[r.name] || { wage: 17000, role: getStaffRole(r.name) };
      staffAgg[r.name] = {
        name: r.name,
        role: emp.role,
        wage: emp.wage,
        shifts: 0,
        mins: 0,
        standardCost: 0,
        otCost: 0,
        lateMins: 0,
        lateOver10Count: 0,
        lateOver30Count: 0
      };
    }
    staffAgg[r.name].shifts++;
    staffAgg[r.name].mins += r.mins;
    staffAgg[r.name].standardCost += r.standardCost;
    staffAgg[r.name].otCost += r.overtimeCost;
    staffAgg[r.name].lateMins += r.lateMins;
    if (r.lateMins > POLICY.LATE_THRESHOLD_MINS) {
      staffAgg[r.name].lateOver10Count++;
    }
    if (r.lateMins > POLICY.LATE_THRESHOLD_INSTANT_FINE) {
      staffAgg[r.name].lateOver30Count++;
    }
  });

  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;

  // Precompute financial netPay & disbursement status for each staff
  let allCalculatedStaff = Object.values(staffAgg).map(s => {
    const hours = (s.mins / 60).toFixed(1);
    const bSummary = getStaffBonusSummary(m, s.name);
    const aSummary = (m === '8') ? 0 : getStaffAdvanceSummary(m, s.name);
    const dSummary = getStaffDeductionSummary(m, s.name);

    let latePenalty = 0;
    const enablePenalties = (m !== '8');
    if (enablePenalties && s.lateOver30Count > 0) {
      latePenalty += s.lateOver30Count * POLICY.LATE_INSTANT_FINE_AMOUNT;
    }
    for (let i = 1; enablePenalties && i <= s.lateOver10Count && i <= POLICY.LATE_PENALTIES.length; i++) {
      const rule = POLICY.LATE_PENALTIES[i - 1];
      if (rule.action === 'fine') {
        latePenalty += rule.amount;
      }
    }

    const emp = state.employeesMap[s.name] || {};
    const salaryType = emp.salary_type || 'HOURLY';
    const fixedSalary = Number(emp.fixed_salary) || 0;
    const standardCost = (salaryType === 'FIXED' && fixedSalary > 0) ? fixedSalary : s.standardCost;

    const netPay = Math.max(0, Math.round(standardCost + s.otCost + bSummary.total - aSummary - dSummary.total - latePenalty));
    const isPaid = checkStaffIsPaid(m, s.name);

    return {
      ...s,
      standardCost,
      hours,
      netPay,
      advanceAmt: aSummary,
      bonusAmt: bSummary.total,
      deductionAmt: dSummary.total + latePenalty,
      isPaid
    };
  });

  // Budget Summary Metrics
  const totalGrossFund = filtered.reduce((sum, r) => sum + (r.totalCost || 0), 0);
  const totalStandardFund = filtered.reduce((sum, r) => sum + (r.standardCost || 0), 0);
  const totalOTFund = filtered.reduce((sum, r) => sum + (r.overtimeCost || 0), 0);
  const totalAdvances = allCalculatedStaff.reduce((sum, s) => sum + (s.advanceAmt || 0), 0);
  const totalDeductions = allCalculatedStaff.reduce((sum, s) => sum + (s.deductionAmt || 0), 0);
  const totalBonuses = allCalculatedStaff.reduce((sum, s) => sum + (s.bonusAmt || 0), 0);
  const totalAdjustments = totalAdvances + totalDeductions - totalBonuses;

  const totalPayrollFund = allCalculatedStaff.reduce((sum, s) => sum + s.netPay, 0);
  const disbursedFund = allCalculatedStaff.filter(s => s.isPaid).reduce((sum, s) => sum + s.netPay, 0);
  const remainingFund = Math.max(0, totalPayrollFund - disbursedFund);
  const paidCount = allCalculatedStaff.filter(s => s.isPaid).length;
  const unpaidCount = allCalculatedStaff.length - paidCount;

  // Render Gross & Disbursement KPI banner
  const kpiEl = document.getElementById('payrollDisbursementSummary');
  if (kpiEl) {
    kpiEl.innerHTML = `
      <div class="payroll-gross-banner" style="background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:12px 14px; margin-bottom:10px; box-shadow:0 1px 3px rgba(0,0,0,0.03);">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
          <div>
            <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.04em;">Tổng Quỹ Lương Tháng</div>
            <div class="tabular-nums" style="font-size:20px; font-weight:800; color:var(--text-primary); margin-top:2px;">
              ${fmtMoney.format(Math.round(totalGrossFund)).replace('₫', 'đ')}
            </div>
          </div>
          <div style="text-align:right; font-size:11px;">
            <div style="font-weight:700; color:var(--text-secondary);">${filtered.length} ca làm việc</div>
            ${totalAdjustments > 0 ? `
              <div style="color:var(--accent-coral); font-weight:700; margin-top:2px;">
                -${fmtMoney.format(totalAdjustments).replace('₫', 'đ')} giảm trừ
              </div>
            ` : (totalBonuses > 0 ? `
              <div style="color:var(--accent-emerald); font-weight:700; margin-top:2px;">
                +${fmtMoney.format(totalBonuses).replace('₫', 'đ')} thưởng
              </div>
            ` : `<div style="color:var(--text-muted); margin-top:2px;">0đ giảm trừ</div>`)}
          </div>
        </div>

        <div style="display:flex; flex-wrap:wrap; gap:8px 14px; margin-top:8px; padding-top:8px; border-top:1px dashed var(--border); font-size:11px; color:var(--text-muted);">
          <span>Ca chuẩn: <strong style="color:var(--text-primary); font-weight:700;">${fmtMoney.format(Math.round(totalStandardFund)).replace('₫','đ')}</strong></span>
          <span>Tăng ca: <strong style="color:var(--accent-coral); font-weight:700;">${fmtMoney.format(Math.round(totalOTFund)).replace('₫','đ')}</strong></span>
          ${totalAdvances > 0 ? `<span>Ứng lương: <strong style="color:#d97706; font-weight:700;">-${fmtMoney.format(totalAdvances).replace('₫','đ')}</strong></span>` : ''}
          ${totalDeductions > 0 ? `<span>Phạt trễ/trừ: <strong style="color:#dc2626; font-weight:700;">-${fmtMoney.format(totalDeductions).replace('₫','đ')}</strong></span>` : ''}
          ${totalBonuses > 0 ? `<span>Thưởng: <strong style="color:#059669; font-weight:700;">+${fmtMoney.format(totalBonuses).replace('₫','đ')}</strong></span>` : ''}
        </div>
      </div>

      <div class="payroll-disbursement-kpi">
        <div class="disb-kpi-card total">
          <div class="disb-kpi-label">THỰC CHUYỂN (NET)</div>
          <div class="disb-kpi-val tabular-nums">${fmtMoney.format(totalPayrollFund).replace('₫', 'đ')}</div>
          <div class="disb-kpi-sub">${allCalculatedStaff.length} nhân sự</div>
        </div>
        <div class="disb-kpi-card paid">
          <div class="disb-kpi-label">ĐÃ CHUYỂN KHOẢN</div>
          <div class="disb-kpi-val tabular-nums" style="color:var(--accent-emerald);">${fmtMoney.format(disbursedFund).replace('₫', 'đ')}</div>
          <div class="disb-kpi-sub">${paidCount} đã thanh toán</div>
        </div>
        <div class="disb-kpi-card unpaid">
          <div class="disb-kpi-label">CÒN PHẢI CHUYỂN</div>
          <div class="disb-kpi-val tabular-nums" style="color:var(--accent-coral);">${fmtMoney.format(remainingFund).replace('₫', 'đ')}</div>
          <div class="disb-kpi-sub">${unpaidCount} chưa thanh toán</div>
        </div>
      </div>
    `;
  }

  // Update count in disbursement pills
  const countUnpaidEl = document.getElementById('countUnpaid');
  const countPaidEl = document.getElementById('countPaid');
  if (countUnpaidEl) countUnpaidEl.textContent = unpaidCount;
  if (countPaidEl) countPaidEl.textContent = paidCount;

  // Filter staff list
  let staffList = [...allCalculatedStaff];
  const qRaw = (document.getElementById('payslipSearch')?.value || '').trim();
  const q = removeAccents(qRaw);
  if (q) {
    staffList = staffList.filter(s => removeAccents(s.name).includes(q) || removeAccents(s.role).includes(q));
  }

  if (state.currentRoleFilter && state.currentRoleFilter !== 'ALL') {
    staffList = staffList.filter(s => s.role.toLowerCase() === state.currentRoleFilter.toLowerCase());
  }

  const disbFilter = state.currentDisbursementFilter || 'ALL';
  if (disbFilter === 'UNPAID') {
    staffList = staffList.filter(s => !s.isPaid);
  } else if (disbFilter === 'PAID') {
    staffList = staffList.filter(s => s.isPaid);
  }

  staffList.sort((a, b) => {
    // Unpaid on top, then by hours descending
    if (a.isPaid !== b.isPaid) return a.isPaid ? 1 : -1;
    return b.mins - a.mins;
  });

  const container = document.getElementById('slipList');
  if (!container) return;
  container.innerHTML = '';

  if (staffList.length === 0) {
    container.innerHTML = `<div style="text-align:center; padding:30px 10px; color:var(--text-secondary); font-size:13px;">Không có nhân sự nào phù hợp bộ lọc.</div>`;
    return;
  }

  const canManage = (['ADMIN', 'MANAGER'].includes(localStorage.getItem('vnaigc_role')) || ['ADMIN', 'MANAGER'].includes(state.rawData && state.rawData._meta && state.rawData._meta.role));
  const viewerRole = (localStorage.getItem('vnaigc_role') || 'STAFF').toUpperCase();
  const curUname = (localStorage.getItem('vnaigc_username') || '').toUpperCase().trim();
  const curName = (localStorage.getItem('vnaigc_name') || '').toUpperCase().trim();

  staffList.forEach(s => {
    const isSelfStaff = (s.name.toUpperCase().trim() === curName || removeAccents(s.name).toUpperCase().trim() === removeAccents(curName).toUpperCase().trim() || removeAccents(s.name).toUpperCase().trim() === curUname);
    const item = document.createElement('div');
    item.className = `slip-item ${s.isPaid ? 'slip-item-paid' : 'slip-item-unpaid'}`;
    item.innerHTML = `
      <div class="slip-avatar" style="${s.isPaid ? 'background:rgba(16, 185, 129, 0.15); color:#047857;' : ''}">${escapeHtml(s.name.charAt(0))}</div>
      <div class="slip-meta">
        <div style="display:flex; align-items:center; gap:6px;">
          <strong class="slip-name">${escapeHtml(s.name)}</strong>
          ${(viewerRole === 'ADMIN' && s.advanceAmt > 0) ? `<span style="font-size:11px; background:rgba(239, 68, 68, 0.1); color:#dc2626; padding:1px 5px; border-radius:4px; font-weight:700;">Ứng -${fmtMoney.format(s.advanceAmt).replace('₫','đ')}</span>` : ''}
        </div>
        <div class="slip-role">${escapeHtml(s.role)} • ${s.shifts} ca • ${s.hours}h</div>
      </div>
      <div class="slip-finance" style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;">
        ${(viewerRole === 'MANAGER' && !isSelfStaff) ? `
          <div class="slip-pay tabular-nums" style="font-size:13px; color:var(--text-muted); font-weight:600;">*** đ</div>
        ` : `
          <div class="slip-pay tabular-nums" style="font-size:15px; font-weight:800; ${s.isPaid ? 'color:#047857;' : 'color:var(--text-primary);'}">${fmtMoney.format(s.netPay).replace('₫', 'đ')}</div>
        `}
        ${(viewerRole === 'ADMIN') ? `
          <button type="button" class="disb-toggle-btn ${s.isPaid ? 'paid' : 'unpaid'}" onclick="event.stopPropagation(); toggleStaffDisbursement('${escapeHtml(s.name)}', '${s.isPaid ? 'UNPAID' : 'PAID'}', ${s.netPay})">
            ${s.isPaid ? '✓ ĐÃ CK' : '○ Chưa CK'}
          </button>
        ` : `
          <span style="font-size:11px; font-weight:700; ${s.isPaid ? 'color:#047857;' : 'color:var(--accent-coral);'}">
            ${s.isPaid ? '✓ Đã CK' : '○ Chưa CK'}
          </span>
        `}
      </div>
    `;
    item.addEventListener('click', () => openPayslipModal(s.name));
    container.appendChild(item);
  });
}

export async function fetchServerPayrollSummary(month, staffName) {
  const token = localStorage.getItem('vnaigc_jwt');
  if (!token) return null;
  const m = month || currentRealtimeMonth;
  const cacheKey = `${m}_${staffName || 'all'}`;
  if (state.serverPayrollSummaryCache[cacheKey]) {
    return state.serverPayrollSummaryCache[cacheKey];
  }
  try {
    const url = staffName
      ? `/api/v1/cc/payroll/summary?month=${m}&staff_name=${encodeURIComponent(staffName)}`
      : `/api/v1/cc/payroll/summary?month=${m}`;
    const res = await fetch(url, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      const b = data.breakdown || (data.summaries ? data.summaries[0] : data);
      state.serverPayrollSummaryCache[cacheKey] = b;
      return b;
    }
  } catch (e) {
    console.warn("Could not fetch server payroll summary:", e);
  }
  return null;
}

export function generatePayslipHtml(staffName, serverBreakdown = null) {
  const userRole = (localStorage.getItem('vnaigc_role') || 'STAFF').toUpperCase();
  const curUname = (localStorage.getItem('vnaigc_username') || '').toUpperCase().trim();
  const curName = (localStorage.getItem('vnaigc_name') || '').toUpperCase().trim();
  const targetName = (staffName || '').toUpperCase().trim();
  const targetNorm = removeAccents(staffName).toUpperCase().trim();
  const curNameNorm = removeAccents(curName).toUpperCase().trim();
  const isSelf = (targetName === curName) || 
                 (targetNorm === curNameNorm) || 
                 (targetNorm === curUname);
  const isManagerOther = (userRole === 'MANAGER' && !isSelf);
  const filtered = state.currentMonth === 'all' ? state.records : state.records.filter(r => r.month === state.currentMonth);
  const canonTarget = getCanonicalStaffName(staffName);
  const empRecords = filtered.filter(r => r.name === staffName || getCanonicalStaffName(r.name) === canonTarget);
  
  let standardMins = 0;
  let otMins = 0;
  let standardCost = 0;
  let otCost = 0;
  let totalShifts = 0;
  let lateCount = 0;
  let lateOver10Count = 0;
  let lateOver30Count = 0;

  let holidayShiftsCount = 0;
  let holidayExtraTotal = 0;
  let holidayMins = 0;

  empRecords.forEach(r => {
    standardMins += r.standardMins;
    otMins += r.overtimeMins;
    standardCost += r.standardCost;
    otCost += r.overtimeCost;
    totalShifts++;
    if (r.isHoliday) {
      holidayShiftsCount++;
      holidayMins += r.mins;
      holidayExtraTotal += (r.holidayExtra || 0);
    }
    if (r.lateMins > POLICY.LATE_THRESHOLD_MINS) {
      lateCount++;
      lateOver10Count++;
    }
    if (r.lateMins > POLICY.LATE_THRESHOLD_INSTANT_FINE) {
      lateOver30Count++;
    }
  });

  const emp = state.employeesMap[staffName] || { wage: 17000 };
  const salaryType = (emp && emp.salary_type) || 'HOURLY';
  const fixedSalary = (emp && Number(emp.fixed_salary)) || 0;
  if (salaryType === 'FIXED' && fixedSalary > 0) {
    standardCost = fixedSalary;
    emp.wage = fixedSalary;
  }
  const monthLabel = state.currentMonth === 'all' ? 'TẤT CẢ CÁC THÁNG' : `THÁNG ${state.currentMonth}/2026`;
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;

  const bSummary = getStaffBonusSummary(m, staffName);
  let totalBonus = bSummary.total;
  let totalReceived = standardCost + otCost + totalBonus;

  let aSummary = (m === '8') ? 0 : getStaffAdvanceSummary(m, staffName);
  const aList = (m === '8') ? [] : getStaffAdvances(m, staffName);
  let bankTransfer = Math.max(0, standardCost + otCost + bSummary.bank - aSummary);

  let totalHours = ((standardMins + otMins) / 60).toFixed(1);
  let standardHours = (standardMins / 60).toFixed(1);
  let otHours = (otMins / 60).toFixed(1);
  const roleLabel = (emp && emp.role) ? emp.role : getStaffRole(staffName);
  const isManagerViolation = (m === '8') ? false : (roleLabel.toLowerCase().includes('quản lý') && lateOver10Count >= 5);

  // B5: Progressive discipline penalties & incident deductions
  let totalPenalty = 0;
  let penaltyDetails = [];
  const enablePenalties = (m !== '8');
  if (enablePenalties && lateOver30Count > 0) {
    const instantFine = lateOver30Count * POLICY.LATE_INSTANT_FINE_AMOUNT;
    totalPenalty += instantFine;
    penaltyDetails.push(`Trễ >30p: ${lateOver30Count} lần × ${fmtMoney.format(POLICY.LATE_INSTANT_FINE_AMOUNT).replace('₫','đ')}`);
  }
  for (let i = 1; enablePenalties && i <= lateOver10Count && i <= POLICY.LATE_PENALTIES.length; i++) {
    const rule = POLICY.LATE_PENALTIES[i - 1];
    if (rule.action === 'fine') {
      totalPenalty += rule.amount;
      penaltyDetails.push(`Lần ${i}: ${fmtMoney.format(rule.amount).replace('₫','đ')}`);
    } else if (rule.action === 'terminate') {
      penaltyDetails.push(`Lần ${i}: CẢNH BÁO ĐỎ - CHO NGHỈ`);
    }
  }

  const dSummary = getStaffDeductionSummary(m, staffName);
  if (dSummary.list && dSummary.list.length > 0) {
    dSummary.list.forEach(d => {
      totalPenalty += d.amount;
      penaltyDetails.push(`${escapeHtml(d.reason || 'Kỷ luật sự cố')}: -${fmtMoney.format(d.amount).replace('₫','đ')}`);
    });
  }

  const sB = serverBreakdown || (state.serverPayrollSummaryCache ? state.serverPayrollSummaryCache[`${m}_${staffName}`] : null);
  const isServerVerified = !!sB;

  if (sB) {
    standardCost = Number(sB.standard_pay || 0);
    otCost = 0;
    totalBonus = Number(sB.eval_bonus || 0);
    totalReceived = Number(sB.gross_salary || (standardCost + totalBonus));
    totalPenalty = Number(sB.total_deductions != null ? sB.total_deductions : (Number(sB.late_penalty_total || 0) + Number(sB.eval_deductions || 0)));
    if (sB.violations && Array.isArray(sB.violations) && sB.violations.length > 0) {
      penaltyDetails = sB.violations.map(v => escapeHtml(v));
    }
    const currentAdvance = (m === '8') ? 0 : getStaffAdvanceSummary(m, staffName);
    aSummary = Math.max(Number(sB.advance_amount || 0), currentAdvance);
    bankTransfer = Math.max(0, standardCost - aSummary);
    totalHours = Number(sB.total_hours || 0).toFixed(1);
    standardHours = totalHours;
    totalShifts = Number(sB.total_shifts || 0);
    if (sB.base_wage) emp.wage = sB.base_wage;
  }

  const bankTransferAfterPenalty = (sB && sB.net_pay != null)
    ? Number(sB.net_pay)
    : Math.max(0, totalReceived - aSummary - totalPenalty);
  const refCode = `TB-${staffName}-${state.currentMonth || 'ALL'}-${Date.now().toString().slice(-4)}`;

  state.currentViewingStaff = {
    name: staffName,
    bankTransferAfterPenalty: bankTransferAfterPenalty,
    mins: standardMins + otMins,
    shifts: totalShifts,
    wage: emp.wage,
    totalBonus: totalBonus,
    violations: penaltyDetails
  };

  let bonusNoteSub = '';
  if (bSummary.cash > 0 && bSummary.bank > 0) {
    bonusNoteSub = ` <em style="font-size:12px; opacity:0.85;">(TM: ${fmtMoney.format(bSummary.cash).replace('₫','đ')} | CK: ${fmtMoney.format(bSummary.bank).replace('₫','đ')})</em>`;
  } else if (bSummary.cash > 0) {
    bonusNoteSub = ` <em style="font-size:12px; opacity:0.85;">(Đã nhận TM tại quầy)</em>`;
  }

  let advanceNoteSub = '';
  if (aList && aList.length > 0) {
    const canManageLedger = (['ADMIN', 'MANAGER'].includes(localStorage.getItem('vnaigc_role')) || ['ADMIN', 'MANAGER'].includes(state.rawData && state.rawData._meta && state.rawData._meta.role));
    const itemsHtml = aList.map((a) => {
      const dateStr = a.date || (a.timestamp ? a.timestamp.split(' ')[0] : '') || '';
      const typeStr = a.type === 'bank' ? 'CK' : 'TM';
      const reasonStr = a.reason ? ` • ${escapeHtml(a.reason)}` : '';
      let actions = '';
      if (canManageLedger && a.id) {
        actions = `
          <span style="display:inline-flex; align-items:center; gap:4px; margin-left:6px; flex-shrink:0;">
            <button type="button" onclick="window.editStaffLedger('${escapeHtml(a.id)}', '${escapeHtml(staffName)}', ${Number(a.amount) || 0}, '${escapeHtml(a.type || 'cash')}', '${escapeHtml(a.reason || '')}', '${escapeHtml(m)}')" style="background:rgba(59, 130, 246, 0.1); border:1px solid rgba(59, 130, 246, 0.3); color:#2563eb; border-radius:4px; cursor:pointer; font-size:11px; font-weight:700; padding:2px 6px;">✎ Sửa</button>
            <button type="button" onclick="window.deleteStaffLedger('${escapeHtml(a.id)}', '${escapeHtml(staffName)}', ${Number(a.amount) || 0}, '${escapeHtml(m)}')" style="background:rgba(239, 68, 68, 0.1); border:1px solid rgba(239, 68, 68, 0.3); color:#dc2626; border-radius:4px; cursor:pointer; font-size:11px; font-weight:700; padding:2px 6px;">✕ Xóa</button>
          </span>
        `;
      }
      return `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:3px; font-size:11.5px; background:rgba(0,0,0,0.02); padding:4px 8px; border-radius:6px; border:1px dashed var(--border);">
          <span style="color:var(--text-secondary); min-width:0; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(dateStr)}: <strong style="color:var(--accent-coral);">-${fmtMoney.format(a.amount).replace('₫','đ')}</strong> (${escapeHtml(typeStr)})${reasonStr}</span>
          ${actions}
        </div>
      `;
    }).join('');
    advanceNoteSub = `<div style="margin-top:4px; display:flex; flex-direction:column; gap:3px; width:100%;">${itemsHtml}</div>`;
  }

  state.currentViewingStaff = {
    name: staffName,
    role: roleLabel,
    wage: emp.wage,
    shifts: totalShifts,
    mins: standardMins + otMins,
    totalBonus,
    bankTransferAfterPenalty,
    violations: penaltyDetails
  };

  return `
    <div class="receipt-card-premium payslip-card">
        <div class="rc-perforated-top"></div>

        <!-- Brand Header -->
        <div class="rc-brand">
            <div class="rc-logo-text">${escapeHtml(((typeof window !== 'undefined' && window.vnaigc_store_name) || (typeof localStorage !== 'undefined' && localStorage.getItem('vnaigc_store_name')) || 'FnBOps').toUpperCase())}</div>
            <div class="rc-sub">Powered by FnBOps</div>
            <div class="rc-badge-pill">PHIẾU LƯƠNG NHÂN SỰ • ${monthLabel}</div>
            ${isServerVerified ? `
              <div style="margin-top:6px; display:inline-flex; align-items:center; gap:4px; background:rgba(16, 185, 129, 0.15); border:1px solid var(--accent-emerald); border-radius:6px; padding:3px 10px; font-size:12px; font-weight:700; color:var(--accent-emerald);">
                <span>✓</span> ĐÃ ĐỐI SOÁT TỪ SERVER
              </div>
            ` : `
              <div style="margin-top:6px; display:inline-flex; align-items:center; gap:4px; background:rgba(245, 158, 11, 0.15); border:1px solid #f59e0b; border-radius:6px; padding:3px 10px; font-size:12px; font-weight:700; color:#d97706;">
                <span>⚡</span> BẢNG LƯƠNG TẠM TÍNH
              </div>
            `}
        </div>

        <div class="rc-divider-dashed"></div>

        <!-- Employee Metadata Grid -->
        <div class="rc-employee-section">
            <div class="rc-emp-meta">
                <span class="rc-emp-label">${roleLabel.toLowerCase().includes('quản lý') ? 'QUẢN LÝ VẬN HÀNH' : 'NHÂN VIÊN VẬN HÀNH'}</span>
                <span class="rc-emp-name">${escapeHtml(staffName)}</span>
                <span class="rc-emp-role">${escapeHtml(roleLabel)}</span>
            </div>
            <div class="rc-emp-meta rc-hide-mobile" style="text-align: right; align-items: flex-end;">
                <span class="rc-emp-label">MÃ TRA CỨU</span>
                <span class="rc-ref-code">${escapeHtml(refCode)}</span>
                <span class="rc-badge-status">ĐÃ XÁC THỰC</span>
            </div>
        </div>

        <!-- Hero Amount Section -->
        <div class="rc-hero-total">
            <span class="rc-hero-label">THỰC CHUYỂN KHOẢN (ĐÃ TRỪ ỨNG)</span>
            ${isManagerOther ? `
            <div class="rc-hero-amount tabular-nums" style="font-size:18px; letter-spacing:1px; color:var(--text-muted);">BẢO MẬT QUẢN TRỊ</div>
            <div class="rc-hero-sub">Chỉ Chủ quán (Admin) và nhân sự mới có quyền xem chi tiết số tiền lương</div>
            ` : `
            <div class="rc-hero-amount tabular-nums">${fmtMoney.format(bankTransferAfterPenalty).replace('₫', 'đ')}</div>
            <div class="rc-hero-sub">Lương thực nhận sau khi khấu trừ tạm ứng &amp; kỷ luật</div>
            `}

            <!-- 3-Mini Stats Trio (from Figma) -->
            <div class="rc-stats-trio">
                <div class="rc-stat-box">
                    <span class="rc-stat-val tabular-nums">${totalShifts} ca</span>
                    <span class="rc-stat-lbl">Ca làm</span>
                </div>
                <div class="rc-stat-box">
                    <span class="rc-stat-val tabular-nums">${totalHours}h</span>
                    <span class="rc-stat-lbl">Giờ công</span>
                </div>
                <div class="rc-stat-box">
                    <span class="rc-stat-val tabular-nums">${isManagerOther ? '***' : (fmtMoney.format(emp.wage).replace('₫', 'đ') + '/h')}</span>
                    <span class="rc-stat-lbl">Đơn giá</span>
                </div>
            </div>
        </div>

        <!-- Action Buttons Bar (Figma Actions) -->
        <div class="rc-actions-bar">
            ${(userRole === 'ADMIN' || (state.rawData && state.rawData._meta && state.rawData._meta.role === 'ADMIN')) ? `
              <button type="button" onclick="openLedgerEntryModal('${escapeHtml(staffName)}', 'advance')" class="rc-btn-earthy primary">
                + Ghi Tạm Ứng
              </button>
            ` : ''}
            <button type="button" onclick="handleStaffDispute()" class="rc-btn-earthy secondary" style="display:inline-flex; align-items:center; gap:4px;">
              <iconify-icon icon="solar:danger-circle-linear" width="15" height="15"></iconify-icon> Báo Sai Lệch Giờ
            </button>
            <button type="button" onclick="openStaffShiftsDetailModal('${escapeHtml(staffName)}')" class="rc-btn-earthy secondary">
              Chi Tiết 31 Ngày
            </button>
        </div>

        ${isManagerViolation ? `
        <div class="governance-hold-box">
            <strong>KỶ LUẬT VẬN HÀNH QUÁN:</strong> Nhân sự quản lý vi phạm trễ ca ${lateOver10Count} lần (>10p). Khoản thưởng hiệu suất (+${fmtMoney.format(totalBonus).replace('₫','đ')}) đang tạm giữ, cần Chủ quán (Admin) phê duyệt giải ngân thủ công.
        </div>
        ` : ''}

        <div class="rc-divider-dashed"></div>

        <!-- Details Breakdown (Khung chi tiết giờ công / ca trực) -->
        <div class="rc-details-table">
            <div class="rc-row">
                <span class="rc-row-title">Tổng ca trực hoàn thành</span>
                <span class="rc-row-val tabular-nums">${totalShifts} ca</span>
            </div>
            <div class="rc-row">
                <span class="rc-row-title">Tổng thời gian làm việc</span>
                <span class="rc-row-val tabular-nums">${fmtNum.format(standardMins + otMins)} phút <em>(${totalHours} giờ)</em></span>
            </div>
            <div class="rc-row">
                <span class="rc-row-title">Đơn giá lương cơ bản</span>
                <span class="rc-row-val tabular-nums">${isManagerOther ? '*** đ/giờ' : (fmtMoney.format(emp.wage).replace('₫', 'đ') + '/giờ')}</span>
            </div>
            <div class="rc-row">
                <span class="rc-row-title">Lương tiêu chuẩn (${standardHours} giờ)</span>
                <span class="rc-row-val tabular-nums">${fmtMoney.format(standardCost).replace('₫', 'đ')}</span>
            </div>
            <div class="rc-row highlight-ot">
                <span class="rc-row-title">Lương làm thêm Overtime (${otHours} giờ)</span>
                <span class="rc-row-val tabular-nums">+${fmtMoney.format(otCost).replace('₫', 'đ')}</span>
            </div>
            ${holidayExtraTotal > 0 ? `
            <div class="rc-row rc-row-holiday">
                <span class="rc-row-title">
                    Phụ cấp Lễ 2/9 (Hệ số x2: +100%)
                    <div style="font-size: 12px; font-weight: 400; opacity: 0.85;">${holidayShiftsCount} ca trực • ${(holidayMins/60).toFixed(1)} giờ làm ngày lễ</div>
                </span>
                <span class="rc-row-val tabular-nums" style="font-weight: 800; font-size: 13px;">
                    +${fmtMoney.format(holidayExtraTotal).replace('₫', 'đ')}
                </span>
            </div>
            ` : ''}
            <div class="rc-row">
                <span class="rc-row-title">Thưởng nóng / Hiệu suất ${isManagerViolation ? '<em style="color:var(--accent-coral); font-weight:700;">(Đang tạm giữ)</em>' : ''}</span>
                <span class="rc-row-val tabular-nums" style="color: ${isManagerViolation ? 'var(--accent-coral)' : 'var(--accent-emerald)'};">
                    +${fmtMoney.format(totalBonus).replace('₫', 'đ')}
                    ${bonusNoteSub}
                </span>
            </div>
            <div class="rc-row">
                <span class="rc-row-title">Tạm ứng trong kỳ (${aList ? aList.length : 0} lần)</span>
                <span class="rc-row-val tabular-nums" style="color: var(--accent-coral);">
                    -${fmtMoney.format(aSummary).replace('₫', 'đ')}
                    ${advanceNoteSub}
                </span>
            </div>
            <div class="rc-row rc-row-penalty"${totalPenalty > 0 ? ' data-penalty="true"' : ''}>
                <span class="rc-row-title"${totalPenalty > 0 ? ' style="color: var(--accent-coral); font-weight: 600;"' : ''}>Khấu trừ vi phạm &amp; Kỷ luật (${lateOver10Count} lần trễ${dSummary.count > 0 ? ` • ${dSummary.count} phạt vi phạm` : ''})</span>
                <span class="rc-row-val tabular-nums${totalPenalty > 0 ? '' : ' text-muted'}"${totalPenalty > 0 ? ' style="color: var(--accent-coral); font-weight: 700;"' : ''}>
                    -${fmtMoney.format(totalPenalty).replace('₫', 'đ')}
                    ${penaltyDetails.length > 0 ? `<div style="font-size:12px; opacity:0.85; margin-top:2px; font-weight:400;">(${penaltyDetails.join(' • ')})</div>` : ''}
                </span>
            </div>
        </div>

        <div class="rc-divider-double"></div>

        <!-- Sổ Cái Bất Biến (Audit Trail) -->
        <div id="payslipLedgerSection" style="margin-bottom: 12px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 6px;">
                    <iconify-icon icon="solar:bill-list-bold" style="font-size: 16px; color: var(--accent-coral);"></iconify-icon>
                    <span style="font-size: 13px; font-weight: 800; color: var(--text-primary);">Sổ Cái Điều Chỉnh Lương</span>
                </div>
                <span style="font-size: 10.5px; color: var(--text-muted); font-weight: 600;">Bất Biến &amp; Minh Bạch</span>
            </div>
            <div id="payslipLedgerList">
                <div style="font-size: 11.5px; color: var(--text-muted); text-align: center; padding: 8px 0;">Đang tải lịch sử sổ cái...</div>
            </div>
        </div>

        <!-- Button: Xem Chi Tiết Ngày Công 1 - 31 -->
        <button type="button" onclick="openStaffShiftsDetailModal('${escapeHtml(staffName)}')" class="sheet-btn secondary rc-btn-detail">
            <span>Xem Chi Tiết Ngày Công (Ngày 1 - 31)</span>
            <span class="rc-shifts-badge">${totalShifts} ca trực</span>
        </button>

        <!-- Admin/Manager Quick Actions: Ghi Tạm Ứng & Trạng Thái Chuyển Khoản -->
        <div class="rc-admin-actions" style="margin-top: 10px; display: flex; flex-direction: column; gap: 8px;">
            ${(['ADMIN', 'MANAGER'].includes(localStorage.getItem('vnaigc_role')) || ['ADMIN', 'MANAGER'].includes(state.rawData && state.rawData._meta && state.rawData._meta.role)) ? `
              <div style="display:flex; gap:8px;">
                <button type="button" onclick="sendPayslipZaloCard('${escapeHtml(staffName)}', '${escapeHtml(m)}')" class="sheet-btn" style="flex:1; background:rgba(48, 209, 88, 0.12); color:var(--accent-emerald); border:1.5px solid rgba(48, 209, 88, 0.4); font-weight:700; padding:10px; font-size:12.5px; border-radius:8px; cursor:pointer; display:flex; align-items:center; justify-content:center; gap:6px;">
                  <span>📱</span> Gửi Ảnh Zalo
                </button>
                <button type="button" onclick="previewPayslipZaloCard('${escapeHtml(staffName)}', '${escapeHtml(m)}')" class="sheet-btn secondary" style="width:auto; padding:10px 12px; font-size:12px; font-weight:600;" title="Xem trước ảnh thẻ lương Dark Luxury">
                  👁️ Xem Thẻ
                </button>
              </div>
              ${(userRole === 'ADMIN' || (state.rawData && state.rawData._meta && state.rawData._meta.role === 'ADMIN')) ? `
              <button type="button" onclick="openLedgerEntryModal('${escapeHtml(staffName)}', 'advance')" class="sheet-btn" style="background: rgba(239, 68, 68, 0.1); color: #dc2626; border: 1.5px solid #ef4444; font-weight: 700; padding: 10px; font-size: 13px; border-radius: 8px; cursor: pointer;">
                ➕ Ghi Tạm Ứng Cho ${escapeHtml(staffName)}
              </button>
              ` : ''}
            ` : ''}

            ${(() => {
              const isPaid = checkStaffIsPaid(m, staffName);
              const canToggle = (userRole === 'ADMIN' || (state.rawData && state.rawData._meta && state.rawData._meta.role === 'ADMIN'));
              if (isPaid) {
                return `
                  <div style="background: rgba(16, 185, 129, 0.12); border: 1.5px solid #10b981; border-radius: 8px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: #047857; font-weight: 800; font-size: 13px;">✓ ĐÃ CHUYỂN KHOẢN LƯƠNG</span>
                    ${canToggle ? `<button onclick="toggleStaffDisbursement('${escapeHtml(staffName)}', 'UNPAID', ${bankTransferAfterPenalty})" style="background: none; border: 1px solid #059669; color: #047857; border-radius: 6px; padding: 4px 8px; font-size: 12px; font-weight: 600; cursor: pointer;">Đổi sang Chưa CK</button>` : ''}
                  </div>
                `;
              } else {
                return `
                  <div style="background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="color: var(--accent-coral); font-weight: 800; font-size: 13px;">⏳ CHƯA CHUYỂN KHOẢN</span>
                    ${canToggle ? `<button onclick="toggleStaffDisbursement('${escapeHtml(staffName)}', 'PAID', ${bankTransferAfterPenalty})" style="background: #059669; color: #fff; border: none; border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 700; cursor: pointer;">✓ Xác Nhận Đã CK</button>` : ''}
                  </div>
                `;
              }
            })()}
        </div>

        <!-- Summary Total Row -->
        <div class="rc-summary-row" style="${checkStaffIsPaid(m, staffName) ? 'border-top: 2px solid #10b981; background: rgba(16, 185, 129, 0.08); padding: 10px 12px; border-radius: 8px;' : ''}">
            <span class="rc-sum-label" style="${checkStaffIsPaid(m, staffName) ? 'color: #047857; font-weight: 800;' : ''}">${checkStaffIsPaid(m, staffName) ? '✓ ĐÃ CHUYỂN KHOẢN HOÀN TẤT:' : 'THỰC CHUYỂN KHOẢN (ĐÃ TRỪ ỨNG):'}</span>
            <span class="rc-sum-val tabular-nums" style="color: ${checkStaffIsPaid(m, staffName) ? '#047857 !important;' : 'var(--accent-coral);'} font-size: 20px; font-weight: 800;">${fmtMoney.format(bankTransferAfterPenalty).replace('₫', 'đ')}</span>
        </div>

        <!-- Notice & Policy -->
        <div class="rc-notice-box">
            <p>📌 <strong>Quy định thanh toán:</strong> Mọi thắc mắc về lương/thưởng/tạm ứng, các bạn vui lòng phản hồi trong 24h. Lương sẽ được chuyển khoản vào ngày 05 hàng tháng.</p>
        </div>

        <!-- Barcode Footer -->
        <div class="rc-barcode-footer">
            <div class="rc-barcode-lines">
                <span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span>
            </div>
            <div class="rc-footer-text">${escapeHtml(((typeof window !== 'undefined' && window.vnaigc_store_name) || (typeof localStorage !== 'undefined' && localStorage.getItem('vnaigc_store_name')) || 'FNBOPS').toUpperCase())} • CONFIDENTIAL PAYROLL DOCUMENT</div>
        </div>

        <div class="rc-serrated-edge"></div>
    </div>
  `;
}

export async function loadStaffSoCaiLuong(staffName, m) {
  const container = document.getElementById('payslipLedgerList');
  if (!container) return;
  const token = localStorage.getItem('vnaigc_jwt');
  if (!token) return;

  const monthParam = (m && m !== 'all') ? `&month=${m}` : '';
  const url = `/api/v1/cc/admin/so-cai-luong?staff_name=${encodeURIComponent(staffName || '')}${monthParam}`;

  try {
    const res = await fetch(url, {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    if (!res.ok) {
      container.innerHTML = '<div style="font-size:11.5px; color:var(--text-muted); text-align:center; padding:10px 0;">Chưa có bút toán sổ cái nào được ghi nhận.</div>';
      return;
    }
    const data = await res.json();
    const events = (data && data.events) || [];
    if (events.length === 0) {
      container.innerHTML = '<div style="font-size:11.5px; color:var(--text-muted); text-align:center; padding:10px 0;">Không có bút toán điều chỉnh trong kỳ này.</div>';
      return;
    }

    let h = '';
    events.forEach(ev => {
      let typeLabel = ev.event_type;
      let badgeColor = 'var(--text-secondary)';
      let badgeBg = 'var(--bg-input)';
      let valueHtml = '';

      if (ev.event_type === 'THUONG') {
        typeLabel = 'Thưởng';
        badgeColor = '#059669';
        badgeBg = 'rgba(16, 185, 129, 0.12)';
        valueHtml = `<span style="color:#059669; font-weight:700; font-family:var(--font-mono);">+${fmtMoney.format(ev.amount || 0).replace('₫', 'đ')}</span>`;
      } else if (ev.event_type === 'PHAT') {
        typeLabel = 'Phạt / Trừ';
        badgeColor = '#dc2626';
        badgeBg = 'rgba(239, 68, 68, 0.12)';
        valueHtml = `<span style="color:#dc2626; font-weight:700; font-family:var(--font-mono);">-${fmtMoney.format(ev.amount || 0).replace('₫', 'đ')}</span>`;
      } else if (ev.event_type === 'UNG_LUONG') {
        typeLabel = 'Tạm Ứng';
        badgeColor = '#d97706';
        badgeBg = 'rgba(245, 158, 11, 0.12)';
        valueHtml = `<span style="color:#d97706; font-weight:700; font-family:var(--font-mono);">-${fmtMoney.format(ev.amount || 0).replace('₫', 'đ')}</span>`;
      } else if (ev.event_type === 'DIEU_CHINH_GIO') {
        typeLabel = 'Duyệt Giờ Ca';
        badgeColor = '#2563eb';
        badgeBg = 'rgba(37, 99, 235, 0.12)';
        const mins = ev.minutes || 0;
        valueHtml = `<span style="color:#2563eb; font-weight:700; font-family:var(--font-mono);">${mins > 0 ? '+' : ''}${mins}p</span>`;
      } else if (ev.event_type === 'DOI_MUC_LUONG') {
        typeLabel = 'Đổi Lương';
        badgeColor = '#7c3aed';
        badgeBg = 'rgba(139, 92, 246, 0.12)';
        valueHtml = `<span style="color:#7c3aed; font-weight:700; font-family:var(--font-mono);">${(ev.amount || 0).toLocaleString('vi-VN')}đ/h</span>`;
      }

      const dateStr = (ev.created_at || '').slice(0, 16);

      h += `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:7px 0; border-bottom:1px dashed var(--border); font-size:11.5px;">
          <div>
            <div style="display:flex; align-items:center; gap:6px;">
              <span style="font-size:10px; font-weight:700; background:${badgeBg}; color:${badgeColor}; padding:1px 5px; border-radius:4px;">${typeLabel}</span>
              <span style="color:var(--text-primary); font-weight:600;">${escapeHtml(ev.note || ev.reason || 'Bút toán sổ cái')}</span>
            </div>
            <div style="font-size:10.5px; color:var(--text-muted); margin-top:2px;">${dateStr ? dateStr : ''} ${ev.author ? '• Bởi: ' + escapeHtml(ev.author) : ''}</div>
          </div>
          <div>${valueHtml}</div>
        </div>
      `;
    });

    container.innerHTML = h;
  } catch (err) {
    container.innerHTML = '<div style="font-size:11.5px; color:var(--text-muted); text-align:center; padding:10px 0;">Không thể tải sổ cái.</div>';
  }
}

export async function openPayslipModal(staffName) {
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  const cached = state.serverPayrollSummaryCache[`${m}_${staffName}`];
  const html = generatePayslipHtml(staffName, cached);
  const contentEl = document.getElementById('payslipContent');
  if (contentEl) contentEl.innerHTML = html;
  document.getElementById('payslipSheet').classList.add('active');
  loadStaffSoCaiLuong(staffName, m);

  if (!cached) {
    const fresh = await fetchServerPayrollSummary(m, staffName);
    if (fresh && contentEl) {
      contentEl.innerHTML = generatePayslipHtml(staffName, fresh);
      loadStaffSoCaiLuong(staffName, m);
    }
  }
}


export function setupPayslipActionButtons() {
  const btnPrint = document.getElementById("btnPrintSheet");
  if (btnPrint) {
    btnPrint.addEventListener("click", () => window.print());
  }

  const btnExportExcelMobile = document.getElementById("btnExportPayrollExcelMobile");
  if (btnExportExcelMobile) {
    btnExportExcelMobile.addEventListener("click", () => {
      const currentM = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
      const url = getExportPayrollUrl(currentM);
      window.open(url, "_blank");
    });
  }

  const btnBulkZalo = document.getElementById("btnSendBulkZaloCards");
  if (btnBulkZalo) {
    btnBulkZalo.addEventListener("click", () => {
      const currentM = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
      sendBulkPayslipZaloCards(currentM);
    });
  }

  const btnTelegram = document.getElementById("btnTelegramSend");
  if (btnTelegram) {
    btnTelegram.addEventListener("click", async () => {
      if (!state.currentViewingStaff) {
        showToast("Chưa chọn nhân sự để gửi phiếu lương!", "warn");
        return;
      }
      btnTelegram.innerHTML = "<span>⏳</span> Đang gửi...";
      btnTelegram.disabled = true;

      const currentM = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
      const payload = {
        staffName: state.currentViewingStaff.name,
        monthTitle: `Tháng ${currentM}/2026`,
        finalPayFormatted: fmtMoney.format(state.currentViewingStaff.bankTransferAfterPenalty).replace("₫", "đ"),
        totalHours: (state.currentViewingStaff.mins / 60).toFixed(1),
        totalMinsFormatted: fmtNum.format(state.currentViewingStaff.mins),
        shifts: state.currentViewingStaff.shifts.toString(),
        baseWageFormatted: `${fmtNum.format(state.currentViewingStaff.wage)} đ/h`,
        bonusFormatted: state.currentViewingStaff.totalBonus > 0 ? `+${fmtMoney.format(state.currentViewingStaff.totalBonus).replace("₫", "đ")}` : "+0 đ",
        violations: state.currentViewingStaff.violations || []
      };

      try {
        const res = await sendPayslipTelegramApi(payload);
        if (res.ok) {
          showToast(`Đã gửi phiếu lương của ${state.currentViewingStaff.name} vào Telegram thành công!`, 'success');
        } else {
          showToast("Lỗi từ N8N Webhook!", "error");
        }
      } catch (e) {
        showToast("Không thể kết nối đến Webhook Telegram!", "error");
      } finally {
        btnTelegram.innerHTML = "Gửi Telegram";
        btnTelegram.disabled = false;
      }
    });
  }

  const closePayslipModal = () => {
    const sheet = document.getElementById("payslipSheet");
    if (sheet) sheet.classList.remove("active");
  };
  const btnClose = document.getElementById("btnCloseSheet");
  if (btnClose) {
    btnClose.addEventListener("click", closePayslipModal);
  }
  const btnCloseTop = document.getElementById("btnCloseSheetTop");
  if (btnCloseTop) {
    btnCloseTop.addEventListener("click", closePayslipModal);
  }

  document.querySelectorAll(".role-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".role-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      state.currentRoleFilter = pill.getAttribute("data-role");
      renderTabPayslip();
    });
  });

  const searchInput = document.getElementById("payslipSearch");
  if (searchInput) {
    searchInput.addEventListener("input", () => renderTabPayslip());
  }

  // Disbursement filter pills
  document.querySelectorAll(".disb-filter-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".disb-filter-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      state.currentDisbursementFilter = pill.getAttribute("data-disb") || "ALL";
      renderTabPayslip();
    });
  });

  // Setup ledger entry modal events
  setupLedgerEntryModal();
}


export function setupEvalModal() {
  const btnOpen = document.getElementById('btnOpenEval');
  const btnClose = document.getElementById('btnCloseEval');
  const modal = document.getElementById('evalSheet');
  const staffSelect = document.getElementById('evalStaffSelect');
  const shiftSelect = document.getElementById('evalShiftSelect');
  const dateInput = document.getElementById('evalDateInput');
  const notesInput = document.getElementById('evalNotesInput');
  const amountInput = document.getElementById('evalAmountInput');
  const typeSelect = document.getElementById('evalTypeSelect');
  const btnCustom = document.getElementById('btnSubmitCustomEval');

  const tabPenalty = document.getElementById('tabEvalPenalty');
  const tabBonus = document.getElementById('tabEvalBonus');
  const containerPenalty = document.getElementById('evalPenaltyContainer');
  const containerBonus = document.getElementById('evalBonusContainer');
  const quickPills = document.querySelectorAll('.quick-amount-pill');

  let currentEvalType = 'Phạt';

  function switchEvalTab(type) {
    currentEvalType = type;
    if (type === 'Phạt') {
      tabPenalty?.classList.add('active');
      tabBonus?.classList.remove('active');
      if (containerPenalty) containerPenalty.style.display = 'block';
      if (containerBonus) containerBonus.style.display = 'none';
      modal?.classList.remove('eval-sheet-bonus-mode');
      if (typeSelect) typeSelect.value = 'Phạt';
      if (btnCustom) {
        btnCustom.textContent = 'Gửi Biên Bản Phạt & Lưu Bảng Lương';
        btnCustom.style.background = 'var(--accent-coral)';
        btnCustom.style.borderColor = 'var(--accent-coral)';
      }
    } else {
      tabBonus?.classList.add('active');
      tabPenalty?.classList.remove('active');
      if (containerBonus) containerBonus.style.display = 'block';
      if (containerPenalty) containerPenalty.style.display = 'none';
      modal?.classList.add('eval-sheet-bonus-mode');
      if (typeSelect) typeSelect.value = 'Thưởng';
      if (btnCustom) {
        btnCustom.textContent = 'Gửi Khen Thưởng & Lưu Bảng Lương';
        btnCustom.style.background = 'var(--accent-emerald)';
        btnCustom.style.borderColor = 'var(--accent-emerald)';
      }
    }
  }

  if (tabPenalty) {
    tabPenalty.addEventListener('click', () => switchEvalTab('Phạt'));
  }
  if (tabBonus) {
    tabBonus.addEventListener('click', () => switchEvalTab('Thưởng'));
  }

  // Quick Amount Pills selection & two-way sync with amount input
  quickPills.forEach(pill => {
    pill.addEventListener('click', () => {
      const amt = parseInt(pill.getAttribute('data-amount')) || 0;
      quickPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      if (amountInput) {
        amountInput.value = amt;
      }
    });
  });

  if (amountInput) {
    amountInput.addEventListener('input', () => {
      const val = parseInt(amountInput.value) || 0;
      quickPills.forEach(p => {
        const pAmt = parseInt(p.getAttribute('data-amount')) || 0;
        p.classList.toggle('active', pAmt === val);
      });
    });
  }

  if (btnOpen) {
    btnOpen.addEventListener('click', () => {
      // Populate staff
      if (staffSelect) {
        staffSelect.innerHTML = '';
        const names = Object.values(state.employeesMap)
          .filter(e => e.status === 'ĐANG LÀM')
          .map(e => e.name)
          .sort();
        names.forEach(n => {
          const opt = document.createElement('option');
          opt.value = n;
          opt.textContent = n;
          staffSelect.appendChild(opt);
        });
      }
      if (dateInput) {
        dateInput.value = new Date().toISOString().split('T')[0];
      }
      if (notesInput) {
        notesInput.value = '';
      }
      if (amountInput) {
        amountInput.value = '';
      }
      quickPills.forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.incident-action-btn').forEach(b => b.classList.remove('active'));
      switchEvalTab('Phạt');
      modal?.classList.add('active');
      updateSheetScrollLock();
    });
  }

  if (btnClose) {
    btnClose.addEventListener('click', () => {
      modal?.classList.remove('active');
      updateSheetScrollLock();
    });
  }

  // Mẫu vi phạm / khen thưởng nhanh: Nhấn để điền trước thông tin vào form (không ghi thẳng)
  document.querySelectorAll('.incident-action-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const incident = btn.getAttribute('data-incident') || '';
      const explicitType = btn.getAttribute('data-type') || currentEvalType || 'Phạt';
      const explicitAmount = parseInt(btn.getAttribute('data-amount')) || 0;

      // Đồng bộ tab Phạt / Thưởng nếu khác loại
      if (explicitType !== currentEvalType) {
        switchEvalTab(explicitType);
      }

      // Đánh dấu nút được chọn
      document.querySelectorAll('.incident-action-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // Điền số tiền và đồng bộ quick-amount-pill
      if (amountInput) {
        amountInput.value = explicitAmount > 0 ? explicitAmount : '';
        quickPills.forEach(p => {
          const pAmt = parseInt(p.getAttribute('data-amount')) || 0;
          p.classList.toggle('active', pAmt === explicitAmount && explicitAmount > 0);
        });
      }

      // Điền lý do vào ô nhập
      if (notesInput) {
        notesInput.value = incident;
      }

      // Rung phản hồi haptics
      if (typeof window.triggerHaptic === 'function') {
        window.triggerHaptic('selection');
      }

      showToast(`Đã chọn: "${incident}". Hãy kiểm tra, sửa số tiền/lý do nếu muốn rồi bấm nút gửi bên dưới!`, 'info');
    });
  });

  if (btnCustom) {
    btnCustom.addEventListener('click', async () => {
      const staffName = staffSelect?.value;
      if (!staffName) return showToast('Vui lòng chọn nhân sự!', 'warn');
      const notes = (notesInput?.value || '').trim();
      if (!notes || notes.length < 3) return showToast('Vui lòng nhập nội dung ghi chú chi tiết (tối thiểu 3 ký tự)!', 'warn');

      const shift = (shiftSelect && shiftSelect.value) || 'Ca Sáng';
      const date = (dateInput && dateInput.value) ? dateInput.value : new Date().toISOString().split('T')[0];
      const evalType = (typeSelect && typeSelect.value) || currentEvalType || 'Phạt';
      const evalAmount = parseInt(amountInput?.value) || 0;
      if (evalAmount <= 0) return showToast('Vui lòng nhập số tiền phạt / thưởng hợp lệ (> 0đ)!', 'warn');

      const originalBtnText = btnCustom.textContent;
      btnCustom.textContent = 'Đang gửi...';
      btnCustom.disabled = true;

      const token = localStorage.getItem('vnaigc_jwt');
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const backendPayload = {
        staff_name: staffName,
        date: date,
        shift: shift,
        type: evalType,
        amount: evalAmount,
        reason: notes,
        notes: notes,
        ratings: { discipline: evalType === 'Thưởng' ? 5 : 3, service: evalType === 'Thưởng' ? 5 : 3, cleanliness: 4 },
        red_flags: evalType === 'Phạt' ? [notes] : []
      };

      try {
        const res = await fetch('/api/v1/cc/admin/staff-evaluation', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify(backendPayload)
        });


        if (res.ok) {
          const resData = await res.json();
          showToast(resData.message || `Đã lưu biên bản ${evalType} cho ${staffName}!`, 'success');
          modal?.classList.remove('active');
          updateSheetScrollLock();
          if (notesInput) notesInput.value = '';
          if (amountInput) amountInput.value = '';
          quickPills.forEach(p => p.classList.remove('active'));
          document.querySelectorAll('.incident-action-btn').forEach(b => b.classList.remove('active'));

          // Invalidate cache and update local ledger reactively
          state.serverPayrollSummaryCache = {};
          const curM = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
          if (evalType === 'Thưởng') {
            if (!state.bonusLedger[curM]) state.bonusLedger[curM] = {};
            if (!state.bonusLedger[curM][staffName]) state.bonusLedger[curM][staffName] = [];
            state.bonusLedger[curM][staffName].push({
              id: `EVAL-${Date.now()}`,
              date: date,
              amount: evalAmount,
              type: 'bank',
              reason: notes,
              timestamp: new Date().toISOString()
            });
          } else {
            if (!state.deductionLedger[curM]) state.deductionLedger[curM] = {};
            if (!state.deductionLedger[curM][staffName]) state.deductionLedger[curM][staffName] = [];
            state.deductionLedger[curM][staffName].push({
              id: `EVAL-${Date.now()}`,
              date: date,
              amount: evalAmount,
              reason: notes,
              timestamp: new Date().toISOString()
            });
          }

          if (typeof window !== 'undefined') {
            if (typeof window.updateAllViews === 'function') {
              window.updateAllViews();
            } else if (typeof window.renderTabPayslip === 'function') {
              window.renderTabPayslip();
            }
            if (typeof window.loadData === 'function') {
              window.loadData().catch(() => {});
            }
          }
        } else {
          const err = await res.json().catch(() => ({}));
          showToast(safeErrorDetail(err, 'Không thể gửi biên bản đến máy chủ!'), 'error');
        }
      } catch (e) {
        showToast('Lỗi kết nối máy chủ!', 'error');
      } finally {
        btnCustom.textContent = originalBtnText;
        btnCustom.disabled = false;
      }
    });
  }
}

export function renderStaffPortal() {
  const container = document.getElementById('staffPortalContainer');
  if (!container) return;
  const meta = (state.rawData && state.rawData._meta) || {};
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  const locks = meta.payroll_locks || {};
  const lockInfo = locks[m] || { status: 'OPEN' };
  const isLocked = lockInfo.status === 'LOCKED';

  // Find staff member's name accurately using strict canonical matching
  const empKeys = Object.keys(state.employeesMap);
  let staffName = resolveStaffCanonicalKey(meta, empKeys);

  // Fallback an toàn nếu chưa có trong employeesMap nhưng có trong records
  if (!staffName && state.records.length > 0) {
    const recordNames = Array.from(new Set(state.records.map(r => r.name)));
    staffName = resolveStaffCanonicalKey(meta, recordNames);
  }

  if (!staffName && meta.full_name) {
    staffName = getCanonicalStaffName(meta.full_name);
  }

  let lockBannerHtml = '';
  const isVerificationOpen = meta.payroll_verification_open !== false;
  if (!isVerificationOpen) {
    lockBannerHtml = `
      <div style="background:rgba(245, 158, 11, 0.12); border:1px solid #f59e0b; border-radius:10px; padding:10px 12px; margin-bottom:8px; text-align:center;">
        <div style="color:#b45309; font-weight:700; font-size:13px;">KỲ ĐỐI SOÁT &amp; XÁC NHẬN LƯƠNG ĐANG TẠM KHÓA</div>
        <div style="font-size:12px; color:#92400e; margin-top:2px;">Quản lý đang tạm thời đóng cổng xác nhận công tháng. Vui lòng liên hệ Quản lý nếu cần hỗ trợ.</div>
      </div>
    `;
  } else if (isLocked) {
    lockBannerHtml = `
      <div style="background:rgba(245, 158, 11, 0.12); border:1px solid #f59e0b; border-radius:10px; padding:10px 12px; margin-bottom:8px; text-align:center;">
        <div style="color:#b45309; font-weight:700; font-size:13px;">KỲ LƯƠNG THÁNG ${m} ĐANG ĐỐI SOÁT</div>
        <div style="font-size:12px; color:#92400e; margin-top:2px;">${lockInfo.message || 'Số liệu ca trực đang được tổng hợp, chưa chốt chính thức.'}</div>
      </div>
    `;
  } else {
    lockBannerHtml = `
      <div style="background:var(--accent-emerald-sub); border:1px solid var(--accent-emerald); border-radius:10px; padding:8px 12px; margin-bottom:8px; display:flex; justify-content:space-between; align-items:center;">
        <div style="font-size:12px; font-weight:700; color:var(--accent-emerald);">Kỳ Lương Tháng ${m} (Đã Mở)</div>
        <div style="font-size:12px; color:var(--text-secondary);">Vui lòng kiểm tra & bấm xác nhận</div>
      </div>
    `;
  }

  let receiptHtml = '';
  if (staffName) {
    receiptHtml = generatePayslipHtml(staffName);
  } else {
    receiptHtml = `<div style="text-align:center; padding:30px 10px; color:var(--text-secondary);">Chưa có dữ liệu ca trực của bạn trong tháng ${m}.</div>`;
  }

  const conf = (meta.confirmations && meta.confirmations[m]) || null;
  let confHtml = '';
  if (conf && conf.status === 'CONFIRMED') {
    confHtml = `
      <div style="background:var(--accent-emerald-sub); border:1.5px solid var(--accent-emerald); border-radius:12px; padding:14px; margin-top:10px; text-align:center;">
        <div style="color:var(--accent-emerald); font-weight:800; font-size:14px;">BẠN ĐÃ XÁC NHẬN CÔNG ĐÚNG</div>
        <div style="font-size:12px; color:var(--text-secondary); margin-top:3px;">Thời gian ghi nhận: ${conf.timestamp}</div>
        ${conf.note ? `<div style="font-size:12px; margin-top:4px;">Ghi chú: ${escapeHtml(conf.note)}</div>` : ''}
        <div style="margin-top:10px; display:flex; gap:8px; justify-content:center;">
          <button onclick="openStaffShiftsDetailModal('${staffName}')" class="sheet-btn secondary" style="padding:7px 12px; font-size:12px; font-weight:600;">
            Xem Chi Tiết Chấm Công (1-31)
          </button>
          <button onclick="handleStaffDispute()" class="sheet-btn secondary" style="padding:7px 12px; font-size:12px; color:var(--accent-coral); border-color:var(--accent-coral);">
            Báo Lại Nếu Sai Sót
          </button>
        </div>
      </div>
    `;
  } else if (conf && conf.status === 'DISPUTED') {
    confHtml = `
      <div style="background:var(--accent-coral-sub); border:1.5px solid var(--accent-coral); border-radius:12px; padding:14px; margin-top:10px; text-align:center;">
        <div style="color:var(--accent-coral); font-weight:800; font-size:14px;">ĐÃ GỬI BÁO CÁO SAI LỆCH CÔNG</div>
        <div style="font-size:12px; color:var(--text-secondary); margin-top:3px;">Thời gian gửi: ${conf.timestamp}</div>
        <div style="font-size:12px; font-weight:600; margin-top:6px; background:var(--bg-card); padding:8px 12px; border-radius:8px; border:1px solid var(--border);">"${escapeHtml(conf.note)}"</div>
        <div style="font-size:12px; color:var(--text-muted); margin-top:6px;">Quản lý và kế toán đang rà soát ca trực để cập nhật lại.</div>
        <div style="margin-top:10px; display:flex; gap:8px; justify-content:center;">
          <button onclick="openStaffShiftsDetailModal('${staffName}')" class="sheet-btn secondary" style="padding:7px 12px; font-size:12px; font-weight:600;">
            Xem Chi Tiết Chấm Công (1-31)
          </button>
          <button onclick="handleStaffConfirm()" class="sheet-btn secondary" style="padding:7px 12px; font-size:12px; color:var(--accent-emerald); border-color:var(--accent-emerald);">
            Đổi Sang Xác Nhận Đúng
          </button>
        </div>
      </div>
    `;
  } else {
    confHtml = `
      <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:14px; margin-top:10px;">
        <div style="font-weight:700; font-size:13px; margin-bottom:4px; text-align:center;">ĐỐI SOÁT & XÁC NHẬN CÔNG</div>
        <div style="font-size:12px; color:var(--text-secondary); text-align:center; margin-bottom:12px;">
          Bạn vui lòng kiểm tra kỹ số ca, tổng giờ, phụ cấp lễ 2/9, thưởng và tạm ứng trước khi bấm xác nhận.
        </div>
        <div style="display:flex; flex-direction:column; gap:8px;">
          <button onclick="openStaffShiftsDetailModal('${escapeHtml(staffName)}')" class="sheet-btn secondary" style="padding:10px; font-size:12px; font-weight:700; display:flex; align-items:center; justify-content:center; gap:6px;">
            Xem Chi Tiết Từng Ngày Check-in / Out (1-31)
          </button>
          <button onclick="handleStaffConfirm()" class="sheet-btn" style="background:var(--accent-emerald); color:#fff; font-weight:700; padding:11px; font-size:13px; ${!isVerificationOpen ? 'opacity:0.4; cursor:not-allowed;' : ''}" ${!isVerificationOpen ? 'disabled' : ''}>
            Xác Nhận Công Đúng
          </button>
          <button onclick="handleStaffDispute()" class="sheet-btn secondary" style="color:var(--accent-coral); border-color:var(--accent-coral); padding:9px; font-size:12px; font-weight:600; ${!isVerificationOpen ? 'opacity:0.4; cursor:not-allowed;' : ''}" ${!isVerificationOpen ? 'disabled' : ''}>
            Báo sai lệch giờ làm
          </button>
        </div>
      </div>
    `;
  }

  container.innerHTML = `
    ${lockBannerHtml}
    ${receiptHtml}
    ${confHtml}
    <div style="height: 36px; flex-shrink: 0;" aria-hidden="true"></div>
  `;
  if (staffName) {
    loadStaffSoCaiLuong(staffName, m);
    // Realtime Sync Server Payroll Summary
    fetchServerPayrollSummary(m, staffName).then(serverBreakdown => {
      if (serverBreakdown && container) {
        const freshReceipt = generatePayslipHtml(staffName, serverBreakdown);
        const receiptEl = container.querySelector('.receipt-container');
        if (receiptEl) {
          receiptEl.outerHTML = freshReceipt;
        }
      }
    }).catch(() => {});
  }
}

export async function handleStaffConfirm() {
  const meta = (state.rawData && state.rawData._meta) || {};
  if (meta.payroll_verification_open === false) {
    showToast('Kỳ đối soát & xác nhận lương hiện đang tạm thời đóng theo chỉ thị Quản lý.', 'error');
    return;
  }
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  const ok = await showConfirmDialog({
    title: 'Xác Nhận Kỳ Lương',
    message: `Bạn xác nhận toàn bộ số giờ công, ca trực và số tiền thực nhận Tháng ${m} là CHÍNH XÁC?`,
    confirmText: 'Xác Nhận Đúng',
    cancelText: 'Xem Lại',
    type: 'success',
    icon: 'solar:shield-check-bold'
  });
  if (!ok) return;

  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/staff/confirm-payroll', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ month: m, status: 'CONFIRMED', note: '' })
    });
    if (res.ok) {
      const d = await res.json();
      if (!state.rawData._meta) state.rawData._meta = {};
      if (!state.rawData._meta.confirmations) state.rawData._meta.confirmations = {};
      state.rawData._meta.confirmations[m] = d.confirmation;
      showToast(`Đã ghi nhận xác nhận công đúng cho Tháng ${m}!`, 'success');
      renderStaffPortal();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(safeErrorDetail(err, 'Lỗi xác nhận!'), 'error');
    }
  } catch (e) {
    showToast('Lỗi kết nối máy chủ!', 'error');
  }
}

export function handleStaffDispute() {
  const meta = (state.rawData && state.rawData._meta) || {};
  if (meta.payroll_verification_open === false) {
    showToast('Kỳ đối soát & xác nhận lương hiện đang tạm thời đóng theo chỉ thị Quản lý.', 'error');
    return;
  }
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  const modal = document.getElementById('disputeModal');
  if (!modal) return;

  const titleEl = document.getElementById('disputeModalTitle');
  if (titleEl) {
    titleEl.innerHTML = `<span>Báo Sai Lệch Giờ Làm Tháng ${escapeHtml(m)}</span>`;
  }

  const noteInput = document.getElementById('disputeNoteInput');
  const draftNotice = document.getElementById('disputeDraftNotice');
  const savedDraft = localStorage.getItem('draft_dispute_note') || '';
  if (noteInput) {
    noteInput.value = savedDraft;
    if (draftNotice) {
      draftNotice.style.display = savedDraft.trim() ? 'inline' : 'none';
    }
    // Auto-save draft on typing
    noteInput.oninput = () => {
      localStorage.setItem('draft_dispute_note', noteInput.value);
      if (draftNotice) {
        draftNotice.style.display = noteInput.value.trim() ? 'inline' : 'none';
      }
    };
  }

  const btnCancel = document.getElementById('btnCancelDispute');
  const btnCloseX = document.getElementById('btnDisputeCloseX');
  const closeModal = () => {
    modal.classList.remove('active');
    updateSheetScrollLock();
  };
  if (btnCancel) btnCancel.onclick = closeModal;
  if (btnCloseX) btnCloseX.onclick = closeModal;

  const btnSubmit = document.getElementById('btnSubmitDispute');
  if (btnSubmit) {
    btnSubmit.onclick = async () => {
      const note = noteInput ? noteInput.value.trim() : '';
      if (!note) {
        return showToast('Vui lòng nhập chi tiết nội dung sai lệch công cần kiểm tra!', 'warn');
      }

      btnSubmit.textContent = 'Đang gửi...';
      btnSubmit.disabled = true;

      const token = localStorage.getItem('vnaigc_jwt');
      try {
        const res = await fetch('/api/v1/cc/staff/confirm-payroll', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ month: m, status: 'DISPUTED', note: note })
        });
        if (res.ok) {
          const d = await res.json();
          if (!state.rawData._meta) state.rawData._meta = {};
          if (!state.rawData._meta.confirmations) state.rawData._meta.confirmations = {};
          state.rawData._meta.confirmations[m] = d.confirmation;

          localStorage.removeItem('draft_dispute_note');
          if (noteInput) noteInput.value = '';
          if (draftNotice) draftNotice.style.display = 'none';

          closeModal();
          showToast(`Đã gửi báo sai lệch Tháng ${m} cho Quản lý & Kế toán!`, 'success');
          renderStaffPortal();
        } else {
          const err = await res.json().catch(() => ({}));
          showToast(safeErrorDetail(err, 'Lỗi gửi phản hồi sai lệch!'), 'error');
        }
      } catch (e) {
        showToast('Lỗi kết nối máy chủ!', 'error');
      } finally {
        btnSubmit.textContent = 'Gửi Báo Cáo';
        btnSubmit.disabled = false;
      }
    };
  }

  modal.classList.add('active');
  updateSheetScrollLock();
  if (noteInput) {
    setTimeout(() => noteInput.focus(), 150);
  }
}

export function getStaffShiftsList(staffName, targetMonth) {
  const canonTarget = getCanonicalStaffName(staffName);
  const normTarget = removeAccents(staffName).toUpperCase();

  // Dữ liệu nhân viên thật từ state.records (so khớp chính xác canonical name)
  const matched = state.records.filter(r => {
    const rCanon = getCanonicalStaffName(r.name);
    const rNorm = removeAccents(r.name).toUpperCase();
    const isSameName = (r.name === staffName || rCanon === canonTarget || rNorm === normTarget);
    const isSameMonth = (targetMonth === 'all' || !targetMonth) ? true : (r.month === targetMonth);
    return isSameName && isSameMonth;
  });

  // Sắp xếp ngày tăng dần từ ngày 1 đến ngày 31
  matched.sort((a, b) => {
    const parseD = (s) => {
      if (!s) return 0;
      const p = s.split('/');
      return new Date(parseInt(p[2] || 2026), parseInt(p[1] || 1) - 1, parseInt(p[0] || 1)).getTime();
    };
    return parseD(a.date) - parseD(b.date);
  });

  return matched.map(r => ({
    date: r.date,
    dayOfWeek: getDayOfWeekVN(r.date),
    shift: r.shift || 'Thường',
    in: r.in || '--:--',
    out: r.out || '--:--',
    mins: r.mins || 0,
    effectiveMins: r.effectiveMins || r.mins || 0,
    lateMins: r.lateMins || 0,
    isHoliday: !!r.isHoliday,
    note: r.isHoliday ? 'Lễ Quốc Khánh 2/9 (Hệ số x2: +100%)' : (r.lateMins > 0 ? `Trễ ${r.lateMins} phút` : 'Đúng giờ'),
    cost: r.totalCost || 0,
    shiftKey: r.shiftKey || `${r.date}|${r.name}|${r.shift}|${r.in}`,
    otStatus: r.otStatus || 'STANDARD',
    approval: r.approval || null,
    name: r.name
  }));
}

export function openStaffShiftsDetailModal(staffName) {
  const modal = document.getElementById('staffShiftsSheet');
  if (!modal) return;

  const targetName = staffName || (state.currentViewingStaff && state.currentViewingStaff.name) || (state.employeesMap && Object.keys(state.employeesMap)[0]) || 'NHÂN VIÊN';
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  const monthTitle = state.currentMonth === 'all' ? 'Tất Cả Các Tháng' : `Tháng ${m}/2026`;

  document.getElementById('shiftsModalTitle').textContent = `Chi Tiết Chấm Công • ${monthTitle}`;
  document.getElementById('shiftsModalSubtitle').textContent = `Nhân sự: ${targetName} • Xem lịch sử Check-in / Out từng ngày`;

  const shifts = getStaffShiftsList(targetName, state.currentMonth);

  let totalMins = 0;
  let lateCount = 0;
  let holidayCount = 0;

  shifts.forEach(s => {
    totalMins += (s.effectiveMins || s.mins || 0);
    if (s.lateMins > 10) lateCount++;
    if (s.isHoliday) holidayCount++;
  });

  const totalHours = (totalMins / 60).toFixed(1);

  // Quick summary strip
  const summaryBox = document.getElementById('shiftsModalSummary');
  if (summaryBox) {
    summaryBox.innerHTML = `
      <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:8px 6px; text-align:center;">
        <div style="font-size:12px; color:var(--text-muted); font-weight:700;">TỔNG CA</div>
        <div style="font-size:16px; font-weight:800; color:var(--text-primary); margin-top:2px;">${shifts.length} ca</div>
      </div>
      <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:8px 6px; text-align:center;">
        <div style="font-size:12px; color:var(--text-muted); font-weight:700;">TỔNG GIỜ</div>
        <div style="font-size:16px; font-weight:800; color:var(--accent-emerald); margin-top:2px;">${totalHours}h</div>
      </div>
      <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:8px 6px; text-align:center;">
        <div style="font-size:12px; color:var(--text-muted); font-weight:700;">VI PHẠM TRỄ</div>
        <div style="font-size:16px; font-weight:800; color:${lateCount > 0 ? 'var(--accent-coral)' : 'var(--accent-emerald)'}; margin-top:2px;">${lateCount} lần</div>
      </div>
    `;
  }

  // Shifts list container
  const listBox = document.getElementById('shiftsModalList');
  if (listBox) {
    if (shifts.length === 0) {
      listBox.innerHTML = `<div style="text-align:center; padding:30px 10px; color:var(--text-secondary); font-size:12px;">Chưa ghi nhận ca làm việc nào trong kỳ này.</div>`;
    } else {
      listBox.innerHTML = shifts.map(s => {
        const isLate = s.lateMins > 0;
        const lateBadge = isLate 
          ? `<span style="background:rgba(239, 68, 68, 0.12); color:#dc2626; font-size:12px; font-weight:700; padding:2px 6px; border-radius:4px;">Trễ ${s.lateMins}p</span>`
          : `<span style="background:var(--accent-emerald-sub); color:var(--accent-emerald); font-size:12px; font-weight:700; padding:2px 6px; border-radius:4px;">Đúng giờ</span>`;

        const stdMins = s.standardShiftMins || s.standardMins || 300;
        const stdHours = (stdMins / 60).toFixed(1);
        const otBuffer = POLICY.OT_BUFFER_MINS || 30;

        let shiftBadge = '';
        if (s.mins <= stdMins) {
          shiftBadge = `<span style="background:rgba(16, 185, 129, 0.12); color:#059669; font-size:12px; font-weight:700; padding:2px 6px; border-radius:4px;">Chuẩn ${stdHours}h</span>`;
        } else if (s.mins <= (stdMins + otBuffer)) {
          shiftBadge = `<span style="background:rgba(245, 158, 11, 0.12); color:#d97706; font-size:12px; font-weight:700; padding:2px 6px; border-radius:4px;">OT hiệu suất (+${s.mins - stdMins}p)</span>`;
        } else {
          // Lố quá ngưỡng buffer
          if (s.otStatus === 'APPROVED') {
            shiftBadge = `<span style="background:rgba(16, 185, 129, 0.15); color:#047857; font-size:12px; font-weight:800; padding:2px 8px; border-radius:4px; border:1px solid #10b981;">✓ Đã duyệt (+${s.mins - stdMins}p)</span>`;
          } else if (s.otStatus === 'CUT') {
            shiftBadge = `<span style="background:rgba(239, 68, 68, 0.12); color:#dc2626; font-size:12px; font-weight:800; padding:2px 8px; border-radius:4px; border:1px solid #ef4444;">✕ Cắt về ${s.effectiveMins}p</span>`;
          } else {
            shiftBadge = `<span style="background:rgba(245, 158, 11, 0.15); color:#d97706; font-size:12px; font-weight:800; padding:2px 8px; border-radius:4px; border:1px solid #f59e0b;">⏳ +${s.mins - stdMins}p OT • Chờ duyệt</span>`;
          }
        }

        const holidayBadge = s.isHoliday 
          ? `<span style="background:#fee2e2; color:#b91c1c; font-size:12px; font-weight:800; padding:2px 6px; border-radius:4px; border:1px solid #f87171;">Lễ 2/9 (x2 Lương)</span>`
          : '';

        const hours = ((s.effectiveMins || s.mins || 0) / 60).toFixed(1);
        const costStr = fmtMoney.format(s.cost || 0).replace('₫', 'đ');

        const isExcess = (s.mins > (stdMins + otBuffer));
        const canManageShifts = (['ADMIN', 'MANAGER'].includes(localStorage.getItem('vnaigc_role')) || ['ADMIN', 'MANAGER'].includes(state.rawData && state.rawData._meta && state.rawData._meta.role));
        let adminActionHtml = '';
        if (canManageShifts && isExcess) {
          adminActionHtml = `
            <div style="display:flex; justify-content:flex-end; align-items:center; gap:6px; margin-top:6px; padding-top:6px; border-top:1px dashed var(--border);">
              <span style="font-size:12px; color:var(--text-muted); margin-right:auto;">Quản lý:</span>
              <button onclick="(window.confirmShiftOT || function(){})('${s.shiftKey}', 'APPROVE', ${s.mins})" style="background:rgba(16, 185, 129, 0.12); color:#059669; border:1px solid #10b981; border-radius:6px; padding:3px 8px; font-size:12px; font-weight:700; cursor:pointer;">Duyệt đủ ${s.mins}p</button>
              <button onclick="(window.confirmShiftOT || function(){})('${s.shiftKey}', 'CUT', ${stdMins})" style="background:rgba(239, 68, 68, 0.12); color:#dc2626; border:1px solid #ef4444; border-radius:6px; padding:3px 8px; font-size:12px; font-weight:700; cursor:pointer;">Cắt ${stdMins}p</button>
              ${s.approval ? `<button onclick="(window.confirmShiftOT || function(){})('${s.shiftKey}', 'RESET', ${stdMins})" title="Hoàn tác ca này về chờ duyệt" style="background:rgba(239, 68, 68, 0.08); border:1px solid rgba(239, 68, 68, 0.25); color:#dc2626; border-radius:4px; padding:2px 6px; font-size:11px; font-weight:700; cursor:pointer;">↩ Hoàn tác</button>` : ''}
            </div>
          `;
        }

        return `
          <div style="background:var(--bg-card); border:1px solid ${s.isHoliday ? '#fca5a5' : 'var(--border)'}; border-radius:10px; padding:10px 12px; display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="font-weight:800; font-size:13px; color:var(--text-primary);">${escapeHtml(s.date)}</span>
                <span style="font-size:12px; color:var(--text-muted);">(${escapeHtml(s.dayOfWeek)})</span>
                <span style="background:var(--bg-card-sub); border:1px solid var(--border); font-size:12px; font-weight:600; padding:1px 5px; border-radius:4px;">Ca ${escapeHtml(s.shift)}</span>
              </div>
              <div style="display:flex; gap:4px; align-items:center;">
                ${holidayBadge}
                ${shiftBadge}
                ${lateBadge}
              </div>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; background:var(--bg); padding:6px 10px; border-radius:6px; font-size:12px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <span>Vào: <strong style="color:var(--text-primary); font-size:12px;">${escapeHtml(s.in || '--:--')}</strong></span>
                <span style="color:var(--text-muted);">➔</span>
                <span>Ra: <strong style="color:var(--text-primary); font-size:12px;">${escapeHtml(s.out || '--:--')}</strong></span>
              </div>
              <div>
                <span style="font-weight:700; color:var(--text-primary);">${s.effectiveMins || s.mins} phút</span>
                <span style="color:var(--text-muted); font-size:12px;">(${hours}h)</span>
              </div>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; margin-top:2px;">
              <div style="color:var(--text-secondary); font-size:12px; max-width:65%; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                ${s.note ? `<em>${escapeHtml(s.note)}</em>` : ''}
              </div>
              <div style="text-align:right;">
                <span style="font-size:12px; color:var(--text-muted);">Lương ca: </span>
                <strong style="color:${s.isHoliday ? '#b91c1c' : 'var(--text-primary)'}; font-size:12px;">${costStr}</strong>
              </div>
            </div>

            ${adminActionHtml}
          </div>
        `;
      }).join('');
    }
  }

  modal.classList.add('active');
}

export function closeStaffShiftsModal() {
  const modal = document.getElementById('staffShiftsSheet');
  if (modal) modal.classList.remove('active');
}
export function setupStaffShiftsModalEvents() {
  const btnClose = document.getElementById("btnCloseStaffShifts");
  if (btnClose) btnClose.addEventListener("click", closeStaffShiftsModal);

  const btnCloseBottom = document.getElementById("btnCloseStaffShiftsBottom");
  if (btnCloseBottom) btnCloseBottom.addEventListener("click", closeStaffShiftsModal);

  const sheet = document.getElementById("staffShiftsSheet");
  if (sheet) {
    sheet.addEventListener("click", (e) => {
      if (e.target === sheet) closeStaffShiftsModal();
    });
  }
}


// ==========================================================================
// DISBURSEMENT & SALARY ADVANCE (TẠM ỨNG) HELPERS
// ==========================================================================

export async function toggleStaffDisbursement(staffName, targetStatus, amount = 0) {
  const m = String(state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth);
  const targetStatusUpper = String(targetStatus).toUpperCase();
  const canon = getCanonicalStaffName(staffName);
  const norm = removeAccents(staffName).toUpperCase().trim();

  // 1. Optimistic client update immediately
  if (typeof navigator !== 'undefined') navigator.vibrate?.(12);
  if (!state.disbursements) state.disbursements = {};
  if (!state.disbursements[m]) state.disbursements[m] = {};

  const entry = {
    status: targetStatusUpper,
    amount: Number(amount) || 0,
    paid_by: localStorage.getItem('vnaigc_name') || 'Chủ Quán (Admin)',
    updated_at: new Date().toISOString().replace('T', ' ').slice(0, 19)
  };

  // Set all matching keys so lookup never fails
  state.disbursements[m][staffName] = entry;
  state.disbursements[m][canon] = entry;
  state.disbursements[m][norm] = entry;

  // Persist to local storage
  try {
    const local = JSON.parse(localStorage.getItem('vnaigc_local_disbursements') || '{}');
    if (!local[m]) local[m] = {};
    local[m][staffName] = entry;
    local[m][canon] = entry;
    local[m][norm] = entry;
    localStorage.setItem('vnaigc_local_disbursements', JSON.stringify(local));
  } catch (_) {}

  // Instantly re-render tab payslip and open modal
  renderTabPayslip();
  const pSheet = document.getElementById('payslipSheet');
  if (pSheet && pSheet.classList.contains('active')) {
    openPayslipModal(staffName);
  }

  const successMsg = targetStatusUpper === 'PAID'
    ? `Đã xác nhận ĐÃ CHUYỂN KHOẢN cho ${staffName}`
    : `Đã đổi về CHƯA CK cho ${staffName}`;
  showToast(successMsg, 'success');

  // 2. Async sync with backend
  const token = localStorage.getItem('vnaigc_jwt') || localStorage.getItem('vnaigc_token') || localStorage.getItem('cc_token');
  if (token) {
    try {
      const res = await fetch('/api/v1/cc/payroll/disbursements/toggle', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          month: m,
          staff_name: staffName,
          status: targetStatusUpper,
          amount: Number(amount) || 0
        })
      });
      if (res.ok) {
        const d = await res.json();
        if (d.entry) {
          state.disbursements[m][staffName] = d.entry;
          state.disbursements[m][canon] = d.entry;
          state.disbursements[m][norm] = d.entry;
        }
      }
    } catch (e) {
      console.warn("Backend sync failed, state preserved locally:", e);
    }
  }
}
if (typeof window !== 'undefined') {
  window.toggleStaffDisbursement = toggleStaffDisbursement;
  window.checkStaffIsPaid = checkStaffIsPaid;
  window.getStaffDisbursementRecord = getStaffDisbursementRecord;
}

export function openLedgerEntryModal(staffName = '', defaultType = 'advance') {
  state.editingLedgerId = null;
  state.editingLedgerStaff = null;
  state.editingLedgerMonth = null;
  state.editingLedgerAmount = null;

  const modal = document.getElementById('ledgerEntrySheet');
  if (!modal) return;

  const staffSelect = document.getElementById('ledgerStaffSelect');
  const monthSelect = document.getElementById('ledgerMonthSelect');
  const typeSelect = document.getElementById('ledgerTypeSelect');
  const amountInput = document.getElementById('ledgerAmountInput');
  const reasonInput = document.getElementById('ledgerReasonInput');
  const sheetTitle = document.getElementById('ledgerSheetTitle');
  const sheetSub = document.getElementById('ledgerSheetSub');
  const btnSubmit = document.getElementById('btnSubmitLedgerEntry');

  if (sheetTitle) sheetTitle.textContent = 'Ghi Nhận Tạm Ứng / Sổ Phụ';
  if (sheetSub) sheetSub.textContent = 'Ghi nhận tạm ứng lương trừ vào kỳ quyết toán';
  if (btnSubmit) btnSubmit.textContent = 'Lưu Bản Ghi';

  // Populate staff select
  if (staffSelect) {
    const names = Object.keys(state.employeesMap || {});
    if (names.length === 0) {
      staffSelect.innerHTML = '<option value="">(Chưa có danh sách nhân sự)</option>';
    } else {
      staffSelect.innerHTML = names.map(n => `<option value="${escapeHtml(n)}" ${n === staffName ? 'selected' : ''}>${escapeHtml(n)} (${escapeHtml(state.employeesMap[n]?.role || '')})</option>`).join('');
      if (staffName) staffSelect.value = staffName;
    }
  }

  // Populate month
  if (monthSelect) {
    const curM = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
    monthSelect.value = curM;
  }

  if (typeSelect) {
    typeSelect.value = defaultType === 'advance' ? 'advance' : (defaultType === 'bonus' ? 'bonus' : 'deduction');
  }
  if (amountInput) amountInput.value = '';
  if (reasonInput) reasonInput.value = '';

  modal.classList.add('active');
  if (amountInput) setTimeout(() => amountInput.focus(), 200);
}
if (typeof window !== 'undefined') window.openLedgerEntryModal = openLedgerEntryModal;

export function closeLedgerEntryModal() {
  state.editingLedgerId = null;
  state.editingLedgerStaff = null;
  state.editingLedgerMonth = null;
  state.editingLedgerAmount = null;

  const sheetTitle = document.getElementById('ledgerSheetTitle');
  const sheetSub = document.getElementById('ledgerSheetSub');
  const btnSubmit = document.getElementById('btnSubmitLedgerEntry');
  if (sheetTitle) sheetTitle.textContent = 'Ghi Nhận Tạm Ứng / Sổ Phụ';
  if (sheetSub) sheetSub.textContent = 'Ghi nhận tạm ứng lương trừ vào kỳ quyết toán';
  if (btnSubmit) btnSubmit.textContent = 'Lưu Bản Ghi';

  const modal = document.getElementById('ledgerEntrySheet');
  if (modal) modal.classList.remove('active');
}
if (typeof window !== 'undefined') window.closeLedgerEntryModal = closeLedgerEntryModal;

export function editStaffLedger(id, staffName, amount, type, reason, month) {
  state.editingLedgerId = id;
  state.editingLedgerStaff = staffName;
  state.editingLedgerMonth = month || currentRealtimeMonth;
  state.editingLedgerAmount = Number(amount) || 0;

  const modal = document.getElementById('ledgerEntrySheet');
  if (!modal) return;

  const staffSelect = document.getElementById('ledgerStaffSelect');
  const monthSelect = document.getElementById('ledgerMonthSelect');
  const typeSelect = document.getElementById('ledgerTypeSelect');
  const methodSelect = document.getElementById('ledgerMethodSelect');
  const amountInput = document.getElementById('ledgerAmountInput');
  const reasonInput = document.getElementById('ledgerReasonInput');
  const sheetTitle = document.getElementById('ledgerSheetTitle');
  const sheetSub = document.getElementById('ledgerSheetSub');
  const btnSubmit = document.getElementById('btnSubmitLedgerEntry');

  if (staffSelect) {
    const names = Object.keys(state.employeesMap || {});
    if (names.length > 0) {
      staffSelect.innerHTML = names.map(n => `<option value="${escapeHtml(n)}" ${n === staffName ? 'selected' : ''}>${escapeHtml(n)} (${escapeHtml(state.employeesMap[n]?.role || '')})</option>`).join('');
    }
    staffSelect.value = staffName;
  }

  if (monthSelect) monthSelect.value = month || state.currentMonth || currentRealtimeMonth;
  if (typeSelect) typeSelect.value = 'advance';
  if (methodSelect) methodSelect.value = (type === 'bank' || type === 'ck') ? 'bank' : 'cash';
  if (amountInput) amountInput.value = fmtNum.format(Number(amount) || 0);
  if (reasonInput) reasonInput.value = reason || '';

  if (sheetTitle) sheetTitle.textContent = 'Chỉnh Sửa Tạm Ứng / Sổ Phụ';
  if (sheetSub) sheetSub.textContent = `Chỉnh sửa khoản ghi nhận của ${staffName}`;
  if (btnSubmit) btnSubmit.textContent = 'Cập Nhật Thay Đổi';

  modal.classList.add('active');
  if (amountInput) setTimeout(() => amountInput.focus(), 200);
}
if (typeof window !== 'undefined') window.editStaffLedger = editStaffLedger;

export async function deleteStaffLedger(ledgerId, staffName, amount, month) {
  const token = localStorage.getItem('vnaigc_jwt') || localStorage.getItem('vnaigc_token') || localStorage.getItem('cc_token');
  if (!token) return showToast('Vui lòng đăng nhập quyền Quản lý / Admin', 'warn');

  const amtFormatted = fmtMoney.format(Number(amount) || 0).replace('₫', 'đ');
  const confirmed = await showConfirmDialog({
    title: 'Xóa Bản Ghi Tạm Ứng',
    message: `Bạn có chắc muốn xóa bản ghi tạm ứng ${amtFormatted} của nhân sự ${staffName}? Số tiền tạm ứng này sẽ được cộng trả lại vào lương thực nhận.`,
    confirmText: 'Xác Nhận Xóa',
    cancelText: 'Hủy',
    type: 'danger',
    icon: 'solar:trash-bin-trash-bold'
  });
  if (!confirmed) return;

  try {
    const res = await deleteStaffLedgerApi(ledgerId, staffName, month || currentRealtimeMonth, Number(amount) || 0);
    if (res && res.error) throw new Error(res.error);

    // Clear stale server caches
    state.serverPayrollSummaryCache = {};

    // Remove from in-memory state.advanceLedger immediately for instant response
    const curM = String(month || currentRealtimeMonth);
    if (state.advanceLedger[curM] && state.advanceLedger[curM][staffName]) {
      state.advanceLedger[curM][staffName] = state.advanceLedger[curM][staffName].filter(
        x => x.id !== ledgerId && !(Number(x.amount) === Number(amount))
      );
    }

    // Reload full data
    if (typeof window !== 'undefined' && typeof window.loadData === 'function') {
      await window.loadData();
    } else {
      renderTabPayslip();
    }

    // Refresh open payslip modal if active
    const pSheet = document.getElementById('payslipSheet');
    if (pSheet && pSheet.classList.contains('active')) {
      openPayslipModal(staffName);
    }

    showToast(`Đã xóa khoản tạm ứng ${amtFormatted} của ${staffName}`, 'success');
  } catch (err) {
    showToast(safeErrorDetail(err), 'error');
  }
}
if (typeof window !== 'undefined') window.deleteStaffLedger = deleteStaffLedger;

export function setupLedgerEntryModal() {
  const modal = document.getElementById('ledgerEntrySheet');
  const btnClose = document.getElementById('btnCloseLedgerSheet');
  const btnCloseX = document.getElementById('btnCloseLedgerX');
  const btnSubmit = document.getElementById('btnSubmitLedgerEntry');
  const btnToolbar = document.getElementById('btnOpenToolbarAdvance');

  if (btnToolbar) {
    btnToolbar.addEventListener('click', () => openLedgerEntryModal('', 'advance'));
  }
  if (btnClose) btnClose.addEventListener('click', closeLedgerEntryModal);
  if (btnCloseX) btnCloseX.addEventListener('click', closeLedgerEntryModal);

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeLedgerEntryModal();
    });
  }

  // Live auto-formatting with thousand dots for amount input
  const amountInput = document.getElementById('ledgerAmountInput');
  if (amountInput) {
    amountInput.addEventListener('input', (e) => {
      const cursor = e.target.selectionStart;
      const prevVal = e.target.value;
      const rawDigits = prevVal.replace(/\D/g, '');
      if (!rawDigits) {
        e.target.value = '';
        return;
      }
      const formatted = fmtNum.format(parseInt(rawDigits, 10));
      e.target.value = formatted;
      const diff = formatted.length - prevVal.length;
      if (cursor !== null) {
        e.target.setSelectionRange(cursor + diff, cursor + diff);
      }
    });
  }

  // Quick amount chips
  document.querySelectorAll('.ledger-quick-amount-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      const amt = pill.getAttribute('data-amount');
      const input = document.getElementById('ledgerAmountInput');
      if (input && amt) {
        input.value = fmtNum.format(parseInt(amt, 10));
      }
    });
  });

  if (btnSubmit) {
    btnSubmit.addEventListener('click', async () => {
      const staffSelect = document.getElementById('ledgerStaffSelect');
      const monthSelect = document.getElementById('ledgerMonthSelect');
      const typeSelect = document.getElementById('ledgerTypeSelect');
      const methodSelect = document.getElementById('ledgerMethodSelect');
      const amountInput = document.getElementById('ledgerAmountInput');
      const reasonInput = document.getElementById('ledgerReasonInput');

      const staffName = staffSelect?.value;
      if (!staffName) return showToast('Vui lòng chọn nhân sự!', 'warn');

      const rawDigits = (amountInput?.value || '').replace(/\D/g, '');
      const amount = parseInt(rawDigits, 10) || 0;
      if (amount <= 0) return showToast('Vui lòng nhập số tiền hợp lệ (> 0đ)!', 'warn');

      const token = localStorage.getItem('vnaigc_jwt') || localStorage.getItem('vnaigc_token') || localStorage.getItem('cc_token');
      if (!token) return showToast('Vui lòng đăng nhập quyền Quản lý / Admin', 'warn');

      const month = monthSelect?.value || currentRealtimeMonth;
      const typeVal = typeSelect?.value || 'advance';
      const methodVal = methodSelect?.value || 'cash';
      const reason = (reasonInput?.value || '').trim() || (typeVal === 'advance' ? 'Tạm ứng lương' : 'Ghi sổ phụ');

      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Đang lưu...';

      try {
        const isEditing = !!state.editingLedgerId;
        if (isEditing) {
          try {
            await deleteStaffLedgerApi(
              state.editingLedgerId,
              state.editingLedgerStaff || staffName,
              state.editingLedgerMonth || month,
              state.editingLedgerAmount || amount
            );
          } catch (delErr) {
            console.warn('Could not delete prior ledger entry during edit:', delErr);
          }
        }

        const res = await fetch('/api/v1/cc/payroll/ledger', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            month: month,
            staff_name: staffName,
            type: typeVal,
            amount: amount,
            payment_method: methodVal,
            reason: reason
          })
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || 'Không thể lưu sổ phụ');

        // Clear stale server breakdown cache!
        state.serverPayrollSummaryCache = {};

        closeLedgerEntryModal();

        // Reload data from server so SQLite ledgers are cleanly merged into state without duplicate
        if (typeof window !== 'undefined' && typeof window.loadData === 'function') {
          await window.loadData();
        } else {
          renderTabPayslip();
        }

        // If modal payslip is open, refresh it with clean updated data
        const pSheet = document.getElementById('payslipSheet');
        if (pSheet && pSheet.classList.contains('active')) {
          openPayslipModal(staffName);
        }

        const successMsg = isEditing
          ? `Đã cập nhật tạm ứng ${fmtMoney.format(amount).replace('₫','đ')} cho ${staffName}!`
          : (d.message || `Đã ghi nhận tạm ứng ${fmtMoney.format(amount).replace('₫','đ')} cho ${staffName}!`);
        showToast(successMsg, 'success');
      } catch (err) {
        showToast(safeErrorDetail(err), 'error');
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = 'Lưu Bản Ghi';
      }
    });
  }
}

export async function sendPayslipZaloCard(staffName, month) {
  const token = localStorage.getItem('vnaigc_jwt');
  const targetMonth = month || state.currentSelectedMonth || '9';
  const ok = await showConfirmDialog({
    title: 'Gửi Thẻ Lương Zalo',
    message: `Xác nhận tạo ảnh phiếu lương Dark Luxury và gửi trực tiếp qua Zalo cho nhân sự "${staffName}" (Tháng ${targetMonth})?`,
    confirmText: 'Gửi Thẻ Zalo',
    cancelText: 'Hủy',
    type: 'zalo',
    icon: 'solar:chat-round-dots-bold'
  });
  if (!ok) return;
  showToast(`Đang sinh ảnh thẻ lương & kết nối Zalo Gateway cho ${staffName}...`, 'info');
  try {
    const res = await fetch('/api/v1/cc/notifications/send-payslip-zalo-card', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        staff_name: staffName,
        month: targetMonth.toString()
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || data.error || 'Gửi Zalo thất bại');
    }
    showToast(data.message || `Đã gửi ảnh phiếu lương qua Zalo cho ${staffName}!`, 'success');
  } catch (err) {
    showToast(safeErrorDetail(err, 'Không thể gửi ảnh phiếu lương qua Zalo'), 'error');
  }
}

export function previewPayslipZaloCard(staffName, month) {
  const token = localStorage.getItem('vnaigc_jwt');
  const targetMonth = month || state.currentSelectedMonth || '9';
  const url = `/api/v1/cc/notifications/preview-payslip-card?staff_name=${encodeURIComponent(staffName)}&month=${encodeURIComponent(targetMonth)}&token=${encodeURIComponent(token || '')}`;
  window.open(url, '_blank');
}

export async function sendBulkPayslipZaloCards(month) {
  const token = localStorage.getItem('vnaigc_jwt');
  const targetMonth = month || state.currentSelectedMonth || '9';
  const ok = await showConfirmDialog({
    title: 'Gửi Phiếu Lương Hàng Loạt',
    message: `Xác nhận tạo ảnh và gửi phiếu lương qua Zalo hàng loạt cho toàn bộ nhân sự có số điện thoại trong Tháng ${targetMonth}?`,
    confirmText: 'Gửi Tất Cả Zalo',
    cancelText: 'Xem Lại',
    type: 'zalo',
    icon: 'solar:chat-round-dots-bold'
  });
  if (!ok) return;
  showToast(`Đang xử lý sinh ảnh và gửi hàng loạt qua Zalo Gateway...`, 'info');
  try {
    const res = await fetch('/api/v1/cc/notifications/send-bulk-payslip-zalo-cards', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        month: targetMonth.toString()
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || data.error || 'Gửi hàng loạt thất bại');
    }
    showToast(`Đã gửi thành công ${data.total_sent} ảnh phiếu lương qua Zalo! (Bỏ qua: ${data.total_skipped})`, 'success');
  } catch (err) {
    showToast(safeErrorDetail(err, 'Không thể gửi ảnh hàng loạt'), 'error');
  }
}

if (typeof window !== 'undefined') {
  window.sendPayslipZaloCard = sendPayslipZaloCard;
  window.previewPayslipZaloCard = previewPayslipZaloCard;
  window.sendBulkPayslipZaloCards = sendBulkPayslipZaloCards;
  window.loadStaffSoCaiLuong = loadStaffSoCaiLuong;
}

