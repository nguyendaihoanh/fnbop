// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// OPS MODULE: KPI DASHBOARD, BENTO CARDS, OT APPROVAL & ANOMALY ALERTS
// ==========================================================================

import { fmtMoney, fmtNum, escapeHtml, fmtBentoMoney } from "../utils/formatters.js";
import { showToast, safeErrorDetail } from "../utils/toast.js";
import { triggerHaptic } from "../utils/haptics.js";
import {
  state,
  POLICY,
  getStaffRole,
  getStaffBonusSummary,
  getStaffAdvanceSummary,
  getStaffDeductionSummary,
  processData,
  currentRealtimeMonth
} from "../store/state.js";
import { confirmShiftOTApi } from "../api/payrollApi.js";

export function renderTabOps() {
  const filtered = state.currentMonth === 'all' ? state.records : state.records.filter(r => r.month === state.currentMonth);
  let totalPay = 0, otCost = 0, totalShifts = 0, totalLate = 0;
  let deptCost = { 'Pha chế': 0, 'Phục vụ': 0, 'Other': 0 };
  state.allAlerts = [];

  let staffAggMap = {};

  filtered.forEach(r => {
    totalPay += r.totalCost;
    otCost += r.overtimeCost;
    totalShifts++;
    if (r.lateMins > 10) totalLate++;

    // Department grouping
    const role = r.role || getStaffRole(r.name);
    if (role === 'Pha chế') deptCost['Pha chế'] += r.totalCost;
    else if (role === 'Phục vụ') deptCost['Phục vụ'] += r.totalCost;
    else deptCost['Other'] += r.totalCost;

    // Staff aggregate
    if (!staffAggMap[r.name]) {
      const emp = state.employeesMap[r.name] || { wage: 17000, role: getStaffRole(r.name) };
      staffAggMap[r.name] = {
        name: r.name,
        role: emp.role,
        shifts: 0,
        mins: 0,
        otMins: 0,
        otCost: 0,
        lateCount: 0,
        lateMins: 0,
        bonus: 0,
        advance: 0
      };
    }
    staffAggMap[r.name].shifts++;
    staffAggMap[r.name].mins += r.mins;
    staffAggMap[r.name].otMins += r.overtimeMins;
    staffAggMap[r.name].otCost += r.overtimeCost;
    staffAggMap[r.name].lateMins += r.lateMins;
    if (r.lateMins > 10) staffAggMap[r.name].lateCount++;

    // Aggregated counters for OT and Late
    if (r.overtimeMins > POLICY.OT_BUFFER_MINS) {
      if (!staffAggMap[r.name].otBufferCount) staffAggMap[r.name].otBufferCount = 0;
      staffAggMap[r.name].otBufferCount++;
    }
    if (r.lateMins > 30) {
      if (!staffAggMap[r.name].lateOver30Count) staffAggMap[r.name].lateOver30Count = 0;
      staffAggMap[r.name].lateOver30Count++;
    }
  });

  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  Object.keys(staffAggMap).forEach(n => {
    staffAggMap[n].bonus = getStaffBonusSummary(m, n).total;
    staffAggMap[n].advance = getStaffAdvanceSummary(m, n);
    staffAggMap[n].deduction = getStaffDeductionSummary(m, n).total;
  });

  // 1. KPI Bento
  const elTotalPay = document.getElementById('valTotalPay');
  if (elTotalPay) {
    const bentoRes = fmtBentoMoney(totalPay);
    elTotalPay.innerHTML = bentoRes.formattedHtml;
    elTotalPay.setAttribute('title', `Tổng quỹ: ${bentoRes.fullText}`);
    elTotalPay.dataset.fullAmount = bentoRes.fullText;
    elTotalPay.dataset.isCompact = bentoRes.isCompact ? '1' : '0';
    elTotalPay.dataset.showingFull = '0';
  }
  const elMomPayTrend = document.getElementById('momPayTrend');
  if (elMomPayTrend) elMomPayTrend.textContent = `${totalShifts} ca • Công gộp`;

  // Dynamic 3 submetrics for #bentoCardTotalPay
  const basePay = Math.max(0, totalPay - otCost);
  const totalAdvance = Object.values(staffAggMap).reduce((sum, s) => sum + (s.advance || 0), 0);
  const fmtShort = (v) => {
    if (v >= 1000000) return (v / 1000000).toFixed(2) + ' M';
    if (v >= 1000) return Math.round(v / 1000) + ' K';
    return (v || 0) + ' đ';
  };
  const elBase = document.getElementById('subMetricBasePay');
  if (elBase) elBase.textContent = fmtShort(basePay);
  const elOTSub = document.getElementById('subMetricOTPay');
  if (elOTSub) elOTSub.textContent = fmtShort(otCost);
  const elAdvSub = document.getElementById('subMetricAdvancePay');
  if (elAdvSub) elAdvSub.textContent = fmtShort(totalAdvance);
  const elOTCost = document.getElementById('valOTCost');
  if (elOTCost) {
    const bentoRes = fmtBentoMoney(otCost);
    elOTCost.innerHTML = bentoRes.formattedHtml;
    elOTCost.setAttribute('title', `Tăng ca: ${bentoRes.fullText}`);
    elOTCost.dataset.fullAmount = bentoRes.fullText;
    elOTCost.dataset.isCompact = bentoRes.isCompact ? '1' : '0';
    elOTCost.dataset.showingFull = '0';
  }
  const elTotalShifts = document.getElementById('valTotalShifts');
  if (elTotalShifts) elTotalShifts.innerHTML = `${totalShifts} <small class="bento-unit">ca</small>`;
  let attRate = totalShifts > 0 ? Math.max(0, Math.round((1 - (totalLate / totalShifts)) * 100)) : 100;
  const elAttScore = document.getElementById('valAttendanceScore');
  if (elAttScore) elAttScore.innerHTML = `${attRate}<small class="bento-unit">%</small>`;
  const elLateSummary = document.getElementById('valLateSummary');
  if (elLateSummary) elLateSummary.textContent = `${totalLate} ca trễ (>10p)`;
  const elMomOTSub = document.getElementById('momOTSub');
  if (elMomOTSub) elMomOTSub.textContent = totalPay > 0 ? `Chiếm ${((otCost / totalPay) * 100).toFixed(1)}% quỹ` : '--';

  // Dynamic submetrics for #bentoCardOT (Tăng ca)
  const otShiftsCount = filtered.filter(r => (r.overtimeMins || 0) > 0).length;
  const totalOTMins = filtered.reduce((sum, r) => sum + (r.overtimeMins || 0), 0);
  const elSubMetricOTShifts = document.getElementById('subMetricOTShifts');
  if (elSubMetricOTShifts) elSubMetricOTShifts.textContent = `${otShiftsCount} ca`;
  const elSubMetricOTHours = document.getElementById('subMetricOTHours');
  if (elSubMetricOTHours) elSubMetricOTHours.textContent = `${(totalOTMins / 60).toFixed(1)}h`;
  const elSubMetricOTPending = document.getElementById('subMetricOTPending');
  if (elSubMetricOTPending) elSubMetricOTPending.textContent = '0 ca';

  // Dynamic submetrics for #bentoCardShifts (Tổng ca)
  const morningShifts = filtered.filter(r => (r.shift || '').toLowerCase().includes('sáng')).length;
  const eveningShifts = filtered.filter(r => (r.shift || '').toLowerCase().includes('tối')).length;
  const elSubMetricMorning = document.getElementById('subMetricMorningShifts');
  if (elSubMetricMorning) elSubMetricMorning.textContent = `${morningShifts} ca`;
  const elSubMetricEvening = document.getElementById('subMetricEveningShifts');
  if (elSubMetricEvening) elSubMetricEvening.textContent = `${eveningShifts} ca`;
  const elSubMetricFullStaff = document.getElementById('subMetricFullStaffShifts');
  if (elSubMetricFullStaff) elSubMetricFullStaff.textContent = `${totalShifts} ca`;

  // Dynamic submetrics for #bentoCardAttendance (Chuyên cần)
  const onTimeShifts = Math.max(0, totalShifts - totalLate);
  const elSubMetricOnTime = document.getElementById('subMetricOnTimeShifts');
  if (elSubMetricOnTime) elSubMetricOnTime.textContent = `${onTimeShifts} ca`;
  const elSubMetricLate = document.getElementById('subMetricLateShifts');
  if (elSubMetricLate) elSubMetricLate.textContent = `${totalLate} ca`;
  const elSubMetricMissing = document.getElementById('subMetricMissingCheckout');
  if (elSubMetricMissing) elSubMetricMissing.textContent = '0 ca';

  // 2. Department Progress Bar
  const totalD = totalPay || 1;
  const pctPC = Math.round((deptCost['Pha chế'] / totalD) * 100);
  const pctPV = Math.round((deptCost['Phục vụ'] / totalD) * 100);
  const pctOT = Math.max(0, 100 - pctPC - pctPV);

  const elSegPC = document.getElementById('segPhaChe');
  if (elSegPC) elSegPC.style.width = `${pctPC}%`;
  const elSegPV = document.getElementById('segPhucVu');
  if (elSegPV) elSegPV.style.width = `${pctPV}%`;
  const elSegOther = document.getElementById('segOther');
  if (elSegOther) elSegOther.style.width = `${pctOT}%`;

  const elLblPC = document.getElementById('lblPhaChe');
  if (elLblPC) elLblPC.textContent = `${(deptCost['Pha chế']/1000000).toFixed(1)}tr (${pctPC}%)`;
  const elLblPV = document.getElementById('lblPhucVu');
  if (elLblPV) elLblPV.textContent = `${(deptCost['Phục vụ']/1000000).toFixed(1)}tr (${pctPV}%)`;
  const elLblOther = document.getElementById('lblOther');
  if (elLblOther) elLblOther.textContent = `${(deptCost['Other']/1000000).toFixed(1)}tr (${pctOT}%)`;

  // 3. High-Density Key Staff Performance Insights (Cost Leakage & Governance)
  const staffListSortedByShifts = Object.values(staffAggMap).sort((a,b) => b.shifts - a.shifts);
  const topOTStaff = Object.values(staffAggMap).filter(s => s.otCost > 0).sort((a,b) => b.otCost - a.otCost)[0];
  const topLateStaff = Object.values(staffAggMap).filter(s => s.lateCount > 0).sort((a,b) => b.lateMins - a.lateMins)[0];
  const topBonusStaff = Object.values(staffAggMap).filter(s => s.bonus > 0).sort((a,b) => b.bonus - a.bonus)[0];
  const topAdvanceStaff = Object.values(staffAggMap).filter(s => s.advance > 0).sort((a,b) => b.advance - a.advance)[0];

  const statStaffCount = document.getElementById('statStaffCount');
  const statOnTimeRate = document.getElementById('statOnTimeRate');
  if (statStaffCount) statStaffCount.textContent = `${staffListSortedByShifts.length} NV`;
  if (statOnTimeRate) statOnTimeRate.textContent = `${attRate}% Đúng giờ`;

  const allRows = [];

  // 1. Cost Leakage OT Warning
  if (topOTStaff) {
    const otShare = Math.round((topOTStaff.otCost / (otCost || 1)) * 100);
    allRows.push(`
      <div class="key-staff-row" data-name="${topOTStaff.name}">
        <div class="key-staff-left">
          <span class="key-staff-badge ot" style="background:rgba(238,93,54,0.18); color:var(--accent-coral); font-weight:800;">CẢNH BÁO OT</span>
          <span class="key-staff-name">${topOTStaff.name}</span>
          <span class="key-staff-sub">(${topOTStaff.role} • ${(topOTStaff.otMins/60).toFixed(1)}h OT • chiếm ${otShare}% OT quán)</span>
        </div>
        <div class="key-staff-val coral-text tabular-nums">+${fmtMoney.format(Math.round(topOTStaff.otCost)).replace('₫', 'đ')}</div>
      </div>
    `);
  }

  // 2. Top Shifts 1
  if (staffListSortedByShifts[0]) {
    const s = staffListSortedByShifts[0];
    allRows.push(`
      <div class="key-staff-row" data-name="${s.name}">
        <div class="key-staff-left">
          <span class="key-staff-badge shifts">TOP CA</span>
          <span class="key-staff-name">${s.name}</span>
          <span class="key-staff-sub">(${s.role} • ${s.shifts} ca)</span>
        </div>
        <div class="key-staff-val emerald-text tabular-nums">${(s.mins/60).toFixed(1)}h làm</div>
      </div>
    `);
  }

  // 3. Top Shifts 2
  if (staffListSortedByShifts[1]) {
    const s = staffListSortedByShifts[1];
    allRows.push(`
      <div class="key-staff-row" data-name="${s.name}">
        <div class="key-staff-left">
          <span class="key-staff-badge shifts">TOP 2 CA</span>
          <span class="key-staff-name">${s.name}</span>
          <span class="key-staff-sub">(${s.role} • ${s.shifts} ca)</span>
        </div>
        <div class="key-staff-val emerald-text tabular-nums">${(s.mins/60).toFixed(1)}h làm</div>
      </div>
    `);
  }

  // 4. Top Shifts 3
  if (staffListSortedByShifts[2]) {
    const s = staffListSortedByShifts[2];
    allRows.push(`
      <div class="key-staff-row" data-name="${s.name}">
        <div class="key-staff-left">
          <span class="key-staff-badge shifts">TOP 3 CA</span>
          <span class="key-staff-name">${s.name}</span>
          <span class="key-staff-sub">(${s.role} • ${s.shifts} ca)</span>
        </div>
        <div class="key-staff-val emerald-text tabular-nums">${(s.mins/60).toFixed(1)}h làm</div>
      </div>
    `);
  }

  // 5. Management Governance or Staff Late Violation
  if (topLateStaff) {
    const isMgr = (topLateStaff.role === 'Quản lý' || getStaffRole(topLateStaff.name) === 'Quản lý');
    const lateBadge = isMgr ? 'KỶ LUẬT QL' : 'TRỄ CA';
    const lateBadgeStyle = isMgr ? 'background:rgba(225,29,72,0.15); color:#E11D48; font-weight:800;' : '';
    const subNote = isMgr && topLateStaff.lateCount >= 5 ? ' • TẠM GIỮ THƯỞNG' : '';
    allRows.push(`
      <div class="key-staff-row" data-name="${topLateStaff.name}">
        <div class="key-staff-left">
          <span class="key-staff-badge late" style="${lateBadgeStyle}">${lateBadge}</span>
          <span class="key-staff-name">${topLateStaff.name}</span>
          <span class="key-staff-sub">(${topLateStaff.lateCount} ca trễ • ${topLateStaff.lateMins}p${subNote})</span>
        </div>
        <div class="key-staff-val tabular-nums" style="color:var(--accent-coral);">${topLateStaff.lateMins > 30 ? '-50.000 đ' : 'Cảnh cáo'}</div>
      </div>
    `);
  }

  if (topAdvanceStaff) {
    allRows.push(`
      <div class="key-staff-row" data-name="${topAdvanceStaff.name}">
        <div class="key-staff-left">
          <span class="key-staff-badge adv">TẠM ỨNG</span>
          <span class="key-staff-name">${topAdvanceStaff.name}</span>
          <span class="key-staff-sub">(Đã ứng trong kỳ)</span>
        </div>
        <div class="key-staff-val coral-text tabular-nums">-${fmtMoney.format(topAdvanceStaff.advance).replace('₫', 'đ')}</div>
      </div>
    `);
  }

  if (topBonusStaff) {
    allRows.push(`
      <div class="key-staff-row" data-name="${escapeHtml(topBonusStaff.name)}">
        <div class="key-staff-left">
          <span class="key-staff-badge bonus">THƯỞNG</span>
          <span class="key-staff-name">${escapeHtml(topBonusStaff.name)}</span>
          <span class="key-staff-sub">(Thưởng quản lý/ca)</span>
        </div>
        <div class="key-staff-val emerald-text tabular-nums">+${fmtMoney.format(topBonusStaff.bonus).replace('₫', 'đ')}</div>
      </div>
    `);
  }

  const keyBox = document.getElementById('keyStaffList');
  if (keyBox) {
    if (allRows.length === 0) {
      keyBox.innerHTML = `
        <div class="empty-state-card" style="padding: 18px 12px; text-align: center; background: var(--bg-card-sub, rgba(0,0,0,0.02)); border-radius: 10px; border: 1px dashed var(--border);">
          <div style="margin-bottom: 6px; opacity: 0.7;"><iconify-icon icon="solar:bill-list-linear" width="28" height="28" style="color:var(--text-muted);"></iconify-icon></div>
          <div style="font-size: 13px; font-weight: 700; color: var(--text-primary); margin-bottom: 3px;">Chưa có dữ liệu ca trực</div>
          <div style="font-size: 11.5px; color: var(--text-muted); line-height: 1.4;">Chỉ số hiệu suất và biến động sẽ tự động cập nhật khi có ca làm việc phát sinh trong kỳ</div>
        </div>
      `;
    } else {
      const primaryLimit = 2;
      if (allRows.length > primaryLimit) {
        const primaryRows = allRows.slice(0, primaryLimit);
        const extraRows = allRows.slice(primaryLimit);
        keyBox.innerHTML = `
          <div class="key-staff-primary flex-col gap-6">
            ${primaryRows.join('')}
          </div>
          <div id="keyStaffExtraRows" style="display:none; flex-direction:column; gap:6px; margin-top:6px; padding-top:6px; border-top:1px dashed var(--border);">
            ${extraRows.join('')}
          </div>
          <button type="button" id="btnToggleKeyStaff" class="section-expand-btn">
            <span id="txtToggleKeyStaff">Xem thêm (${extraRows.length} chỉ số hiệu suất)</span>
            <span id="iconToggleKeyStaff">▾</span>
          </button>
        `;

        const btnToggle = document.getElementById('btnToggleKeyStaff');
        const extraDiv = document.getElementById('keyStaffExtraRows');
        const txtToggle = document.getElementById('txtToggleKeyStaff');
        const iconToggle = document.getElementById('iconToggleKeyStaff');
        if (btnToggle && extraDiv) {
          btnToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            const isHidden = (extraDiv.style.display === 'none');
            extraDiv.style.display = isHidden ? 'flex' : 'none';
            if (txtToggle) txtToggle.textContent = isHidden ? 'Thu gọn danh sách' : `Xem thêm (${extraRows.length} chỉ số hiệu suất)`;
            if (iconToggle) iconToggle.textContent = isHidden ? '▴' : '▾';
          });
        }
      } else {
        keyBox.innerHTML = allRows.join('');
      }
    }

    keyBox.querySelectorAll('.key-staff-row').forEach(row => {
      row.addEventListener('click', () => {
        const staffName = row.getAttribute('data-name');
        if (staffName) (window.openPayslipModal || function(){})(staffName);
      });
    });
  }

  // 4. Aggregated Cost Leakage & Violations Box (Cộng dồn thông minh)
  state.staffAggMapCache = staffAggMap;
  renderAggAlerts();
  fetchPendingHangingShifts().then(() => renderAggAlerts()).catch(() => {});
  setupBentoCardInteractions();
}

