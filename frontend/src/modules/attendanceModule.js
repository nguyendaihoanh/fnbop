// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// ATTENDANCE & SOP MODULE: LIVE CLOCK, CHECK-IN/OUT, SLIDER & MANAGER ACTIONS
// ==========================================================================

import { showToast, safeErrorDetail } from "../utils/toast.js";
import { showConfirmDialog } from "../utils/dialog.js";
import { escapeHtml } from "../utils/formatters.js";
import { updateSheetScrollLock } from "../store/authStore.js";
import { state } from "../store/state.js";
import { triggerHaptic, setupPushNotifications } from "../utils/haptics.js";
import {
  fetchAttendanceStatusApi,
  checkInAttendanceApi,
  checkOutAttendanceApi,
  fetchSOPApi,
  fetchPendingManagerCheckoutsApi,
  managerDeleteShiftApi,
  managerReopenShiftApi,
  managerManualCloseShiftApi,
  autoCloseCheckApi,
  resetDevLogsApi
} from "../api/attendanceApi.js";

// --------------------------------------------------------------------------
// ATTENDANCE & SOP MODULE (FNBOPS STORE)
// --------------------------------------------------------------------------
state.simulatedWifiMode = false; // Default FALSE on production
state.attendanceClockInterval = null;
state.currentActiveAttendance = null;

export function setupAttendanceModule() {
  // Live Clock
  if (!state.attendanceClockInterval) {
    state.attendanceClockInterval = setInterval(() => {
      const el = document.getElementById('liveClock');
      if (el) {
        const d = new Date();
        el.textContent = d.toTimeString().split(' ')[0];
      }
    }, 1000);
  }

  // Dev / Simulator Visibility - Only available on localhost with ?dev=1
  const devStrip = document.getElementById('devSimulatorStrip');
  const isLocalDev = typeof window !== 'undefined' && window.location && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');
  const isExplicitDev = isLocalDev && window.location.search && window.location.search.includes('dev=1');
  if (devStrip) {
    if (isExplicitDev) {
      devStrip.style.display = 'flex';
    } else {
      devStrip.style.display = 'none';
    }
  }

  // Simulator Buttons
  const btnWifi = document.getElementById('btnSimulateWifi');
  const btn4G = document.getElementById('btnSimulate4G');
  const btnReset = document.getElementById('btnResetLogs');
  const lblStatus = document.getElementById('devWifiStatusLabel');

  if (btnWifi && btn4G) {
    btnWifi.onclick = () => {
      state.simulatedWifiMode = true;
      if (lblStatus) {
        lblStatus.textContent = 'WiFi Quán';
        lblStatus.style.color = 'var(--accent-emerald)';
      }
      loadAttendanceTab();
    };
    btn4G.onclick = () => {
      state.simulatedWifiMode = false;
      if (lblStatus) {
        lblStatus.textContent = '4G Ngoài Quán';
        lblStatus.style.color = 'var(--accent-coral)';
      }
      loadAttendanceTab();
    };
  }

  if (btnReset) {
    btnReset.onclick = async () => {
      try {
        await fetch('/api/v1/cc/attendance/dev/reset-logs', { method: 'POST' });
        loadAttendanceTab();
        if (typeof renderStaffPortal === 'function' && document.getElementById('staffPortalContainer') && document.getElementById('staffPortalContainer').style.display !== 'none') {
          (window.renderStaffPortal || function(){})();
        }
      } catch (e) {
        console.error(e);
      }
    };
  }

  // SOP Checklist Collapsible Toggle
  const btnToggleSop = document.getElementById('btnToggleSopContent');
  const sopBody = document.getElementById('sopBodyContent');
  const sopQuick = document.getElementById('sopQuickPreview');
  const txtToggleSop = document.getElementById('txtToggleSop');
  const iconToggleSop = document.getElementById('iconToggleSop');
  if (btnToggleSop && sopBody && !btnToggleSop.dataset.bound) {
    btnToggleSop.dataset.bound = 'true';
    btnToggleSop.addEventListener('click', () => {
      const isExpanded = (sopBody.style.display === 'block' || (sopQuick && sopQuick.style.display === 'flex'));
      if (isExpanded) {
        sopBody.style.display = 'none';
        if (sopQuick) sopQuick.style.display = 'none';
        if (txtToggleSop) txtToggleSop.textContent = 'Mở xem checklist';
        if (iconToggleSop) iconToggleSop.textContent = '▾';
      } else {
        sopBody.style.display = 'block';
        if (sopQuick) sopQuick.style.display = 'none';
        if (txtToggleSop) txtToggleSop.textContent = 'Thu gọn';
        if (iconToggleSop) iconToggleSop.textContent = '▴';
      }
    });
  }

  // Review Hanging Shift Modal Bindings
  const btnCloseReviewHanging = document.getElementById('btnCloseReviewHangingSheet');
  if (btnCloseReviewHanging && !btnCloseReviewHanging.dataset.bound) {
    btnCloseReviewHanging.dataset.bound = 'true';
    btnCloseReviewHanging.addEventListener('click', closeReviewHangingShiftModal);
  }
  const btnSubmitReviewHanging = document.getElementById('btnSubmitReviewHanging');
  if (btnSubmitReviewHanging && !btnSubmitReviewHanging.dataset.bound) {
    btnSubmitReviewHanging.dataset.bound = 'true';
    btnSubmitReviewHanging.addEventListener('click', submitReviewHangingShift);
  }

  // SOP Role Pills (horizontal touch buttons)
  const rolePills = document.querySelectorAll('.sop-role-btn');
  rolePills.forEach(btn => {
    btn.onclick = () => {
      rolePills.forEach(b => {
        b.style.background = 'var(--bg-card-sub)';
        b.style.color = 'var(--text-secondary)';
        b.style.borderColor = 'var(--border)';
        b.style.fontWeight = '600';
        b.classList.remove('active');
      });
      btn.style.background = 'var(--accent-coral)';
      btn.style.color = '#fff';
      btn.style.borderColor = 'var(--accent-coral)';
      btn.style.fontWeight = '700';
      btn.classList.add('active');
      const roleKey = btn.getAttribute('data-role');
      renderSOPContent(roleKey, state.currentSopShift);
    };
  });

  // SOP Shift Pills (Ca Sáng & Ca Tối)
  const shiftPills = document.querySelectorAll('.sop-shift-btn');
  shiftPills.forEach(btn => {
    btn.onclick = () => {
      shiftPills.forEach(b => {
        b.style.background = 'var(--bg-card-sub)';
        b.style.color = 'var(--text-secondary)';
        b.style.borderColor = 'var(--border)';
        b.style.fontWeight = '600';
        b.classList.remove('active');
      });
      btn.style.background = 'var(--accent-amber)';
      btn.style.color = '#000';
      btn.style.borderColor = 'var(--accent-amber)';
      btn.style.fontWeight = '700';
      btn.classList.add('active');
      state.currentSopShift = btn.getAttribute('data-shift') || 'sang';
      const activeRolePill = document.querySelector('.sop-role-btn.active');
      const roleKey = activeRolePill ? activeRolePill.getAttribute('data-role') : 'phuc_vu_trong_nha';
      renderSOPContent(roleKey, state.currentSopShift);
    };
  });

  // Primary Check-in / Check-out Button
  const btnAction = document.getElementById('btnCheckinPrimary');
  if (btnAction) {
    btnAction.onclick = async () => {
      await handleAttendanceAction();
    };
  }

  // Auto-close trigger
  const btnAutoClose = document.getElementById('btnAutoCloseTrigger');
  if (btnAutoClose) {
    btnAutoClose.onclick = async () => {
      try {
        btnAutoClose.disabled = true;
        btnAutoClose.textContent = 'Đang quét...';
        const token = localStorage.getItem('vnaigc_jwt');
        const res = await fetch('/api/v1/cc/attendance/manager/auto-close-check', { 
          method: 'POST',
          headers: {
            'Authorization': 'Bearer ' + (token || '')
          }
        });
        const d = await res.json();
        if (res.ok) {
          showToast(`Đã quét xong: Tự động đóng ${d.closed_count || 0} ca.`, 'success');
          loadPendingManagerCheckouts();
        } else {
          showToast(safeErrorDetail(d, 'Không thể quét auto-close'), 'error');
        }
      } catch (e) {
        console.error(e);
        showToast('Lỗi khi quét auto-close!', 'error');
      } finally {
        btnAutoClose.disabled = false;
        btnAutoClose.textContent = 'Đóng ca quên check-out';
      }
    };
  }
}

