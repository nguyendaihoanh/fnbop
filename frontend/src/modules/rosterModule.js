// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// ROSTER MODULE: SCHEDULING, SHIFT REGISTRATION, PEER SWAP & ANALYTICS
// ==========================================================================

import {
  isHolidayDate,
  parseVNDate,
  isoToVNDate,
  vnToISODate,
  getCurrentVNDate,
  getCurrentISOWeekDays,
  getDayOfWeekVN
} from "../utils/dateUtils.js";
import { showToast, safeErrorDetail } from "../utils/toast.js";
import { showConfirmDialog } from "../utils/dialog.js";
import { removeAccents, escapeHtml, copyTextToClipboard } from "../utils/formatters.js";
import { updateSheetScrollLock } from "../store/authStore.js";
import {
  state,
  POLICY,
  getStaffRole,
  getCanonicalStaffName
} from "../store/state.js";
import {
  fetchRosterWeekApi,
  registerShiftsApi,
  autoFillRosterApi,
  publishRosterApi,
  peerSwapApi,
  updateShiftSlotApi
} from "../api/rosterApi.js";

export async function fetchRosterWeekData(weekId = 'current', forceRefresh = false) {
  const token = localStorage.getItem('vnaigc_jwt');
  const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
  const cacheKey = weekId || 'current';
  if (!forceRefresh && state.currentRosterWeeksCache[cacheKey]) {
    return state.currentRosterWeeksCache[cacheKey];
  }
  try {
    const res = await fetch(`/api/v1/cc/roster/week?week_id=${encodeURIComponent(cacheKey)}&_t=${Date.now()}`, { headers });
    if (res.ok) {
      const data = await res.json();
      if (data.success && data.week) {
        state.currentRosterWeeksCache[cacheKey] = data;
        if (data.week.week_id) {
          state.currentRosterWeeksCache[data.week.week_id] = data;
        }
        if (data.is_active_week) {
          state.currentRosterWeeksCache['current'] = data;
        }
        if (cacheKey === 'next' || data.week.week_id === data.next_week_id) {
          state.currentRosterWeeksCache['next'] = data;
          state.currentNextWeekRosterData = data;
        }
        return data;
      }
    }
  } catch (e) {
    console.error('Lỗi tải dữ liệu roster:', e);
  }
  return null;
}

state.currentStaffRegState = {
  hasLoaded: false,
  isRegistered: false,
  shiftCount: 0,
  targetShifts: 5,
  note: '',
  registeredAt: '',
  preferences: null
};

state.currentRegWeekMode = 'next';

export async function updateStaffRegStatus(weekMode = null) {
  if (weekMode) state.currentRegWeekMode = weekMode;
  const token = localStorage.getItem('vnaigc_jwt');
  const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
  try {
    const res = await fetch(`/api/v1/cc/roster/week?week_id=${state.currentRegWeekMode}`, { headers });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.success || !data.week) return;

    state.currentNextWeekRosterData = data;
    state.currentRosterWeeksCache[state.currentRegWeekMode] = data;
    if (data.week && data.week.week_id) {
      state.currentRosterWeeksCache[data.week.week_id] = data;
    }
    const week = data.week;
    const registrations = week.registrations || {};
    const myUname = (data.current_user || localStorage.getItem('vnaigc_username') || '').toLowerCase();

    let myReg = null;
    for (const [u, r] of Object.entries(registrations)) {
      if (u.toLowerCase() === myUname) {
        myReg = r;
        break;
      }
    }

    if (myReg) {
      let shiftCount = 0;
      const prefs = myReg.preferences || {};
      Object.keys(prefs).forEach(k => {
        const v = prefs[k];
        if (Array.isArray(v)) shiftCount += v.filter(s => s !== 'OFF').length;
        else if (typeof v === 'string' && v !== 'OFF') shiftCount += 1;
      });

      state.currentStaffRegState = {
        hasLoaded: true,
        isRegistered: true,
        shiftCount: shiftCount,
        targetShifts: myReg.target_shifts || shiftCount,
        note: myReg.note || '',
        registeredAt: myReg.registered_at || '',
        preferences: myReg.preferences || {}
      };
    } else {
      state.currentStaffRegState = {
        hasLoaded: true,
        isRegistered: false,
        shiftCount: 0,
        targetShifts: 5,
        note: '',
        registeredAt: '',
        preferences: null
      };
    }
    updateRosterCountdown();
  } catch (e) {
    console.error('Lỗi kiểm tra trạng thái nộp phiếu:', e);
  }
}

export function checkIsShiftRegistrationOpen(targetWeekMode = null) {
  const mode = targetWeekMode || state.currentRegWeekMode || 'next';
  const now = new Date();
  const day = now.getDay(); // 0 = Sun, 1 = Mon, ..., 6 = Sat
  const hour = now.getHours();

  // 1. Tuần hiện tại ('current'): Khóa cứng đối với nhân viên thường (chỉ xem hoặc đổi ca)
  if (mode === 'current') {
    return {
      isOpen: false,
      targetDeadline: null,
      badgeText: 'ĐÃ CHỐT',
      deadlineLabel: 'Tuần đang chạy (đã khóa)'
    };
  }

  // 2. Tuần kế tiếp ('next'):
  // Kiểm tra cờ mở cổng đăng ký từ Quản trị hệ thống
  if (state.currentNextWeekRosterData && state.currentNextWeekRosterData.registration_window_open === false) {
    return {
      isOpen: false,
      targetDeadline: null,
      badgeText: 'TẠM KHÓA',
      deadlineLabel: state.currentNextWeekRosterData.registration_message || 'Cổng nộp ca đang tạm khóa'
    };
  }

  // Nếu tuần kế tiếp đã được Quản lý công bố chính thức (PUBLISHED) -> Khóa đăng ký
  if (state.currentNextWeekRosterData && state.currentNextWeekRosterData.week && state.currentNextWeekRosterData.week.status === 'PUBLISHED') {
    return {
      isOpen: false,
      targetDeadline: null,
      badgeText: 'ĐÃ CÔNG BỐ',
      deadlineLabel: 'Lịch ca đã chốt chính thức'
    };
  }

  // Mở tự do 24/7: Đến 18:00 Chủ Nhật hệ thống tự động nhảy lịch sang tuần tiếp theo
  const daysUntilSunday = (day === 0 && hour >= 18) ? 7 : ((7 - day) % 7 || 7);
  const deadline = new Date(now);
  deadline.setDate(now.getDate() + daysUntilSunday);
  deadline.setHours(18, 0, 0, 0);

  return {
    isOpen: true,
    targetDeadline: deadline,
    badgeText: 'ĐANG MỞ',
    deadlineLabel: 'Đóng 18:00 CN'
  };
}

export function updateRosterCountdown() {
  const countdownEl = document.getElementById('rosterCountdownText');
  const badgeEl = document.getElementById('rosterRegStatusBadge');
  const btnOpen = document.getElementById('btnOpenShiftRegistration');
  if (!countdownEl) return;

  const btnBannerCurrent = document.getElementById('btnBannerWeekCurrent');
  const btnBannerNext = document.getElementById('btnBannerWeekNext');
  if (btnBannerCurrent && btnBannerNext) {
    const curW = getCurrentISOWeekDays(0);
    const nextW = getCurrentISOWeekDays(1);
    const curRange = `${curW[0].slice(0, 5)} - ${curW[6].slice(0, 5)}`;
    const nextRange = `${nextW[0].slice(0, 5)} - ${nextW[6].slice(0, 5)}`;
    btnBannerCurrent.textContent = `Tuần Này (${curRange})`;
    btnBannerNext.textContent = `Tuần Sau (${nextRange})`;

    if (state.currentRegWeekMode === 'current') {
      btnBannerCurrent.style.background = 'var(--accent-emerald-sub)';
      btnBannerCurrent.style.color = 'var(--accent-emerald)';
      btnBannerCurrent.style.borderColor = 'var(--accent-emerald)';
      btnBannerCurrent.style.fontWeight = '700';

      btnBannerNext.style.background = 'var(--bg-card-sub)';
      btnBannerNext.style.color = 'var(--text-secondary)';
      btnBannerNext.style.borderColor = 'var(--border)';
      btnBannerNext.style.fontWeight = '600';
    } else {
      btnBannerNext.style.background = 'var(--accent-emerald-sub)';
      btnBannerNext.style.color = 'var(--accent-emerald)';
      btnBannerNext.style.borderColor = 'var(--accent-emerald)';
      btnBannerNext.style.fontWeight = '700';

      btnBannerCurrent.style.background = 'var(--bg-card-sub)';
      btnBannerCurrent.style.color = 'var(--text-secondary)';
      btnBannerCurrent.style.borderColor = 'var(--border)';
      btnBannerCurrent.style.fontWeight = '600';
    }
  }

  const now = new Date();
  const regStatus = checkIsShiftRegistrationOpen(state.currentRegWeekMode);
  const isOpen = regStatus.isOpen;
  const targetDeadline = regStatus.targetDeadline;

  const weekTitleLabel = state.currentRegWeekMode === 'current' ? 'Tuần Này' : 'Tuần Sau';

  if (isOpen && targetDeadline) {
    const diffMs = targetDeadline - now;
    if (diffMs > 0) {
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
      const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
      const diffSecs = Math.floor((diffMs % (1000 * 60)) / 1000);
      countdownEl.innerHTML = `Hạn đăng ký: <strong style="color:var(--accent-amber);">18:00 Chủ Nhật</strong>`;
      
      if (badgeEl) {
        if (state.currentStaffRegState.hasLoaded && state.currentStaffRegState.isRegistered) {
          badgeEl.textContent = `ĐÃ NỘP (${state.currentStaffRegState.shiftCount} CA)`;
          badgeEl.style.background = 'rgba(16, 185, 129, 0.2)';
          badgeEl.style.color = 'var(--accent-emerald)';
        } else if (state.currentStaffRegState.hasLoaded && !state.currentStaffRegState.isRegistered) {
          badgeEl.textContent = 'CHƯA NỘP PHIẾU';
          badgeEl.style.background = 'rgba(239, 68, 68, 0.15)';
          badgeEl.style.color = 'var(--accent-coral)';
        } else {
          badgeEl.textContent = 'ĐANG MỞ TỰ DO';
          badgeEl.style.background = 'rgba(16, 185, 129, 0.2)';
          badgeEl.style.color = 'var(--accent-emerald)';
        }
      }
      if (btnOpen) {
        btnOpen.disabled = false;
        if (state.currentStaffRegState.hasLoaded && state.currentStaffRegState.isRegistered) {
          btnOpen.textContent = `Đã Nộp (${state.currentStaffRegState.shiftCount} ca) • Xem/Sửa`;
        } else {
          btnOpen.textContent = `Điền Phiếu Đăng Ký ${weekTitleLabel}`;
        }
      }
    }
  } else {
    if (badgeEl) {
      if (state.currentRegWeekMode === 'current') {
        badgeEl.textContent = state.currentStaffRegState.isRegistered ? `LỊCH TUẦN NÀY (${state.currentStaffRegState.shiftCount} CA)` : 'TUẦN NÀY (ĐÃ CHỐT)';
        badgeEl.style.background = 'rgba(143, 163, 126, 0.2)';
        badgeEl.style.color = 'var(--text-secondary)';
      } else {
        badgeEl.textContent = regStatus.badgeText || 'ĐÃ ĐÓNG';
        badgeEl.style.background = 'rgba(239, 68, 68, 0.15)';
        badgeEl.style.color = 'var(--accent-coral)';
      }
    }
    if (state.currentRegWeekMode === 'current') {
      countdownEl.innerHTML = `Tuần hiện tại đang diễn ra • Lịch ca đã cố định`;
    } else {
      countdownEl.innerHTML = `Cổng tuần sau đã đóng lúc 18:00 Chủ Nhật để chốt lịch ca`;
    }
    if (btnOpen) {
      if (state.currentStaffRegState.hasLoaded && state.currentStaffRegState.isRegistered) {
        btnOpen.textContent = `Xem Phiếu Đã Nộp (${state.currentStaffRegState.shiftCount} ca)`;
      } else {
        btnOpen.textContent = `Xem Phiếu Đăng Ký ${weekTitleLabel}`;
      }
    }
  }
}