export async function confirmShiftOT(shiftKey, action, approvedMins, note = '') {
  const token = localStorage.getItem('vnaigc_jwt') || localStorage.getItem('vnaigc_token') || localStorage.getItem('cc_token');
  if (!token) return showToast('Vui lòng đăng nhập quyền Quản lý', 'warn');

  try {
    const res = await fetch('/api/v1/cc/shifts/confirm-ot', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        shift_key: shiftKey,
        action: action,
        approved_mins: approvedMins || 300,
        manager_note: note || ''
      })
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || 'Lỗi xử lý duyệt ca');

    // Cập nhật bộ nhớ đệm tại chỗ
    if (!state.rawData._meta) state.rawData._meta = {};
    if (!state.rawData._meta.shift_approvals) state.rawData._meta.shift_approvals = {};
    if (action === 'RESET') {
      delete state.rawData._meta.shift_approvals[shiftKey];
    } else {
      state.rawData._meta.shift_approvals[shiftKey] = d.approval;
    }

    // Tính toán lại và vẽ lại giao diện (Bảo lưu tháng đang chọn)
    const savedMonth = state.currentMonth;
    processData();
    if (savedMonth) state.currentMonth = savedMonth;
    (window.updateAllViews || function(){})();

    // Nếu modal chi tiết ca đang mở thì cập nhật lại
    const modal = document.getElementById('staffShiftsSheet');
    if (modal && modal.classList.contains('active')) {
      const subTitle = document.getElementById('shiftsModalSubtitle')?.textContent || '';
      const namePart = subTitle.split('•')[0]?.replace('Nhân sự:', '').trim();
      if (namePart) (window.openStaffShiftsDetailModal || function(){})(namePart);
    }

    if (action === 'RESET') {
      const listEl = document.getElementById('aggAlertList');
      if (listEl) {
        listEl.scrollTo({ top: 0, behavior: 'smooth' });
      }
      setTimeout(() => {
        try {
          const targetCard = document.querySelector(`.ot-card-pending[data-shift-key="${CSS.escape(shiftKey)}"]`);
          if (targetCard) {
            targetCard.style.transition = 'all 0.4s ease';
            targetCard.style.borderColor = '#f59e0b';
            targetCard.style.boxShadow = '0 0 12px rgba(245, 158, 11, 0.4)';
            targetCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            setTimeout(() => {
              targetCard.style.borderColor = 'rgba(245, 158, 11, 0.4)';
              targetCard.style.boxShadow = '0 1px 2px rgba(0,0,0,0.03)';
            }, 3000);
          }
        } catch (_) {}
      }, 100);
      showToast('Đã hoàn tác: Ca này đã chuyển về mục "⚡ CA CẦN DUYỆT" ở trên đầu để chọn lại', 'info');
    } else {
      showToast(d.message || 'Cập nhật duyệt ca thành công', 'success');
    }
  } catch (err) {
    showToast(safeErrorDetail(err), 'error');
  }
}
window.confirmShiftOT = confirmShiftOT;