export async function loadAttendanceTab() {
  setupAttendanceModule();
  
  // 1. Check Network & User Status
  const user = localStorage.getItem('vnaigc_username') || (typeof currentUser !== 'undefined' && currentUser) || '';
  const dot = document.getElementById('netStatusDot');
  const title = document.getElementById('netStatusTitle');
  const desc = document.getElementById('netStatusDesc');
  const badge = document.getElementById('netLockBadge');
  const btn = document.getElementById('btnCheckinPrimary');
  const strip = document.getElementById('checkinResultStrip');

  try {
    const res = await fetch(`/api/v1/cc/attendance/status?username=${encodeURIComponent(user)}&dev_mode=${state.simulatedWifiMode}`);
    const data = await res.json();

    const isLocal = typeof window !== 'undefined' && window.location && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1');
    const isAllowed = isLocal ? (state.simulatedWifiMode || Boolean(data && data.is_cafe_wifi)) : Boolean(data && data.is_cafe_wifi);
    
    if (dot && title && badge && btn) {
      if (isAllowed) {
        const currentStoreName = (typeof window !== 'undefined' && window.currentStoreConfig && window.currentStoreConfig.store_name) ||
                                 (typeof localStorage !== 'undefined' && localStorage.getItem('vnaigc_store_name')) ||
                                 'Quán';
        const isEmergency = Boolean(data && data.is_emergency_remote && !data.is_matching_cafe_wifi);
        if (isEmergency) {
          dot.style.background = 'var(--accent-coral)';
          title.innerHTML = '<span style="display:inline-flex; align-items:center; gap:6px;">Chế độ khẩn cấp (Sự cố mạng quán)</span>';
          if (desc) desc.textContent = 'Quản lý mở quyền điểm danh ngoài quán';
          badge.textContent = 'KHẨN CẤP';
          badge.style.background = 'var(--accent-coral-sub)';
          badge.style.color = 'var(--accent-coral)';
          badge.style.border = '1px solid rgba(239, 68, 68, 0.3)';
        } else {
          dot.style.background = 'var(--accent-emerald)';
          title.innerHTML = `<span style="display:inline-flex; align-items:center; gap:6px;">Đã kết nối WiFi ${currentStoreName}</span>`;
          if (desc) desc.textContent = 'Vị trí hợp lệ để chấm công vào ca';
          badge.textContent = 'HỢP LỆ';
          badge.style.background = 'var(--accent-emerald-sub)';
          badge.style.color = 'var(--accent-emerald)';
          badge.style.border = '1px solid rgba(16, 185, 129, 0.2)';
        }
        btn.disabled = false;
        btn.style.opacity = '1';
        if (strip && !state.currentActiveAttendance) {
          strip.innerHTML = '';
        }
      } else {
        const currentStoreName = (typeof window !== 'undefined' && window.currentStoreConfig && window.currentStoreConfig.store_name) ||
                                 (typeof localStorage !== 'undefined' && localStorage.getItem('vnaigc_store_name')) ||
                                 'Quán';
        dot.style.background = 'var(--badge-neutral-text)';
        title.innerHTML = '<span style="display:inline-flex; align-items:center; gap:6px;">Chế độ xem từ xa <span style="font-weight:400; opacity:0.8;">• Cần WiFi Quán</span></span>';
        if (desc) desc.textContent = `Kết nối WiFi ${currentStoreName} để chấm công`;
        badge.textContent = 'NGOÀI QUÁN';
        badge.style.background = 'var(--badge-neutral-bg)';
        badge.style.color = 'var(--badge-neutral-text)';
        badge.style.border = '1px solid var(--badge-neutral-border)';
        badge.style.whiteSpace = 'nowrap';
        badge.style.flexShrink = '0';
        btn.disabled = true;
        btn.style.opacity = '0.6';
        if (strip) {
          strip.innerHTML = '<div style="display:flex; align-items:center; gap:8px; color:var(--text-secondary); font-size:12px; font-weight:500; background:var(--bg-card-sub); border:1px solid var(--border); border-radius:10px; padding:8px 12px; margin-top:8px;"><svg xmlns=\"http://www.w3.org/2000/svg\" width=\"15\" height=\"15\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" style=\"color:var(--text-muted); flex-shrink:0;\"><path d=\"M5 12.55a11 11 0 0 1 14.08 0\"/><path d=\"M1.42 9a16 16 0 0 1 21.16 0\"/><path d=\"M8.53 16.11a6 6 0 0 1 6.95 0\"/><line x1=\"12\" y1=\"20\" x2=\"12.01\" y2=\"20\"/></svg><span>Vui lòng kết nối WiFi <strong>FnBOps Store</strong> tại quán để chấm công</span></div>';
        }
      }
    }

    // Active shift badge
    const shiftBadge = document.getElementById('shiftBadge');
    if (shiftBadge) {
      if (data.active_shift) {
        shiftBadge.textContent = data.active_shift.name.toUpperCase();
      } else if (data.upcoming_shift) {
        const up = data.upcoming_shift;
        shiftBadge.textContent = `SẮP TỚI: ${up.name.toUpperCase()}`;
      } else {
        shiftBadge.textContent = 'NGOÀI KHUNG CA (HỖ TRỢ)';
      }
    }

    // Record state: ACTIVE vs CLOSED vs COMPLETED
    state.currentActiveAttendance = data.user_record;
    const activeShiftCard = document.getElementById('activeShiftCard');
    const userRole = (localStorage.getItem('vnaigc_role') || (typeof currentUserRole !== 'undefined' ? currentUserRole : 'STAFF')).toUpperCase();
    if (userRole === 'ADMIN') {
      if (activeShiftCard) activeShiftCard.style.display = 'none';
    } else {
      if (activeShiftCard) activeShiftCard.style.display = 'block';
    }

    const completedCard = document.getElementById('completedShiftCard');
    const checkinArea = document.getElementById('checkinActionArea');
    const completedDetails = document.getElementById('completedShiftDetails');
    const completedNextNotice = document.getElementById('completedShiftNextNotice');

    const pressHoldBtn = document.getElementById('btnPressHoldCheckout');
    const sliderContainer = document.getElementById('sliderCheckoutContainer');

    if (data.shift_state === 'COMPLETED' && data.last_closed_record) {
      // State 3: Shift is COMPLETED! Show summary card, hide button and checkout controls
      if (checkinArea) checkinArea.style.display = 'none';
      if (pressHoldBtn) {
        pressHoldBtn.classList.add('hidden');
        if (pressHoldBtn.style && typeof pressHoldBtn.style.setProperty === 'function') {
          pressHoldBtn.style.setProperty('display', 'none', 'important');
        } else if (pressHoldBtn.style) {
          pressHoldBtn.style.display = 'none';
        }
      }
      if (sliderContainer) sliderContainer.style.display = 'none';
      if (btn) {
        btn.classList.add('hidden');
        if (btn.style && typeof btn.style.setProperty === 'function') {
          btn.style.setProperty('display', 'none', 'important');
        } else if (btn.style) {
          btn.style.display = 'none';
        }
        btn.disabled = false;
        btn.textContent = 'Vào Ca Ngay';
      }
      if (completedCard) {
        window._lastClosedRecord = data.last_closed_record;
        completedCard.style.display = 'block';
        if (completedDetails) {
          completedDetails.textContent = `Vào: ${data.last_closed_record.checkin_time} • Ra: ${data.last_closed_record.checkout_time} (${data.last_closed_record.total_mins} phút)`;
        }
        if (completedNextNotice) {
          const nextShiftName = data.last_closed_record.shift_key === 'sang' ? 'Ca Tối' : 'Ca Sáng ngày mai';
          completedNextNotice.textContent = `Ca tiếp theo: ${nextShiftName}`;
        }
        
        const managerActions = document.getElementById('completedShiftManagerActions');
        const linkStaffAskManager = document.getElementById('linkStaffAskManager');
        const userRole = (localStorage.getItem('vnaigc_role') || (typeof currentUserRole !== 'undefined' ? currentUserRole : 'STAFF')).toUpperCase();
        if (['MANAGER', 'ADMIN'].includes(userRole)) {
          if (managerActions) managerActions.style.display = 'flex';
          if (linkStaffAskManager) linkStaffAskManager.style.display = 'none';
        } else {
          if (managerActions) managerActions.style.display = 'none';
          if (linkStaffAskManager) linkStaffAskManager.style.display = 'inline';
        }
      }
      if (strip) strip.style.display = 'none';
    } else if (data.shift_state === 'OUTSIDE_SHIFT_HOURS') {
      // State 4: Outside official shift window
      if (completedCard) completedCard.style.display = 'none';
      if (checkinArea) checkinArea.style.display = 'block';
      if (pressHoldBtn) {
        pressHoldBtn.classList.add('hidden');
        pressHoldBtn.style.setProperty('display', 'none', 'important');
      }
      if (sliderContainer) sliderContainer.style.display = 'none';
      if (strip) strip.style.display = 'block';

      if (btn && strip) {
        btn.classList.remove('hidden');
        if (btn.style && typeof btn.style.removeProperty === 'function') {
          btn.style.removeProperty('display');
        } else if (btn.style) {
          btn.style.display = '';
        }
        btn.style.display = 'flex';
        btn.textContent = 'NGOÀI KHUNG GIỜ CA TRỰC';
        btn.style.background = 'var(--bg-card)';
        btn.style.border = '1px solid var(--border)';
        btn.style.color = 'var(--text-muted)';
        btn.disabled = !state.simulatedWifiMode;
        strip.innerHTML = '<span style="color:var(--text-muted);">Quán hoạt động theo 2 ca: Ca Sáng và Ca Tối. Cổng check-in mở trước ca 30 phút.</span>';
      }
    } else {
      // State 1 or 2: Ready to check-in or In-progress
      if (completedCard) completedCard.style.display = 'none';
      if (checkinArea) checkinArea.style.display = 'block';
      if (strip) strip.style.display = 'block';

      if (data.user_record && !data.user_record.checkout_time) {
        // State 1: Currently checked in -> USE PRESS-AND-HOLD TO CHECK-OUT
        if (btn) {
          btn.classList.add('hidden');
          if (btn.style && typeof btn.style.setProperty === 'function') {
            btn.style.setProperty('display', 'none', 'important');
          } else if (btn.style) {
            btn.style.display = 'none';
          }
          btn.disabled = false;
          btn.textContent = 'Vào Ca Ngay';
        }
        if (pressHoldBtn) {
          pressHoldBtn.classList.remove('hidden');
          if (pressHoldBtn.style && typeof pressHoldBtn.style.removeProperty === 'function') {
            pressHoldBtn.style.removeProperty('display');
          } else if (pressHoldBtn.style) {
            pressHoldBtn.style.display = '';
          }
          pressHoldBtn.style.display = 'flex';
          initPressHoldCheckout();
        }
        if (sliderContainer) {
          sliderContainer.style.display = 'block';
          initCheckoutSlider();
        }
        const lateMsg = data.user_record.is_late 
          ? `<span style="color:var(--accent-coral); font-weight:700;">(TRỄ ${data.user_record.late_mins} PHÚT)</span>` 
          : '<span style="color:var(--accent-emerald); font-weight:700;">(ĐÚNG GIỜ)</span>';
        if (strip) {
          strip.innerHTML = `Đang trong ca trực: Vào lúc <strong>${data.user_record.checkin_time}</strong> ${lateMsg}. Giữ 1.2 giây để kết thúc ca.`;
        }
      } else {
        // State 2: Ready to check-in -> USE 1-TAP BUTTON
        if (pressHoldBtn) {
          pressHoldBtn.classList.add('hidden');
          if (pressHoldBtn.style && typeof pressHoldBtn.style.setProperty === 'function') {
            pressHoldBtn.style.setProperty('display', 'none', 'important');
          } else if (pressHoldBtn.style) {
            pressHoldBtn.style.display = 'none';
          }
        }
        if (sliderContainer) sliderContainer.style.display = 'none';
        if (btn) {
          btn.classList.remove('hidden');
          if (btn.style && typeof btn.style.removeProperty === 'function') {
            btn.style.removeProperty('display');
          } else if (btn.style) {
            btn.style.display = '';
          }
          btn.style.display = 'flex';
          btn.textContent = 'Vào Ca Ngay';
          btn.style.background = 'var(--accent-coral)';
          btn.style.color = '#FFF';
          btn.style.border = 'none';
          btn.disabled = !isAllowed;
        }
        if (strip && isAllowed) {
          const tolLimit = (data.active_shift && data.active_shift.tolerance_limit) 
            ? ` (trước ${data.active_shift.tolerance_limit})` 
            : '';
          strip.innerHTML = `Dung sai: Cho phép trễ tối đa 10 phút đầu ca${tolLimit}. Sau đó tính đi trễ.`;
        }
      }
    }
  } catch (e) {
    console.error('Status fetch error:', e);
  }

  // Load SOP based on currently active pill
  const activePill = document.querySelector('.sop-role-btn.active');
  if (activePill) {
    renderSOPContent(activePill.getAttribute('data-role'));
  }

  // Load Manager Panel if user has role
  const userRole = localStorage.getItem('vnaigc_role') || (typeof currentUserRole !== 'undefined' ? currentUserRole : 'STAFF');
  if (['MANAGER', 'ADMIN'].includes(userRole.toUpperCase())) {
    loadPendingManagerCheckouts();
  }

  // Proactively register Web Push subscription if permission available
  const curUser = localStorage.getItem('vnaigc_username') || (typeof currentUser !== 'undefined' && currentUser);
  if (curUser) {
    setupPushNotifications(curUser);
  }
}