export async function openShiftRegistrationModal(weekMode = null) {
  if (weekMode) state.currentRegWeekMode = weekMode;
  const modal = document.getElementById('shiftRegSheet');
  if (!modal) return;

  const daysContainer = document.getElementById('shiftRegDaysContainer');
  if (!daysContainer) return;

  const curW = getCurrentISOWeekDays(0);
  const nextW = getCurrentISOWeekDays(1);
  const curRange = `${curW[0].slice(0, 5)} - ${curW[6].slice(0, 5)}`;
  const nextRange = `${nextW[0].slice(0, 5)} - ${nextW[6].slice(0, 5)}`;

  const btnModalCurrent = document.getElementById('btnModalWeekCurrent');
  const btnModalNext = document.getElementById('btnModalWeekNext');
  if (btnModalCurrent && btnModalNext) {
    btnModalCurrent.textContent = `Tuần Này (${curRange})`;
    btnModalNext.textContent = `Tuần Sau (${nextRange})`;

    if (state.currentRegWeekMode === 'current') {
      btnModalCurrent.style.background = 'var(--accent-emerald-sub)';
      btnModalCurrent.style.color = 'var(--accent-emerald)';
      btnModalCurrent.style.borderColor = 'var(--accent-emerald)';
      btnModalCurrent.style.fontWeight = '700';

      btnModalNext.style.background = 'var(--bg-card-sub)';
      btnModalNext.style.color = 'var(--text-secondary)';
      btnModalNext.style.borderColor = 'var(--border)';
      btnModalNext.style.fontWeight = '600';
    } else {
      btnModalNext.style.background = 'var(--accent-emerald-sub)';
      btnModalNext.style.color = 'var(--accent-emerald)';
      btnModalNext.style.borderColor = 'var(--accent-emerald)';
      btnModalNext.style.fontWeight = '700';

      btnModalCurrent.style.background = 'var(--bg-card-sub)';
      btnModalCurrent.style.color = 'var(--text-secondary)';
      btnModalCurrent.style.borderColor = 'var(--border)';
      btnModalCurrent.style.fontWeight = '600';
    }
  }

  const regStatus = checkIsShiftRegistrationOpen(state.currentRegWeekMode);
  const isOpen = regStatus.isOpen;
  const userRole = localStorage.getItem('vnaigc_role') || 'STAFF';
  const canSubmit = isOpen || userRole === 'ADMIN' || userRole === 'MANAGER';

  const btnSubmit = document.getElementById('btnSubmitShiftRegistration');
  const targetInput = document.getElementById('shiftRegTargetCount');
  const noteInput = document.getElementById('shiftRegNote');
  const weekLabel = document.getElementById('shiftRegWeekLabel');

  // Lấy dữ liệu đăng ký mới nhất từ server theo state.currentRegWeekMode
  const token = localStorage.getItem('vnaigc_jwt');
  const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
  let myReg = null;
  let targetWeekId = state.currentRegWeekMode === 'current' ? 'Tuần Này' : 'Tuần Sau';

  try {
    const res = await fetch(`/api/v1/cc/roster/week?week_id=${state.currentRegWeekMode}`, { headers });
    if (res.ok) {
      const data = await res.json();
      state.currentNextWeekRosterData = data;
      if (data.week) {
        targetWeekId = data.week.week_id || targetWeekId;
        const regs = data.week.registrations || {};
        const myUname = (data.current_user || localStorage.getItem('vnaigc_username') || '').toLowerCase();
        for (const [u, r] of Object.entries(regs)) {
          if (u.toLowerCase() === myUname) {
            myReg = r;
            break;
          }
        }
      }
    }
  } catch (e) {
    console.error('Lỗi nạp dữ liệu ca đăng ký:', e);
  }

  // Tự động điền lại nếu đã có phiếu (Prefill)
  state.shiftPrefState = {};
  let weekRangeLabel = state.currentRegWeekMode === 'current' ? curRange : nextRange;
  if (state.currentNextWeekRosterData && Array.isArray(state.currentNextWeekRosterData.days) && state.currentNextWeekRosterData.days.length === 7) {
    const d0 = state.currentNextWeekRosterData.days[0];
    const d6 = state.currentNextWeekRosterData.days[6];
    weekRangeLabel = `${d0.slice(8, 10)}/${d0.slice(5, 7)} - ${d6.slice(8, 10)}/${d6.slice(5, 7)}`;
  }
  const closedReasonText = state.currentRegWeekMode === 'current' ? 'Tuần Này Đã Chốt (Chỉ Xem Trước)' : 'Cổng Đã Đóng 18:00 CN (Chỉ Xem Trước)';

  if (myReg && myReg.preferences) {
    const prefs = myReg.preferences;
    for (let i = 0; i < 7; i++) {
      const p = prefs[i] || prefs[String(i)] || ['OFF'];
      state.shiftPrefState[i] = Array.isArray(p) ? [...p] : [p];
      if (state.shiftPrefState[i].length === 0) state.shiftPrefState[i] = ['OFF'];
    }
    if (targetInput) targetInput.value = myReg.target_shifts || 5;
    if (noteInput) noteInput.value = myReg.note || '';
    if (weekLabel) {
      weekLabel.innerHTML = `Tuần <strong>${targetWeekId}</strong> (${weekRangeLabel}) • Đã nộp lúc ${myReg.registered_at || 'trước đó'}`;
    }
    if (btnSubmit) {
      if (!canSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.style.opacity = '0.5';
        btnSubmit.style.cursor = 'not-allowed';
        btnSubmit.textContent = closedReasonText;
      } else {
        btnSubmit.disabled = false;
        btnSubmit.style.opacity = '1';
        btnSubmit.style.cursor = 'pointer';
        btnSubmit.textContent = `Cập Nhật Phiếu Đăng Ký (${targetWeekId})`;
      }
    }
  } else {
    for (let i = 0; i < 7; i++) {
      state.shiftPrefState[i] = ['OFF'];
    }
    if (targetInput) targetInput.value = 5;
    if (noteInput) noteInput.value = '';
    if (weekLabel) {
      weekLabel.innerHTML = `Tuần <strong>${targetWeekId}</strong> (${weekRangeLabel}) • Chọn ca rảnh`;
    }
    if (btnSubmit) {
      if (!canSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.style.opacity = '0.5';
        btnSubmit.style.cursor = 'not-allowed';
        btnSubmit.textContent = closedReasonText;
      } else {
        btnSubmit.disabled = false;
        btnSubmit.style.opacity = '1';
        btnSubmit.style.cursor = 'pointer';
        btnSubmit.textContent = `Gửi Đăng Ký Ca (${targetWeekId})`;
      }
    }
  }

  const daysOfWeek = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ Nhật'];
  daysContainer.innerHTML = '';

  if (!isOpen && userRole === 'STAFF') {
    const notice = document.createElement('div');
    notice.style.cssText = 'background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.3); border-radius:8px; padding:8px 10px; font-size:12px; color:var(--accent-amber); font-weight:600; margin-bottom:6px;';
    notice.innerHTML = state.currentRegWeekMode === 'current' 
      ? 'Tuần hiện tại đang diễn ra (đã khóa đăng ký ca). Bạn đang ở chế độ xem.' 
      : 'Cổng đăng ký ca đã chốt lúc 18:00 Chủ Nhật. Bạn đang ở chế độ xem trước.';
    daysContainer.appendChild(notice);
  } else if (myReg) {
    const notice = document.createElement('div');
    notice.style.cssText = 'background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); border-radius:8px; padding:8px 10px; font-size:12px; color:var(--accent-emerald); font-weight:600; margin-bottom:6px;';
    notice.innerHTML = 'Bạn đã nộp phiếu tuần này. Các lựa chọn đã được nạp lại để bạn xem hoặc sửa.';
    daysContainer.appendChild(notice);
  }

  const weekDaysDates = (state.currentNextWeekRosterData && Array.isArray(state.currentNextWeekRosterData.days) && state.currentNextWeekRosterData.days.length === 7)
    ? state.currentNextWeekRosterData.days
    : (state.currentRegWeekMode === 'current' ? curW.map(vnToISODate) : nextW.map(vnToISODate));
  daysOfWeek.forEach((dName, idx) => {
    const dDateStr = weekDaysDates[idx] ? ` (${weekDaysDates[idx].slice(8,10)}/${weekDaysDates[idx].slice(5,7)})` : '';
    const fullDayTitle = `${dName}${dDateStr}`;
    const row = document.createElement('div');
    row.style.cssText = 'background:var(--bg-card-sub); border:1px solid var(--border); border-radius:10px; padding:10px; display:flex; flex-direction:column; gap:8px;';
    row.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-size:13px; font-weight:700; color:var(--text-primary);">${fullDayTitle}</span>
        <span class="day-status-pill" style="font-size:12px; font-weight:700; padding:2px 8px; border-radius:12px; background:rgba(239, 68, 68, 0.12); color:var(--accent-coral);">Nghỉ (0 ca)</span>
      </div>
      <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:5px;">
        <button type="button" class="pref-btn" data-day="${idx}" data-val="MORNING" style="padding:7px 2px; font-size:12px; font-weight:600; border-radius:7px; border:1px solid var(--border); background:var(--bg-card); color:var(--text-secondary); cursor:pointer; transition:all 0.15s ease;">Sáng</button>
        <button type="button" class="pref-btn" data-day="${idx}" data-val="EVENING_17" style="padding:7px 2px; font-size:12px; font-weight:600; border-radius:7px; border:1px solid var(--border); background:var(--bg-card); color:var(--text-secondary); cursor:pointer; transition:all 0.15s ease;">Tối 17h</button>
        <button type="button" class="pref-btn" data-day="${idx}" data-val="EVENING_18" style="padding:7px 2px; font-size:12px; font-weight:600; border-radius:7px; border:1px solid var(--border); background:var(--bg-card); color:var(--text-secondary); cursor:pointer; transition:all 0.15s ease;">Tối 18h</button>
        <button type="button" class="pref-btn active" data-day="${idx}" data-val="OFF" style="padding:7px 2px; font-size:12px; font-weight:700; border-radius:7px; border:1px solid var(--accent-coral); background:var(--accent-coral-sub); color:var(--accent-coral); cursor:pointer; transition:all 0.15s ease;">Nghỉ</button>
      </div>
    `;

    const btnMorning = row.querySelector('[data-val="MORNING"]');
    const btn17 = row.querySelector('[data-val="EVENING_17"]');
    const btn18 = row.querySelector('[data-val="EVENING_18"]');
    const btnOff = row.querySelector('[data-val="OFF"]');
    const statusPill = row.querySelector('.day-status-pill');

    function syncRowUI() {
      const list = state.shiftPrefState[idx] || [];
      const hasMorning = list.includes('MORNING');
      const has17 = list.includes('EVENING_17');
      const has18 = list.includes('EVENING_18');
      const isOff = list.includes('OFF') || list.length === 0;

      const setBtn = (btn, active, isGreen) => {
        if (!btn) return;
        btn.classList.toggle('active', active);
        if (active) {
          btn.style.background = isGreen ? 'var(--accent-emerald-sub)' : 'var(--accent-coral-sub)';
          btn.style.color = isGreen ? 'var(--accent-emerald)' : 'var(--accent-coral)';
          btn.style.borderColor = isGreen ? 'var(--accent-emerald)' : 'var(--accent-coral)';
          btn.style.fontWeight = '700';
        } else {
          btn.style.background = 'var(--bg-card)';
          btn.style.color = 'var(--text-secondary)';
          btn.style.borderColor = 'var(--border)';
          btn.style.fontWeight = '600';
        }
      };

      setBtn(btnMorning, hasMorning, true);
      setBtn(btn17, has17, true);
      setBtn(btn18, has18, true);
      setBtn(btnOff, isOff, false);

      if (isOff) {
        statusPill.textContent = 'Nghỉ (0 ca)';
        statusPill.style.background = 'rgba(239, 68, 68, 0.12)';
        statusPill.style.color = 'var(--accent-coral)';
      } else {
        const parts = [];
        if (hasMorning) parts.push('Sáng');
        if (has17) parts.push('Tối 17h');
        if (has18) parts.push('Tối 18h');
        statusPill.textContent = `✓ ${parts.join(' + ')} (${parts.length} ca)`;
        statusPill.style.background = 'rgba(16, 185, 129, 0.15)';
        statusPill.style.color = 'var(--accent-emerald)';
      }

      updateTotalShiftCounter();
    }

    btnMorning.onclick = () => {
      let cur = (state.shiftPrefState[idx] || []).filter(x => x !== 'OFF');
      if (cur.includes('MORNING')) {
        cur = cur.filter(x => x !== 'MORNING');
      } else {
        cur.push('MORNING');
      }
      if (cur.length === 0) cur = ['OFF'];
      state.shiftPrefState[idx] = cur;
      syncRowUI();
    };

    btn17.onclick = () => {
      let cur = (state.shiftPrefState[idx] || []).filter(x => x !== 'OFF');
      if (cur.includes('EVENING_17')) {
        cur = cur.filter(x => x !== 'EVENING_17');
      } else {
        cur = cur.filter(x => x !== 'EVENING_18');
        cur.push('EVENING_17');
      }
      if (cur.length === 0) cur = ['OFF'];
      state.shiftPrefState[idx] = cur;
      syncRowUI();
    };

    btn18.onclick = () => {
      let cur = (state.shiftPrefState[idx] || []).filter(x => x !== 'OFF');
      if (cur.includes('EVENING_18')) {
        cur = cur.filter(x => x !== 'EVENING_18');
      } else {
        cur = cur.filter(x => x !== 'EVENING_17');
        cur.push('EVENING_18');
      }
      if (cur.length === 0) cur = ['OFF'];
      state.shiftPrefState[idx] = cur;
      syncRowUI();
    };

    btnOff.onclick = () => {
      state.shiftPrefState[idx] = ['OFF'];
      syncRowUI();
    };

    daysContainer.appendChild(row);
    syncRowUI();
  });

  function updateTotalShiftCounter() {
    let total = 0;
    for (let i = 0; i < 7; i++) {
      const list = state.shiftPrefState[i] || [];
      total += list.filter(x => x !== 'OFF').length;
    }
    const badge = document.getElementById('shiftRegTotalCountBadge');
    if (badge) badge.textContent = `Đã chọn: ${total} ca`;
    const targetInput = document.getElementById('shiftRegTargetCount');
    if (targetInput && (!targetInput.value || parseInt(targetInput.value) === 0)) {
      targetInput.value = Math.max(3, Math.min(10, total || 5));
    }
  }

  updateTotalShiftCounter();

  modal.classList.add('active');
  updateSheetScrollLock();
}

export async function submitShiftRegistration() {
  const btn = document.getElementById('btnSubmitShiftRegistration');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang gửi đăng ký...';
  }

  const targetCount = parseInt(document.getElementById('shiftRegTargetCount').value) || 5;
  const note = (document.getElementById('shiftRegNote').value || '').trim();
  const token = localStorage.getItem('vnaigc_jwt');

  try {
    const targetWId = (typeof state.currentNextWeekRosterData !== 'undefined' && state.currentNextWeekRosterData && state.currentNextWeekRosterData.week && state.currentNextWeekRosterData.week.week_id) 
      ? state.currentNextWeekRosterData.week.week_id 
      : (state.currentRegWeekMode === 'next' ? (state.currentNextWeekRosterData?.next_week_id || 'next') : (state.currentNextWeekRosterData?.active_week_id || 'current'));

    const res = await fetch('/api/v1/cc/roster/register', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        week_id: targetWId,
        preferences: state.shiftPrefState,
        target_shifts: targetCount,
        note: note
      })
    });

    if (res.ok) {
      const data = await res.json();
      showToast(data.message || `Đã gửi đăng ký ca (${targetWId}) thành công!`, 'success');
      document.getElementById('shiftRegSheet').classList.remove('active');
      updateSheetScrollLock();
      await updateStaffRegStatus(state.currentRegWeekMode);
      if (typeof loadAndRenderManagerRegProgress === 'function') {
        loadAndRenderManagerRegProgress(state.mgrRegWeekMode);
      }
    } else {
      let errData = null;
      try { errData = await res.json(); } catch(e) {}
      const msg = safeErrorDetail(errData, 'Lỗi gửi đăng ký ca!');
      showToast(msg, 'error');
    }
  } catch (e) {
    showToast('Lỗi kết nối máy chủ!', 'error');
  } finally {
    if (btn) {
      const regStatus = checkIsShiftRegistrationOpen(state.currentRegWeekMode);
      const userRole = localStorage.getItem('vnaigc_role') || 'STAFF';
      const canSubmit = regStatus.isOpen || userRole === 'ADMIN' || userRole === 'MANAGER';
      const closedReasonText = state.currentRegWeekMode === 'current' ? 'Tuần Này Đã Chốt (Chỉ Xem Trước)' : 'Cổng Đã Đóng 18:00 CN (Chỉ Xem Trước)';
      btn.disabled = !canSubmit;
      btn.style.opacity = canSubmit ? '1' : '0.5';
      btn.textContent = canSubmit ? (state.currentStaffRegState.isRegistered ? 'Cập Nhật Phiếu Đăng Ký' : 'Gửi Đăng Ký Ca') : closedReasonText;
    }
  }
}

state.mgrRegWeekMode = 'current';

export async function loadAndRenderManagerRegProgress(weekMode = null) {
  if (weekMode) state.mgrRegWeekMode = weekMode;
  const userRole = localStorage.getItem('vnaigc_role') || 'STAFF';
  const card = document.getElementById('managerRosterRegCard');
  if (!card) return;

  if (userRole === 'STAFF') {
    card.style.display = 'none';
    return;
  }
  card.style.display = 'block';

  const btnToggleMgr = document.getElementById('btnToggleMgrReg');
  const regBody = document.getElementById('managerRosterRegBody');
  const iconToggle = document.getElementById('iconToggleMgrReg');
  if (btnToggleMgr && regBody && !btnToggleMgr.dataset.bound) {
    btnToggleMgr.dataset.bound = 'true';
    btnToggleMgr.addEventListener('click', () => {
      const isHidden = (regBody.style.display === 'none');
      regBody.style.display = isHidden ? 'block' : 'none';
      if (iconToggle) iconToggle.innerHTML = isHidden ? 'Thu gọn <iconify-icon icon="solar:alt-arrow-up-linear" width="12" height="12" style="vertical-align:middle;"></iconify-icon>' : 'Chi tiết <iconify-icon icon="solar:alt-arrow-down-linear" width="12" height="12" style="vertical-align:middle;"></iconify-icon>';
    });
  }

  const btnMgrCurrent = document.getElementById('btnMgrRegWeekCurrent');
  const btnMgrNext = document.getElementById('btnMgrRegWeekNext');
  if (btnMgrCurrent && btnMgrNext) {
    if (state.mgrRegWeekMode === 'current') {
      btnMgrCurrent.style.background = 'var(--accent-emerald-sub)';
      btnMgrCurrent.style.color = 'var(--accent-emerald)';
      btnMgrCurrent.style.borderColor = 'var(--accent-emerald)';
      btnMgrCurrent.style.fontWeight = '700';

      btnMgrNext.style.background = 'var(--bg-card)';
      btnMgrNext.style.color = 'var(--text-secondary)';
      btnMgrNext.style.borderColor = 'var(--border)';
      btnMgrNext.style.fontWeight = '600';
    } else {
      btnMgrNext.style.background = 'var(--accent-emerald-sub)';
      btnMgrNext.style.color = 'var(--accent-emerald)';
      btnMgrNext.style.borderColor = 'var(--accent-emerald)';
      btnMgrNext.style.fontWeight = '700';

      btnMgrCurrent.style.background = 'var(--bg-card)';
      btnMgrCurrent.style.color = 'var(--text-secondary)';
      btnMgrCurrent.style.borderColor = 'var(--border)';
      btnMgrCurrent.style.fontWeight = '600';
    }
  }

  const targetWeekEl = document.getElementById('managerRosterRegTargetWeek');
  const ratioBadge = document.getElementById('managerRosterRegRatioBadge');
  const listEl = document.getElementById('managerRosterRegList');
  const btnCopy = document.getElementById('btnCopyUnregisteredStaff');

  try {
    const token = localStorage.getItem('vnaigc_jwt');
    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
    const res = await fetch(`/api/v1/cc/roster/week?week_id=${state.mgrRegWeekMode}`, { headers });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.success || !data.week) return;

    state.currentNextWeekRosterData = data;
    const week = data.week;
    const targetWeekId = week.week_id || (state.mgrRegWeekMode === 'current' ? data.active_week_id : data.next_week_id);
    const registrations = week.registrations || {};
    const staffDirectory = data.staff_directory || {};

    if (targetWeekEl) {
      targetWeekEl.textContent = `Tuần: ${targetWeekId} (${week.start_date || ''} - ${week.end_date || ''})`;
    }

    if (btnMgrCurrent && data.active_week_id) {
      const activeWNum = data.active_week_id.includes('-') ? data.active_week_id.split('-')[1] : data.active_week_id;
      btnMgrCurrent.textContent = `Tuần Này (${activeWNum})`;
    }
    if (btnMgrNext && data.next_week_id) {
      const nextWNum = data.next_week_id.includes('-') ? data.next_week_id.split('-')[1] : data.next_week_id;
      btnMgrNext.textContent = `Tuần Sau (${nextWNum})`;
    }

    const staffUsernames = Object.keys(staffDirectory).filter(u => {
      const acc = staffDirectory[u];
      return acc.status === 'ACTIVE' && acc.role === 'STAFF';
    });

    const registeredUsers = [];
    const unregisteredUsers = [];

    staffUsernames.forEach(u => {
      if (registrations[u]) {
        registeredUsers.push({ username: u, ...registrations[u], info: staffDirectory[u] });
      } else {
        unregisteredUsers.push({ username: u, info: staffDirectory[u] });
      }
    });

    const totalStaff = staffUsernames.length;
    const regCount = registeredUsers.length;

    if (ratioBadge) {
      ratioBadge.textContent = `${regCount}/${totalStaff} nhân sự đã nộp`;
      ratioBadge.style.background = regCount === totalStaff ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)';
      ratioBadge.style.color = regCount === totalStaff ? 'var(--accent-emerald)' : 'var(--accent-amber)';
    }

    if (listEl) {
      let html = '';
      
      registeredUsers.forEach(item => {
        const fullName = (item.info && item.info.full_name) || item.username;
        const role = (item.info && item.info.role) || 'STAFF';
        const pos = (item.info && item.info.position) || '';
        const roleName = role === 'MANAGER' ? 'Quản lý' : ((pos === 'BARISTA' || getStaffRole(fullName) === 'Pha chế') ? 'Pha chế' : 'Phục vụ');
        
        let shiftCount = 0;
        const prefs = item.preferences || {};
        Object.keys(prefs).forEach(k => {
          const v = prefs[k];
          if (Array.isArray(v)) {
            shiftCount += v.filter(s => s !== 'OFF').length;
          } else if (typeof v === 'string' && v !== 'OFF') {
            shiftCount += 1;
          }
        });

        html += `
          <div class="reg-staff-row" data-uname="${item.username}" style="display:flex; justify-content:space-between; align-items:center; background:var(--bg-card-sub); border:1px solid rgba(16, 185, 129, 0.3); border-radius:8px; padding:7px 10px; cursor:pointer; transition:all 0.15s ease;">
            <div>
              <span style="font-size:13px; font-weight:700; color:var(--text-primary);">${fullName}</span>
              <span style="font-size:12px; color:var(--text-muted); margin-left:4px;">(${roleName})</span>
              <div style="font-size:12px; color:var(--text-secondary); margin-top:1px;">Nộp: ${item.registered_at || 'Gần đây'} • Nguyện vọng: ${item.target_shifts || shiftCount} ca</div>
            </div>
            <div style="text-align:right;">
              <span style="font-size:12px; font-weight:700; padding:2px 7px; border-radius:10px; background:rgba(16, 185, 129, 0.15); color:var(--accent-emerald);">Đã nộp (${shiftCount} ca) ❯</span>
            </div>
          </div>
        `;
      });

      unregisteredUsers.forEach(item => {
        const fullName = (item.info && item.info.full_name) || item.username;
        const role = (item.info && item.info.role) || 'STAFF';
        const pos = (item.info && item.info.position) || '';
        const roleName = role === 'MANAGER' ? 'Quản lý' : ((pos === 'BARISTA' || getStaffRole(fullName) === 'Pha chế') ? 'Pha chế' : 'Phục vụ');

        html += `
          <div style="display:flex; justify-content:space-between; align-items:center; background:var(--bg-card-sub); border:1px solid var(--border); border-radius:8px; padding:7px 10px; opacity:0.85;">
            <div>
              <span style="font-size:13px; font-weight:600; color:var(--text-secondary);">${fullName}</span>
              <span style="font-size:12px; color:var(--text-muted); margin-left:4px;">(${roleName})</span>
            </div>
            <span style="font-size:12px; font-weight:700; padding:2px 7px; border-radius:10px; background:rgba(239, 68, 68, 0.12); color:var(--accent-coral);">Chưa nộp</span>
          </div>
        `;
      });

      listEl.innerHTML = html;

      listEl.querySelectorAll('.reg-staff-row').forEach(row => {
        row.addEventListener('click', () => {
          const uname = row.getAttribute('data-uname');
          if (uname) openShiftRegDetailModal(uname);
        });
      });
    }

    if (btnCopy) {
      if (unregisteredUsers.length > 0) {
        btnCopy.style.display = 'block';
        btnCopy.onclick = () => {
          const unregNames = unregisteredUsers.map(u => (u.info && u.info.full_name) || u.username);
          const storeName = window.vnaigc_store_name || 'FnBOps';
          const msg = `[${storeName.toUpperCase()} - NHẮC LỊCH CA] Các bạn sau chưa nộp phiếu đăng ký ca tuần mới (${targetWeekId}):\n- ${unregNames.join('\n- ')}\nCác bạn vui lòng truy cập ${window.location.origin} để nộp phiếu nhé!`;
          copyTextToClipboard(msg, 'Đã chép danh sách chưa nộp để gửi Zalo!');
        };
      } else {
        btnCopy.style.display = 'none';
      }
    }
  } catch (e) {
    console.error('Lỗi tải tiến độ đăng ký ca:', e);
  }
}

export function openShiftRegDetailModal(uname) {
  if (!state.currentNextWeekRosterData) return;
  const reg = state.currentNextWeekRosterData.week.registrations[uname];
  const staffInfo = state.currentNextWeekRosterData.staff_directory[uname] || {};
  if (!reg) return;

  const modal = document.getElementById('shiftRegDetailSheet');
  if (!modal) return;

  document.getElementById('shiftRegDetailStaffName').textContent = `${staffInfo.full_name || uname} • Nguyện vọng ${reg.target_shifts || 5} ca`;
  document.getElementById('shiftRegDetailTime').textContent = `Thời gian gửi: ${reg.registered_at || '--'}`;
  document.getElementById('shiftRegDetailNoteText').textContent = reg.note || 'Không có ghi chú';

  const daysOfWeek = ['Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7', 'Chủ Nhật'];
  const shiftLabels = {
    'MORNING': 'Ca Sáng (06:00 - 11:00)',
    'EVENING_17': 'Ca Tối 17h (17:00 - 23:00)',
    'EVENING_18': 'Ca Tối 18h (18:00 - 23:00)',
    'OFF': 'Nghỉ'
  };

  const container = document.getElementById('shiftRegDetailContent');
  container.innerHTML = '';

  const prefs = reg.preferences || {};
  daysOfWeek.forEach((dName, idx) => {
    const p = prefs[idx] || prefs[String(idx)] || ['OFF'];
    const pList = Array.isArray(p) ? p : [p];
    const isOff = pList.includes('OFF') || pList.length === 0;

    const row = document.createElement('div');
    row.style.cssText = 'background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:8px 10px; display:flex; justify-content:space-between; align-items:center;';
    
    let contentHtml = '';
    if (isOff) {
      contentHtml = '<span style="font-size:12px; color:var(--text-muted); font-weight:600;">Nghỉ (0 ca)</span>';
    } else {
      contentHtml = pList.map(s => {
        const lbl = shiftLabels[s] || s;
        return `<span style="font-size:12px; font-weight:700; padding:2px 6px; border-radius:6px; background:rgba(16,185,129,0.15); color:var(--accent-emerald); margin-left:3px;">${lbl}</span>`;
      }).join('');
    }

    row.innerHTML = `
      <span style="font-size:13px; font-weight:700; color:var(--text-primary);">${dName}</span>
      <div>${contentHtml}</div>
    `;
    container.appendChild(row);
  });

  modal.classList.add('active');
  updateSheetScrollLock();
}

export function openAutoRosterConfirmModal() {
  const modal = document.getElementById('autoRosterConfirmSheet');
  if (modal) {
    const isNext = (state.currentWeekPage === -1);
    const activeInfo = state.currentNextWeekRosterData || {};
    const weekLabel = isNext 
      ? (activeInfo.next_week_id ? `Tuần Tới (${activeInfo.next_week_id})` : 'Tuần Tới')
      : (activeInfo.active_week_id ? `Tuần Này (${activeInfo.active_week_id})` : 'Tuần Này');

    const msgEl = modal.querySelector('#autoRosterConfirmMsg') || modal.querySelector('p');
    if (msgEl) {
      msgEl.innerHTML = `Thao tác này sẽ tự động phân ca nhân sự và <strong>GHI ĐÈ lịch trực của ${weekLabel}</strong> dựa trên phiếu đăng ký ca của nhân viên. Bạn có chắc chắn muốn tiếp tục?`;
    }
    const btnConfirm = document.getElementById('btnConfirmAutoRoster');
    if (btnConfirm) {
      btnConfirm.textContent = `Xác Nhận Xếp Ca ${weekLabel}`;
    }
    modal.classList.add('active');
    updateSheetScrollLock();
  }
}

export function closeAutoRosterConfirmModal() {
  const modal = document.getElementById('autoRosterConfirmSheet');
  if (modal) {
    modal.classList.remove('active');
    updateSheetScrollLock();
  }
}

export async function executeRosterAutoFill() {
  closeAutoRosterConfirmModal();
  const btn = document.getElementById('btnAutoRoster') || document.getElementById('btnRosterAutoFill');
  const btnConfirm = document.getElementById('btnConfirmAutoRoster');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang xếp ca...';
  }
  if (btnConfirm) {
    btnConfirm.disabled = true;
    btnConfirm.textContent = 'Đang xếp ca...';
  }
  const token = localStorage.getItem('vnaigc_jwt');
  const targetWeek = (state.currentWeekPage === -1) ? 'next' : 'current';
  try {
    const res = await fetch('/api/v1/cc/roster/auto-fill', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ week_id: targetWeek })
    });
    if (res.ok) {
      const d = await res.json().catch(() => ({}));
      showToast(d.message || 'Tự động xếp ca thành công!', 'success');
      state.currentRosterWeeksCache = {};
      await fetchRosterWeekData('current');
      await fetchRosterWeekData('next');
      renderTabRoster();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(safeErrorDetail(err, 'Lỗi xếp ca!'), 'error');
    }
  } catch (e) {
    showToast(safeErrorDetail(e, 'Lỗi kết nối máy chủ!'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = (state.currentWeekPage === -1) ? '⚡ Xếp Ca Tuần Tới' : '⚡ Xếp Ca Tuần Này';
    }
    if (btnConfirm) {
      btnConfirm.disabled = false;
      btnConfirm.textContent = 'Xác Nhận Ghi Đè & Xếp Ca';
    }
  }
}

export function handleRosterAutoFill() {
  openAutoRosterConfirmModal();
}

export async function handleClonePreviousWeek() {
  const isNext = (state.currentWeekPage === -1);
  const targetWeek = isNext ? 'next' : 'current';
  const targetLabel = isNext ? 'Tuần Tới' : 'Tuần Này';
  const sourceLabel = isNext ? 'Tuần Này' : 'Tuần Trước';

  const ok = await showConfirmDialog({
    title: `Sao Chép Lịch Ca Sang ${targetLabel}`,
    message: `Bạn có muốn sao chép toàn bộ phân bổ ca trực từ ${sourceLabel} sang ${targetLabel} không? Thao tác này sẽ ghi đè lịch trực hiện tại của ${targetLabel}.`,
    confirmText: 'Sao Chép & Ghi Đè',
    cancelText: 'Hủy',
    type: 'warning'
  });
  if (!ok) return;

  const btn = document.getElementById('btnClonePrevWeek');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang sao chép...';
  }
  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/roster/clone-previous-week', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ target_week_id: targetWeek })
    });
    if (res.ok) {
      const d = await res.json().catch(() => ({}));
      showToast(d.message || `Đã sao chép lịch ca sang ${targetLabel} thành công!`, 'success');
      state.currentRosterWeeksCache = {};
      await fetchRosterWeekData('current');
      await fetchRosterWeekData('next');
      renderTabRoster();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(safeErrorDetail(err, 'Lỗi sao chép lịch ca!'), 'error');
    }
  } catch (e) {
    showToast(safeErrorDetail(e, 'Lỗi kết nối máy chủ!'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = isNext ? '📋 Sao Chép Tuần Này' : '📋 Sao Chép Tuần Trước';
    }
  }
}

export async function handleRosterPublish() {
  const targetWeek = (state.currentWeekPage === -1) ? 'next' : 'current';
  const ok = await showConfirmDialog({
    title: 'Công Bố Lịch Ca Lên Telegram',
    message: `Bạn có chắc chắn muốn chốt và công bố lịch ca tuần ${targetWeek === 'next' ? 'mới' : 'này'} cho toàn bộ nhân sự quán qua Telegram?`,
    confirmText: 'Chốt & Công Bố',
    cancelText: 'Xem Lại',
    type: 'telegram',
    icon: 'solar:plain-bold'
  });
  if (!ok) return;
  const btn = document.getElementById('btnRosterPublish');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang công bố...';
  }
  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/roster/publish', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ week_id: targetWeek })
    });
    if (res.ok) {
      const d = await res.json().catch(() => ({}));
      showToast(d.message || 'Đã công bố lịch ca tuần lên Telegram thành công!', 'success');
      state.currentRosterWeeksCache = {};
      await fetchRosterWeekData('current');
      await fetchRosterWeekData('next');
      renderTabRoster();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(safeErrorDetail(err, 'Lỗi công bố lịch!'), 'error');
    }
  } catch (e) {
    showToast(safeErrorDetail(e, 'Lỗi kết nối máy chủ!'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Chốt Lịch & Công Bố';
    }
  }
}

state.currentSwapContext = null;
state.currentEditSlotContext = null;

export function openPeerSwapModal(weekId, isoDate, shiftPeriod, slotType, dayName, vnDate, shiftName) {
  const curRole = (localStorage.getItem('vnaigc_role') || 'STAFF').toUpperCase();
  const isSwapAllowed = !(state.currentNextWeekRosterData && state.currentNextWeekRosterData.peer_shift_swap_allowed === false);
  if (!isSwapAllowed && curRole !== 'ADMIN' && curRole !== 'MANAGER') {
    showToast('Tính năng tự đổi ca đang tạm thời bị Quản lý khóa.', 'error');
    return;
  }
  state.currentSwapContext = { weekId, isoDate, shiftPeriod, slotType };
  const modal = document.getElementById('peerSwapSheet');
  if (!modal) return;

  const infoEl = document.getElementById('peerSwapShiftInfo');
  if (infoEl) {
    infoEl.textContent = `${dayName} • ${vnDate} • ${shiftName}`;
  }

  const reasonEl = document.getElementById('peerSwapReason');
  if (reasonEl) reasonEl.value = '';

  const selectEl = document.getElementById('peerSwapTargetUser');
  if (selectEl) {
    selectEl.innerHTML = '<option value="">-- Chọn nhân sự nhận ca --</option>';
    const curUname = (localStorage.getItem('vnaigc_username') || '').toLowerCase().trim();
    const staffDir = (state.currentNextWeekRosterData && state.currentNextWeekRosterData.staff_directory) ||
                     (state.currentRosterWeeksCache['current'] && state.currentRosterWeeksCache['current'].staff_directory) ||
                     (state.currentRosterWeeksCache['next'] && state.currentRosterWeeksCache['next'].staff_directory) || {};

    const staffList = Object.entries(staffDir).map(([u, s]) => ({ username: u, ...s }));
    staffList.sort((a, b) => (a.full_name || a.username).localeCompare(b.full_name || b.username));

    staffList.forEach(s => {
      if (s.username.toLowerCase() === curUname) return;
      if (s.status === 'INACTIVE') return;
      const gTag = s.gender === 'NU' ? 'Nữ' : 'Nam';
      const pos = s.position || 'Nhân viên';
      const opt = document.createElement('option');
      opt.value = s.username;
      opt.textContent = `${s.full_name || s.username} (${gTag} • ${pos})`;
      selectEl.appendChild(opt);
    });
  }

  modal.classList.add('active');
  updateSheetScrollLock();
}

export function closePeerSwapModal() {
  const modal = document.getElementById('peerSwapSheet');
  if (modal) modal.classList.remove('active');
  updateSheetScrollLock();
}

/**
 * ============================================================================
 * TASK 2.2: TEAMMATES ROSTER & 1-TOUCH SHIFT SWAP (KHAY ĐỒNG ĐỘI & ĐỔI CA 1-CHẠM)
 * ============================================================================
 */

export function getInitialsAvatar(name) {
  if (!name) return 'OP';
  const clean = removeAccents(String(name).trim().replace(/\(.*?\)/g, '')).trim();
  const words = clean.split(/\s+/).filter(Boolean);
  if (words.length === 0) return 'OP';
  if (words.length === 1) {
    return words[0].substring(0, Math.min(2, words[0].length)).toUpperCase();
  }
  const first = words[0][0];
  const last = words[words.length - 1][0];
  return (first + last).toUpperCase();
}

export function closeShiftDetailModal() {
  const modal = document.getElementById('shiftDetailSheet');
  if (modal) {
    modal.classList.remove('active');
  }
  updateSheetScrollLock();
}

export function handleRequestSwapShift(targetStaffName, shiftDate, shiftKey) {
  const myName = localStorage.getItem('vnaigc_name') || localStorage.getItem('vnaigc_username') || 'mình';
  const storeName = (typeof localStorage !== 'undefined' ? localStorage.getItem('vnaigc_store_name') : null) || 'FnBOps';
  const message = `[YÊU CẦU ĐỔI CA - ${storeName}] @${targetStaffName} ơi, ca ${shiftKey} ngày ${shiftDate} bạn có thể đổi ca hỗ trợ mình (@${myName}) được không? Cảm ơn bạn nhiều!`;

  copyTextToClipboard(message, 'Đã sao chép tin nhắn xin đổi ca! Hãy gửi cho bạn ấy qua Zalo.');

  const swapRequestRecord = {
    targetStaffName,
    shiftDate,
    shiftKey,
    requesterName: myName,
    message,
    timestamp: new Date().toISOString()
  };

  state.lastSwapRequest = swapRequestRecord;
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('fnbop_last_swap_request', JSON.stringify(swapRequestRecord));
    }
  } catch (e) {}

  return swapRequestRecord;
}

export function openShiftDetailModal(dayKey, shiftKey) {
  const modal = document.getElementById('shiftDetailSheet');
  if (!modal) return;

  const titleEl = document.getElementById('shiftDetailTitle');
  const timeEl = document.getElementById('shiftDetailTime');
  const teammatesContainer = document.getElementById('teammatesListContainer');
  const offDutyContainer = document.getElementById('offDutyListContainer');
  const teammatesBadge = document.getElementById('teammatesCountBadge');
  const offDutyBadge = document.getElementById('offDutyCountBadge');

  // 1. Chuẩn hóa ngày (ISO và VN)
  const isVN = typeof dayKey === 'string' && dayKey.includes('/');
  const vnDate = isVN ? dayKey : isoToVNDate(dayKey);
  const isoDate = isVN ? vnToISODate(dayKey) : dayKey;
  const dayOfWeek = getDayOfWeekVN(vnDate);

  // 2. Chuẩn hóa ca (morning / evening)
  const normShift = String(shiftKey || '').toLowerCase();
  const isMorning = normShift.includes('morning') || normShift.includes('sáng');
  const period = isMorning ? 'morning' : 'evening';
  const shiftTitle = isMorning ? 'Ca Sáng' : 'Ca Tối';
  let defaultShiftHours = isMorning ? '06:00 - 11:30' : '17:00 - 23:00';

  // 3. User info
  const myUname = (localStorage.getItem('vnaigc_username') || '').toLowerCase().trim();
  const myFullName = (localStorage.getItem('vnaigc_name') || '').trim();
  const canonMyName = getCanonicalStaffName(myFullName || myUname);

  // 4. Lấy dữ liệu phân ca
  let targetWeekData = state.currentRosterWeekData || null;
  if (!targetWeekData && state.currentRosterWeeksCache) {
    for (const key of ['current', 'next', ...Object.keys(state.currentRosterWeeksCache)]) {
      const c = state.currentRosterWeeksCache[key];
      if (c && c.week && c.week.shifts && c.week.shifts[isoDate]) {
        targetWeekData = c;
        break;
      }
    }
  }
  if (!targetWeekData && state.currentNextWeekRosterData) {
    if (state.currentNextWeekRosterData.week && state.currentNextWeekRosterData.week.shifts && state.currentNextWeekRosterData.week.shifts[isoDate]) {
      targetWeekData = state.currentNextWeekRosterData;
    }
  }

  const staffDirectory = (targetWeekData && targetWeekData.staff_directory) || {};
  const getDisplayName = (u) => {
    if (!u) return '';
    if (staffDirectory[u] && staffDirectory[u].full_name) return staffDirectory[u].full_name;
    return u;
  };

  const dayShifts = targetWeekData && targetWeekData.week && targetWeekData.week.shifts
    ? targetWeekData.week.shifts[isoDate]
    : null;

  const workingTodaySet = new Set();
  const teammatesInThisShift = [];

  if (dayShifts) {
    const m = dayShifts.morning || {};
    const ev = dayShifts.evening || {};

    if (isMorning && m.time) defaultShiftHours = m.time;
    if (!isMorning && ev.time) defaultShiftHours = ev.time;

    // Ghi nhận tất cả những ai làm trong ngày
    const mStaff = [m.manager, m.barista, ...(Array.isArray(m.service) ? m.service : [])];
    mStaff.forEach(u => {
      if (u) {
        workingTodaySet.add(u.toLowerCase());
        const dn = getDisplayName(u);
        if (dn) {
          workingTodaySet.add(dn.toLowerCase());
          workingTodaySet.add(getCanonicalStaffName(dn));
        }
      }
    });

    const evStaff = [ev.manager, ev.barista, ev.service_17, ev.service_18, ...(Array.isArray(ev.service) ? ev.service : [])];
    evStaff.forEach(u => {
      if (u) {
        workingTodaySet.add(u.toLowerCase());
        const dn = getDisplayName(u);
        if (dn) {
          workingTodaySet.add(dn.toLowerCase());
          workingTodaySet.add(getCanonicalStaffName(dn));
        }
      }
    });

    // Lấy nhân sự của ca được chọn
    const curPeriodData = isMorning ? m : ev;
    const addTeammate = (username, fallbackRole, slotLabel) => {
      if (!username) return;
      const uLower = username.toLowerCase();
      const dispName = getDisplayName(username);
      const pos = (staffDirectory[username]?.position || '').toUpperCase();
      let role = 'Phục Vụ';
      if (fallbackRole === 'Quản Lý' || pos.includes('MANAGE') || pos.includes('QUẢN')) {
        role = 'Quản Lý';
      } else if (fallbackRole === 'Pha Chế' || pos.includes('BAR') || pos.includes('PHA')) {
        role = 'Pha Chế';
      } else {
        role = 'Phục Vụ';
      }

      const isMe = (uLower === myUname || getCanonicalStaffName(dispName) === canonMyName);
      teammatesInThisShift.push({
        username: username,
        name: dispName,
        role: role,
        slotLabel: slotLabel,
        isMe: isMe
      });
    };

    if (curPeriodData.manager) addTeammate(curPeriodData.manager, 'Quản Lý', 'Quản lý ca');
    if (curPeriodData.barista) addTeammate(curPeriodData.barista, 'Pha Chế', 'Pha chế chính');
    if (isMorning) {
      if (Array.isArray(curPeriodData.service)) {
        curPeriodData.service.forEach((u, idx) => addTeammate(u, 'Phục Vụ', `Phục vụ ${idx + 1}`));
      }
    } else {
      if (curPeriodData.service_17) addTeammate(curPeriodData.service_17, 'Phục Vụ', 'Phục vụ (17h)');
      if (curPeriodData.service_18) addTeammate(curPeriodData.service_18, 'Phục Vụ', 'Phục vụ (18h)');
      if (Array.isArray(curPeriodData.service)) {
        curPeriodData.service.forEach((u, idx) => addTeammate(u, 'Phục Vụ', `Phục vụ ${idx + 1}`));
      }
    }
  } else {
    // Fallback: Dùng dữ liệu records
    const allRecordsToday = (state.records || []).filter(r => r.date === vnDate);
    allRecordsToday.forEach(r => {
      const rName = r.name || '';
      workingTodaySet.add(rName.toLowerCase());
      workingTodaySet.add(getCanonicalStaffName(rName));
    });

    const shiftRecords = allRecordsToday.filter(r => {
      const sNorm = (r.shift || '').toLowerCase();
      return isMorning
        ? (sNorm.includes('sáng') || sNorm.includes('morning'))
        : (sNorm.includes('tối') || sNorm.includes('evening') || sNorm.includes('chiều'));
    });

    shiftRecords.forEach(r => {
      const rRole = r.role || getStaffRole(r.name);
      let role = 'Phục Vụ';
      if (rRole === 'Quản lý' || rRole === 'Quản Lý') role = 'Quản Lý';
      else if (rRole === 'Pha chế' || rRole === 'Pha Chế') role = 'Pha Chế';
      else role = 'Phục Vụ';

      if (r.in && r.out) defaultShiftHours = `${r.in} - ${r.out}`;

      const isMe = (r.name.toLowerCase() === myUname || getCanonicalStaffName(r.name) === canonMyName);
      teammatesInThisShift.push({
        username: r.name,
        name: r.name,
        role: role,
        slotLabel: role,
        isMe: isMe
      });
    });
  }

  // 5. Tìm danh sách nhân sự toàn quán và lọc ai đang OFF hôm nay
  const allStaffMap = new Map();

  const hasStaffDirectory = Object.keys(staffDirectory).length > 0;
  if (hasStaffDirectory) {
    Object.entries(staffDirectory).forEach(([u, info]) => {
      if (info.status === 'INACTIVE') return;
      const name = info.full_name || u;
      const cName = getCanonicalStaffName(name);
      let role = 'Phục Vụ';
      const pos = (info.position || '').toUpperCase();
      if (pos.includes('MANAGE') || pos.includes('QUẢN')) role = 'Quản Lý';
      else if (pos.includes('BAR') || pos.includes('PHA')) role = 'Pha Chế';
      allStaffMap.set(cName, { username: u, name: name, role: role });
    });
  } else if (state.employeesMap && Object.keys(state.employeesMap).length > 0) {
    // Fallback 1: Dùng employeesMap nếu có
    Object.keys(state.employeesMap).forEach(name => {
      const cName = getCanonicalStaffName(name);
      if (!allStaffMap.has(cName)) {
        allStaffMap.set(cName, { username: name, name: name, role: getStaffRole(name) });
      }
    });
  } else {
    // Fallback 2: Dùng POLICY.ROLE_MAP nếu chưa load được data nhân sự
    Object.keys(POLICY.ROLE_MAP).forEach(name => {
      const role = POLICY.ROLE_MAP[name];
      if (role === 'Giữ Xe') return;
      const cName = getCanonicalStaffName(name);
      if (!allStaffMap.has(cName)) {
        allStaffMap.set(cName, { username: name, name: name, role: role });
      }
    });
  }

  // Lọc ra danh sách OFF
  const offDutyList = [];
  allStaffMap.forEach((staff, cName) => {
    const uLower = (staff.username || '').toLowerCase();
    const nLower = (staff.name || '').toLowerCase();
    if (uLower === myUname || nLower === myUname || cName === canonMyName) return;
    if (workingTodaySet.has(uLower) || workingTodaySet.has(nLower) || workingTodaySet.has(cName)) return;

    offDutyList.push(staff);
  });

  offDutyList.sort((a, b) => a.name.localeCompare(b.name, 'vi'));

  // Cập nhật Header
  if (titleEl) titleEl.textContent = `Chi Tiết ${shiftTitle}`;
  if (timeEl) timeEl.textContent = `${dayOfWeek}, ${vnDate} • ${defaultShiftHours}`;

  // Render Section 1: ĐỒNG ĐỘI LÀM CÙNG CA
  if (teammatesBadge) teammatesBadge.textContent = `${teammatesInThisShift.length} người`;
  if (teammatesContainer) {
    if (teammatesInThisShift.length === 0) {
      teammatesContainer.innerHTML = `
        <div class="teammate-empty-state">
          Chưa có dữ liệu đồng đội làm cùng ca này.
        </div>
      `;
    } else {
      teammatesContainer.innerHTML = teammatesInThisShift.map(t => {
        const initials = getInitialsAvatar(t.name);
        let roleClass = 'role-service';
        if (t.role === 'Pha Chế' || t.role === 'Pha chế') roleClass = 'role-barista';
        else if (t.role === 'Quản Lý' || t.role === 'Quản lý') roleClass = 'role-manager';

        return `
          <div class="teammate-row">
            <div class="teammate-info">
              <div class="teammate-avatar">${escapeHtml(initials)}</div>
              <div class="teammate-details">
                <div class="teammate-name">
                  ${escapeHtml(t.name)}
                  ${t.isMe ? '<span class="teammate-me-badge">Tôi</span>' : ''}
                </div>
                <div class="teammate-sub">
                  <span>${escapeHtml(t.slotLabel || t.role)}</span>
                </div>
              </div>
            </div>
            <span class="teammate-role-badge ${roleClass}">
              ${escapeHtml(t.role)}
            </span>
          </div>
        `;
      }).join('');
    }
  }

  // Render Section 2: NHÂN SỰ ĐANG NGHỈ (OFF) NGÀY HÔM NAY
  if (offDutyBadge) offDutyBadge.textContent = `${offDutyList.length} người`;
  if (offDutyContainer) {
    if (offDutyList.length === 0) {
      offDutyContainer.innerHTML = `
        <div class="teammate-empty-state">
          Tất cả đồng nghiệp đều đã có ca trực trong ngày ${escapeHtml(vnDate)}.
        </div>
      `;
    } else {
      offDutyContainer.innerHTML = offDutyList.map(staff => {
        const initials = getInitialsAvatar(staff.name);
        let roleClass = 'role-service';
        if (staff.role === 'Pha Chế' || staff.role === 'Pha chế') roleClass = 'role-barista';
        else if (staff.role === 'Quản Lý' || staff.role === 'Quản lý') roleClass = 'role-manager';

        return `
          <div class="teammate-row off-duty-row">
            <div class="teammate-info">
              <div class="teammate-avatar">${escapeHtml(initials)}</div>
              <div class="teammate-details">
                <div class="teammate-name">${escapeHtml(staff.name)}</div>
                <div class="teammate-sub">
                  <span class="teammate-role-badge ${roleClass}" style="font-size: 10px; padding: 1px 6px;">${escapeHtml(staff.role)}</span>
                  <span>• Nghỉ cả ngày</span>
                </div>
              </div>
            </div>
            <button type="button" class="btn-request-swap" onclick="handleRequestSwapShift('${escapeHtml(staff.name)}', '${escapeHtml(vnDate)}', '${escapeHtml(shiftTitle)}')">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="m3 16 4 4 4-4"/>
                <path d="M7 20V4"/>
                <path d="m21 8-4-4-4 4"/>
                <path d="M17 4v16"/>
              </svg>
              <span>Yêu Cầu Đổi Ca</span>
            </button>
          </div>
        `;
      }).join('');
    }
  }

  modal.classList.add('active');
  updateSheetScrollLock();
}

export async function handlePeerSwapSubmit() {
  if (!state.currentSwapContext) return;
  const selectEl = document.getElementById('peerSwapTargetUser');
  const reasonEl = document.getElementById('peerSwapReason');
  const targetUser = selectEl ? selectEl.value : '';
  const reason = reasonEl ? reasonEl.value.trim() : '';

  if (!targetUser) {
    showToast('Vui lòng chọn nhân sự bạn muốn chuyển ca!', 'warn');
    return;
  }

  const btn = document.getElementById('btnSubmitPeerSwap');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang gửi yêu cầu...';
  }

  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/roster/peer-swap', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        week_id: state.currentSwapContext.weekId,
        date: state.currentSwapContext.isoDate,
        shift_period: state.currentSwapContext.shiftPeriod,
        slot_type: state.currentSwapContext.slotType,
        target_username: targetUser,
        reason: reason
      })
    });

    if (res.ok) {
      const d = await res.json().catch(() => ({}));
      showToast(d.message || 'Đổi ca thành công!', 'success');
      closePeerSwapModal();
      state.currentRosterWeeksCache = {};
      await fetchRosterWeekData('current');
      await fetchRosterWeekData('next');
      renderTabRoster();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(safeErrorDetail(err, 'Lỗi đổi ca!'), 'error');
    }
  } catch (e) {
    showToast(safeErrorDetail(e, 'Lỗi kết nối máy chủ khi gửi yêu cầu đổi ca!'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Xác Nhận Đổi Ca';
    }
  }
}

export async function handleRespondPeerSwap(swapId, action, weekId) {
  const token = localStorage.getItem('vnaigc_jwt');
  if (!token) return;
  const isAccept = (action === 'ACCEPT');
  const ok = await showConfirmDialog({
    title: isAccept ? 'Đồng Ý Nhận Ca' : 'Từ Chối Đổi Ca',
    message: isAccept
      ? 'Bạn có chắc chắn muốn nhận ca làm việc này không? Ca trực sẽ được chuyển sang tên bạn.'
      : 'Bạn muốn từ chối yêu cầu đổi ca này?',
    confirmText: isAccept ? 'Đồng Ý Nhận' : 'Từ Chối',
    cancelText: 'Xem Lại',
    type: isAccept ? 'success' : 'danger',
    icon: isAccept ? 'solar:check-circle-bold' : 'solar:close-circle-bold'
  });
  if (!ok) return;

  try {
    const res = await fetch('/api/v1/cc/roster/peer-swap/respond', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        swap_id: swapId,
        action: action,
        week_id: weekId || 'current'
      })
    });
    if (res.ok) {
      const d = await res.json().catch(() => ({}));
      showToast(d.message || (isAccept ? 'Đã nhận ca thành công!' : 'Đã từ chối đổi ca!'), 'success');
      state.currentRosterWeeksCache = {};
      await fetchRosterWeekData('current');
      await fetchRosterWeekData('next');
      renderTabRoster();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(safeErrorDetail(err, 'Lỗi xử lý đổi ca!'), 'error');
    }
  } catch (e) {
    showToast(safeErrorDetail(e, 'Lỗi kết nối máy chủ!'), 'error');
  }
}

export async function fetchAndRenderPendingPeerSwaps() {
  const box = document.getElementById('staffPendingPeerSwapsBox');
  if (!box) return;
  const token = localStorage.getItem('vnaigc_jwt');
  if (!token) {
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }
  const currentUname = (localStorage.getItem('vnaigc_username') || '').toLowerCase().trim();
  const currentFullName = (localStorage.getItem('vnaigc_name') || '').toLowerCase().trim();

  try {
    const res = await fetch('/api/v1/cc/roster/peer-swaps/pending', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (!res.ok) return;
    const data = await res.json().catch(() => ({}));
    const swaps = Array.isArray(data.pending_swaps) ? data.pending_swaps : [];

    const forMe = swaps.filter(sw => {
      const toU = String(sw.to_user || '').toLowerCase().trim();
      const toN = String(sw.to_name || '').toLowerCase().trim();
      return toU === currentUname || toN === currentFullName || toN.includes(currentUname);
    });

    const byMe = swaps.filter(sw => {
      const fromU = String(sw.from_user || '').toLowerCase().trim();
      const fromN = String(sw.from_name || '').toLowerCase().trim();
      return fromU === currentUname || fromN === currentFullName;
    });

    if (forMe.length === 0 && byMe.length === 0) {
      box.style.display = 'none';
      box.innerHTML = '';
      return;
    }

    box.style.display = 'block';
    let html = '';

    forMe.forEach(sw => {
      const shiftName = (sw.shift_period === 'morning' || sw.shift === 'morning' || (sw.shift || '').includes('Sáng')) ? 'Ca Sáng' : 'Ca Tối';
      const dStr = sw.date ? isoToVNDate(sw.date) : (sw.date_str || sw.date || '');
      html += `
        <div style="background: rgba(245, 158, 11, 0.12); border: 1.5px solid rgba(245, 158, 11, 0.4); border-radius: 10px; padding: 12px; margin-bottom: 8px;">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:6px; margin-bottom:6px;">
            <span style="font-size:12px; font-weight:700; color:#f59e0b; display:inline-flex; align-items:center; gap:5px;">
              <iconify-icon icon="solar:refresh-circle-bold" width="16"></iconify-icon> Yêu Cầu Nhờ Đổi Ca
            </span>
            <span style="font-size:11px; color:var(--text-secondary);">${escapeHtml(dStr)}</span>
          </div>
          <div style="font-size:13px; color:var(--text-primary); margin-bottom:10px; line-height:1.45;">
            <strong>${escapeHtml(sw.from_name || sw.from_user)}</strong> muốn nhờ bạn làm thay <strong>${escapeHtml(shiftName)}</strong> ngày <strong>${escapeHtml(dStr)}</strong>.
            ${sw.note ? `<div style="margin-top:4px; font-size:12px; color:var(--text-secondary); font-style:italic;">Ghi chú: "${escapeHtml(sw.note)}"</div>` : ''}
          </div>
          <div style="display:flex; gap:8px; justify-content:flex-end;">
            <button type="button" class="btn" style="padding:5px 12px; font-size:12px; font-weight:700; background:rgba(239,68,68,0.1); color:#ef4444; border:1px solid rgba(239,68,68,0.3); border-radius:6px; cursor:pointer;" onclick="handleRespondPeerSwap('${escapeHtml(sw.swap_id)}', 'REJECT', '${escapeHtml(sw.week_id || 'current')}')">Từ Chối</button>
            <button type="button" class="btn btn-primary" style="padding:5px 14px; font-size:12px; font-weight:700; background:#10b981; color:#fff; border:none; border-radius:6px; cursor:pointer;" onclick="handleRespondPeerSwap('${escapeHtml(sw.swap_id)}', 'ACCEPT', '${escapeHtml(sw.week_id || 'current')}')">Đồng Ý Nhận Ca</button>
          </div>
        </div>
      `;
    });

    byMe.forEach(sw => {
      const shiftName = (sw.shift_period === 'morning' || sw.shift === 'morning' || (sw.shift || '').includes('Sáng')) ? 'Ca Sáng' : 'Ca Tối';
      const dStr = sw.date ? isoToVNDate(sw.date) : (sw.date_str || sw.date || '');
      html += `
        <div style="background: rgba(99, 102, 241, 0.08); border: 1px dashed rgba(99, 102, 241, 0.3); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap;">
          <div style="font-size:12px; color:var(--text-secondary); display:inline-flex; align-items:center; gap:5px;">
            <iconify-icon icon="solar:clock-circle-bold" width="14"></iconify-icon>
            <span>Đang chờ <strong>${escapeHtml(sw.to_name || sw.to_user)}</strong> nhận ca <strong>${escapeHtml(shiftName)}</strong> (${escapeHtml(dStr)})...</span>
          </div>
          <button type="button" class="btn" style="padding:4px 10px; font-size:11px; font-weight:700; background:rgba(239,68,68,0.1); color:#ef4444; border:1px solid rgba(239,68,68,0.25); border-radius:6px; cursor:pointer;" onclick="handleRespondPeerSwap('${escapeHtml(sw.swap_id)}', 'REJECT', '${escapeHtml(sw.week_id || 'current')}')">Hủy Yêu Cầu</button>
        </div>
      `;
    });

    box.innerHTML = html;
  } catch (e) {
    console.error('Error fetching pending peer swaps:', e);
  }
}

export function extractUserDayPrefTags(reg, isoDate, dayIdx, dayKey) {
  if (!reg) return [];
  const prefs = reg.preferences || reg.days || reg.shifts || reg.availability || {};
  if (!prefs || typeof prefs !== 'object') return [];

  const candidates = [
    prefs[String(dayIdx)],
    prefs[dayIdx],
    prefs[isoDate],
    dayKey ? prefs[dayKey] : null,
    dayKey ? prefs[dayKey.toLowerCase()] : null
  ];

  let raw = null;
  for (const c of candidates) {
    if (c !== undefined && c !== null) {
      raw = c;
      break;
    }
  }

  if (!raw) return [];
  if (Array.isArray(raw)) {
    return raw.map(x => String(x).toUpperCase().trim());
  }
  return [String(raw).toUpperCase().trim()];
}

export function isPrefMatchingShift(tags, shiftPeriod, slotType) {
  if (!tags || tags.length === 0) return false;
  if (tags.includes('OFF') || tags.includes('NGHI')) return false;

  const isMorning = (shiftPeriod === 'morning' || shiftPeriod === 'sang');
  const isEvening = (shiftPeriod === 'evening' || shiftPeriod === 'toi');

  if (isMorning) {
    return tags.some(t => t.includes('MORN') || t.includes('SANG') || t === 'BOTH');
  }

  if (isEvening) {
    const wants17 = tags.some(t => t.includes('17'));
    const wants18 = tags.some(t => t.includes('18'));
    const wantsEvGeneral = tags.some(t => t.includes('EVEN') || t.includes('TOI') || t === 'BOTH');

    if (slotType === 'service_17') {
      return wants17 || (wantsEvGeneral && !wants18);
    }
    if (slotType === 'service_18') {
      return wants18 || (wantsEvGeneral && !wants17);
    }
    return wants17 || wants18 || wantsEvGeneral;
  }

  return false;
}

export function openUpdateShiftModal(weekId, isoDate, shiftPeriod, slotType, currentUser, slotLabel) {
  state.currentEditSlotContext = { weekId, isoDate, shiftPeriod, slotType, currentUser };
  const modal = document.getElementById('updateShiftSlotSheet');
  if (!modal) return;

  const infoEl = document.getElementById('updateShiftSlotInfo');
  if (infoEl) {
    infoEl.textContent = `${isoDate} • ${shiftPeriod === 'morning' ? 'Ca Sáng' : 'Ca Tối'} • ${slotLabel}`;
  }

  const selectEl = document.getElementById('updateShiftUserSelect');
  if (selectEl) {
    selectEl.innerHTML = '<option value="">-- Trống / Hủy ca --</option>';
    const staffDir = (state.currentNextWeekRosterData && state.currentNextWeekRosterData.staff_directory) ||
                     (state.currentRosterWeeksCache['current'] && state.currentRosterWeeksCache['current'].staff_directory) ||
                     (state.currentRosterWeeksCache['next'] && state.currentRosterWeeksCache['next'].staff_directory) || {};

    const staffList = Object.entries(staffDir).map(([u, s]) => ({ username: u, ...s }));
    staffList.sort((a, b) => (a.full_name || a.username).localeCompare(b.full_name || b.username));

    staffList.forEach(s => {
      if (s.status === 'INACTIVE') return;
      const gTag = s.gender === 'NU' ? 'Nữ' : 'Nam';
      const pos = s.position || 'Nhân viên';
      const opt = document.createElement('option');
      opt.value = s.username;
      opt.textContent = `${s.full_name || s.username} (${gTag} • ${pos})`;
      if (currentUser && currentUser.toLowerCase() === s.username.toLowerCase()) {
        opt.selected = true;
      }
      selectEl.appendChild(opt);
    });
  }

  modal.classList.add('active');
  updateSheetScrollLock();
}

export function closeUpdateShiftModal() {
  const modal = document.getElementById('updateShiftSlotSheet');
  if (modal) modal.classList.remove('active');
  updateSheetScrollLock();
}

export async function handleUpdateShiftSlotSubmit() {
  if (!state.currentEditSlotContext) return;
  const selectEl = document.getElementById('updateShiftUserSelect');
  const selectedUser = selectEl ? selectEl.value : '';

  const btn = document.getElementById('btnSubmitUpdateShiftSlot');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Đang lưu...';
  }

  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/roster/update-shift', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        week_id: state.currentEditSlotContext.weekId,
        date: state.currentEditSlotContext.isoDate,
        shift_period: state.currentEditSlotContext.shiftPeriod,
        slot_type: state.currentEditSlotContext.slotType,
        username: selectedUser || null
      })
    });

    if (res.ok) {
      const d = await res.json();
      showToast(d.message || 'Cập nhật phân ca thành công!', 'success');
      closeUpdateShiftModal();
      state.currentRosterWeeksCache = {};
      await fetchRosterWeekData('current');
      await fetchRosterWeekData('next');
      renderTabRoster();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(safeErrorDetail(err, 'Lỗi cập nhật ca!'), 'error');
    }
  } catch (e) {
    showToast(safeErrorDetail(e, 'Lỗi kết nối máy chủ!'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Lưu Thay Đổi';
    }
  }
}

if (typeof window !== 'undefined') {
  window.openPeerSwapModal = openPeerSwapModal;
  window.closePeerSwapModal = closePeerSwapModal;
  window.openUpdateShiftModal = openUpdateShiftModal;
  window.closeUpdateShiftModal = closeUpdateShiftModal;
  window.openShiftDetailModal = openShiftDetailModal;
  window.closeShiftDetailModal = closeShiftDetailModal;
  window.handleRequestSwapShift = handleRequestSwapShift;
  window.getInitialsAvatar = getInitialsAvatar;
}

export function setupRosterNav() {
  const btnPrev = document.getElementById('btnPrevWeek');
  const btnNext = document.getElementById('btnNextWeek');
  if (btnPrev) {
    btnPrev.onclick = () => {
      state.currentWeekPage++;
      renderTabRoster();
    };
  }
  if (btnNext) {
    btnNext.onclick = () => {
      if (state.currentWeekPage > -1) {
        state.currentWeekPage--;
        renderTabRoster();
      }
    };
  }

  const btnOpenReg = document.getElementById('btnOpenShiftRegistration');
  if (btnOpenReg) {
    btnOpenReg.onclick = () => openShiftRegistrationModal(state.currentRegWeekMode);
  }
  const btnSubmitReg = document.getElementById('btnSubmitShiftRegistration');
  if (btnSubmitReg) {
    btnSubmitReg.onclick = submitShiftRegistration;
  }

  // Week Selector Buttons
  const btnBannerCurrent = document.getElementById('btnBannerWeekCurrent');
  const btnBannerNext = document.getElementById('btnBannerWeekNext');
  if (btnBannerCurrent) {
    btnBannerCurrent.onclick = () => {
      state.currentRegWeekMode = 'current';
      updateStaffRegStatus('current');
    };
  }
  if (btnBannerNext) {
    btnBannerNext.onclick = () => {
      state.currentRegWeekMode = 'next';
      updateStaffRegStatus('next');
    };
  }

  const btnModalCurrent = document.getElementById('btnModalWeekCurrent');
  const btnModalNext = document.getElementById('btnModalWeekNext');
  if (btnModalCurrent) {
    btnModalCurrent.onclick = () => openShiftRegistrationModal('current');
  }
  if (btnModalNext) {
    btnModalNext.onclick = () => openShiftRegistrationModal('next');
  }

  const btnMgrCurrent = document.getElementById('btnMgrRegWeekCurrent');
  const btnMgrNext = document.getElementById('btnMgrRegWeekNext');
  if (btnMgrCurrent) {
    btnMgrCurrent.onclick = () => {
      state.currentWeekPage = 0;
      loadAndRenderManagerRegProgress('current');
      renderTabRoster();
    };
  }
  if (btnMgrNext) {
    btnMgrNext.onclick = () => {
      state.currentWeekPage = -1;
      loadAndRenderManagerRegProgress('next');
      renderTabRoster();
    };
  }

  const btnAutoFill = document.getElementById('btnAutoRoster') || document.getElementById('btnRosterAutoFill');
  if (btnAutoFill) {
    btnAutoFill.onclick = openAutoRosterConfirmModal;
  }
  const btnClonePrev = document.getElementById('btnClonePrevWeek');
  if (btnClonePrev) {
    btnClonePrev.onclick = handleClonePreviousWeek;
  }
  const btnCancelAutoRoster = document.getElementById('btnCancelAutoRoster');
  if (btnCancelAutoRoster) {
    btnCancelAutoRoster.onclick = closeAutoRosterConfirmModal;
  }
  const btnCloseAutoRoster = document.getElementById('btnCloseAutoRoster');
  if (btnCloseAutoRoster) {
    btnCloseAutoRoster.onclick = closeAutoRosterConfirmModal;
  }
  const btnConfirmAutoRoster = document.getElementById('btnConfirmAutoRoster');
  if (btnConfirmAutoRoster) {
    btnConfirmAutoRoster.onclick = executeRosterAutoFill;
  }
  const btnPublish = document.getElementById('btnRosterPublish');
  if (btnPublish) {
    btnPublish.onclick = handleRosterPublish;
  }

  const btnPeerSwap = document.getElementById('btnSubmitPeerSwap');
  if (btnPeerSwap) {
    btnPeerSwap.onclick = handlePeerSwapSubmit;
  }
  const btnUpdateShift = document.getElementById('btnSubmitUpdateShiftSlot');
  if (btnUpdateShift) {
    btnUpdateShift.onclick = handleUpdateShiftSlotSubmit;
  }

  const btnCloseShiftDetailX = document.getElementById('btnShiftDetailCloseX');
  if (btnCloseShiftDetailX) {
    btnCloseShiftDetailX.onclick = closeShiftDetailModal;
  }
  const btnCloseShiftDetail = document.getElementById('btnShiftDetailClose');
  if (btnCloseShiftDetail) {
    btnCloseShiftDetail.onclick = closeShiftDetailModal;
  }

  if (state.rosterCountdownInterval) clearInterval(state.rosterCountdownInterval);
  state.rosterCountdownInterval = setInterval(updateRosterCountdown, 1000);
  updateRosterCountdown();
  updateStaffRegStatus(state.currentRegWeekMode);

  fetchRosterWeekData('current');
  fetchRosterWeekData('next');
}

export function renderTabRoster() {
  const userRole = localStorage.getItem('vnaigc_role') || 'STAFF';
  const isStaffRole = (userRole === 'STAFF');

  const staffBanner = document.getElementById('staffRosterBanner');
  const staffScheduleCard = document.getElementById('staffMyScheduleCard');
  const managerToolbar = document.getElementById('managerRosterToolbar');
  const matrixCard = document.querySelector('.weekly-matrix-card');
  const dayDetailCard = document.querySelector('.roster-day-detail-card');
  const cardAnomalies = document.getElementById('cardWeeklyAnomalies');
  const cardWorkload = document.getElementById('cardWeeklyWorkload');
  const navRosterLabel = document.getElementById('navRosterLabel');

  const managerRegCard = document.getElementById('managerRosterRegCard');

  if (isStaffRole) {
    // 100% GỌN GÀNG CHO NHÂN VIÊN (PHƯƠNG ÁN 1)
    if (staffBanner) staffBanner.style.display = 'block';
    if (staffScheduleCard) staffScheduleCard.style.display = 'block';
    if (managerToolbar) managerToolbar.style.display = 'none';
    if (managerRegCard) managerRegCard.style.display = 'none';
    if (matrixCard) matrixCard.style.display = 'none';
    if (dayDetailCard) dayDetailCard.style.display = 'none';
    if (cardAnomalies) cardAnomalies.style.display = 'none';
    if (cardWorkload) cardWorkload.style.display = 'none';
    if (navRosterLabel) navRosterLabel.textContent = 'Lịch Ca';

    // Tải và hiển thị trạng thái nộp phiếu của nhân viên
    updateStaffRegStatus();
  } else {
    // QUẢN LÝ / ADMIN: ĐẦY ĐỦ MA TRẬN & ĐỊNH BIÊN
    if (staffBanner) staffBanner.style.display = 'none';
    if (staffScheduleCard) staffScheduleCard.style.display = 'none';
    if (managerToolbar) managerToolbar.style.display = 'flex';
    if (managerRegCard) managerRegCard.style.display = 'block';
    if (matrixCard) matrixCard.style.display = 'block';
    if (dayDetailCard) dayDetailCard.style.display = 'block';
    if (cardAnomalies) cardAnomalies.style.display = 'block';
    if (cardWorkload) cardWorkload.style.display = 'block';
    if (navRosterLabel) navRosterLabel.textContent = 'Phân Ca';

    const btnAuto = document.getElementById('btnAutoRoster') || document.getElementById('btnRosterAutoFill');
    const btnClone = document.getElementById('btnClonePrevWeek');
    const btnPub = document.getElementById('btnRosterPublish');

    if (state.currentWeekPage === -1) {
      if (btnAuto) {
        btnAuto.disabled = false;
        btnAuto.textContent = '⚡ Xếp Ca Tuần Tới';
        btnAuto.title = 'Tự động xếp lịch làm việc cho tuần tới';
      }
      if (btnClone) {
        btnClone.style.display = 'inline-block';
        btnClone.disabled = false;
        btnClone.textContent = '📋 Sao Chép Tuần Này';
        btnClone.title = 'Sao chép toàn bộ phân ca từ tuần này sang tuần tới';
      }
      if (btnPub) {
        btnPub.disabled = false;
        btnPub.textContent = 'Chốt & Công Bố Tuần Tới';
      }
    } else if (state.currentWeekPage === 0) {
      if (btnAuto) {
        btnAuto.disabled = false;
        btnAuto.textContent = '⚡ Xếp Ca Tuần Này';
        btnAuto.title = 'Tự động xếp lịch làm việc cho tuần này';
      }
      if (btnClone) {
        btnClone.style.display = 'inline-block';
        btnClone.disabled = false;
        btnClone.textContent = '📋 Sao Chép Tuần Trước';
        btnClone.title = 'Sao chép toàn bộ phân ca từ tuần trước sang tuần này';
      }
      if (btnPub) {
        btnPub.disabled = false;
        btnPub.textContent = 'Chốt & Công Bố Tuần Này';
      }
    } else {
      if (btnAuto) {
        btnAuto.disabled = true;
        btnAuto.textContent = 'Đã Kết Thúc';
        btnAuto.title = 'Không thể xếp lại lịch cho tuần trong quá khứ';
      }
      if (btnClone) {
        btnClone.style.display = 'none';
      }
      if (btnPub) {
        btnPub.disabled = true;
        btnPub.textContent = 'Đã Lưu Trữ';
      }
    }

    // Tải và hiển thị tiến độ nộp phiếu ca tương ứng với tuần đang xem
    const targetRegMode = (state.currentWeekPage === -1) ? 'next' : 'current';
    loadAndRenderManagerRegProgress(targetRegMode);
  }

  // Lấy dữ liệu roster tương ứng với tuần đang chọn
  const targetWeekId = (state.currentWeekPage === -1) ? 'next' : (state.currentWeekPage === 0 ? 'current' : null);
  let rosterData = null;
  if (targetWeekId) {
    rosterData = state.currentRosterWeeksCache[targetWeekId];
    if (!rosterData) {
      fetchRosterWeekData(targetWeekId, true).then(d => {
        if (d) renderTabRoster();
      });
    } else {
      // Stale-While-Revalidate: Hiển thị ngay từ cache, fetch ngầm bản mới nhất
      fetchRosterWeekData(targetWeekId, true).then(fresh => {
        if (fresh && fresh.week && rosterData && rosterData.week) {
          const freshStr = JSON.stringify(fresh.week.shifts || {});
          const currentStr = JSON.stringify(rosterData.week.shifts || {});
          if (freshStr !== currentStr || fresh.week.status !== rosterData.week.status) {
            renderTabRoster();
          }
        }
      });
    }
  }

  const filtered = state.currentMonth === 'all' ? state.records : state.records.filter(r => r.month === state.currentMonth);
  let dateSet = new Set();
  filtered.forEach(r => { if (r.date) dateSet.add(r.date); });
  let dates = Array.from(dateSet);
  const totalWeekPages = 8;

  let currentWeekDates = [];
  if (state.currentWeekPage === -1) {
    // TUẦN SAU (W39)
    if (rosterData && Array.isArray(rosterData.days) && rosterData.days.length > 0) {
      currentWeekDates = rosterData.days.map(isoToVNDate);
    } else {
      currentWeekDates = getCurrentISOWeekDays(1);
    }
  } else if (state.currentWeekPage === 0) {
    // TUẦN HIỆN TẠI (W38)
    if (rosterData && Array.isArray(rosterData.days) && rosterData.days.length > 0) {
      currentWeekDates = rosterData.days.map(isoToVNDate);
    } else {
      currentWeekDates = getCurrentISOWeekDays(0);
    }
  } else {
    // CÁC TUẦN TRƯỚC ĐÓ (LỊCH SỬ) - Luôn chuẩn 7 ngày từ Thứ Hai đến Chủ Nhật
    currentWeekDates = getCurrentISOWeekDays(-state.currentWeekPage);
  }

  if (currentWeekDates.length === 0) return;

  const btnPrev = document.getElementById('btnPrevWeek');
  const btnNext = document.getElementById('btnNextWeek');
  if (btnPrev) btnPrev.disabled = (state.currentWeekPage >= totalWeekPages);
  if (btnNext) btnNext.disabled = (state.currentWeekPage <= -1);

  if (!state.selectedDateStr || !currentWeekDates.includes(state.selectedDateStr)) {
    const todayVn = getCurrentVNDate();
    if (currentWeekDates.includes(todayVn)) {
      state.selectedDateStr = todayVn;
    } else {
      state.selectedDateStr = currentWeekDates[0] || '';
    }
  }

  const weekTitleEl = document.getElementById('rosterWeekTitle');
  if (weekTitleEl && currentWeekDates.length > 0) {
    const startStr = currentWeekDates[0];
    const endStr = currentWeekDates[currentWeekDates.length - 1];
    const sShort = startStr.slice(0, 5);
    const eShort = endStr.slice(0, 5);
    if (state.currentWeekPage === -1) {
      weekTitleEl.textContent = `Tuần tới • ${sShort} – ${eShort}`;
    } else if (state.currentWeekPage === 0) {
      weekTitleEl.textContent = `Tuần này • ${sShort} – ${eShort}`;
    } else if (state.currentWeekPage === 1) {
      weekTitleEl.textContent = `Tuần trước • ${sShort} – ${eShort}`;
    } else {
      weekTitleEl.textContent = `${sShort} – ${eShort} • ${state.currentWeekPage} tuần trước`;
    }
  }

  // NẾU LÀ NHÂN VIÊN: RENDER LỊCH CÁ NHÂN VÀ KẾT THÚC (PHƯƠNG ÁN 1)
  if (isStaffRole) {
    renderStaffMySchedule(currentWeekDates, filtered, rosterData);
    return;
  }

  // NẾU LÀ QUẢN LÝ / ADMIN: RENDER MA TRẬN 7 NGÀY VÀ CHI TIẾT ĐỊNH BIÊN
  const getDayRecordsCombined = (dateStr) => {
    let recs = filtered.filter(r => r.date === dateStr);
    if (recs.length === 0 && rosterData && rosterData.week && rosterData.week.shifts) {
      const isoD = vnToISODate(dateStr);
      const sInfo = rosterData.week.shifts[isoD];
      if (sInfo) {
        const sDir = rosterData.staff_directory || {};
        const getUName = u => (sDir[u] && sDir[u].full_name) || u;
        const syn = [];
        if (sInfo.morning) {
          const m = sInfo.morning;
          if (m.barista) syn.push({ date: dateStr, name: getUName(m.barista), shift: 'Ca sáng', role: 'Pha chế', in: '06:00', out: '11:00' });
          if (Array.isArray(m.service)) {
            m.service.forEach(s => {
              if (s) syn.push({ date: dateStr, name: getUName(s), shift: 'Ca sáng', role: 'Phục vụ', in: '06:00', out: '11:00' });
            });
          }
        }
        if (sInfo.evening) {
          const ev = sInfo.evening;
          if (ev.barista) syn.push({ date: dateStr, name: getUName(ev.barista), shift: 'Ca tối', role: 'Pha chế', in: '17:00', out: '23:00' });
          if (ev.service_17) syn.push({ date: dateStr, name: getUName(ev.service_17), shift: 'Ca tối', role: 'Phục vụ', in: '17:00', out: '23:00' });
          if (ev.service_18) syn.push({ date: dateStr, name: getUName(ev.service_18), shift: 'Ca tối', role: 'Phục vụ', in: '18:00', out: '23:00' });
        }
        recs = syn;
      }
    }
    return recs;
  };

  const matrixGrid = document.getElementById('weekMatrixGrid');
  if (matrixGrid) {
    matrixGrid.innerHTML = '';

    currentWeekDates.forEach((dStr, idx) => {
      const parts = dStr.split('/');
      const dNum = parts[0] || '01';
      
      let dayLabel = `N${idx+1}`;
      let isWeekend = false;
      if (parts.length === 3) {
        const dObj = new Date(parts[2], parseInt(parts[1]) - 1, parts[0]);
        const dayIdx = dObj.getDay();
        dayLabel = dayIdx === 0 ? 'CN' : `T${dayIdx + 1}`;
        isWeekend = (dayIdx === 0 || dayIdx === 6);
      }

      const reqM = { barista: 1, total: 2 };
      const reqE = { barista: isWeekend ? 1 : 0, total: 2 };

      const isoDate = vnToISODate(dStr);
      const curDayRoster = (rosterData && rosterData.week && rosterData.week.shifts && rosterData.week.shifts[isoDate])
        ? rosterData.week.shifts[isoDate]
        : null;

      let mBar = 0;
      let mTotal = 0;
      let eBar = 0;
      let evTotal = 0;
      let mDotColor = 'var(--border, #6b7280)';
      let eDotColor = 'var(--border, #6b7280)';

      if (curDayRoster) {
        const m = curDayRoster.morning || {};
        mBar = (m.baristas && m.baristas.filter(Boolean).length) || (m.barista ? 1 : 0);
        const mSvc = (m.service && Array.isArray(m.service)) ? m.service.filter(Boolean).length : 0;
        mTotal = mBar + mSvc;

        const ev = curDayRoster.evening || {};
        eBar = (ev.baristas && ev.baristas.filter(Boolean).length) || (ev.barista ? 1 : 0);
        const evSvc = (ev.service && Array.isArray(ev.service))
          ? (ev.service.filter(Boolean).length || 0)
          : ([ev.service_17, ev.service_18].filter(Boolean).length || 0);
        evTotal = eBar + evSvc;

        if (mTotal > 0) {
          mDotColor = (mBar < reqM.barista || mTotal < reqM.total)
            ? 'var(--accent-coral, #ef4444)'
            : 'var(--accent-emerald, #10b981)';
        }

        if (evTotal > 0) {
          eDotColor = (eBar < reqE.barista || evTotal < reqE.total)
            ? 'var(--accent-coral, #ef4444)'
            : 'var(--accent-emerald, #10b981)';
        }
      } else {
        const dayShifts = getDayRecordsCombined(dStr);
        const mShifts = dayShifts.filter(r => {
          const s = (r.shift || '').toLowerCase();
          return s.includes('sáng') || s.includes('cả ngày') || s.includes('full');
        });
        const eShifts = dayShifts.filter(r => {
          const s = (r.shift || '').toLowerCase();
          return s.includes('tối') || s.includes('chiều') || s.includes('cả ngày') || s.includes('full');
        });

        mBar = mShifts.filter(r => (r.role || getStaffRole(r.name)) === 'Pha chế').length;
        mTotal = mShifts.length;
        eBar = eShifts.filter(r => (r.role || getStaffRole(r.name)) === 'Pha chế').length;
        evTotal = eShifts.length;

        // Status dots: Xanh lá = Đủ, Đỏ/Cam = Thiếu, Xám = Chưa xếp
        if (mShifts.length > 0) {
          mDotColor = (mBar === 0 || mShifts.length < 2) ? 'var(--accent-coral, #ef4444)' : 'var(--accent-emerald, #10b981)';
        }
        if (eShifts.length > 0) {
          eDotColor = (eBar === 0 || eShifts.length < 2) ? 'var(--accent-coral, #ef4444)' : 'var(--accent-emerald, #10b981)';
        }
      }

      const col = document.createElement('div');
      col.className = `matrix-col ${dStr === state.selectedDateStr ? 'active' : ''}`;
      col.style.cssText = 'cursor:pointer; display:flex; flex-direction:column; align-items:center; padding:8px 4px; border-radius:10px; transition:all 0.2s;';
      col.innerHTML = `
        <div class="matrix-day-title" style="font-size:11px; font-weight:700; color:${isWeekend ? 'var(--accent-coral)' : 'var(--text-muted)'}; margin-bottom:2px;">${dayLabel}</div>
        <div class="matrix-day-num" style="font-size:16px; font-weight:800; font-family:var(--font-mono); margin-bottom:6px; color:var(--text-primary);">${dNum}</div>
        <div style="display:flex; justify-content:center; align-items:center; gap:4px;">
          <span style="width:6px; height:6px; border-radius:50%; background:${mDotColor}; display:inline-block;" title="Ca sáng: ${mTotal} NV (${mBar} Barista)"></span>
          <span style="width:6px; height:6px; border-radius:50%; background:${eDotColor}; display:inline-block;" title="Ca tối: ${evTotal} NV (${eBar} Barista)"></span>
        </div>
      `;

      col.addEventListener('click', () => {
        state.selectedDateStr = dStr;
        renderTabRoster();
      });

      matrixGrid.appendChild(col);
    });
  }

  // Render Selected Day Detail (Header ngắn gọn chuẩn tự nhiên: Thứ Năm, 15/10)
  const isSelectedHoliday = isHolidayDate(state.selectedDateStr);
  const detailTitleEl = document.getElementById('detailSelectedDayTitle');
  if (detailTitleEl) {
    const selP = (state.selectedDateStr || '').split('/');
    let dayOfWeekName = 'Thứ Năm';
    if (selP.length === 3) {
      const selDObj = new Date(selP[2], parseInt(selP[1]) - 1, selP[0]);
      const dow = selDObj.getDay();
      dayOfWeekName = dow === 0 ? 'Chủ Nhật' : `Thứ ${dow + 1}`;
    }
    const shortDate = `${selP[0] || '15'}/${selP[1] || '10'}`;
    detailTitleEl.textContent = isSelectedHoliday 
      ? `${dayOfWeekName}, ${shortDate} (LỄ x2 LƯƠNG)`
      : `${dayOfWeekName}, ${shortDate}`;
  }

  let isSelWeekend = false;
  const selParts = (state.selectedDateStr || '').split('/');
  if (selParts.length === 3) {
    const selDObj = new Date(selParts[2], parseInt(selParts[1]) - 1, selParts[0]);
    const selDay = selDObj.getDay();
    isSelWeekend = (selDay === 0 || selDay === 6);
  }

  const isoSelected = vnToISODate(state.selectedDateStr);
  const curDayRoster = (rosterData && rosterData.week && rosterData.week.shifts && rosterData.week.shifts[isoSelected]) ? rosterData.week.shifts[isoSelected] : null;

  const dayRecords = getDayRecordsCombined(state.selectedDateStr);

  const mList = dayRecords.filter(r => {
    const s = (r.shift || '').toLowerCase();
    return s.includes('sáng') || s.includes('cả ngày') || s.includes('full');
  });

  const eList = dayRecords.filter(r => {
    const s = (r.shift || '').toLowerCase();
    return s.includes('tối') || s.includes('chiều') || s.includes('cả ngày') || s.includes('full');
  });

  let curMBar = 0;
  let curMSvc = 0;
  let curEBar = 0;
  let curESvc = 0;

  if (curDayRoster) {
    curMBar = curDayRoster.morning
      ? ((curDayRoster.morning.baristas && curDayRoster.morning.baristas.filter(Boolean).length) || (curDayRoster.morning.barista ? 1 : 0))
      : 0;
    curMSvc = curDayRoster.morning && Array.isArray(curDayRoster.morning.service)
      ? curDayRoster.morning.service.filter(Boolean).length
      : 0;

    curEBar = curDayRoster.evening
      ? ((curDayRoster.evening.baristas && curDayRoster.evening.baristas.filter(Boolean).length) || (curDayRoster.evening.barista ? 1 : 0))
      : 0;
    curESvc = curDayRoster.evening
      ? ((curDayRoster.evening.service && Array.isArray(curDayRoster.evening.service))
          ? curDayRoster.evening.service.filter(Boolean).length
          : [curDayRoster.evening.service_17, curDayRoster.evening.service_18].filter(Boolean).length || 0)
      : 0;
  } else {
    curMBar = mList.filter(r => (r.role || getStaffRole(r.name)) === 'Pha chế').length;
    curMSvc = mList.length - curMBar;
    curEBar = eList.filter(r => (r.role || getStaffRole(r.name)) === 'Pha chế').length;
    curESvc = eList.length - curEBar;
  }

  const txtMorning = document.getElementById('txtMorningCount');
  const txtEvening = document.getElementById('txtEveningCount');
  if (txtMorning) txtMorning.textContent = `${curMBar} Barista • ${curMSvc} Phục vụ`;
  if (txtEvening) txtEvening.textContent = `${curEBar} Barista • ${curESvc} Phục vụ`;

  let hasEmptySlot = false;
  if (curDayRoster) {
    const m = curDayRoster.morning;
    if (m) {
      if (!m.barista || !m.manager || !(m.service && m.service[0]) || !(m.service && m.service[1])) {
        hasEmptySlot = true;
      }
    } else {
      hasEmptySlot = true;
    }
    const ev = curDayRoster.evening;
    if (ev) {
      const hasBar = isSelWeekend ? !!ev.barista : true;
      const hasS1 = !!(ev.service_17 || (ev.service && ev.service[0]));
      const hasS2 = !!(ev.service_18 || (ev.service && ev.service[1]));
      if (!hasBar || !ev.manager || !hasS1 || !hasS2) {
        hasEmptySlot = true;
      }
    } else {
      hasEmptySlot = true;
    }
  } else {
    if (curMBar === 0 || (isSelWeekend && curEBar === 0)) {
      hasEmptySlot = true;
    }
  }

  let statusText = 'Đủ Người';
  let statusClass = 'emerald';
  if (dayRecords.length === 0 && !curDayRoster) {
    statusText = 'Chưa có dữ liệu ca';
    statusClass = 'warn';
  } else if (hasEmptySlot || curMBar === 0 || (isSelWeekend && curEBar === 0)) {
    statusText = 'Thiếu Nhân Sự';
    statusClass = 'warn';
  } else if (isSelWeekend) {
    if (curMBar === 0 && curEBar === 0) {
      statusText = 'Vắng Pha Chế Cả Ngày';
      statusClass = 'coral';
    } else if (curMBar === 0) {
      statusText = 'Thiếu Pha Chế Ca Sáng';
      statusClass = 'coral';
    } else if (curEBar === 0) {
      statusText = 'Thiếu Pha Chế Ca Tối';
      statusClass = 'coral';
    }
  } else {
    if (curMBar === 0) {
      statusText = 'Thiếu Pha Chế Ca Sáng';
      statusClass = 'coral';
    }
  }

  const statusBadge = document.getElementById('detailDayStatusBadge');
  if (statusBadge) {
    statusBadge.className = `status-chip ${statusClass}`;
    statusBadge.textContent = statusText;
  }

  const mBox = document.getElementById('boxMorningStaff');
  const eBox = document.getElementById('boxEveningStaff');
  const currentWeekIdForEdit = (rosterData && rosterData.week && rosterData.week.week_id) || (state.currentWeekPage === -1 ? 'next' : 'current');
  const staffDirForEdit = (rosterData && rosterData.staff_directory) || {};
  const getStaffNameForEdit = u => (staffDirForEdit[u] && staffDirForEdit[u].full_name) || u;

  if (mBox) {
    mBox.innerHTML = '';
    if (curDayRoster && curDayRoster.morning) {
      const m = curDayRoster.morning;
      const slots = [
        { slotType: 'manager', label: 'Quản lý', user: m.manager, badge: '<span class="competency-badge mgr">QL</span>' },
        { slotType: 'barista', label: 'Pha chế', user: m.barista, badge: '<span class="competency-badge bar">BAR</span>' },
        { slotType: 'service_1', label: 'Phục vụ 1', user: (m.service && m.service[0]) || null, badge: '<span class="competency-badge svc">PV</span>' },
        { slotType: 'service_2', label: 'Phục vụ 2', user: (m.service && m.service[1]) || null, badge: '<span class="competency-badge svc">PV</span>' }
      ];
      slots.forEach(sl => {
        const chip = document.createElement('span');
        chip.className = 'staff-mini-chip';
        chip.style.cssText = 'display:inline-flex; align-items:center; gap:4px; cursor:pointer; padding:3px 8px; border-radius:6px; margin:2px;';
        const uname = sl.user ? escapeHtml(getStaffNameForEdit(sl.user)) : '<em style="color:var(--text-muted);">(Trống)</em>';
        chip.innerHTML = `${sl.badge} <strong>${uname}</strong> <iconify-icon icon="solar:pen-linear" width="12" height="12" style="opacity:0.6; margin-left:3px; vertical-align:middle;"></iconify-icon>`;
        chip.title = `Bấm để chỉnh sửa slot ${sl.label}`;
        chip.addEventListener('click', () => {
          openUpdateShiftModal(currentWeekIdForEdit, isoSelected, 'morning', sl.slotType, sl.user, sl.label);
        });
        mBox.appendChild(chip);
      });
    } else {
      if (mList.length === 0) mBox.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">Chưa xếp ca sáng</span>';
      mList.forEach(r => {
        const role = r.role || getStaffRole(r.name);
        const badge = role === 'Pha chế' ? '<span class="competency-badge bar">BAR</span>' : (role === 'Quản lý' ? '<span class="competency-badge mgr">QL</span>' : '<span class="competency-badge svc">PV</span>');
        const chip = document.createElement('span');
        chip.className = 'staff-mini-chip';
        const holidayBadge = r.isHoliday ? ' <span style="background:rgba(239,68,68,0.15); color:#dc2626; padding:1px 5px; border-radius:4px; font-size:12px; font-weight:700;">x2 LỄ</span>' : '';
        chip.innerHTML = `${badge} <strong>${escapeHtml(r.name)}</strong> <em>(${escapeHtml(r.in)}-${escapeHtml(r.out)})</em>${holidayBadge}`;
        chip.addEventListener('click', () => openPayslipModal(r.name));
        mBox.appendChild(chip);
      });
    }
  }

  if (eBox) {
    eBox.innerHTML = '';
    if (curDayRoster && curDayRoster.evening) {
      const ev = curDayRoster.evening;
      const slots = [
        { slotType: 'manager', label: 'Quản lý', user: ev.manager, badge: '<span class="competency-badge mgr">QL</span>' },
        { slotType: 'barista', label: 'Pha chế', user: ev.barista, badge: '<span class="competency-badge bar">BAR</span>' },
        { slotType: 'service_17', label: 'Phục vụ 17h', user: ev.service_17, badge: '<span class="competency-badge svc">PV</span>', timeTag: '17h' },
        { slotType: 'service_18', label: 'Phục vụ 18h', user: ev.service_18, badge: '<span class="competency-badge svc">PV</span>', timeTag: '18h' }
      ];
      slots.forEach(sl => {
        const chip = document.createElement('span');
        chip.className = 'staff-mini-chip';
        chip.style.cssText = 'display:inline-flex; align-items:center; gap:4px; cursor:pointer; padding:3px 8px; border-radius:6px; margin:2px;';
        const uname = sl.user ? escapeHtml(getStaffNameForEdit(sl.user)) : '<em style="color:var(--text-muted);">(Trống)</em>';
        const timeBadge = sl.timeTag ? `<span style="font-size:12px; color:var(--text-muted); font-weight:600;">(${sl.timeTag})</span>` : '';
        chip.innerHTML = `${sl.badge} <strong>${uname}</strong>${timeBadge ? ` ${timeBadge}` : ''} <iconify-icon icon="solar:pen-linear" width="12" height="12" style="opacity:0.6; margin-left:3px; vertical-align:middle;"></iconify-icon>`;
        chip.title = `Bấm để chỉnh sửa slot ${sl.label}`;
        chip.addEventListener('click', () => {
          openUpdateShiftModal(currentWeekIdForEdit, isoSelected, 'evening', sl.slotType, sl.user, sl.label);
        });
        eBox.appendChild(chip);
      });
    } else {
      if (eList.length === 0) eBox.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">Chưa xếp ca chiều/tối</span>';
      eList.forEach(r => {
        const role = r.role || getStaffRole(r.name);
        const badge = role === 'Pha chế' ? '<span class="competency-badge bar">BAR</span>' : (role === 'Quản lý' ? '<span class="competency-badge mgr">QL</span>' : '<span class="competency-badge svc">PV</span>');
        const chip = document.createElement('span');
        chip.className = 'staff-mini-chip';
        const holidayBadge = r.isHoliday ? ' <span style="background:rgba(239,68,68,0.15); color:#dc2626; padding:1px 5px; border-radius:4px; font-size:12px; font-weight:700;">x2 LỄ</span>' : '';
        chip.innerHTML = `${badge} <strong>${escapeHtml(r.name)}</strong> <em>(${escapeHtml(r.in)}-${escapeHtml(r.out)})</em>${holidayBadge}`;
        chip.addEventListener('click', () => openPayslipModal(r.name));
        eBox.appendChild(chip);
      });
    }
  }

  // Accordion gập mở cho Ca Sáng & Ca Tối (Tự động thu gọn nếu đã Đủ Người)
  const isMorningFull = (curDayRoster && curDayRoster.morning)
    ? !!(curDayRoster.morning.barista && curDayRoster.morning.service && curDayRoster.morning.service.filter(Boolean).length >= 2)
    : (mList.length >= 2 && curMBar > 0);
  const isEveningFull = (curDayRoster && curDayRoster.evening)
    ? !!((!isSelWeekend || curDayRoster.evening.barista) && (
        (curDayRoster.evening.service && curDayRoster.evening.service.filter(Boolean).length >= 2) ||
        (curDayRoster.evening.service_17 && curDayRoster.evening.service_18)
      ))
    : (eList.length >= 2 && (!isSelWeekend || curEBar > 0));

  const headMorning = document.getElementById('headMorningShift');
  const iconMorning = document.getElementById('iconToggleMorning');
  if (mBox) {
    mBox.style.display = isMorningFull ? 'none' : 'flex';
    if (iconMorning) iconMorning.setAttribute('icon', isMorningFull ? 'solar:alt-arrow-right-linear' : 'solar:alt-arrow-down-linear');
  }
  if (headMorning && mBox && !headMorning._hasAccordion) {
    headMorning._hasAccordion = true;
    headMorning.onclick = () => {
      const isHidden = (mBox.style.display === 'none');
      mBox.style.display = isHidden ? 'flex' : 'none';
      if (iconMorning) iconMorning.setAttribute('icon', isHidden ? 'solar:alt-arrow-down-linear' : 'solar:alt-arrow-right-linear');
    };
  }

  const headEvening = document.getElementById('headEveningShift');
  const iconEvening = document.getElementById('iconToggleEvening');
  if (eBox) {
    eBox.style.display = isEveningFull ? 'none' : 'flex';
    if (iconEvening) iconEvening.setAttribute('icon', isEveningFull ? 'solar:alt-arrow-right-linear' : 'solar:alt-arrow-down-linear');
  }
  if (headEvening && eBox && !headEvening._hasAccordion) {
    headEvening._hasAccordion = true;
    headEvening.onclick = () => {
      const isHidden = (eBox.style.display === 'none');
      eBox.style.display = isHidden ? 'flex' : 'none';
      if (iconEvening) iconEvening.setAttribute('icon', isHidden ? 'solar:alt-arrow-down-linear' : 'solar:alt-arrow-right-linear');
    };
  }

  // Render High-Density Weekly Analytics cho Quản lý
  renderWeeklyRosterAnalytics(currentWeekDates, filtered, rosterData);
}

export function renderStaffMySchedule(currentWeekDates, filtered, rosterData) {
  const scheduleCard = document.getElementById('staffMyScheduleCard');
  const scheduleList = document.getElementById('staffMyScheduleList');
  const countBadge = document.getElementById('staffMyScheduleCountBadge');
  const titleEl = document.getElementById('staffMyScheduleCardTitle');
  if (!scheduleCard || !scheduleList) return;

  let pendingBox = document.getElementById('staffPendingPeerSwapsBox');
  if (!pendingBox) {
    pendingBox = document.createElement('div');
    pendingBox.id = 'staffPendingPeerSwapsBox';
    pendingBox.style.display = 'none';
    pendingBox.style.marginBottom = '10px';
    scheduleList.parentNode.insertBefore(pendingBox, scheduleList);
  }
  fetchAndRenderPendingPeerSwaps();

  if (titleEl) {
    if (state.currentWeekPage === 0) {
      titleEl.textContent = 'LỊCH LÀM VIỆC CỦA BẠN TUẦN NÀY';
    } else if (state.currentWeekPage === -1) {
      titleEl.textContent = 'LỊCH LÀM VIỆC CỦA BẠN TUẦN SAU';
    } else if (state.currentWeekPage === 1) {
      titleEl.textContent = 'LỊCH LÀM VIỆC CỦA BẠN TUẦN TRƯỚC';
    } else {
      titleEl.textContent = `LỊCH LÀM VIỆC CỦA BẠN (${state.currentWeekPage} TUẦN TRƯỚC)`;
    }
  }

  const currentUname = (
    (rosterData && rosterData.current_user) ||
    localStorage.getItem('vnaigc_username') ||
    ''
  ).toLowerCase().trim();
  const currentFullName = (localStorage.getItem('vnaigc_name') || '').toLowerCase().trim();
  let cachedSheetNames = [];
  try {
    const rawSN = localStorage.getItem('vnaigc_sheet_names');
    if (rawSN) cachedSheetNames = JSON.parse(rawSN);
  } catch (e) {}

  const staffDir = (rosterData && rosterData.staff_directory) || {};
  const myStaffInfo = staffDir[currentUname] || {};
  const mySheetNames = [
    ...(Array.isArray(myStaffInfo.sheet_names) ? myStaffInfo.sheet_names : []),
    ...(Array.isArray(cachedSheetNames) ? cachedSheetNames : [])
  ].map(s => String(s).trim().toLowerCase());

  const getStaffDisplayName = (u) => {
    if (!u) return '';
    if (staffDir[u] && staffDir[u].full_name) return staffDir[u].full_name;
    return u;
  };

  const weekObj = rosterData && rosterData.week;
  const isRosterPublished = weekObj && (weekObj.status === 'PUBLISHED');
  const rosterShifts = (isRosterPublished && weekObj.shifts) ? weekObj.shifts : null;

  const myShifts = [];

  const datesToProcess = Array.isArray(currentWeekDates) && currentWeekDates.length > 0
    ? currentWeekDates
    : ((rosterData && Array.isArray(rosterData.days)) ? rosterData.days.map(isoToVNDate) : getCurrentISOWeekDays(0));

  datesToProcess.forEach(dStr => {
    const parts = dStr.split('/');
    let dayOfWeekName = dStr;
    if (parts.length === 3) {
      const dObj = new Date(parts[2], parseInt(parts[1]) - 1, parts[0]);
      const dayIdx = dObj.getDay();
      dayOfWeekName = dayIdx === 0 ? 'Chủ Nhật' : `Thứ ${dayIdx + 1}`;
    }

    const isoDateStr = (parts.length === 3)
      ? `${parts[2]}-${parts[1].padStart(2, '0')}-${parts[0].padStart(2, '0')}`
      : dStr;

    // ƯU TIÊN 1: NẾU ROSTER TUẦN ĐÃ ĐƯỢC CÔNG BỐ (PUBLISHED)
    if (rosterShifts && rosterShifts[isoDateStr]) {
      const dayData = rosterShifts[isoDateStr];
      const m = dayData.morning || {};
      const ev = dayData.evening || {};

      // Kiểm tra user có trong ca sáng
      let morningRole = null;
      let morningSlotType = null;
      if (m.barista && (m.barista.toLowerCase() === currentUname || getStaffDisplayName(m.barista).toLowerCase() === currentFullName)) {
        morningRole = 'Pha chế';
        morningSlotType = 'barista';
      } else if (Array.isArray(m.service)) {
        if (m.service[0] && (m.service[0].toLowerCase() === currentUname || getStaffDisplayName(m.service[0]).toLowerCase() === currentFullName)) {
          morningRole = 'Phục vụ';
          morningSlotType = 'service_1';
        } else if (m.service[1] && (m.service[1].toLowerCase() === currentUname || getStaffDisplayName(m.service[1]).toLowerCase() === currentFullName)) {
          morningRole = 'Phục vụ';
          morningSlotType = 'service_2';
        }
      } else if (m.manager && (m.manager.toLowerCase() === currentUname || getStaffDisplayName(m.manager).toLowerCase() === currentFullName)) {
        morningRole = 'Quản lý';
        morningSlotType = 'manager';
      }

      // Kiểm tra user có trong ca tối
      let eveningRole = null;
      let eveningSlotType = null;
      let eveningTime = '17:00 - 23:00';
      if (ev.barista && (ev.barista.toLowerCase() === currentUname || getStaffDisplayName(ev.barista).toLowerCase() === currentFullName)) {
        eveningRole = 'Pha chế';
        eveningSlotType = 'barista';
      } else if (ev.service_17 && (ev.service_17.toLowerCase() === currentUname || getStaffDisplayName(ev.service_17).toLowerCase() === currentFullName)) {
        eveningRole = 'Phục vụ';
        eveningSlotType = 'service_17';
        eveningTime = '17:00 - 23:00';
      } else if (ev.service_18 && (ev.service_18.toLowerCase() === currentUname || getStaffDisplayName(ev.service_18).toLowerCase() === currentFullName)) {
        eveningRole = 'Phục vụ';
        eveningSlotType = 'service_18';
        eveningTime = '18:00 - 23:00';
      } else if (ev.manager && (ev.manager.toLowerCase() === currentUname || getStaffDisplayName(ev.manager).toLowerCase() === currentFullName)) {
        eveningRole = 'Quản lý';
        eveningSlotType = 'manager';
      }

      const dayRecords = filtered ? filtered.filter(r => r.date === dStr) : [];
      const canonMyName = getCanonicalStaffName(currentFullName);
      const canonUname = getCanonicalStaffName(currentUname);
      const myRec = dayRecords.find(r => {
        const rName = (r.name || '').toLowerCase();
        const canonR = getCanonicalStaffName(r.name);
        return rName === currentUname || rName === currentFullName || canonR === canonMyName || canonR === canonUname;
      });
      const actualTime = (myRec && myRec.in && myRec.out) ? `${myRec.in} - ${myRec.out}` : '';

      if (morningRole) {
        const teammates = [];
        if (m.manager && m.manager.toLowerCase() !== currentUname) {
          teammates.push(`${getStaffDisplayName(m.manager)} (QL)`);
        }
        if (m.barista && m.barista.toLowerCase() !== currentUname) {
          teammates.push(`${getStaffDisplayName(m.barista)} (BAR)`);
        }
        if (Array.isArray(m.service)) {
          m.service.forEach(u => {
            if (u && u.toLowerCase() !== currentUname) {
              teammates.push(`${getStaffDisplayName(u)} (PV)`);
            }
          });
        }

        myShifts.push({
          dayName: dayOfWeekName,
          date: dStr,
          isoDate: isoDateStr,
          shift: 'Ca Sáng',
          shiftPeriod: 'morning',
          slotType: morningSlotType,
          weekId: (weekObj && weekObj.week_id) || 'current',
          shiftTime: m.time || '06:00 - 11:00',
          actualTime: actualTime,
          role: morningRole,
          isHoliday: isHolidayDate(dStr),
          teammates: teammates,
          source: 'roster'
        });
      }

      if (eveningRole) {
        const teammates = [];
        if (ev.manager && ev.manager.toLowerCase() !== currentUname) {
          teammates.push(`${getStaffDisplayName(ev.manager)} (QL)`);
        }
        if (ev.barista && ev.barista.toLowerCase() !== currentUname) {
          teammates.push(`${getStaffDisplayName(ev.barista)} (BAR)`);
        }
        if (ev.service_17 && ev.service_17.toLowerCase() !== currentUname) {
          teammates.push(`${getStaffDisplayName(ev.service_17)} (PV 17h)`);
        }
        if (ev.service_18 && ev.service_18.toLowerCase() !== currentUname) {
          teammates.push(`${getStaffDisplayName(ev.service_18)} (PV 18h)`);
        }

        myShifts.push({
          dayName: dayOfWeekName,
          date: dStr,
          isoDate: isoDateStr,
          shift: 'Ca Tối',
          shiftPeriod: 'evening',
          slotType: eveningSlotType,
          weekId: (weekObj && weekObj.week_id) || 'current',
          shiftTime: eveningTime,
          actualTime: actualTime,
          role: eveningRole,
          isHoliday: isHolidayDate(dStr),
          teammates: teammates,
          source: 'roster'
        });
      }

    } else {
      // ƯU TIÊN 2: FALLBACK VỀ DỮ LIỆU SHEETS CŨ (FILTERED / RECORDS)
      const dayRecords = filtered ? filtered.filter(r => r.date === dStr) : [];
      const canonMyName = getCanonicalStaffName(currentFullName);
      const canonUname = getCanonicalStaffName(currentUname);
      const normUname = removeAccents(currentUname).toLowerCase();
      const myRec = dayRecords.find(r => {
        const rName = (r.name || '').trim().toLowerCase();
        const normR = removeAccents(rName);
        const canonR = getCanonicalStaffName(r.name);

        if (rName === currentUname || rName === currentFullName) return true;
        if (canonR && (canonR === canonMyName || canonR === canonUname)) return true;
        if (canonMyName && canonR && canonMyName.includes(canonR)) return true;
        if (normR === normUname) return true;
        if (mySheetNames.includes(rName) || mySheetNames.includes(canonR.toLowerCase())) return true;
        if (currentFullName && currentFullName.includes(rName)) return true;
        return false;
      });

      if (myRec) {
        const isMorning = (myRec.shift || '').toLowerCase().includes('sáng');
        const teammates = dayRecords.filter(r => {
          const otherIsMorning = (r.shift || '').toLowerCase().includes('sáng');
          return r !== myRec && otherIsMorning === isMorning;
        }).map(r => {
          const role = r.role || getStaffRole(r.name);
          const tag = role === 'Pha chế' ? 'BAR' : (role === 'Quản lý' ? 'QL' : 'PV');
          return `${r.name} (${tag})`;
        });

        myShifts.push({
          dayName: dayOfWeekName,
          date: dStr,
          shift: isMorning ? 'Ca Sáng' : 'Ca Tối',
          shiftTime: isMorning ? '06:00 - 11:30' : '17:00 - 22:30',
          actualTime: (myRec.in && myRec.out) ? `${myRec.in} - ${myRec.out}` : '',
          role: myRec.role || getStaffRole(myRec.name),
          isHoliday: !!myRec.isHoliday || isHolidayDate(dStr),
          teammates: teammates,
          source: 'sheets'
        });
      }
    }
  });

  if (countBadge) countBadge.textContent = `${myShifts.length} ca`;

  if (myShifts.length === 0) {
    const weekLabel = state.currentWeekPage === 0 ? 'tuần này' : (state.currentWeekPage === 1 ? 'tuần trước' : (state.currentWeekPage === -1 ? 'tuần sau' : 'tuần này'));
    if (weekObj && weekObj.status !== 'PUBLISHED') {
      scheduleList.innerHTML = `
        <div style="text-align: center; padding: 24px 12px; background: var(--bg-card-sub); border: 1px dashed var(--border); border-radius: 10px;">
          <div style="font-size: 14px; font-weight: 700; color: var(--text-primary);">Lịch ca tuần ${weekObj.week_id || 'mới'} đang mở đăng ký</div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Quản lý sẽ chốt và công bố lịch sau 18:00 Chủ Nhật. Bạn nhớ gửi phiếu đăng ký ca bên dưới nhé!</div>
        </div>
      `;
    } else {
      scheduleList.innerHTML = `
        <div style="text-align: center; padding: 24px 12px; background: var(--bg-card-sub); border: 1px dashed var(--border); border-radius: 10px;">
          <div style="font-size: 14px; font-weight: 700; color: var(--text-primary);">Bạn chưa có ca làm việc trong ${weekLabel}</div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">Dùng nút mũi tên ‹ › trên thanh Tuần để xem các tuần khác hoặc điền đăng ký ca bên dưới.</div>
        </div>
      `;
    }
    return;
  }

  scheduleList.innerHTML = myShifts.map(s => {
    const isSwapAllowed = !(state.currentNextWeekRosterData && state.currentNextWeekRosterData.peer_shift_swap_allowed === false);
    const userRole = (localStorage.getItem('vnaigc_role') || 'STAFF').toUpperCase();
    const canSwap = isSwapAllowed || userRole === 'ADMIN' || userRole === 'MANAGER';

    const swapBtn = (canSwap && s.source === 'roster' && s.slotType && s.slotType !== 'manager')
      ? `<button type="button" class="pref-btn" style="padding: 3px 8px; font-size: 12px; font-weight: 700; border-radius: 6px; border: 1px solid var(--accent-indigo); background: rgba(99, 102, 241, 0.1); color: var(--accent-indigo); cursor: pointer; display: inline-flex; align-items: center; gap: 4px;" onclick="event.stopPropagation(); openPeerSwapModal('${escapeHtml(s.weekId)}', '${escapeHtml(s.isoDate)}', '${escapeHtml(s.shiftPeriod)}', '${escapeHtml(s.slotType)}', '${escapeHtml(s.dayName)}', '${escapeHtml(s.date)}', '${escapeHtml(s.shift)}')">Đổi ca</button>`
      : '';

    return `
    <div class="shift-card-clickable" style="background: var(--bg-card-sub); border: 1px solid var(--border); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 8px;" onclick="openShiftDetailModal('${escapeHtml(s.isoDate || s.date)}', '${escapeHtml(s.shiftPeriod || (s.shift.toLowerCase().includes('sáng') ? 'morning' : 'evening'))}')" title="Chạm để xem đồng đội & đổi ca">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div style="display: flex; align-items: center; gap: 6px;">
          <span style="font-size: 13px; font-weight: 800; color: var(--text-primary);">${escapeHtml(s.dayName)} • ${escapeHtml(s.date)}</span>
          ${s.isHoliday ? '<span style="font-size: 12px; font-weight: 700; padding: 1px 6px; border-radius: 4px; background: rgba(239, 68, 68, 0.15); color: #dc2626;">x2 LỄ</span>' : ''}
          ${s.source === 'roster' ? '<span style="font-size: 12px; font-weight: 700; padding: 1px 5px; border-radius: 4px; background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald);">LỊCH CHỐT</span>' : ''}
        </div>
        <div style="display: flex; align-items: center; gap: 6px;">
          <span style="font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 6px; ${s.shift === 'Ca Sáng' ? 'background: rgba(245, 158, 11, 0.15); color: #d97706;' : 'background: rgba(99, 102, 241, 0.15); color: #4f46e5;'}">${escapeHtml(s.shift)}</span>
          ${swapBtn}
        </div>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--text-secondary);">
        <span>Giờ ca: <strong>${escapeHtml(s.actualTime || s.shiftTime)}</strong></span>
        <span style="font-size: 12px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: var(--accent-emerald-sub); color: var(--accent-emerald);">${escapeHtml(s.role)}</span>
      </div>
      <div style="font-size: 12px; color: var(--text-muted); border-top: 1px dashed var(--border); padding-top: 6px; display: flex; justify-content: space-between; align-items: center;">
        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80%;">👥 <strong>Làm cùng:</strong> ${s.teammates.length > 0 ? s.teammates.map(t => escapeHtml(t)).join(', ') : '<em style="color:var(--text-muted);">Trực độc lập</em>'}</span>
        <span style="font-size: 11px; font-weight: 700; color: var(--accent-coral); white-space: nowrap;">Chi tiết ➔</span>
      </div>
    </div>
  `;
  }).join('');
}

export function renderWeeklyRosterAnalytics(currentWeekDates, filtered, rosterData) {
  if (!currentWeekDates || currentWeekDates.length === 0) return;

  const totalShifts = currentWeekDates.length * 2;
  let compliantShifts = 0;
  let totalMissing = 0;
  let weeklyWorkload = {};
  let weeklyAnomalies = [];

  currentWeekDates.forEach(dStr => {
    const parts = dStr.split('/');
    let dayLabel = dStr;
    let isWk = false;
    if (parts.length === 3) {
      const dObj = new Date(parts[2], parseInt(parts[1]) - 1, parts[0]);
      const dayIdx = dObj.getDay();
      dayLabel = dayIdx === 0 ? 'Chủ Nhật' : `Thứ ${dayIdx + 1}`;
      isWk = (dayIdx === 0 || dayIdx === 6);
    }

    const reqM = { barista: 1, total: 2 };
    const reqE = { barista: isWk ? 1 : 0, total: 2 };

    const dRecords = filtered.filter(r => r.date === dStr);
    dRecords.forEach(r => {
      weeklyWorkload[r.name] = (weeklyWorkload[r.name] || 0) + 1;
    });

    const isoD = vnToISODate(dStr);
    const rDay = (rosterData && rosterData.week && rosterData.week.shifts) ? rosterData.week.shifts[isoD] : null;

    if (rDay) {
      const m = rDay.morning || {};
      const mBar = (m.baristas && m.baristas.filter(Boolean).length) || (m.barista ? 1 : 0);
      const mSvc = (m.service && Array.isArray(m.service)) ? m.service.filter(Boolean).length : 0;
      const mTotal = mBar + mSvc;

      const ev = rDay.evening || {};
      const eBar = (ev.baristas && ev.baristas.filter(Boolean).length) || (ev.barista ? 1 : 0);
      const eSvc = (ev.service && Array.isArray(ev.service))
        ? (ev.service.filter(Boolean).length || 0)
        : ([ev.service_17, ev.service_18].filter(Boolean).length || 0);
      const eTotal = eBar + eSvc;

      if (dRecords.length === 0) {
        const sDir = (rosterData && rosterData.staff_directory) || {};
        const getStaffName = u => (sDir[u] && sDir[u].full_name) || u;
        const staffList = [];
        if (m.baristas) staffList.push(...m.baristas);
        else if (m.barista) staffList.push(m.barista);
        if (Array.isArray(m.service)) staffList.push(...m.service);

        if (ev.baristas) staffList.push(...ev.baristas);
        else if (ev.barista) staffList.push(ev.barista);
        if (Array.isArray(ev.service)) staffList.push(...ev.service);
        if (ev.service_17) staffList.push(ev.service_17);
        if (ev.service_18) staffList.push(ev.service_18);

        staffList.filter(Boolean).forEach(u => {
          const name = getStaffName(u);
          weeklyWorkload[name] = (weeklyWorkload[name] || 0) + 1;
        });
      }

      // Morning check
      if (mTotal === 0) {
        weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca sáng: Chưa xếp ca`, type: 'empty' });
        totalMissing += reqM.total;
      } else if (mBar < reqM.barista) {
        weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca sáng: Thiếu Pha chế mở quán`, type: 'bar' });
        totalMissing += (reqM.barista - mBar);
      } else if (mTotal < reqM.total) {
        weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca sáng: Thiếu nhân sự (${mTotal}/${reqM.total} người)`, type: 'svc' });
        totalMissing += (reqM.total - mTotal);
      } else {
        compliantShifts++;
      }

      // Evening check
      if (isWk) {
        if (eTotal === 0) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Tối cuối tuần: Chưa xếp ca`, type: 'empty' });
          totalMissing += reqE.total;
        } else if (eBar < reqE.barista) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Tối cuối tuần: Thiếu Barista tăng cường`, type: 'bar' });
          totalMissing += (reqE.barista - eBar);
        } else if (eTotal < reqE.total) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Tối cuối tuần: Thiếu phục vụ (${eTotal}/${reqE.total} người)`, type: 'svc' });
          totalMissing += (reqE.total - eTotal);
        } else {
          compliantShifts++;
        }
      } else {
        if (eTotal === 0) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca tối: Chưa xếp ca`, type: 'empty' });
          totalMissing += reqE.total;
        } else if (eTotal < reqE.total) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca tối: Thiếu nhân sự (${eTotal}/${reqE.total} người)`, type: 'svc' });
          totalMissing += (reqE.total - eTotal);
        } else {
          compliantShifts++;
        }
      }
    } else {
      const mShifts = dRecords.filter(r => {
        const s = (r.shift || '').toLowerCase();
        return s.includes('sáng') || s.includes('cả ngày') || s.includes('full');
      });
      const eShifts = dRecords.filter(r => {
        const s = (r.shift || '').toLowerCase();
        return s.includes('tối') || s.includes('chiều') || s.includes('cả ngày') || s.includes('full');
      });

      const mBar = mShifts.filter(r => (r.role || getStaffRole(r.name)) === 'Pha chế').length;
      const eBar = eShifts.filter(r => (r.role || getStaffRole(r.name)) === 'Pha chế').length;

      // Morning check: needs Barista and at least 2 staff
      if (mShifts.length === 0) {
        weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca sáng: Chưa xếp ca`, type: 'empty' });
        totalMissing += 2;
      } else if (mBar === 0) {
        weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca sáng: Thiếu Pha chế mở quán`, type: 'bar' });
        totalMissing += 1;
      } else if (mShifts.length < 2) {
        weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca sáng: Thiếu nhân sự (${mShifts.length}/2 người)`, type: 'svc' });
        totalMissing += 1;
      } else {
        compliantShifts++;
      }

      // Evening check
      if (isWk) {
        // Weekend: needs Barista and at least 2 staff
        if (eShifts.length === 0) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Tối cuối tuần: Trống ca chấm công`, type: 'empty' });
          totalMissing += 2;
        } else if (eBar === 0) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Tối cuối tuần: Thiếu Barista tăng cường`, type: 'bar' });
          totalMissing += 1;
        } else if (eShifts.length < 2) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Tối cuối tuần: Thiếu phục vụ (${eShifts.length}/2 người)`, type: 'svc' });
          totalMissing += 1;
        } else {
          compliantShifts++;
        }
      } else {
        // Weekday: does not need Barista, needs at least 2 staff
        if (eShifts.length === 0) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca tối: Chưa xếp ca`, type: 'empty' });
          totalMissing += 2;
        } else if (eShifts.length < 2) {
          weeklyAnomalies.push({ dStr, text: `${dayLabel} (${dStr}) - Ca tối: Thiếu nhân sự (${eShifts.length}/2 người)`, type: 'svc' });
          totalMissing += 1;
        } else {
          compliantShifts++;
        }
      }
    }
  });

  // Calculate Metrics
  const complianceRate = Math.round((compliantShifts / Math.max(1, totalShifts)) * 100);
  const totalWeekMins = filtered
    .filter(r => currentWeekDates.includes(r.date))
    .reduce((sum, r) => sum + (r.mins || 0), 0);
  const totalWeekHours = (totalWeekMins / 60).toFixed(0);
  const staffCount = Object.keys(weeklyWorkload).length;

  // 1. Render KPIs
  const elComp = document.getElementById('kpiWeeklyCompliance');
  const elCompSub = document.getElementById('kpiWeeklyComplianceSub');
  const elMiss = document.getElementById('kpiWeeklyMissing');
  const elHours = document.getElementById('kpiWeeklyHours');
  const elStaff = document.getElementById('kpiWeeklyStaffCount');

  if (elComp) {
    elComp.textContent = `${complianceRate}%`;
    elComp.className = `kpi-val ${complianceRate >= 80 ? 'emerald' : (complianceRate >= 50 ? 'amber' : 'coral')}`;
  }
  if (elCompSub) elCompSub.textContent = `${compliantShifts}/${totalShifts} ca chuẩn`;
  if (elMiss) {
    elMiss.textContent = `${totalMissing}`;
    elMiss.className = `kpi-val ${totalMissing === 0 ? 'emerald' : 'coral'}`;
  }
  if (elHours) elHours.textContent = `${totalWeekHours}h`;
  if (elStaff) elStaff.textContent = `${staffCount} NV`;

  // 2. Render Anomalies
  const anomList = document.getElementById('listWeeklyAnomalies');
  const anomBadge = document.getElementById('badgeAnomalyCount');
  if (anomList) {
    anomList.innerHTML = '';
    if (weeklyAnomalies.length === 0) {
      if (anomBadge) {
        anomBadge.className = 'card-section-badge ok';
        anomBadge.textContent = '0 lỗi';
      }
      anomList.innerHTML = '<div style="font-size:12px; color:var(--accent-emerald); padding:6px 0; text-align:center; font-weight:600;">✓ Toàn tuần đạt 100% đủ nhân sự</div>';
    } else {
      if (anomBadge) {
        anomBadge.className = 'card-section-badge';
        anomBadge.textContent = `${weeklyAnomalies.length} ca thiếu`;
      }

      const limit = 3;
      const primaryAnoms = weeklyAnomalies.slice(0, limit);
      const extraAnoms = weeklyAnomalies.slice(limit);

      const renderRow = (anom, targetContainer) => {
        const row = document.createElement('div');
        row.className = `anomaly-item ${anom.type === 'empty' ? 'empty' : ''}`;
        row.innerHTML = `
          <span>${anom.text}</span>
          <span style="font-size:12px; color:var(--accent-coral); font-weight:700;">Xem ►</span>
        `;
        row.addEventListener('click', () => {
          state.selectedDateStr = anom.dStr;
          renderTabRoster();
        });
        targetContainer.appendChild(row);
      };

      primaryAnoms.forEach(anom => renderRow(anom, anomList));

      if (extraAnoms.length > 0) {
        const extraWrap = document.createElement('div');
        extraWrap.id = 'extraAnomaliesWrap';
        extraWrap.style.display = 'none';
        extraWrap.style.flexDirection = 'column';
        extraWrap.style.gap = '4px';
        extraWrap.style.marginTop = '4px';
        extraAnoms.forEach(anom => renderRow(anom, extraWrap));
        anomList.appendChild(extraWrap);

        const btnToggle = document.createElement('button');
        btnToggle.type = 'button';
        btnToggle.className = 'section-expand-btn';
        btnToggle.innerHTML = `<span>Xem thêm (${extraAnoms.length} ca thiếu khác)</span> <span>▾</span>`;
        btnToggle.onclick = () => {
          const isHidden = (extraWrap.style.display === 'none');
          extraWrap.style.display = isHidden ? 'flex' : 'none';
          btnToggle.innerHTML = isHidden
            ? '<span>Thu gọn danh sách</span> <span>▴</span>'
            : `<span>Xem thêm (${extraAnoms.length} ca thiếu khác)</span> <span>▾</span>`;
        };
        anomList.appendChild(btnToggle);
      }
    }
  }

  // 3. Render Workload Bars
  const workloadList = document.getElementById('listWeeklyWorkload');
  if (workloadList) {
    workloadList.innerHTML = '';
    const sorted = Object.entries(weeklyWorkload).sort((a, b) => b[1] - a[1]);
    const topStaff = sorted.slice(0, 5);
    const maxShifts = topStaff.length > 0 ? topStaff[0][1] : 1;

    if (topStaff.length === 0) {
      workloadList.innerHTML = '<div style="font-size:12px; color:var(--text-muted); text-align:center; padding:6px 0;">Chưa có dữ liệu chấm công tuần này</div>';
    } else {
      topStaff.forEach(([name, shifts]) => {
        const pct = Math.min(100, Math.round((shifts / maxShifts) * 100));
        const colorClass = shifts >= 10 ? 'heavy' : (shifts >= 6 ? 'moderate' : '');
        const row = document.createElement('div');
        row.className = 'workload-row';
        row.innerHTML = `
          <span class="workload-name" title="${name}">${name}</span>
          <div class="workload-bar-wrap">
            <div class="workload-bar-fill ${colorClass}" style="width: ${pct}%;"></div>
          </div>
          <span class="workload-count">${shifts} ca</span>
        `;
        workloadList.appendChild(row);
      });
    }
  }
}

// --------------------------------------------------------------------------
// TAB 3: PAYSLIP & EXACT RECEIPT FORM & TELEGRAM WEBHOOK
// --------------------------------------------------------------------------