state.staffAggMapCache = {};
state.currentAggView = 'ot';

export async function fetchPendingHangingShifts() {
  const token = localStorage.getItem('vnaigc_jwt');
  if (!token) return [];
  try {
    const res = await fetch('/api/v1/cc/attendance/manager/pending', {
      headers: { 'Authorization': 'Bearer ' + token }
    });
    if (!res.ok) return [];
    const data = await res.json();
    const records = data.records || [];
    const hanging = records.filter(r => r.is_hanging_pending || r.status === 'QUEN_CHECKOUT' || !r.checkout_time);
    state.pendingHangingShifts = hanging;
    const countHangingEl = document.getElementById('countAlertHanging');
    if (countHangingEl) countHangingEl.textContent = hanging.length;
    return hanging;
  } catch (_) {
    return [];
  }
}

export function renderAggAlerts() {
  const tabOT = document.getElementById('tabAlertOT');
  const tabLate = document.getElementById('tabAlertLate');
  const tabHanging = document.getElementById('tabAlertHanging');
  const countOTEl = document.getElementById('countAlertOT');
  const countLateEl = document.getElementById('countAlertLate');
  const countHangingEl = document.getElementById('countAlertHanging');
  const totalSummaryEl = document.getElementById('aggTotalSummary');
  const listEl = document.getElementById('aggAlertList');

  if (!listEl) return;

  const filteredRecords = state.currentMonth === 'all' ? state.records : state.records.filter(r => r.month === state.currentMonth);
  const excessShifts = filteredRecords
    .filter(r => r.mins >= POLICY.EXCESS_THRESHOLD_MINS)
    .sort((a, b) => {
      if (a.otStatus === 'PENDING' && b.otStatus !== 'PENDING') return -1;
      if (a.otStatus !== 'PENDING' && b.otStatus === 'PENDING') return 1;
      return b.mins - a.mins;
    });

  const pendingCount = excessShifts.filter(s => s.otStatus === 'PENDING').length;

  const lateList = Object.values(state.staffAggMapCache)
    .filter(s => (s.lateCount > 0))
    .sort((a, b) => b.lateCount - a.lateCount);

  const hangingList = state.pendingHangingShifts || [];

  if (countOTEl) countOTEl.textContent = pendingCount > 0 ? pendingCount : excessShifts.length;
  if (countLateEl) countLateEl.textContent = lateList.length;
  if (countHangingEl) countHangingEl.textContent = hangingList.length;

  if (state.currentAggView === 'hanging') {
    if (tabOT) tabOT.className = 'agg-toggle-btn';
    if (tabLate) tabLate.className = 'agg-toggle-btn';
    if (tabHanging) tabHanging.className = 'agg-toggle-btn active';

    if (totalSummaryEl) {
      totalSummaryEl.textContent = `${hangingList.length} ca quên ra • Chờ duyệt`;
      totalSummaryEl.style.color = hangingList.length > 0 ? 'var(--accent-coral)' : 'var(--accent-emerald)';
    }

    if (hangingList.length === 0) {
      listEl.innerHTML = '<div style="font-size:12px; color:var(--text-muted); text-align:center; padding:12px;">Không có ca quên check-out cần duyệt.</div>';
      return;
    }

    listEl.innerHTML = hangingList.map(h => {
      const staffName = escapeHtml(h.display_name || h.name || h.username || 'Nhân viên');
      const shiftName = escapeHtml(h.shift_name || h.shift || 'Ca');
      const dateStr = escapeHtml(h.date || '');
      const timeIn = escapeHtml(h.checkin_time || h.in || '--:--');
      const schedOut = escapeHtml(h.scheduled_end || (shiftName.toLowerCase().includes('tối') ? '23:00' : '12:00'));

      return `
        <div class="agg-row" style="flex-direction:column; gap:6px; padding:10px 12px; background:var(--bg-card); border:1.5px solid rgba(239, 68, 68, 0.4); border-radius:10px; margin-bottom:6px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:6px;">
              <strong style="font-size:14px; color:var(--text-primary);">${staffName}</strong>
              <span style="font-size:11px; background:rgba(239, 68, 68, 0.12); color:var(--accent-coral); padding:2px 6px; border-radius:4px; font-weight:700;">QUÊN CHECK-OUT</span>
            </div>
            <span style="font-size:12px; color:var(--text-secondary);">${dateStr} • ${shiftName}</span>
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:var(--text-secondary); margin-top:2px;">
            <span>Vào: <strong style="color:var(--accent-emerald);">${timeIn}</strong> ➔ Dự kiến ra: <strong style="color:var(--accent-amber);">${schedOut}</strong></span>
            <button type="button" onclick="window.openReviewHangingShiftModal && window.openReviewHangingShiftModal(${JSON.stringify(h).replace(/"/g, '&quot;')})" style="background:#059669; color:#fff; border:none; border-radius:8px; padding:6px 12px; font-size:12px; font-weight:700; cursor:pointer; box-shadow:0 1px 3px rgba(5,150,105,0.3);">
              Duyệt Ca Treo
            </button>
          </div>
        </div>
      `;
    }).join('');
    return;
  }

  if (state.currentAggView === 'ot') {
    if (tabOT) tabOT.className = 'agg-toggle-btn active';
    if (tabLate) tabLate.className = 'agg-toggle-btn';
    if (tabHanging) tabHanging.className = 'agg-toggle-btn';

    const canManageShifts = (['ADMIN', 'MANAGER'].includes(localStorage.getItem('vnaigc_role')) || ['ADMIN', 'MANAGER'].includes(state.rawData && state.rawData._meta && state.rawData._meta.role));

    // Split into pending vs processed
    const pendingShifts = excessShifts.filter(s => s.otStatus === 'PENDING');
    const processedShifts = excessShifts.filter(s => s.otStatus !== 'PENDING');

    const prevHistoryEl = document.getElementById('otProcessedList');
    const wasHistoryOpen = prevHistoryEl ? (prevHistoryEl.style.display === 'flex' || prevHistoryEl.style.display === 'block') : false;

    if (totalSummaryEl) {
      totalSummaryEl.textContent = `${excessShifts.length} ca làm thêm giờ • ${pendingCount > 0 ? `${pendingCount} chờ duyệt` : 'Đã duyệt hết'}`;
      totalSummaryEl.style.color = pendingCount > 0 ? 'var(--accent-coral)' : 'var(--accent-emerald)';
    }

    if (excessShifts.length === 0) {
      listEl.innerHTML = '<div style="font-size:12px; color:var(--text-muted); text-align:center; padding:12px;">Không có ca làm thêm giờ trong kỳ này.</div>';
      return;
    }

    // Helper 1: Render ca CHƯA DUYỆT (Nổi bật, có 2 nút thao tác duyệt/cắt)
    const renderPendingCard = (s) => {
      const stdMins = s.standardShiftMins || 300;
      const isAbnormal = Number(s.mins) > 720;
      const userRole = localStorage.getItem('vnaigc_role') || (state.rawData && state.rawData._meta && state.rawData._meta.role) || 'STAFF';
      const isUserAdmin = (userRole === 'ADMIN');
      const hourlyRate = (s.empWage || (s.totalCost / (s.effectiveMins || stdMins) * 60)) || 17000;
      const projectedCost = s.projectedCost || ((Number(s.mins) / 60) * hourlyRate * (s.holidayMultiplier || 1));
      const otDiff = Math.max(0, s.mins - stdMins);
      const shiftLabel = (s.shift || '').toLowerCase().startsWith('ca ') ? escapeHtml(s.shift) : `Ca ${escapeHtml(s.shift || '')}`;

      let actionsHtml = '';
      if (canManageShifts) {
        if (isAbnormal && !isUserAdmin) {
          actionsHtml = `
            <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:8px; margin-top:8px; padding-top:8px; border-top:1px dashed var(--border);">
              <span style="font-size:11px; color:#dc2626; font-weight:700;">⚠️ Ca >12h có dấu hiệu quên checkout: Chỉ Admin mới được duyệt đủ</span>
              <button onclick="confirmShiftOT('${escapeHtml(s.shiftKey)}', 'CUT', ${stdMins})" style="background:rgba(239, 68, 68, 0.1); color:#dc2626; border:1.5px solid #ef4444; border-radius:8px; padding:7px 12px; font-size:13px; font-weight:700; cursor:pointer; min-height:34px; white-space:nowrap;">✕ Cắt về ${stdMins}p</button>
            </div>
          `;
        } else {
          actionsHtml = `
            <div style="display:flex; flex-wrap:wrap; justify-content:flex-end; align-items:center; gap:8px; margin-top:8px; padding-top:8px; border-top:1px dashed var(--border);">
              <button onclick="confirmShiftOT('${escapeHtml(s.shiftKey)}', 'APPROVE', ${Number(s.mins) || stdMins})" style="background:#059669; color:#fff; border:none; border-radius:8px; padding:7px 14px; font-size:13px; font-weight:700; cursor:pointer; min-height:34px; white-space:nowrap; box-shadow:0 1px 2px rgba(0,0,0,0.1);">✓ Duyệt đủ ${s.mins}p</button>
              <button onclick="confirmShiftOT('${escapeHtml(s.shiftKey)}', 'CUT', ${stdMins})" style="background:rgba(239, 68, 68, 0.1); color:#dc2626; border:1.5px solid #ef4444; border-radius:8px; padding:7px 12px; font-size:13px; font-weight:700; cursor:pointer; min-height:34px; white-space:nowrap;">✕ Cắt về ${stdMins}p</button>
            </div>
          `;
        }
      }

      const otBadge = isAbnormal
        ? `<span style="background:rgba(239, 68, 68, 0.15); color:#dc2626; font-size:12px; font-weight:800; padding:3px 8px; border-radius:6px; border:1px solid #ef4444; white-space:nowrap;">🚨 +${otDiff}p OT • Quá 12h (Nghi quên ra)</span>`
        : `<span style="background:rgba(245, 158, 11, 0.15); color:#d97706; font-size:12px; font-weight:800; padding:3px 8px; border-radius:6px; border:1px solid #f59e0b; white-space:nowrap;">⏳ +${otDiff}p OT • Chờ duyệt</span>`;

      return `
        <div class="agg-row ot-card-pending" data-shift-key="${escapeHtml(s.shiftKey)}" style="flex-direction:column; gap:6px; padding:10px 12px; background:var(--bg-card); border:1.5px solid ${isAbnormal ? 'rgba(239, 68, 68, 0.5)' : 'rgba(245, 158, 11, 0.4)'}; border-radius:10px; margin-bottom:6px; box-shadow:0 1px 2px rgba(0,0,0,0.03);">
          <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:6px;">
            <div style="display:flex; flex-wrap:wrap; align-items:center; gap:6px; min-width:0; flex:1;">
              <strong style="font-size:14px; color:var(--text-primary); letter-spacing:-0.2px;">${escapeHtml(s.name)}</strong>
              <span style="font-size:12px; color:var(--text-muted); font-weight:600;">(${escapeHtml(s.role)})</span>
              <span style="font-size:12px; color:var(--text-secondary); background:var(--bg-card-sub, #f1f5f9); padding:2px 6px; border-radius:4px; border:1px solid var(--border);">${escapeHtml(s.date)} • ${shiftLabel}</span>
            </div>
            <div style="flex-shrink:0;">
              ${otBadge}
            </div>
          </div>
          <div style="display:flex; flex-wrap:wrap; justify-content:space-between; align-items:flex-start; gap:6px; font-size:12px; margin-top:4px;">
            <span style="color:var(--text-secondary); line-height:1.4;">Vào <strong>${escapeHtml(s.in)}</strong> ➔ Ra <strong>${escapeHtml(s.out)}</strong> (<span style="color:var(--accent-coral); font-weight:700;">${Number(s.mins)}p</span>)</span>
            <div style="display:flex; flex-direction:column; align-items:flex-end; gap:2px; text-align:right;">
              <span style="font-weight:700; font-size:12px; color:var(--text-primary); white-space:nowrap;">Tạm tính (${stdMins}p): <strong style="color:var(--accent-emerald);">${fmtMoney.format(s.totalCost).replace('₫','đ')}</strong></span>
              <span style="font-size:11px; color:var(--text-muted); white-space:nowrap;">Dự kiến duyệt (${Number(s.mins)}p): <strong style="color:var(--accent-coral);">${fmtMoney.format(projectedCost).replace('₫','đ')}</strong></span>
            </div>
          </div>
          ${actionsHtml}
        </div>
      `;
    };

    // Helper 2: Render ca ĐÃ XỬ LÝ (Phân định rõ Đã duyệt, Cắt ca, và OT hiệu suất)
    const renderProcessedCard = (s) => {
      let stBadge = '';
      if (s.otStatus === 'APPROVED') {
        stBadge = `<span style="background:rgba(16, 185, 129, 0.12); color:#047857; font-size:11px; font-weight:800; padding:2px 6px; border-radius:4px; border:1px solid #10b981; white-space:nowrap;">✓ Đã duyệt ${s.effectiveMins}p</span>`;
      } else if (s.otStatus === 'CUT') {
        stBadge = `<span style="background:rgba(239, 68, 68, 0.1); color:#dc2626; font-size:11px; font-weight:800; padding:2px 6px; border-radius:4px; border:1px solid #ef4444; white-space:nowrap;">✕ Cắt về ${s.effectiveMins}p</span>`;
      } else if (s.otStatus === 'OT_PERF') {
        stBadge = `<span style="background:rgba(245, 158, 11, 0.12); color:#d97706; font-size:11px; font-weight:800; padding:2px 6px; border-radius:4px; border:1px solid #f59e0b; white-space:nowrap;">⚡ OT hiệu suất ${s.mins}p</span>`;
      } else {
        stBadge = `<span style="background:rgba(16, 185, 129, 0.1); color:#059669; font-size:11px; font-weight:700; padding:2px 6px; border-radius:4px; white-space:nowrap;">Chuẩn ${s.effectiveMins}p</span>`;
      }

      const procShiftLabel = (s.shift || '').toLowerCase().startsWith('ca ') ? escapeHtml(s.shift) : `Ca ${escapeHtml(s.shift || '')}`;

      return `
        <div class="agg-row ot-card-processed" style="justify-content:space-between; align-items:center; padding:8px 10px; background:var(--bg-card-sub, #f8fafc); border:1px solid var(--border); border-radius:8px; margin-bottom:4px; gap:6px; font-size:12px;">
          <div style="display:flex; flex-wrap:wrap; align-items:center; gap:6px; min-width:0; flex:1;">
            <strong style="color:var(--text-primary); font-size:13px;">${escapeHtml(s.name)}</strong>
            <span style="color:var(--text-muted); font-size:11px;">${escapeHtml(s.date)} • ${procShiftLabel}</span>
            <span style="color:var(--text-secondary); font-size:11px;">(${Number(s.mins)}p)</span>
          </div>
          <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
            ${stBadge}
            ${(canManageShifts && s.approval) ? `<button onclick="confirmShiftOT('${escapeHtml(s.shiftKey)}', 'RESET', 300)" title="Hoàn tác ca này về mục Chờ Duyệt ở trên" style="background:rgba(239, 68, 68, 0.08); border:1px solid rgba(239, 68, 68, 0.25); color:#dc2626; border-radius:6px; font-size:11px; font-weight:700; cursor:pointer; padding:3px 8px; white-space:nowrap;">↩ Hoàn tác</button>` : ''}
          </div>
        </div>
      `;
    };

    let html = '';
    // PHẦN CHÍNH: CHỈ HIỂN THỊ CA CHƯA DUYỆT ĐỂ BẤM (Co giãn động theo số ca)
    if (pendingShifts.length > 0) {
      html += `<div style="font-size:12px; font-weight:800; color:var(--accent-coral); margin-bottom:6px; display:flex; align-items:center; gap:6px;">⚡ CA CẦN DUYỆT (${pendingShifts.length} ca)</div>`;
      html += pendingShifts.map(renderPendingCard).join('');
    } else {
      html += '<div style="font-size:12px; color:var(--accent-emerald); text-align:center; padding:8px 12px; font-weight:700; background:rgba(16, 185, 129, 0.08); border-radius:8px; border:1px solid rgba(16, 185, 129, 0.2);">✓ Toàn bộ ca OT đã được duyệt đầy đủ (0 chờ duyệt)</div>';
    }

    // PHẦN RIÊNG BIỆT: LỊCH SỬ ĐÃ XỬ LÝ (Sticky Header Cố Định Ở Đỉnh)
    if (processedShifts.length > 0) {
      html += `
        <div style="margin-top:6px;">
          <div style="position:sticky; top:0; z-index:10; background:var(--bg-card); padding:4px 0 6px;">
            <button id="btnToggleOTHistory" type="button" onclick="window.toggleOTProcessedHistory()" style="background:var(--bg-card-sub, #f8fafc); border:1px dashed var(--border); border-radius:8px; padding:8px 12px; font-size:12px; font-weight:700; color:var(--text-secondary); cursor:pointer; width:100%; display:flex; justify-content:center; align-items:center; gap:6px; box-shadow:0 1px 3px rgba(0,0,0,0.06);">
              <span id="txtToggleOTHistory">${wasHistoryOpen ? 'Thu gọn danh sách đã xử lý' : `Xem lịch sử ${processedShifts.length} ca đã xử lý`}</span>
              <span id="iconToggleOTHistory">${wasHistoryOpen ? '▲' : '▼'}</span>
            </button>
          </div>
          <div id="otProcessedList" style="display:${wasHistoryOpen ? 'flex' : 'none'}; flex-direction:column; gap:4px; margin-top:2px;">
            ${processedShifts.map(renderProcessedCard).join('')}
            <div style="text-align:center; padding:8px 0 4px;">
              <button type="button" onclick="window.toggleOTProcessedHistory()" style="background:none; border:none; color:var(--text-muted); font-size:12px; font-weight:600; cursor:pointer; text-decoration:underline;">▲ Thu gọn danh sách lên đầu</button>
            </div>
          </div>
        </div>
      `;
    }

    listEl.innerHTML = html;
  } else {
    if (tabOT) tabOT.className = 'agg-toggle-btn';
    if (tabLate) tabLate.className = 'agg-toggle-btn active late';
    const totalLateShifts = lateList.reduce((acc, s) => acc + (s.lateCount || 0), 0);
    const totalLateMins = lateList.reduce((acc, s) => acc + (s.lateMins || 0), 0);
    if (totalSummaryEl) {
      totalSummaryEl.textContent = `${totalLateShifts} ca • ${totalLateMins}p trễ`;
      totalSummaryEl.style.color = 'var(--accent-amber)';
    }

    if (lateList.length === 0) {
      listEl.innerHTML = '<div style="font-size:12px; color:var(--text-muted); text-align:center; padding:8px;">Không có vi phạm trễ ca trong tháng này.</div>';
      return;
    }

    listEl.innerHTML = lateList.map(s => {
      const isMgr = (s.role === 'Quản lý' || getStaffRole(s.name) === 'Quản lý');
      let lateBadge = '';
      if (isMgr && s.lateCount >= 5) {
        lateBadge = '<span class="agg-risk-badge high">KỶ LUẬT QL</span>';
      } else if (s.lateCount >= 4) {
        lateBadge = '<span class="agg-risk-badge high">CẢNH BÁO ĐỎ</span>';
      } else if (s.lateCount >= 2) {
        lateBadge = '<span class="agg-risk-badge med">PHẠT TIỀN</span>';
      } else {
        lateBadge = '<span class="agg-risk-badge low">NHẮC NHỞ</span>';
      }
      const avgLateMins = Math.round(s.lateMins / s.lateCount);

      return `
        <div class="agg-row" data-name="${escapeHtml(s.name)}">
          <div class="agg-row-top">
            <div class="agg-user-info">
              <span class="agg-name">${escapeHtml(s.name)}</span>
              <span class="agg-role">(${escapeHtml(s.role)})</span>
              ${lateBadge}
            </div>
            <span class="agg-val amber-text" style="color:var(--accent-coral);">${s.lateMins > 30 ? '-50.000 đ' : (s.lateCount >= 3 ? '-50.000 đ' : 'Cảnh cáo')}</span>
          </div>
          <div class="agg-row-bot">
            <div class="agg-metrics">
              <span class="agg-metric-item"><strong>${s.lateCount}</strong> ca trễ</span>
              <span>•</span>
              <span class="agg-metric-item">Tổng <strong>${s.lateMins}p</strong></span>
              ${s.lateOver30Count > 0 ? `<span>•</span><span class="agg-metric-item coral-text"><strong>${s.lateOver30Count}</strong> lần >30p</span>` : ''}
              <span>•</span>
              <span class="agg-metric-item">TB <strong>${avgLateMins}p</strong>/ca</span>
            </div>
            <span class="agg-action">Xem ❯</span>
          </div>
        </div>
      `;
    }).join('');
  }

  // Click row to open payslip
  listEl.querySelectorAll('.agg-row').forEach(row => {
    row.addEventListener('click', () => {
      const n = row.getAttribute('data-name');
      if (n) (window.openPayslipModal || function(){})(n);
    });
  });
}