state.checkoutSliderBound = false;

export function getActiveShiftElapsedMinutes() {
  if (!state.currentActiveAttendance) return 0;
  if (state.currentActiveAttendance.created_at) {
    try {
      const dtIn = new Date(state.currentActiveAttendance.created_at);
      const diff = Math.floor((new Date() - dtIn) / 60000);
      return Math.max(0, diff);
    } catch (e) {}
  }
  if (state.currentActiveAttendance.checkin_time) {
    try {
      const [h, m] = state.currentActiveAttendance.checkin_time.split(':').map(Number);
      const now = new Date();
      const inDate = new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m);
      const diff = Math.floor((now - inDate) / 60000);
      return Math.max(0, diff);
    } catch (e) {}
  }
  return 0;
}

state.checkoutSliderBound = false;
state.pressHoldBound = false;

// Cross-environment requestAnimationFrame & cancelAnimationFrame
const requestAnim = (typeof requestAnimationFrame !== 'undefined')
  ? requestAnimationFrame
  : (cb) => setTimeout(() => cb(Date.now()), 16);

const cancelAnim = (typeof cancelAnimationFrame !== 'undefined')
  ? cancelAnimationFrame
  : (id) => clearTimeout(id);

let holdRafId = null;
let isHolding = false;
let isCompleted = false;

export function resetPressHoldCheckout() {
  isHolding = false;
  isCompleted = false;
  if (holdRafId) {
    cancelAnim(holdRafId);
    holdRafId = null;
  }

  const btn = document.getElementById('btnPressHoldCheckout');
  const bar = document.getElementById('pressHoldProgressBar');
  const textEl = document.getElementById('pressHoldBtnText');

  if (btn) {
    btn.classList.remove('holding', 'completed');
    btn.style.transform = '';
  }
  if (bar) {
    bar.style.transition = 'width 0.2s ease';
    bar.style.width = '0%';
  }
  if (textEl) {
    textEl.textContent = 'Nhấn giữ để Tan Ca';
  }

  // Legacy slider compatibility
  const thumb = document.getElementById('sliderThumb');
  const fill = document.getElementById('sliderTrackFill');
  const text = document.getElementById('sliderTrackText');
  if (thumb) {
    thumb.style.transition = 'transform 0.25s cubic-bezier(0.2, 0.8, 0.2, 1)';
    thumb.style.transform = 'translateX(0px)';
  }
  if (fill) {
    fill.style.transition = 'width 0.25s cubic-bezier(0.2, 0.8, 0.2, 1)';
    fill.style.width = '0%';
  }
  if (text) {
    text.style.transition = 'opacity 0.25s ease';
    text.style.opacity = '1';
  }
}

export function openEarlyCheckoutModal(elapsedMins) {
  const modal = document.getElementById('earlyCheckoutModal');
  const countEl = document.getElementById('earlyMinsCount');
  if (countEl) countEl.textContent = elapsedMins;
  if (modal) modal.classList.add('active');

  const btnCancel = document.getElementById('btnCancelEarlyCheckout');
  const btnConfirm = document.getElementById('btnConfirmEarlyCheckout');

  if (btnCancel) {
    btnCancel.onclick = () => {
      modal.classList.remove('active');
      resetPressHoldCheckout();
    };
  }

  if (btnConfirm) {
    btnConfirm.onclick = async () => {
      modal.classList.remove('active');
      await executeStaffCheckout(true);
    };
  }
}

export async function executeStaffCheckout(confirmEarly = false) {
  const strip = document.getElementById('checkinResultStrip');
  const user = localStorage.getItem('vnaigc_username') || (typeof currentUser !== 'undefined' && currentUser) || '';

  try {
    if (strip) strip.innerHTML = '<span style="color:var(--accent-amber); font-weight:700;">⏳ Đang xác nhận tan ca...</span>';
    const token = localStorage.getItem('vnaigc_jwt');
    const reqHeaders = { 'Content-Type': 'application/json' };
    if (token) reqHeaders['Authorization'] = 'Bearer ' + token;

    const res = await fetch('/api/v1/cc/attendance/checkout', {
      method: 'POST',
      headers: reqHeaders,
      body: JSON.stringify({
        username: user,
        dev_override_wifi: (typeof window !== 'undefined' && window.location && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) ? state.simulatedWifiMode : false,
        confirm_early: confirmEarly
      })
    });
    const d = await res.json();
    if (res.ok) {
      triggerHaptic('success');
      showToast(d.message || 'Check-out thành công!', 'success');
      if (strip) strip.innerHTML = `<span style="color:var(--accent-emerald); font-weight:700;">${d.message}</span>`;
    } else {
      triggerHaptic('error');
      showToast(safeErrorDetail(d, 'Lỗi Check-out'), 'error');
      if (strip) strip.innerHTML = `<span style="color:var(--accent-coral); font-weight:700;">${d.detail || 'Lỗi Check-out'}</span>`;
      resetPressHoldCheckout();
    }
  } catch (e) {
    triggerHaptic('error');
    showToast(`Lỗi Check-out: ${e.message}`, 'error');
    if (strip) strip.innerHTML = `<span style="color:var(--accent-coral); font-weight:700;">Lỗi: ${e.message}</span>`;
    resetPressHoldCheckout();
  } finally {
    await loadAttendanceTab();
    if (typeof renderStaffPortal === 'function' && document.getElementById('staffPortalContainer') && document.getElementById('staffPortalContainer').style.display !== 'none') {
      (window.renderStaffPortal || function(){})();
    }
  }
}

export function initPressHoldCheckout() {
  resetPressHoldCheckout();
  const btn = document.getElementById('btnPressHoldCheckout');
  if (!btn) {
    if (document.getElementById('sliderCheckoutContainer')) {
      initLegacyCheckoutSlider();
    }
    return;
  }

  if (state.pressHoldBound) return;
  state.pressHoldBound = true;

  const HOLD_DURATION = 1200; // 1.2s

  function onHoldStart(e) {
    if (e && e.button && e.button !== 0) return;
    if (isHolding || isCompleted) return;
    isHolding = true;

    const currentBtn = document.getElementById('btnPressHoldCheckout');
    const bar = document.getElementById('pressHoldProgressBar');
    const textEl = document.getElementById('pressHoldBtnText');

    if (currentBtn) currentBtn.classList.add('holding');
    if (bar) {
      bar.style.transition = 'none';
      bar.style.width = '0%';
    }
    if (textEl) {
      textEl.textContent = 'Nhấn giữ để Tan Ca';
    }

    const startTime = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();

    function tick(now) {
      if (!isHolding) return;
      const currentNow = now || ((typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now());
      const elapsed = currentNow - startTime;
      const progress = Math.min(1, Math.max(0, elapsed / HOLD_DURATION));

      if (bar) {
        bar.style.width = `${(progress * 100).toFixed(1)}%`;
      }

      if (progress < 1) {
        holdRafId = requestAnim(tick);
      } else {
        onHoldSuccess();
      }
    }

    holdRafId = requestAnim(tick);
  }

  function onHoldEnd() {
    if (!isHolding || isCompleted) return;
    isHolding = false;
    if (holdRafId) {
      cancelAnim(holdRafId);
      holdRafId = null;
    }

    const currentBtn = document.getElementById('btnPressHoldCheckout');
    const bar = document.getElementById('pressHoldProgressBar');
    const textEl = document.getElementById('pressHoldBtnText');

    if (currentBtn) currentBtn.classList.remove('holding');
    if (bar) {
      bar.style.transition = 'width 0.2s ease';
      bar.style.width = '0%';
    }
    if (textEl) {
      textEl.textContent = 'Nhấn giữ để Tan Ca';
    }
  }

  async function onHoldSuccess() {
    isHolding = false;
    isCompleted = true;
    if (holdRafId) {
      cancelAnim(holdRafId);
      holdRafId = null;
    }

    const currentBtn = document.getElementById('btnPressHoldCheckout');
    const bar = document.getElementById('pressHoldProgressBar');
    const textEl = document.getElementById('pressHoldBtnText');

    if (currentBtn) {
      currentBtn.classList.remove('holding');
      currentBtn.classList.add('completed');
    }
    if (bar) {
      bar.style.transition = 'none';
      bar.style.width = '100%';
    }
    if (textEl) {
      textEl.textContent = 'ĐANG XÁC NHẬN TAN CA...';
    }

    // Haptic feedback (1.2s hold success)
    if (typeof navigator !== 'undefined' && navigator.vibrate) {
      try {
        navigator.vibrate([30, 50, 30]);
      } catch (err) {}
    }

    // Check shift duration
    const elapsedMins = getActiveShiftElapsedMinutes();
    if (elapsedMins < 60) {
      openEarlyCheckoutModal(elapsedMins);
    } else {
      await executeStaffCheckout(false);
    }
  }

  // Pointer Events (Preferred for mouse, touch, stylus)
  btn.addEventListener('pointerdown', onHoldStart);
  btn.addEventListener('pointerup', onHoldEnd);
  btn.addEventListener('pointerleave', onHoldEnd);
  btn.addEventListener('pointercancel', onHoldEnd);

  // Touch Events (Fallback for WebViews without PointerEvents)
  btn.addEventListener('touchstart', (e) => {
    if (!isHolding) onHoldStart(e);
  }, { passive: true });
  btn.addEventListener('touchend', () => {
    onHoldEnd();
  }, { passive: true });
  btn.addEventListener('touchcancel', () => {
    onHoldEnd();
  }, { passive: true });

  // Mouse Events (Fallback)
  btn.addEventListener('mousedown', (e) => {
    if (!isHolding) onHoldStart(e);
  });
  btn.addEventListener('mouseup', () => {
    onHoldEnd();
  });

  // Prevent native context menu on long-press
  btn.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    return false;
  });
}

function initLegacyCheckoutSlider() {
  resetPressHoldCheckout();
  const container = document.getElementById('sliderCheckoutContainer');
  const thumb = document.getElementById('sliderThumb');
  const fill = document.getElementById('sliderTrackFill');
  const text = document.getElementById('sliderTrackText');
  if (!container || !thumb || state.checkoutSliderBound) return;

  state.checkoutSliderBound = true;
  let isDragging = false;
  let startX = 0;
  let currentDx = 0;

  function getMaxSlide() {
    return Math.max(10, container.clientWidth - thumb.offsetWidth - 6);
  }

  function onDragStart(clientX) {
    isDragging = true;
    startX = clientX;
    thumb.style.transition = 'none';
    if (fill) fill.style.transition = 'none';
    if (text) text.style.transition = 'none';
  }

  function onDragMove(clientX) {
    if (!isDragging) return;
    const maxSlide = getMaxSlide();
    let dx = clientX - startX;
    if (dx < 0) dx = 0;
    if (dx > maxSlide) dx = maxSlide;
    currentDx = dx;

    thumb.style.transform = `translateX(${dx}px)`;
    if (fill) fill.style.width = `${(dx / maxSlide) * 100}%`;
    if (text) text.style.opacity = `${Math.max(0, 1 - (dx / maxSlide) * 1.5)}`;
  }

  async function onDragEnd() {
    if (!isDragging) return;
    isDragging = false;
    const maxSlide = getMaxSlide();

    if (currentDx >= maxSlide * 0.82) {
      thumb.style.transform = `translateX(${maxSlide}px)`;
      if (fill) fill.style.width = '100%';
      if (text) text.style.opacity = '0';

      const elapsedMins = getActiveShiftElapsedMinutes();
      if (elapsedMins < 60) {
        openEarlyCheckoutModal(elapsedMins);
      } else {
        await executeStaffCheckout(false);
      }
    } else {
      resetPressHoldCheckout();
    }
    currentDx = 0;
  }

  thumb.addEventListener('mousedown', (e) => {
    onDragStart(e.clientX);
    const onMouseMove = (ev) => onDragMove(ev.clientX);
    const onMouseUp = () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      onDragEnd();
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  });

  thumb.addEventListener('touchstart', (e) => {
    if (e.touches.length > 0) {
      onDragStart(e.touches[0].clientX);
    }
  }, { passive: true });

  window.addEventListener('touchmove', (e) => {
    if (isDragging && e.touches.length > 0) {
      onDragMove(e.touches[0].clientX);
    }
  }, { passive: true });

  window.addEventListener('touchend', () => {
    if (isDragging) {
      onDragEnd();
    }
  });
}

// Aliases for full compatibility
export const resetCheckoutSlider = resetPressHoldCheckout;
export const initCheckoutSlider = initPressHoldCheckout;

export async function handleQuickAttendanceAction() {
  if (state.currentActiveAttendance && !state.currentActiveAttendance.checkout_time) {
    // Currently in-progress: Trigger Check-out
    const elapsedMins = getActiveShiftElapsedMinutes();
    if (elapsedMins < 60) {
      openEarlyCheckoutModal(elapsedMins);
    } else {
      const ok = await showConfirmDialog({
        title: 'Kết Thúc Ca Làm Việc',
        message: 'Bạn có chắc chắn muốn kết thúc ca làm việc lúc này?',
        confirmText: 'Kết Thúc Ca',
        cancelText: 'Làm Tiếp',
        type: 'warning',
        icon: 'solar:alarm-bold'
      });
      if (ok) {
        await executeStaffCheckout(false);
      }
    }
  } else {
    // Not in-progress: Trigger Check-in
    await handleAttendanceAction();
  }
}