export function setupAggAlertToggles() {
  const tabOT = document.getElementById('tabAlertOT');
  const tabLate = document.getElementById('tabAlertLate');
  const tabHanging = document.getElementById('tabAlertHanging');
  if (tabOT) {
    tabOT.addEventListener('click', () => {
      state.currentAggView = 'ot';
      renderAggAlerts();
    });
  }
  if (tabLate) {
    tabLate.addEventListener('click', () => {
      state.currentAggView = 'late';
      renderAggAlerts();
    });
  }
  if (tabHanging) {
    tabHanging.addEventListener('click', () => {
      state.currentAggView = 'hanging';
      renderAggAlerts();
    });
  }
}

export function setupBentoInteractions() {
  const cOT = document.getElementById('bentoCardOT');
  if (cOT) {
    cOT.addEventListener('click', () => {
      (window.switchTab || function(){})('payslip');
      document.getElementById('payslipSearch').value = '';
    });
  }
  const cShifts = document.getElementById('bentoCardShifts');
  if (cShifts) {
    cShifts.addEventListener('click', () => (window.switchTab || function(){})('roster'));
  }
  const cAtt = document.getElementById('bentoCardAttendance');
  if (cAtt) {
    cAtt.addEventListener('click', () => (window.switchTab || function(){})('payslip'));
  }
}