export async function handleAttendanceAction() {
  const btn = document.getElementById('btnCheckinPrimary');
  const strip = document.getElementById('checkinResultStrip');
  const user = localStorage.getItem('vnaigc_username') || (typeof currentUser !== 'undefined' && currentUser) || '';
  const role = (typeof currentStaffRole !== 'undefined' && currentStaffRole) ? currentStaffRole : (localStorage.getItem('vnaigc_position') || 'Phục vụ');
  const displayName = localStorage.getItem('vnaigc_name') || (typeof currentStaffName !== 'undefined' && currentStaffName) || user;

  // 1-TAP CHECK-IN
  try {
    if (typeof navigator !== 'undefined') navigator.vibrate?.(12);
    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Đang xác nhận vào ca...';
    }
    const token = localStorage.getItem('vnaigc_jwt');
    const reqHeaders = { 'Content-Type': 'application/json' };
    if (token) reqHeaders['Authorization'] = 'Bearer ' + token;

    const res = await fetch('/api/v1/cc/attendance/checkin', {
      method: 'POST',
      headers: reqHeaders,
      body: JSON.stringify({
        username: user,
        display_name: displayName,
        role: role,
        dev_override_wifi: (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? state.simulatedWifiMode : false
      })
    });
    const d = await res.json();
    if (res.ok) {
      triggerHaptic('success');
      showToast(d.message || 'Check-in thành công!', 'success');
      if (strip) strip.innerHTML = `<span style="color:var(--accent-emerald); font-weight:700;">${d.message}</span>`;
    } else {
      triggerHaptic('error');
      showToast(safeErrorDetail(d, 'Lỗi Check-in'), 'error');
      if (strip) strip.innerHTML = `<span style="color:var(--accent-coral); font-weight:700;">${d.detail || 'Lỗi Check-in'}</span>`;
    }
  } catch (e) {
    triggerHaptic('error');
    showToast(`Lỗi Check-in: ${e.message}`, 'error');
    if (strip) strip.innerHTML = `<span style="color:var(--accent-coral); font-weight:700;">Lỗi: ${e.message}</span>`;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Vào Ca Ngay';
    }
    await loadAttendanceTab();
    if (typeof renderStaffPortal === 'function' && document.getElementById('staffPortalContainer') && document.getElementById('staffPortalContainer').style.display !== 'none') {
      (window.renderStaffPortal || function(){})();
    }
  }
}

state.currentSopShift = (new Date().getHours() < 14) ? 'sang' : 'toi';

export async function renderSOPContent(roleKey, shiftKey) {
  const container = document.getElementById('sopPhasesContainer');
  if (!container) return;

  const targetShift = shiftKey || state.currentSopShift || ((new Date().getHours() < 14) ? 'sang' : 'toi');
  state.currentSopShift = targetShift;

  // Sync shift buttons UI
  const btnMorning = document.getElementById('btnSopShiftMorning');
  const btnEvening = document.getElementById('btnSopShiftEvening');
  if (btnMorning && btnEvening) {
    if (targetShift === 'sang') {
      btnMorning.style.background = 'var(--accent-amber)';
      btnMorning.style.color = '#000';
      btnMorning.style.borderColor = 'var(--accent-amber)';
      btnMorning.style.fontWeight = '700';
      btnMorning.classList.add('active');
      btnEvening.style.background = 'var(--bg-card-sub)';
      btnEvening.style.color = 'var(--text-secondary)';
      btnEvening.style.borderColor = 'var(--border)';
      btnEvening.style.fontWeight = '600';
      btnEvening.classList.remove('active');
    } else {
      btnEvening.style.background = 'var(--accent-amber)';
      btnEvening.style.color = '#000';
      btnEvening.style.borderColor = 'var(--accent-amber)';
      btnEvening.style.fontWeight = '700';
      btnEvening.classList.add('active');
      btnMorning.style.background = 'var(--bg-card-sub)';
      btnMorning.style.color = 'var(--text-secondary)';
      btnMorning.style.borderColor = 'var(--border)';
      btnMorning.style.fontWeight = '600';
      btnMorning.classList.remove('active');
    }
  }

  try {
    const res = await fetch(`/api/v1/cc/attendance/sop?role=${encodeURIComponent(roleKey)}`);
    const data = await res.json();
    const sop = data.sop;

    if (!sop) {
      container.innerHTML = '<div style="font-size:12px; color:var(--text-muted);">Chưa có dữ liệu quy trình.</div>';
      return;
    }

    let activePhases = sop.phases;
    if (sop.shifts && sop.shifts[targetShift] && sop.shifts[targetShift].phases) {
      activePhases = sop.shifts[targetShift].phases;
    }

    if (!activePhases) {
      container.innerHTML = '<div style="font-size:12px; color:var(--text-muted);">Chưa có dữ liệu quy trình cho ca này.</div>';
      return;
    }

    const phases = [
      { key: 'open', label: '1. Đầu Ca (Mở / Đón Khách)', color: 'var(--accent-coral)' },
      { key: 'running', label: '2. Trong Ca (Vận Hành & Rửa Ly Cuốn Chiếu)', color: 'var(--accent-amber)' },
      { key: 'close', label: '3. Cuối Ca (Tổng Dọn Sạch & Check-out)', color: 'var(--accent-emerald)' }
    ];

    let html = '';
    phases.forEach(p => {
      const phaseData = activePhases[p.key];
      if (!phaseData) return;

      html += `
        <div style="background: var(--bg-card-sub); border: 1px solid var(--border); border-radius: 10px; padding: 12px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid var(--border);">
            <span style="font-size: 12px; font-weight: 700; color: ${p.color};">${phaseData.phase_name || p.label}</span>
            <span style="font-size: 12px; color: var(--text-muted);">${phaseData.time_window || ''}</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 6px;">
      `;

      phaseData.tasks.forEach(t => {
        html += `
          <div style="display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: var(--text-primary); line-height: 1.4;">
            <span style="color: ${p.color}; font-size: 13px; font-weight: 800; line-height: 1; margin-top: 3px; flex-shrink: 0;">•</span>
            <span style="flex: 1;">${t.task}</span>
          </div>
        `;
      });

      html += `
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = '<div style="font-size:12px; color:var(--text-muted);">Lỗi khi tải dữ liệu checklist.</div>';
  }
}


export async function loadPendingManagerCheckouts() {
  const listEl = document.getElementById('pendingCheckoutsList');
  if (!listEl) return;
  const token = localStorage.getItem('vnaigc_jwt');
  if (!token) return;

  try {
    const [resPending, resEx] = await Promise.all([
      fetch('/api/v1/cc/attendance/manager/pending', { headers: { 'Authorization': 'Bearer ' + token } }),
      fetch('/api/v1/cc/push/manager/exceptions', { headers: { 'Authorization': 'Bearer ' + token } })
        .catch(() => fetch('/api/v1/cc/notifications/push/manager/exceptions', { headers: { 'Authorization': 'Bearer ' + token } }).catch(() => null))
    ]);

    if (!resPending.ok) {
      if (resPending.status === 401 || resPending.status === 403) {
        listEl.innerHTML = '<div style="color:var(--text-muted);">Yêu cầu quyền Quản lý để xem danh sách này.</div>';
        return;
      }
    }

    const data = await resPending.json();
    const pendingList = data.records || [];
    const closedList = data.closed_today || [];
    const exData = resEx && resEx.ok ? await resEx.json() : null;

    const missingCheckins = (exData && exData.missing_checkin) || [];
    const missingRosters = (exData && exData.missing_roster_registration) || [];
    window._pendingMissingRosterList = missingRosters;

    let h = '';

    // 0. BÁO CÁO CẢNH BÁO QUẢN LÝ: CHƯA VÀO CA
    if (missingCheckins.length > 0) {
      h += `
        <div style="margin-bottom:8px; padding:8px 10px; background:rgba(239, 68, 68, 0.08); border:1px solid rgba(239, 68, 68, 0.25); border-radius:8px;">
          <div style="font-weight:700; color:var(--accent-coral); font-size:13px; margin-bottom:4px; display:flex; justify-content:space-between; align-items:center;">
            <span style="display:inline-flex; align-items:center; gap:4px;"><iconify-icon icon="solar:danger-triangle-bold" width="14" height="14" style="color:var(--accent-coral);"></iconify-icon> Đang trễ ca (${missingCheckins.length})</span>
          </div>
          ${missingCheckins.map(m => `
            <div style="padding:6px 0; border-bottom:1px dashed rgba(239, 68, 68, 0.2); display:flex; justify-content:space-between; align-items:center; font-size:12px;">
              <div>
                <strong>${escapeHtml(m.name)}</strong> <span style="color:var(--text-secondary);">(${escapeHtml(m.shift)} - ${escapeHtml(m.slot)})</span>
                <div style="color:${m.is_overdue ? 'var(--accent-coral)' : 'var(--text-muted)'}; font-size:11px;">${escapeHtml(m.status_text)} lúc ${escapeHtml(m.start_time)}</div>
              </div>
              <button type="button" onclick="promptManagerRemindStaff('${escapeHtml(m.username)}', 'CHECKIN')" style="background:var(--accent-coral); color:#fff; border:none; border-radius:6px; padding:4px 8px; font-size:11px; font-weight:700; cursor:pointer;">
                Nhắc Vào Ca
              </button>
            </div>
          `).join('')}
        </div>
      `;
    }

    // 1. Ca Chưa Check-out (Treo giờ ca)
    if (pendingList.length > 0) {
      h += `<div style="margin-bottom:6px; font-weight:700; color:var(--accent-amber);">Ca chưa Check-out (${pendingList.length}):</div>`;
      pendingList.forEach(r => {
        const isHanging = r.is_hanging_pending || r.status === 'QUEN_CHECKOUT';
        const over48 = isHanging
          ? '<span style="color:var(--accent-coral); font-weight:700;">(Quên check-out • Tạm tính 0đ)</span>'
          : (r.is_over_48h 
            ? '<span style="color:var(--accent-coral); font-weight:700;">(Quá 48h - Sẽ tự đóng)</span>' 
            : `(${r.age_hours}h trước)`);
        h += `
          <div style="padding: 8px 0; border-bottom: 1px dotted var(--border); display: flex; justify-content: space-between; align-items: center; gap: 8px;">
            <div style="flex: 1;">
              <div><strong>${escapeHtml(r.display_name || r.username)}</strong> <span style="font-size:12px; color:var(--text-secondary);">${escapeHtml(r.shift_name)} ${escapeHtml(r.date)} (Vào: ${escapeHtml(r.checkin_time)})</span></div>
              <div style="font-size:12px; color:var(--text-muted);">${over48}</div>
            </div>
            <div style="display:flex; gap:4px;">
              ${isHanging ? `
                <button type="button" onclick="openReviewHangingShiftModal(${JSON.stringify(r).replace(/"/g, '&quot;')})" style="background:#059669; color:#fff; border:none; border-radius:6px; padding:4px 8px; font-size:12px; font-weight:700; cursor:pointer; white-space:nowrap;">
                  Duyệt Ca
                </button>
              ` : `
                <button type="button" onclick="promptManagerRemindStaff('${escapeHtml(r.username)}', 'CHECKOUT')" style="background:rgba(245, 158, 11, 0.15); color:var(--accent-amber); border:1px solid var(--accent-amber); border-radius:6px; padding:4px 8px; font-size:12px; font-weight:700; cursor:pointer; white-space:nowrap;">
                  Nhắc Ra
                </button>
                <button type="button" onclick="promptManagerCloseShift('${r.id}', '${escapeHtml(r.display_name || r.username)}', '${r.shift_key}')" style="background:var(--accent-emerald); color:#fff; border:none; border-radius:6px; padding:4px 8px; font-size:12px; font-weight:700; cursor:pointer; white-space:nowrap;">
                  Chốt Ra
                </button>
              `}
              <button type="button" onclick="promptManagerDeleteShift('${r.id}', '${escapeHtml(r.display_name || r.username)}')" style="background:rgba(239, 68, 68, 0.15); color:var(--accent-coral); border:1px solid var(--accent-coral); border-radius:6px; padding:4px 8px; font-size:12px; font-weight:700; cursor:pointer; white-space:nowrap;">
                Xóa Ca
              </button>
            </div>
          </div>
        `;
      });
    }

    // 2. BÁO CÁO CHƯA ĐĂNG KÝ CA TUẦN MỚI
    if (missingRosters.length > 0) {
      h += `
        <div style="margin-top:10px; margin-bottom:8px; padding:8px 10px; background:rgba(59, 130, 246, 0.08); border:1px solid rgba(59, 130, 246, 0.25); border-radius:8px;">
          <div style="font-weight:700; color:#3b82f6; font-size:13px; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
            <span style="display:inline-flex; align-items:center; gap:4px;"><iconify-icon icon="solar:calendar-date-bold" width="14" height="14" style="color:#3b82f6;"></iconify-icon> Chưa đăng ký ca tuần tới (${missingRosters.length})</span>
            <button type="button" onclick="promptManagerRemindAllMissingRoster()" style="background:#3b82f6; color:#fff; border:none; border-radius:8px; padding:4px 10px; font-size:11.5px; font-weight:700; cursor:pointer; display:inline-flex; align-items:center; gap:4px; box-shadow:0 1px 3px rgba(59,130,246,0.3);">
              <iconify-icon icon="solar:bell-bing-bold" width="12" height="12"></iconify-icon> Nhắc tất cả (${missingRosters.length})
            </button>
          </div>
          <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:6px;">
            ${missingRosters.map(m => `
              <span style="display:inline-flex; align-items:center; gap:4px; padding:3px 8px; background:var(--bg-card); border:1px solid var(--border); border-radius:12px; font-size:11px;">
                <strong>${escapeHtml(m.name)}</strong>
                <button type="button" onclick="promptManagerRemindStaff('${escapeHtml(m.username)}', 'ROSTER')" title="Gửi thông báo nhắc nộp lịch" style="background:none; border:none; color:#3b82f6; font-weight:700; cursor:pointer; padding:0 2px; display:inline-flex; align-items:center;">
                  <iconify-icon icon="solar:bell-bing-linear" width="12" height="12"></iconify-icon>
                </button>
              </span>
            `).join('')}
          </div>
        </div>
      `;
    }

    // 3. Ca Đã Đóng Hôm Nay
    if (closedList.length > 0) {
      h += `<div style="margin-top:10px; margin-bottom:6px; font-weight:700; color:var(--accent-emerald);">Đã xong ca hôm nay (${closedList.length}):</div>`;
      closedList.forEach(c => {
        h += `
          <div style="padding: 8px 0; border-bottom: 1px dotted var(--border); display: flex; justify-content: space-between; align-items: center; gap: 8px;">
            <div style="flex: 1;">
              <div><strong>${escapeHtml(c.display_name || c.username)}</strong> <span style="font-size:12px; color:var(--text-secondary);">${escapeHtml(c.shift_name)} (Vào: ${escapeHtml(c.checkin_time)} • Ra: ${escapeHtml(c.checkout_time)} - ${c.total_mins}p)</span></div>
              <div style="font-size:12px; color:var(--text-muted);">${escapeHtml(c.note || (c.closed_by ? 'Đóng bởi: ' + c.closed_by : ''))}</div>
            </div>
            <div style="display:flex; gap:4px;">
              <button type="button" onclick="promptManagerReopenShift('${c.id}', '${escapeHtml(c.display_name || c.username)}')" style="background:var(--accent-emerald); color:#fff; border:none; border-radius:6px; padding:4px 8px; font-size:12px; font-weight:700; cursor:pointer; white-space:nowrap;">
                Mở Lại
              </button>
              <button type="button" onclick="promptManagerDeleteShift('${c.id}', '${escapeHtml(c.display_name || c.username)}')" style="background:rgba(239, 68, 68, 0.15); color:var(--accent-coral); border:1px solid var(--accent-coral); border-radius:6px; padding:4px 8px; font-size:12px; font-weight:700; cursor:pointer; white-space:nowrap;">
                Xóa Ca
              </button>
            </div>
          </div>
        `;
      });
    }

    if (!h) {
      listEl.innerHTML = '<div style="color:var(--accent-emerald); font-weight:600;">Toàn bộ ca hôm nay đã chuẩn chỉ, không có ca lỗi hay quên ra.</div>';
    } else {
      listEl.innerHTML = h;
    }

  } catch (e) {
    listEl.innerHTML = '<div style="color:var(--text-muted);">Không thể tải danh sách ca quản trị: ' + escapeHtml(e.message) + '</div>';
  }
}

export async function promptManagerRemindStaff(username, remindType) {
  const token = localStorage.getItem('vnaigc_jwt');
  try {
    let res = await fetch('/api/v1/cc/push/manager/remind-staff', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (token || '')
      },
      body: JSON.stringify({
        username: username,
        remind_type: remindType
      })
    });
    if (!res.ok && res.status === 404) {
      res = await fetch('/api/v1/cc/notifications/push/manager/remind-staff', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + (token || '')
        },
        body: JSON.stringify({
          username: username,
          remind_type: remindType
        })
      });
    }
    const d = await res.json();
    if (res.ok) {
      showToast(`Đã gửi thông báo nhắc ${remindType} cho "${username}"!`, 'success');
      triggerHaptic('success');
    } else {
      showToast(safeErrorDetail(d, 'Không thể gửi thông báo'), 'error');
      triggerHaptic('error');
    }
  } catch (err) {
    showToast(`Lỗi: ${err.message}`, 'error');
  }
}
window.promptManagerRemindStaff = promptManagerRemindStaff;

export async function promptManagerDeleteShift(recordId, name) {
  const ok = await showConfirmDialog({
    title: 'Xác Nhận Xóa Ca Làm Việc',
    message: `Xác nhận xóa ca làm việc của nhân sự "${name}"?\n(Dành cho ca tới quán chơi bấm nhầm hoặc ca rác. Bản ghi sẽ bị hủy hoàn toàn và không tính lương).`,
    confirmText: 'Xóa Vĩnh Viễn',
    cancelText: 'Hủy',
    type: 'danger',
    icon: 'solar:trash-bin-trash-bold'
  });
  if (!ok) return;
  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/attendance/manager/delete-shift', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (token || '')
      },
      body: JSON.stringify({ record_id: recordId, manager_note: 'Quản lý xóa ca tại bảng điều khiển' })
    });
    const d = await res.json();
    if (res.ok) {
      showToast(d.message || 'Đã xóa ca thành công!', 'success');
      loadPendingManagerCheckouts();
      loadAttendanceTab();
    } else {
      showToast(safeErrorDetail(d, 'Không thể xóa ca'), 'error');
    }
  } catch (e) {
    showToast(`Lỗi: ${e.message}`, 'error');
  }
}

export async function promptManagerReopenShift(recordId, name) {
  const ok = await showConfirmDialog({
    title: 'Mở Lại Ca Trực',
    message: `Xác nhận mở lại ca trực cho nhân sự "${name}"?\n(Giờ Check-out sẽ bị hủy, ca chuyển về trạng thái đang làm việc).`,
    confirmText: 'Mở Lại Ca',
    cancelText: 'Hủy',
    type: 'info',
    icon: 'solar:restart-bold'
  });
  if (!ok) return;
  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/attendance/manager/reopen-shift', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (token || '')
      },
      body: JSON.stringify({ record_id: recordId, manager_note: 'Quản lý mở lại ca tại bảng điều khiển' })
    });
    const d = await res.json();
    if (res.ok) {
      showToast(d.message || 'Đã mở lại ca thành công!', 'success');
      loadPendingManagerCheckouts();
      loadAttendanceTab();
    } else {
      showToast(safeErrorDetail(d, 'Không thể mở lại ca'), 'error');
    }
  } catch (e) {
    showToast(`Lỗi: ${e.message}`, 'error');
  }
}

export async function promptManagerCloseShift(recordId, name, shiftKey) {
  const defaultTime = shiftKey === 'sang' ? '11:30' : '23:00';
  const ok = await showConfirmDialog({
    title: 'Chốt Check-out Quy Chuẩn',
    message: `Xác nhận Chốt Check-out cho nhân sự "${name}" với giờ quy chuẩn (${defaultTime})?`,
    confirmText: 'Chốt Giờ Ca',
    cancelText: 'Hủy',
    type: 'warning',
    icon: 'solar:clock-circle-bold'
  });
  if (!ok) return;
  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/attendance/manager/manual-close', {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (token || '')
      },
      body: JSON.stringify({
        record_id: recordId,
        manual_checkout: defaultTime,
        manager_note: 'Quản lý duyệt tay tại giao diện'
      })
    });
    const d = await res.json();
    if (res.ok) {
      showToast(d.message || 'Đã chốt ca thành công!', 'success');
      loadPendingManagerCheckouts();
      loadAttendanceTab();
    } else {
      showToast(safeErrorDetail(d, 'Không thể chốt ca'), 'error');
    }
  } catch (e) {
    showToast(`Lỗi: ${e.message}`, 'error');
  }
}

export async function executeReopenShift(recordId, managerPin) {
  const rec = window._lastClosedRecord;
  const targetId = recordId || (rec ? rec.id : null);
  const targetUser = (rec ? rec.username : null) || localStorage.getItem('vnaigc_username') || (typeof currentUser !== 'undefined' ? currentUser : '');
  
  const ok = await showConfirmDialog({
    title: 'Mở Lại Ca Trực',
    message: `Xác nhận mở lại ca trực cho nhân sự "${targetUser}"?\nGiờ Check-out sẽ bị hủy và ca tiếp tục hoạt động.`,
    confirmText: 'Mở Lại Ca',
    cancelText: 'Hủy',
    type: 'info',
    icon: 'solar:restart-bold'
  });
  if (!ok) return;

  const token = localStorage.getItem('vnaigc_jwt');
  const reqHeaders = { 'Content-Type': 'application/json' };
  if (token) reqHeaders['Authorization'] = 'Bearer ' + token;

  try {
    const res = await fetch('/api/v1/cc/attendance/manager/reopen-shift', {
      method: 'POST',
      headers: reqHeaders,
      body: JSON.stringify({
        record_id: targetId,
        username: targetUser,
        manager_pin: managerPin || null,
        manager_note: 'Quản lý mở lại ca trực do bấm nhầm Check-out'
      })
    });
    const d = await res.json();
    if (res.ok) {
      showToast(d.message || 'Đã mở lại ca thành công!', 'success');
      await loadAttendanceTab();
      if (typeof renderStaffPortal === 'function' && document.getElementById('staffPortalContainer') && document.getElementById('staffPortalContainer').style.display !== 'none') {
        (window.renderStaffPortal || function(){})();
      }
    } else {
      showToast(safeErrorDetail(d, 'Không thể mở lại ca'), 'error');
    }
  } catch (e) {
    showToast(`Lỗi kết nối: ${e.message}`, 'error');
  }
}

export async function executeDeleteShift(recordId, managerPin) {
  const rec = window._lastClosedRecord;
  const targetId = recordId || (rec ? rec.id : null);
  const targetUser = (rec ? rec.username : null) || localStorage.getItem('vnaigc_username') || (typeof currentUser !== 'undefined' ? currentUser : '');
  
  const ok = await showConfirmDialog({
    title: 'Xóa Hoàn Toàn Ca Làm Việc',
    message: `Cảnh báo: Xóa hoàn toàn ca làm việc này của nhân sự "${targetUser}"?\nBản ghi ca hôm nay sẽ bị xóa để nhân viên có thể bấm Check-in lại.`,
    confirmText: 'Xóa Ca',
    cancelText: 'Hủy',
    type: 'danger',
    icon: 'solar:trash-bin-trash-bold'
  });
  if (!ok) return;

  const token = localStorage.getItem('vnaigc_jwt');
  const reqHeaders = { 'Content-Type': 'application/json' };
  if (token) reqHeaders['Authorization'] = 'Bearer ' + token;

  try {
    const res = await fetch('/api/v1/cc/attendance/manager/delete-shift', {
      method: 'POST',
      headers: reqHeaders,
      body: JSON.stringify({
        record_id: targetId,
        username: targetUser,
        manager_pin: managerPin || null,
        manager_note: 'Quản lý xóa ca lỗi theo yêu cầu nhân viên'
      })
    });
    const d = await res.json();
    if (res.ok) {
      showToast(d.message || 'Đã xóa ca thành công!', 'success');
      await loadAttendanceTab();
      if (typeof renderStaffPortal === 'function' && document.getElementById('staffPortalContainer') && document.getElementById('staffPortalContainer').style.display !== 'none') {
        (window.renderStaffPortal || function(){})();
      }
    } else {
      showToast(safeErrorDetail(d, 'Không thể xóa ca lỗi'), 'error');
    }
  } catch (e) {
    showToast(`Lỗi kết nối: ${e.message}`, 'error');
  }
}

export function promptManagerUnlockShift() {
  const modal = document.getElementById('managerPinSheet');
  if (!modal) return;

  const pinInput = document.getElementById('managerPinInput');
  if (pinInput) {
    pinInput.value = '';
  }

  const radioReopen = document.querySelector('input[name="managerPinActionRadio"][value="1"]');
  if (radioReopen) radioReopen.checked = true;

  const closeModal = () => {
    modal.classList.remove('active');
    updateSheetScrollLock();
  };

  const btnCancel = document.getElementById('btnCancelManagerPin');
  const btnCloseX = document.getElementById('btnManagerPinCloseX');
  if (btnCancel) btnCancel.onclick = closeModal;
  if (btnCloseX) btnCloseX.onclick = closeModal;

  const btnConfirm = document.getElementById('btnConfirmManagerPin');
  if (btnConfirm) {
    btnConfirm.onclick = async () => {
      const pin = pinInput ? pinInput.value.trim() : '';
      if (!pin || !/^\d{4}$/.test(pin)) {
        return showToast('Vui lòng nhập đúng mã PIN Quản lý gồm 4 chữ số!', 'warn');
      }

      const selectedAction = document.querySelector('input[name="managerPinActionRadio"]:checked');
      const actionVal = selectedAction ? selectedAction.value : '1';

      btnConfirm.textContent = 'Đang xử lý...';
      btnConfirm.disabled = true;
      try {
        if (actionVal === '1') {
          await executeReopenShift(null, pin);
        } else {
          await executeDeleteShift(null, pin);
        }
        closeModal();
      } finally {
        btnConfirm.textContent = 'Xác Nhận Thực Hiện';
        btnConfirm.disabled = false;
      }
    };
  }

  modal.classList.add('active');
  updateSheetScrollLock();
  if (pinInput) {
    setTimeout(() => pinInput.focus(), 150);
  }
}

// ==========================================
// DUYỆT CA TREO & QUÊN CHECKOUT (MODAL HANDLERS)
// ==========================================

export function openReviewHangingShiftModal(record) {
  if (!record) return;
  const modal = document.getElementById('reviewHangingShiftSheet');
  if (!modal) return;

  const recId = record.id || record.record_id || '';
  const staffName = record.display_name || record.staff_name || record.username || 'Nhân sự';
  const shiftName = record.shift_name || record.shift || 'Ca làm việc';
  const dateStr = record.date || new Date().toISOString().slice(0, 10);
  const checkinTime = record.checkin_time || '--:--';

  let suggestedCheckout = '12:00';
  const sNameLower = shiftName.toLowerCase();
  if (sNameLower.includes('tối') || sNameLower.includes('evening') || sNameLower.includes('đêm')) {
    suggestedCheckout = '23:00';
  } else if (sNameLower.includes('chiều') || sNameLower.includes('afternoon')) {
    suggestedCheckout = '17:00';
  } else if (record.standard_checkout) {
    suggestedCheckout = record.standard_checkout;
  }

  const idInput = document.getElementById('hangingShiftRecordId');
  const dateInput = document.getElementById('hangingShiftDate');
  const checkinInput = document.getElementById('hangingShiftCheckinTime');
  const nameEl = document.getElementById('hangingShiftStaffName');
  const shiftEl = document.getElementById('hangingShiftName');
  const dateDisplay = document.getElementById('hangingShiftDateDisplay');
  const inDisplay = document.getElementById('hangingShiftInDisplay');
  const schedOutDisplay = document.getElementById('hangingShiftSchedOutDisplay');
  const checkoutInput = document.getElementById('hangingShiftCheckoutInput');
  const minutesInput = document.getElementById('hangingShiftMinutesInput');
  const noteInput = document.getElementById('hangingShiftNoteInput');

  if (idInput) idInput.value = recId;
  if (dateInput) dateInput.value = dateStr;
  if (checkinInput) checkinInput.value = checkinTime;
  if (nameEl) nameEl.textContent = staffName;
  if (shiftEl) shiftEl.textContent = shiftName;
  if (dateDisplay) dateDisplay.textContent = dateStr;
  if (inDisplay) inDisplay.textContent = checkinTime;
  if (schedOutDisplay) schedOutDisplay.textContent = suggestedCheckout;
  if (checkoutInput) checkoutInput.value = suggestedCheckout;
  if (noteInput) noteInput.value = '';

  function calcMinutes(inTime, outTime) {
    try {
      if (!inTime || !outTime || inTime === '--:--') return 300;
      const [h1, m1] = inTime.split(':').map(Number);
      const [h2, m2] = outTime.split(':').map(Number);
      let diff = (h2 * 60 + m2) - (h1 * 60 + m1);
      if (diff <= 0) diff += 1440;
      return Math.min(720, Math.max(30, diff));
    } catch {
      return 300;
    }
  }

  if (minutesInput) {
    minutesInput.value = record.approved_minutes || calcMinutes(checkinTime, suggestedCheckout);
  }

  modal.classList.add('active');
  updateSheetScrollLock();
}

export function closeReviewHangingShiftModal() {
  const modal = document.getElementById('reviewHangingShiftSheet');
  if (modal) modal.classList.remove('active');
  updateSheetScrollLock();
}

export async function submitReviewHangingShift() {
  const idInput = document.getElementById('hangingShiftRecordId');
  const checkoutInput = document.getElementById('hangingShiftCheckoutInput');
  const minutesInput = document.getElementById('hangingShiftMinutesInput');
  const noteInput = document.getElementById('hangingShiftNoteInput');
  const submitBtn = document.getElementById('btnSubmitReviewHanging');

  const recordId = idInput ? idInput.value : '';
  const checkoutTime = checkoutInput ? checkoutInput.value : '';
  const minutes = minutesInput ? parseInt(minutesInput.value, 10) : 0;
  const note = noteInput ? noteInput.value.trim() : '';

  if (!recordId) {
    showToast('Thiếu mã bản ghi ca trực!', 'error');
    return;
  }
  if (!checkoutTime) {
    showToast('Vui lòng chọn giờ ra ca thực tế!', 'warn');
    return;
  }
  if (isNaN(minutes) || minutes <= 0) {
    showToast('Số phút công phải lớn hơn 0!', 'warn');
    return;
  }

  if (typeof navigator !== 'undefined') navigator.vibrate?.(12);
  const token = localStorage.getItem('vnaigc_jwt');
  const reqHeaders = { 'Content-Type': 'application/json' };
  if (token) reqHeaders['Authorization'] = 'Bearer ' + token;

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Đang duyệt ca...';
  }

  try {
    const res = await fetch('/api/v1/cc/attendance/review-hanging-shift', {
      method: 'POST',
      headers: reqHeaders,
      body: JSON.stringify({
        record_id: recordId,
        approved_checkout_time: checkoutTime,
        approved_minutes: minutes,
        note: note || 'Quản lý duyệt ca quên check-out qua hệ thống'
      })
    });
    const d = await res.json();
    if (res.ok && (d.success || d.status === 'success')) {
      triggerHaptic('success');
      showToast(d.message || 'Đã duyệt ca và mở khóa tính lương thành công!', 'success');
      closeReviewHangingShiftModal();
      await loadPendingManagerCheckouts();
      await loadAttendanceTab();
      if (typeof window.fetchPendingHangingShifts === 'function') {
        window.fetchPendingHangingShifts();
      }
    } else {
      triggerHaptic('error');
      showToast(safeErrorDetail(d, 'Không thể duyệt ca'), 'error');
    }
  } catch (err) {
    triggerHaptic('error');
    showToast(`Lỗi: ${err.message}`, 'error');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.innerHTML = '<iconify-icon icon="solar:check-circle-bold" width="16" height="16" style="vertical-align:middle;"></iconify-icon> <span>Duyệt Ca & Tính Lương</span>';
    }
  }
}

export async function promptManagerRemindAllMissingRoster() {
  const missing = window._pendingMissingRosterList || [];
  if (!missing || missing.length === 0) {
    showToast('Tất cả nhân sự đã nộp lịch ca tuần mới!', 'info');
    return;
  }
  const ok = await showConfirmDialog({
    title: 'Nhắc Nộp Lịch Tuần Mới',
    message: `Xác nhận gửi thông báo nhắc nộp lịch ca tuần mới tới ${missing.length} nhân sự chưa đăng ký?`,
    confirmText: 'Gửi Thông Báo',
    cancelText: 'Hủy',
    type: 'telegram',
    icon: 'solar:plain-bold'
  });
  if (!ok) return;
  const token = localStorage.getItem('vnaigc_jwt');
  const reqHeaders = { 'Content-Type': 'application/json' };
  if (token) reqHeaders['Authorization'] = 'Bearer ' + token;

  let sentCount = 0;
  for (const item of missing) {
    const u = item.username || item;
    try {
      let res = await fetch('/api/v1/cc/push/manager/remind-staff', {
        method: 'POST',
        headers: reqHeaders,
        body: JSON.stringify({
          username: u,
          remind_type: 'ROSTER',
          custom_message: 'Cổng đăng ký ca tuần mới đã mở. Vui lòng gửi lịch làm việc tuần trước 12:00 Chủ Nhật!'
        })
      });
      if (!res.ok && res.status === 404) {
        res = await fetch('/api/v1/cc/notifications/push/manager/remind-staff', {
          method: 'POST',
          headers: reqHeaders,
          body: JSON.stringify({
            username: u,
            remind_type: 'ROSTER',
            custom_message: 'Cổng đăng ký ca tuần mới đã mở. Vui lòng gửi lịch làm việc tuần trước 12:00 Chủ Nhật!'
          })
        });
      }
      if (res.ok) sentCount++;
    } catch (e) {
      console.warn('Lỗi nhắc nộp lịch:', u, e);
    }
  }
  triggerHaptic('success');
  showToast(`Đã gửi thông báo nhắc lịch tới ${sentCount} nhân sự!`, 'success');
}

// Gắn sự kiện modal duyệt ca treo khi khởi tạo
if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
  document.addEventListener('DOMContentLoaded', () => {
    const btnClose = document.getElementById('btnCloseReviewHangingSheet');
    if (btnClose) btnClose.addEventListener('click', closeReviewHangingShiftModal);

    const btnSubmit = document.getElementById('btnSubmitReviewHanging');
    if (btnSubmit) btnSubmit.addEventListener('click', submitReviewHangingShift);

    const checkoutInput = document.getElementById('hangingShiftCheckoutInput');
    const minutesInput = document.getElementById('hangingShiftMinutesInput');
    const checkinInput = document.getElementById('hangingShiftCheckinTime');
    if (checkoutInput && minutesInput && checkinInput) {
      checkoutInput.addEventListener('change', () => {
        try {
          const inTime = checkinInput.value;
          const outTime = checkoutInput.value;
          if (inTime && outTime && inTime !== '--:--') {
            const [h1, m1] = inTime.split(':').map(Number);
            const [h2, m2] = outTime.split(':').map(Number);
            let diff = (h2 * 60 + m2) - (h1 * 60 + m1);
            if (diff <= 0) diff += 1440;
            minutesInput.value = Math.min(720, Math.max(30, diff));
          }
        } catch {}
      });
    }
  });
}

// Window export cho global access
if (typeof window !== 'undefined') {
  window.openReviewHangingShiftModal = openReviewHangingShiftModal;
  window.closeReviewHangingShiftModal = closeReviewHangingShiftModal;
  window.submitReviewHangingShift = submitReviewHangingShift;
  window.promptManagerRemindAllMissingRoster = promptManagerRemindAllMissingRoster;
}