export function toggleOTProcessedHistory() {
  const c = document.getElementById('otProcessedList');
  const t = document.getElementById('txtToggleOTHistory');
  const ic = document.getElementById('iconToggleOTHistory');
  if (!c) return;
  if (c.style.display === 'none' || !c.style.display) {
    c.style.display = 'flex';
    if (t) t.textContent = 'Thu gọn danh sách đã xử lý';
    if (ic) ic.textContent = '▲';
  } else {
    c.style.display = 'none';
    const cnt = c.children.length;
    if (t) t.textContent = `Xem lịch sử ${cnt} ca đã xử lý`;
    if (ic) ic.textContent = '▼';
  }
}
window.toggleOTProcessedHistory = toggleOTProcessedHistory;

// ==========================================================================
// QUICK OPS TOGGLES (CÔNG TẮC VẬN HÀNH NHANH)
// ==========================================================================

export async function fetchOpsToggles() {
  const token = localStorage.getItem("vnaigc_jwt") || localStorage.getItem("vnaigc_token") || localStorage.getItem("token");
  if (!token) return null;
  try {
    const res = await fetch("/api/v1/cc/notifications/push/settings/ops-toggles", {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.toggles || null;
  } catch (err) {
    console.error("fetchOpsToggles error:", err);
    return null;
  }
}

export async function updateOpsToggle(key, value) {
  const token = localStorage.getItem("vnaigc_jwt") || localStorage.getItem("vnaigc_token") || localStorage.getItem("token");
  if (!token) throw new Error("Chưa đăng nhập");
  const res = await fetch("/api/v1/cc/notifications/push/settings/ops-toggles", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`
    },
    body: JSON.stringify({ key, value: String(value) })
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || "Không thể cập nhật công tắc vận hành");
  }
  return await res.json();
}

export async function loadOpsToggles() {
  const container = document.getElementById("quickOpsTogglesList");
  if (!container) return;

  const toggles = await fetchOpsToggles();
  if (!toggles) {
    container.innerHTML = `<div class="text-muted-12" style="padding:10px;">Chưa thể tải dữ liệu công tắc vận hành.</div>`;
    return;
  }

  const toggleConfigs = [
    {
      key: "auto_remind_shifts",
      title: "Tự Động Nhắc Ca",
      desc: "Nhắc vào & ra ca đúng giờ",
      icon: "solar:bell-bing-bold",
      iconBg: "rgba(0, 122, 255, 0.12)",
      iconColor: "#007aff",
      isEmergency: false
    },
    {
      key: "emergency_remote_checkin",
      title: "Check-in Khẩn Cấp",
      desc: "Điểm danh khi mất mạng",
      icon: "solar:danger-triangle-bold",
      iconBg: "rgba(239, 68, 68, 0.12)",
      iconColor: "#ef4444",
      isEmergency: true
    },
    {
      key: "roster_registration_open",
      title: "Đăng Ký Ca Tuần",
      desc: "Mở cổng gửi lịch tuần mới",
      icon: "solar:calendar-date-bold",
      iconBg: "rgba(16, 185, 129, 0.12)",
      iconColor: "#10b981",
      isEmergency: false
    },
    {
      key: "peer_shift_swap_allowed",
      title: "Tự Đổi Ca Nội Bộ",
      desc: "Cho phép 2 nhân sự đổi ca",
      icon: "solar:users-group-rounded-bold",
      iconBg: "rgba(245, 158, 11, 0.12)",
      iconColor: "#f59e0b",
      isEmergency: false
    },
    {
      key: "payroll_verification_open",
      title: "Kỳ Xác Nhận Lương",
      desc: "Mở xem và ký nhận lương",
      icon: "solar:wallet-money-bold",
      iconBg: "rgba(139, 92, 246, 0.12)",
      iconColor: "#8b5cf6",
      isEmergency: false
    }
  ];

  let html = `<div class="ui-inset-group">`;
  toggleConfigs.forEach(cfg => {
    const item = toggles[cfg.key] || {};
    const isOn = String(item.value || "0") === "1";
    const rowClass = `ui-inset-row ops-toggle-row ${cfg.isEmergency ? "emergency" : ""} ${isOn ? "active" : ""}`;
    const switchClass = `ui-switch ${cfg.isEmergency ? "emergency" : ""}`;

    html += `
      <div class="${rowClass}" id="toggleRow_${cfg.key}">
        <div class="ui-inset-icon-box" style="background:${cfg.iconBg}; color:${cfg.iconColor};">
          <iconify-icon icon="${cfg.icon}" width="18" height="18"></iconify-icon>
        </div>
        <div class="ui-inset-content">
          <div class="ui-inset-title">${escapeHtml(cfg.title)}</div>
          <div class="ui-inset-desc">${escapeHtml(cfg.desc)}</div>
        </div>
        <label class="${switchClass}">
          <input type="checkbox" id="switch_${cfg.key}" data-key="${cfg.key}" ${isOn ? "checked" : ""}>
          <span class="ui-switch__track"></span>
        </label>
      </div>
    `;
  });
  html += `</div>`;

  container.innerHTML = html;

  // Bind change events
  toggleConfigs.forEach(cfg => {
    const input = document.getElementById(`switch_${cfg.key}`);
    if (!input) return;
    input.addEventListener("change", async (e) => {
      const isChecked = e.target.checked;
      const targetVal = isChecked ? "1" : "0";
      const row = document.getElementById(`toggleRow_${cfg.key}`);

      // Optimistic UI
      triggerHaptic("tick");
      if (row) {
        if (isChecked) row.classList.add("active");
        else row.classList.remove("active");
      }

      input.disabled = true;
      try {
        await updateOpsToggle(cfg.key, targetVal);
        triggerHaptic(cfg.isEmergency && isChecked ? "urgent" : "success");
        const actionVerb = isChecked ? "Đã bật" : "Đã tắt";
        showToast(`${actionVerb}: ${cfg.title}`);
      } catch (err) {
        // Rollback on failure
        input.checked = !isChecked;
        if (row) {
          if (!isChecked) row.classList.add("active");
          else row.classList.remove("active");
        }
        triggerHaptic("error");
        showToast(`Lỗi: ${err.message || "Không thể cập nhật"}`);
      } finally {
        input.disabled = false;
      }
    });
  });
}

export function setupQuickOpsToggles() {
  const refreshBtn = document.getElementById("btnRefreshOpsToggles");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      triggerHaptic("tick");
      loadOpsToggles();
      showToast("Đã làm mới công tắc vận hành");
    });
  }
}

export function setupBentoCardInteractions() {
  const cards = [
    document.getElementById("bentoCardTotalPay"),
    document.getElementById("bentoCardOT")
  ];
  cards.forEach(card => {
    if (!card || card.dataset.hasTapListener) return;
    card.dataset.hasTapListener = "1";
    card.addEventListener("click", () => {
      const valEl = card.querySelector(".bento-val");
      if (!valEl || !valEl.dataset.fullAmount) return;
      if (valEl.dataset.isCompact === "1") {
        const isShowingFull = valEl.dataset.showingFull === "1";
        if (isShowingFull) {
          valEl.innerHTML = valEl.dataset.compactHtml || valEl.innerHTML;
          valEl.dataset.showingFull = "0";
        } else {
          valEl.dataset.compactHtml = valEl.innerHTML;
          valEl.innerHTML = `${valEl.dataset.fullAmount.replace("đ", "").trim()} <small class="bento-unit">đ</small>`;
          valEl.dataset.showingFull = "1";
        }
        triggerHaptic("tick");
      }
    });
  });
}

window.loadOpsToggles = loadOpsToggles;
window.setupQuickOpsToggles = setupQuickOpsToggles;
window.setupBentoCardInteractions = setupBentoCardInteractions;

