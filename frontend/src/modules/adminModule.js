// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// ADMIN MODULE: STAFF ACCOUNTS, PIN MANAGEMENT, ZALO INVITES & SHEET SYNC
// ==========================================================================

import { showToast, safeErrorDetail } from "../utils/toast.js";
import { showConfirmDialog } from "../utils/dialog.js";
import { escapeHtml, removeAccents, copyTextToClipboard } from "../utils/formatters.js";
import { state, currentRealtimeMonth } from "../store/state.js";
import {
  fetchStaffAccountsApi,
  toggleLockApi,
  toggleStaffStatusApi,
  updateStaffPinApi,
  createStaffAccountApi
} from "../api/authApi.js";

state.adminStaffAccountsData = null;

export async function openAdminStaffModal() {
  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/admin/staff-accounts', {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    if (!res.ok) return showToast('Không thể lấy danh sách tài khoản nhân viên', 'error');
    state.adminStaffAccountsData = await res.json();
    renderAdminStaffList();
    updateAdminLockBox();
    populateSheetStaffDropdown();
    document.getElementById('adminStaffSheet').classList.add('active');
  } catch (e) {
    showToast('Lỗi kết nối máy chủ', 'error');
  }
}

export function updateAdminLockBox() {
  const locks = (state.adminStaffAccountsData && state.adminStaffAccountsData.payroll_locks) || {};
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  const lock = locks[m] || { status: 'OPEN' };
  const isLocked = lock.status === 'LOCKED';
  
  const titleEl = document.getElementById('txtAdminLockMonth');
  const statusEl = document.getElementById('txtAdminLockStatus');
  const btnToggle = document.getElementById('btnAdminToggleLock');
  
  if (titleEl) titleEl.textContent = `Kỳ Lương Tháng ${m}`;
  if (statusEl) {
    statusEl.innerHTML = isLocked 
      ? `<span style="color:var(--accent-coral); font-weight:700;">ĐANG KHÓA ĐỐI SOÁT</span>` 
      : `<span style="color:var(--accent-emerald); font-weight:700;">ĐANG MỞ (Nhân viên tra cứu & xác nhận)</span>`;
  }
  if (btnToggle) {
    const currentRole = localStorage.getItem('vnaigc_role') || 'STAFF';
    if (currentRole !== 'ADMIN') {
      btnToggle.style.display = 'none';
    } else {
      btnToggle.style.display = 'inline-block';
      btnToggle.textContent = isLocked ? 'Mở Kỳ Lương' : 'Khóa Kỳ Lương';
      btnToggle.style.color = isLocked ? 'var(--accent-emerald)' : 'var(--accent-coral)';
      btnToggle.onclick = async () => {
        const newStatus = isLocked ? 'OPEN' : 'LOCKED';
        const ok = await showConfirmDialog({
          title: isLocked ? 'Mở Lại Kỳ Lương' : 'Khóa Kỳ Lương',
          message: `Xác nhận ${isLocked ? 'MỞ LẠI' : 'KHÓA'} kỳ lương Tháng ${m}? ${isLocked ? 'Nhân viên sẽ có thể đối soát tiếp.' : 'Bảng lương sẽ được đóng băng để chốt chi trả.'}`,
          confirmText: isLocked ? 'Mở Lại' : 'Khóa Ngay',
          cancelText: 'Hủy',
          type: isLocked ? 'info' : 'warning',
          icon: isLocked ? 'solar:lock-unlocked-bold' : 'solar:lock-keyhole-bold'
        });
        if (!ok) return;
        const msg = isLocked ? '' : 'Đang đối soát chuyển khoản';
        try {
          const token = localStorage.getItem('vnaigc_jwt');
          const r = await fetch('/api/v1/cc/admin/toggle-lock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ month: m, status: newStatus, message: msg })
          });
          if (r.ok) {
            const d = await r.json();
            state.adminStaffAccountsData.payroll_locks = d.payroll_locks;
            updateAdminLockBox();
            showToast(`Đã cập nhật trạng thái Tháng ${m} thành: ${newStatus}`, 'success');
          }
        } catch (e) {
          showToast('Lỗi cập nhật khóa kỳ lương', 'error');
        }
      };
    }
  }
}

state.adminStaffFilter = 'ALL';

export function setAdminStaffFilter(filter) {
  state.adminStaffFilter = filter;
  ['filterTabAll', 'filterTabActive', 'filterTabInactive'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.background = 'var(--bg-card)';
      el.style.fontWeight = '600';
      el.style.border = '1px solid var(--border)';
    }
  });
  const activeBtn = document.getElementById(filter === 'ALL' ? 'filterTabAll' : (filter === 'ACTIVE' ? 'filterTabActive' : 'filterTabInactive'));
  if (activeBtn) {
    activeBtn.style.background = filter === 'INACTIVE' ? 'rgba(239,68,68,0.15)' : (filter === 'ACTIVE' ? 'rgba(16,185,129,0.15)' : 'var(--border)');
    activeBtn.style.fontWeight = '700';
  }
  const searchInput = document.getElementById('adminStaffSearchInput');
  renderAdminStaffList(searchInput ? searchInput.value : '');
}

export async function handleToggleStaffStatus(uname, newStatus) {
  const isLocking = newStatus === 'INACTIVE';
  const confirmMsg = isLocking 
    ? `Xác nhận KHÓA tài khoản của @${uname}?\n\nNhân viên sẽ bị đăng xuất (kick-out) ngay lập tức và không thể chấm công hay xem bảng lương.`
    : `Xác nhận MỞ LẠI tài khoản cho @${uname}?`;
  
  const ok = await showConfirmDialog({
    title: isLocking ? 'Khóa Tài Khoản Nhân Viên' : 'Mở Lại Tài Khoản',
    message: confirmMsg,
    confirmText: isLocking ? 'Khóa Tài Khoản' : 'Mở Lại',
    cancelText: 'Hủy',
    type: isLocking ? 'danger' : 'info',
    icon: isLocking ? 'solar:user-block-bold' : 'solar:user-check-bold'
  });
  if (!ok) return;

  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/admin/toggle-staff-status', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ username: uname, status: newStatus })
    });

    let data;
    try {
      data = await res.json();
    } catch {
      data = { detail: `Lỗi máy chủ (${res.status})` };
    }
    if (res.ok) {
      showToast(data.message || 'Đã cập nhật trạng thái thành công', 'success');
      if (state.adminStaffAccountsData && state.adminStaffAccountsData.staff_accounts && state.adminStaffAccountsData.staff_accounts[uname]) {
        state.adminStaffAccountsData.staff_accounts[uname].status = newStatus;
      }
      const searchInput = document.getElementById('adminStaffSearchInput');
      renderAdminStaffList(searchInput ? searchInput.value : '');
    } else {
      showToast(safeErrorDetail(data, 'Lỗi cập nhật trạng thái'), 'error');
    }
  } catch (e) {
    showToast(`Lỗi kết nối: ${e.message}`, 'error');
  }
}

export function renderAdminStaffList(searchQuery = '') {
  const container = document.getElementById('adminStaffAccountsList');
  if (!container || !state.adminStaffAccountsData) return;
  const accounts = state.adminStaffAccountsData.staff_accounts || {};
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  const query = searchQuery.trim().toLowerCase();

  // Khử trùng lặp (de-duplicate) theo cả uname VÀ full_name chuẩn hóa
  const seenUname = new Set();
  const seenFullName = new Set();
  const allEntries = [];
  Object.entries(accounts).forEach(([uname, acc]) => {
    const key = (uname || '').trim().toLowerCase();
    const nameKey = (acc.full_name || uname || '').trim().toLowerCase().replace(/\s+/g, ' ');
    if (!key || seenUname.has(key)) return;
    if (nameKey && seenFullName.has(nameKey)) return;
    seenUname.add(key);
    if (nameKey) seenFullName.add(nameKey);
    allEntries.push([uname, acc]);
  });

  const totalCount = allEntries.length;
  const activeCount = allEntries.filter(([_, a]) => (a.status || 'ACTIVE') !== 'INACTIVE').length;
  const inactiveCount = allEntries.filter(([_, a]) => a.status === 'INACTIVE').length;

  const subTitle = document.getElementById('adminStaffSubTitle');
  if (subTitle) subTitle.textContent = `${totalCount} Nhân Sự • Cấp Tài Khoản & Gửi Zalo`;
  const btnAll = document.getElementById('filterTabAll');
  if (btnAll) btnAll.textContent = `Tất cả (${totalCount})`;
  const btnAct = document.getElementById('filterTabActive');
  if (btnAct) btnAct.textContent = `Đang làm (${activeCount})`;
  const btnInact = document.getElementById('filterTabInactive');
  if (btnInact) btnInact.textContent = `Đã nghỉ (${inactiveCount})`;

  let items = allEntries;

  if (state.adminStaffFilter === 'ACTIVE') {
    items = items.filter(([_, acc]) => (acc.status || 'ACTIVE') !== 'INACTIVE');
  } else if (state.adminStaffFilter === 'INACTIVE') {
    items = items.filter(([_, acc]) => acc.status === 'INACTIVE');
  }

  if (query) {
    items = items.filter(([uname, acc]) => {
      return uname.toLowerCase().includes(query) || 
             (acc.full_name && acc.full_name.toLowerCase().includes(query)) ||
             (acc.pin && acc.pin.includes(query)) ||
             (acc.phone && acc.phone.includes(query));
    });
  }

  items.sort(([uA, aA], [uB, aB]) => {
    const inactA = (aA.status === 'INACTIVE') ? 1 : 0;
    const inactB = (aB.status === 'INACTIVE') ? 1 : 0;
    if (inactA !== inactB) return inactA - inactB;
    
    const mgrA = (aA.role === 'MANAGER') ? 0 : 1;
    const mgrB = (aB.role === 'MANAGER') ? 0 : 1;
    if (mgrA !== mgrB) return mgrA - mgrB;

    return (aA.full_name || uA).localeCompare(aB.full_name || uB, 'vi');
  });

  const pastels = [
    { bg: 'rgba(59, 130, 246, 0.12)', color: '#2563eb' },
    { bg: 'rgba(16, 185, 129, 0.12)', color: '#059669' },
    { bg: 'rgba(245, 158, 11, 0.12)', color: '#d97706' },
    { bg: 'rgba(139, 92, 246, 0.12)', color: '#7c3aed' },
    { bg: 'rgba(236, 72, 153, 0.12)', color: '#db2777' },
    { bg: 'rgba(20, 184, 166, 0.12)', color: '#0d9488' }
  ];

  let html = '';
  items.forEach(([uname, acc]) => {
    const conf = (acc.confirmations && acc.confirmations[m]) || null;
    let confBadge = '';
    if (conf && conf.status === 'CONFIRMED') {
      confBadge = `<span style="font-size:10.5px; padding:2px 6px; border-radius:4px; background:var(--accent-emerald-sub); color:var(--accent-emerald); font-weight:700;" title="${conf.timestamp}">✓ Đã xác nhận</span>`;
    } else if (conf && conf.status === 'DISPUTED') {
      confBadge = `<span style="font-size:10.5px; padding:2px 6px; border-radius:4px; background:var(--accent-coral-sub); color:var(--accent-coral); font-weight:700;" title="${escapeHtml(conf.note)}">⚠️ Báo sai</span>`;
    }

    const isInactive = acc.status === 'INACTIVE';

    const genderBadge = acc.gender === 'NAM' 
      ? '<span style="font-size:10.5px; background:rgba(59,130,246,0.12); color:#2563eb; padding:1px 5px; border-radius:4px; font-weight:700;">Nam</span>'
      : (acc.gender === 'NU' 
        ? '<span style="font-size:10.5px; background:rgba(236,72,153,0.12); color:#db2777; padding:1px 5px; border-radius:4px; font-weight:700;">Nữ</span>'
        : '');

    const allowed = Array.isArray(acc.allowed_roles) && acc.allowed_roles.length > 0 
      ? acc.allowed_roles 
      : (acc.position ? [acc.position] : (acc.role === 'MANAGER' ? ['MANAGER'] : ['SERVICE']));
    
    let roleBadge = '';
    if (acc.role === 'MANAGER' || allowed.includes('MANAGER')) {
      roleBadge = '<span style="font-size:10.5px; background:rgba(245,158,11,0.15); color:#d97706; padding:1px 6px; border-radius:4px; font-weight:700; display:inline-flex; align-items:center; gap:3px;"><iconify-icon icon="solar:shield-check-bold" width="12" height="12"></iconify-icon> Quản lý</span>';
    } else if (allowed.includes('BARISTA') && allowed.includes('SERVICE')) {
      roleBadge = '<span style="font-size:10.5px; background:rgba(139,92,246,0.12); color:#7c3aed; padding:1px 6px; border-radius:4px; font-weight:700; display:inline-flex; align-items:center; gap:3px;" title="Đa nhiệm: Pha chế & Phục vụ"><iconify-icon icon="solar:bolt-bold" width="12" height="12"></iconify-icon> Đa nhiệm</span>';
    } else if (allowed.includes('BARISTA')) {
      roleBadge = '<span style="font-size:10.5px; background:rgba(249,115,22,0.12); color:#ea580c; padding:1px 6px; border-radius:4px; font-weight:700; display:inline-flex; align-items:center; gap:3px;"><iconify-icon icon="solar:cup-hot-bold" width="12" height="12"></iconify-icon> Pha chế</span>';
    } else {
      roleBadge = '<span style="font-size:10.5px; background:rgba(16,185,129,0.12); color:#059669; padding:1px 6px; border-radius:4px; font-weight:700; display:inline-flex; align-items:center; gap:3px;"><iconify-icon icon="solar:bell-bing-bold" width="12" height="12"></iconify-icon> Phục vụ</span>';
    }

    const charCode = (acc.full_name || uname || 'A').charCodeAt(0) || 65;
    const avatarTheme = pastels[charCode % pastels.length];
    const initial = (acc.full_name || uname || '?').trim().charAt(0).toUpperCase();

    const viewerRole = (localStorage.getItem('vnaigc_role') || 'STAFF').toUpperCase();
    const viewerUname = (localStorage.getItem('vnaigc_username') || '').toLowerCase().trim();
    const canViewWage = (viewerRole === 'ADMIN' || uname.toLowerCase().trim() === viewerUname);

    html += `
      <div class="ios-contact-row" style="background:var(--bg-card); border:1px solid ${isInactive ? 'rgba(239,68,68,0.3)' : 'var(--border)'}; border-radius:12px; padding:10px 12px; display:flex; align-items:center; justify-content:space-between; gap:10px; opacity:${isInactive ? '0.75' : '1'};">
        <!-- Left: Avatar + Info -->
        <div style="display:flex; align-items:center; gap:10px; flex:1; min-width:0;">
          <div style="width:38px; height:38px; border-radius:50%; background:${avatarTheme.bg}; color:${avatarTheme.color}; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:15px; flex-shrink:0;">
            ${initial}
          </div>
          <div style="min-width:0; flex:1;">
            <div style="display:flex; align-items:center; gap:5px; flex-wrap:wrap;">
              <span style="font-weight:700; font-size:13.5px; color:var(--text-primary); ${isInactive ? 'text-decoration:line-through; color:var(--text-muted);' : ''} overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                ${escapeHtml(acc.full_name || uname)}
              </span>
              ${roleBadge}
              ${genderBadge}
              ${confBadge}
              ${isInactive ? '<span style="font-size:10px; background:rgba(239,68,68,0.15); color:#dc2626; padding:1px 5px; border-radius:4px; font-weight:700;">ĐÃ NGHỈ</span>' : ''}
            </div>
            ${canViewWage ? `
              <div style="font-size:11.5px; color:var(--text-secondary); margin-top:2px; display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                ${acc.salary_type === 'FIXED'
                  ? `<span style="color:var(--accent-emerald); font-weight:700; font-family:var(--font-mono);">${(acc.fixed_salary || 6000000).toLocaleString('vi-VN')} đ/tháng (Lương cứng)</span>`
                  : `<span style="color:var(--c-blue); font-weight:700; font-family:var(--font-mono);">${(acc.hourly_rate || 17000).toLocaleString('vi-VN')} đ/h</span>`
                }
              </div>
            ` : ''}
          </div>
        </div>

        <!-- Right: Actions -->
        <div style="display:flex; align-items:center; gap:6px; flex-shrink:0;">
          <button type="button" onclick="copyZaloInvite('${uname}')" class="sheet-btn secondary" style="width:auto; padding:5px 9px; font-size:11.5px; font-weight:600; color:var(--accent-coral); border-color:var(--accent-coral); border-radius:8px; display:inline-flex; align-items:center; gap:4px;" title="Copy tin nhắn Zalo kèm tài khoản & mật khẩu">
            <iconify-icon icon="solar:copy-linear" width="13" height="13"></iconify-icon> Zalo
          </button>
          <button type="button" onclick="handleToggleStaffStatus('${uname}', '${isInactive ? 'ACTIVE' : 'INACTIVE'}')" class="sheet-btn secondary" style="width:auto; padding:5px 8px; font-size:11px; font-weight:700; border-radius:8px; ${isInactive ? 'color:#059669; border-color:#10b981; background:rgba(16,185,129,0.08);' : 'color:#dc2626; border-color:#ef4444; background:rgba(239,68,68,0.08);'}" title="${isInactive ? 'Mở lại tài khoản' : 'Khóa tài khoản'}">
            ${isInactive ? 'Mở' : 'Khóa'}
          </button>
          <button type="button" onclick="openEditStaffModal('${uname}')" class="sheet-btn secondary" style="width:auto; padding:5px 9px; font-size:11.5px; font-weight:700; color:var(--text-primary); border-color:var(--border); border-radius:8px; display:inline-flex; align-items:center; gap:4px;" title="Chỉnh sửa hồ sơ, vai trò, mức lương, PIN">
            <iconify-icon icon="solar:pen-new-square-linear" width="13" height="13"></iconify-icon> Sửa
          </button>
        </div>
      </div>
    `;
  });

  if (items.length === 0) {
    html = `<div style="text-align:center; padding:20px; font-size:12px; color:var(--text-muted);">Không có nhân viên nào phù hợp bộ lọc.</div>`;
  }

  container.innerHTML = html;
}

export async function handleUpdatePin(uname) {
  const input = document.getElementById(`pinInput_${uname}`);
  const newPin = input ? input.value.trim() : '';
  if (!newPin || !/^\d{4}$/.test(newPin)) {
    return showToast('Mật khẩu phải là 4 chữ số (0000 - 9999)!', 'warn');
  }

  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/admin/update-pin', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ username: uname, new_pin: newPin })
    });
    if (res.ok) {
      showToast(`Đã cập nhật mật khẩu mới cho @${uname}: ${newPin}`, 'success');
      if (state.adminStaffAccountsData && state.adminStaffAccountsData.staff_accounts && state.adminStaffAccountsData.staff_accounts[uname]) {
        state.adminStaffAccountsData.staff_accounts[uname].pin = newPin;
      }
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(safeErrorDetail(err, 'Lỗi cập nhật MK'), 'error');
    }
  } catch (e) {
    showToast('Lỗi kết nối máy chủ', 'error');
  }
}

export function copyZaloInvite(uname) {
  if (!state.adminStaffAccountsData) return;
  const acc = (state.adminStaffAccountsData.staff_accounts || {})[uname];
  if (!acc) return;
  const m = state.currentMonth === 'all' ? (state.monthsAvailable[state.monthsAvailable.length - 1] || currentRealtimeMonth) : state.currentMonth;
  
  const pinGuide = acc.has_pin ? 'Mã PIN cá nhân của bạn' : 'Mã PIN mặc định (liên hệ Quản lý)';
  const curYear = new Date().getFullYear();
  const storeName = window.vnaigc_store_name || 'FnBOps';
  const text = `Chào ${acc.full_name || uname}, bảng lương Tháng ${m}/${curYear} của bạn đã có trên hệ thống ${storeName}. Bạn vào link ${window.location.origin} để tra cứu nhé:\n- Tài khoản: ${uname}\n- Mật khẩu: [${pinGuide}]\nBạn vui lòng kiểm tra lại giờ làm và bấm [Xác Nhận] sớm nha!`;

  copyTextToClipboard(text);
  showToast(`Đã copy nội dung gửi Zalo cho ${acc.full_name || uname}!`, 'success');
}


// TỰ ĐỘNG TẠO TÀI KHOẢN CHO NHÂN SỰ TỪ GOOGLE SHEET (ADMIN SELF-SERVICE)
// ==========================================================================

export function populateSheetStaffDropdown() {
  const sel = document.getElementById('newStaffSelect');
  if (!sel) return;

  const accounts = (state.adminStaffAccountsData && state.adminStaffAccountsData.staff_accounts) || {};
  
  // Thu thập toàn bộ các tên xuất hiện trên Google Sheet (khử trùng lặp hoa/thường)
  const sheetNamesMap = new Map();
  
  // Tab NHÂN VIÊN
  if (state.rawData && state.rawData['NHÂN VIÊN']) {
    state.rawData['NHÂN VIÊN'].slice(1).forEach(r => {
      if (r && r[1]) {
        const n = r[1].trim();
        if (n && !n.startsWith('TÊN') && !n.startsWith('STT')) {
          const up = n.toUpperCase();
          if (!sheetNamesMap.has(up)) sheetNamesMap.set(up, n);
        }
      }
    });
  }

  // Tab DỮ LIỆU
  if (state.records && state.records.length > 0) {
    state.records.forEach(r => {
      if (r.name) {
        const n = r.name.trim();
        const up = n.toUpperCase();
        if (!sheetNamesMap.has(up)) sheetNamesMap.set(up, n);
      }
    });
  }

  // Map ngược kiểm tra ai đã có tài khoản (đối soát sheet_names, full_name, aliases và không dấu)
  const existingSheetNames = new Set();
  const normalize = s => (s || '').trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');
  const normalizedExisting = new Set();

  Object.values(accounts).forEach(acc => {
    (acc.sheet_names || []).forEach(sn => {
      if (sn) {
        existingSheetNames.add(sn.trim().toUpperCase());
        normalizedExisting.add(normalize(sn));
      }
    });
    if (acc.full_name) {
      existingSheetNames.add(acc.full_name.trim().toUpperCase());
      normalizedExisting.add(normalize(acc.full_name));
    }
    (acc.aliases || []).forEach(al => {
      if (al) {
        existingSheetNames.add(al.trim().toUpperCase());
        normalizedExisting.add(normalize(al));
      }
    });
  });

  const allNames = Array.from(sheetNamesMap.values()).sort((a, b) => a.localeCompare(b, 'vi'));
  const isMapped = n => {
    const up = n.trim().toUpperCase();
    if (existingSheetNames.has(up)) return true;
    const norm = normalize(n);
    if (normalizedExisting.has(norm)) return true;
    return false;
  };

  const unmapped = allNames.filter(n => !isMapped(n));
  const mapped = allNames.filter(n => isMapped(n));

  let optionsHtml = '<option value="">-- Chọn nhân sự từ bảng chấm công --</option>';
  if (unmapped.length > 0) {
    optionsHtml += '<optgroup label="⚡ CHƯA CẤP TÀI KHOẢN (KHUYÊN TẠO)">';
    unmapped.forEach(n => {
      optionsHtml += `<option value="${n}">${n} (Chưa có tài khoản)</option>`;
    });
    optionsHtml += '</optgroup>';
  }

  if (mapped.length > 0) {
    optionsHtml += '<optgroup label="ĐÃ CÓ TÀI KHOẢN">';
    mapped.forEach(n => {
      optionsHtml += `<option value="${n}">${n} (Đã cấp)</option>`;
    });
    optionsHtml += '</optgroup>';
  }

  sel.innerHTML = optionsHtml;
}

export function setupCreateStaffHandlers() {
  const btnToggle = document.getElementById('btnToggleCreateStaff');
  const box = document.getElementById('createStaffBox');
  const btnCancel = document.getElementById('btnCancelCreateStaff');
  const sel = document.getElementById('newStaffSelect');
  const inputFullName = document.getElementById('newStaffFullName');
  const inputUsername = document.getElementById('newStaffUsername');
  const inputPin = document.getElementById('newStaffPin');
  const btnGen = document.getElementById('btnGenPin');
  const btnSubmit = document.getElementById('btnSubmitCreateStaff');

  if (btnToggle && box) {
    btnToggle.onclick = () => {
      const isVisible = box.style.display === 'block';
      box.style.display = isVisible ? 'none' : 'block';
      if (!isVisible) {
        populateSheetStaffDropdown();
        if (inputPin && !inputPin.value) {
          inputPin.value = Math.floor(1000 + Math.random() * 9000).toString();
        }
      }
    };
  }

  const selNewSalaryType = document.getElementById('newStaffSalaryType');
  const wrapNewHourly = document.getElementById('newStaffHourlyRateWrap');
  const wrapNewFixed = document.getElementById('newStaffFixedSalaryWrap');
  if (selNewSalaryType) {
    selNewSalaryType.onchange = () => {
      const isFixed = selNewSalaryType.value === 'FIXED';
      if (wrapNewFixed) wrapNewFixed.style.display = isFixed ? 'block' : 'none';
      if (wrapNewHourly) wrapNewHourly.style.display = isFixed ? 'none' : 'block';
    };
  }

  if (btnCancel && box) {
    btnCancel.onclick = () => { box.style.display = 'none'; };
  }

  if (sel) {
    sel.onchange = () => {
      const val = sel.value;
      if (!val) return;
      if (inputFullName) inputFullName.value = val;
      if (inputUsername) {
        inputUsername.value = removeAccents(val).toLowerCase().replace(/[^a-z0-9]/g, '');
      }
      if (inputPin && !inputPin.value) {
        inputPin.value = Math.floor(1000 + Math.random() * 9000).toString();
      }
    };
  }

  if (btnGen && inputPin) {
    btnGen.onclick = () => {
      inputPin.value = Math.floor(1000 + Math.random() * 9000).toString();
    };
  }

  if (btnSubmit) {
    btnSubmit.onclick = async () => {
      const sheetName = sel ? sel.value.trim() : '';
      const fullName = inputFullName ? inputFullName.value.trim() : '';
      const username = inputUsername ? inputUsername.value.trim().toLowerCase() : '';
      const pin = inputPin ? inputPin.value.trim() : '';

      // Thu thập giới tính
      const genderRadio = document.querySelector('input[name="newStaffGender"]:checked');
      const gender = genderRadio ? genderRadio.value : 'NAM';

      // Thu thập vị trí chính
      const selPos = document.getElementById('newStaffPosition');
      const position = selPos ? selPos.value : 'SERVICE';
      const chkNewRoleManager = document.getElementById('newStaffRoleManager');
      const role = (chkNewRoleManager && chkNewRoleManager.checked) ? 'MANAGER' : 'STAFF';

      // Thu thập vai trò có thể làm (đa nhiệm)
      const chkServ = document.getElementById('newStaffRoleService');
      const chkBar = document.getElementById('newStaffRoleBarista');
      const allowed_roles = [];
      if (chkServ && chkServ.checked) allowed_roles.push('SERVICE');
      if (chkBar && chkBar.checked) allowed_roles.push('BARISTA');
      if (position === 'MANAGER' && !allowed_roles.includes('MANAGER')) {
        allowed_roles.push('MANAGER');
      }
      if (allowed_roles.length === 0) allowed_roles.push(position);

      if (!sheetName) return showToast('Vui lòng chọn nhân sự từ bảng chấm công!', 'warn');
      if (!fullName) return showToast('Vui lòng nhập họ và tên hiển thị!', 'warn');
      if (!username || username.length < 2) return showToast('Tên đăng nhập tối thiểu 2 ký tự (không dấu)!', 'warn');
      if (!/^\d{4}$/.test(pin)) return showToast('Mã PIN phải gồm đúng 4 chữ số (0000 - 9999)!', 'warn');

      const selSalType = document.getElementById('newStaffSalaryType');
      const salary_type = selSalType ? selSalType.value : 'HOURLY';
      const inputHourlyRate = document.getElementById('newStaffHourlyRate');
      const hourly_rate = inputHourlyRate && inputHourlyRate.value ? parseInt(inputHourlyRate.value, 10) : 17000;
      const inputFixedSalary = document.getElementById('newStaffFixedSalary');
      const fixed_salary = inputFixedSalary && inputFixedSalary.value ? parseInt(inputFixedSalary.value, 10) : 6000000;

      btnSubmit.disabled = true;
      btnSubmit.textContent = 'Đang lưu...';

      const token = localStorage.getItem('vnaigc_jwt');
      try {
        const res = await fetch('/api/v1/cc/admin/create-staff-account', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            username,
            full_name: fullName,
            sheet_names: [sheetName],
            pin,
            gender,
            position,
            role,
            allowed_roles,
            salary_type,
            hourly_rate,
            fixed_salary,
            aliases: [username]
          })
        });

        if (res.ok) {
          const data = await res.json();
          showToast(`Đã tạo tài khoản cho ${fullName} (@${username})!`, 'success');
          
          if (!state.adminStaffAccountsData) state.adminStaffAccountsData = {};
          if (!state.adminStaffAccountsData.staff_accounts) state.adminStaffAccountsData.staff_accounts = {};
          state.adminStaffAccountsData.staff_accounts[username] = data.account;

          if (box) box.style.display = 'none';
          renderAdminStaffList();
          populateSheetStaffDropdown();
        } else {
          const err = await res.json().catch(() => ({}));
          showToast(safeErrorDetail(err, 'Lỗi khi tạo tài khoản!'), 'error');
        }
      } catch (e) {
        showToast('Không thể kết nối đến máy chủ!', 'error');
      } finally {
        btnSubmit.disabled = false;
        btnSubmit.textContent = 'Lưu & Kích Hoạt';
      }
    };
  }
}

// ==========================================================================
// CHỈNH SỬA HỒ SƠ & VAI TRÒ NHÂN SỰ (GENDER, POSITION, MULTI-ROLE)
// ==========================================================================

export function openEditStaffModal(uname) {
  if (!state.adminStaffAccountsData || !state.adminStaffAccountsData.staff_accounts) return;
  const acc = state.adminStaffAccountsData.staff_accounts[uname];
  if (!acc) return showToast('Không tìm thấy tài khoản nhân viên!', 'error');

  const inputUname = document.getElementById('editStaffUsername');
  const inputNewUname = document.getElementById('editStaffNewUsername');
  const txtSubtitle = document.getElementById('editStaffSubtitle');
  const inputFullName = document.getElementById('editStaffFullName');
  const inputPhone = document.getElementById('editStaffPhone');
  const radNam = document.getElementById('editGenderNam');
  const radNu = document.getElementById('editGenderNu');
  const selPos = document.getElementById('editStaffPosition');
  const chkServ = document.getElementById('editRoleService');
  const chkBar = document.getElementById('editRoleBarista');
  const inputPin = document.getElementById('editStaffPin');
  const selFixedShift = document.getElementById('editStaffFixedShift');
  const selSalaryType = document.getElementById('editStaffSalaryType');
  const inputHourlyRate = document.getElementById('editStaffHourlyRate');
  const inputFixedSalary = document.getElementById('editStaffFixedSalary');
  const wrapHourly = document.getElementById('editStaffHourlyRateWrap');
  const wrapFixed = document.getElementById('editStaffFixedSalaryWrap');
  const salaryNotice = document.getElementById('editStaffSalaryNotice');

  if (inputUname) inputUname.value = uname;
  if (inputNewUname) inputNewUname.value = uname;
  if (txtSubtitle) txtSubtitle.textContent = `@${uname} • ${acc.full_name || uname}`;
  if (inputFullName) inputFullName.value = acc.full_name || uname;
  if (inputPhone) inputPhone.value = acc.phone || '';
  if (inputPin) {
    inputPin.value = '';
    inputPin.placeholder = acc.has_pin ? 'Đã có PIN (để trống nếu giữ nguyên)' : 'Nhập 4-8 số để tạo PIN';
  }
  if (selFixedShift) selFixedShift.value = acc.fixed_shift || '';

  const salType = acc.salary_type || 'HOURLY';
  if (selSalaryType) selSalaryType.value = salType;
  if (inputHourlyRate) inputHourlyRate.value = acc.hourly_rate || 17000;
  if (inputFixedSalary) inputFixedSalary.value = acc.fixed_salary || 6000000;
  if (wrapHourly) wrapHourly.style.display = salType === 'FIXED' ? 'none' : 'block';
  if (wrapFixed) wrapFixed.style.display = salType === 'FIXED' ? 'block' : 'none';

  // Ràng buộc bảo mật: Chỉ ADMIN mới được sửa mức lương
  const userRole = (localStorage.getItem('vnaigc_role') || 'STAFF').toUpperCase();
  const isAdmin = userRole === 'ADMIN';
  if (selSalaryType) selSalaryType.disabled = !isAdmin;
  if (inputHourlyRate) inputHourlyRate.disabled = !isAdmin;
  if (inputFixedSalary) inputFixedSalary.disabled = !isAdmin;
  if (salaryNotice) salaryNotice.style.display = isAdmin ? 'none' : 'block';

  const g = (acc.gender || 'NAM').toUpperCase();
  if (radNam) radNam.checked = (g !== 'NU');
  if (radNu) radNu.checked = (g === 'NU');

  const pos = (acc.position || (acc.role === 'MANAGER' ? 'MANAGER' : 'SERVICE')).toUpperCase();
  if (selPos) {
    selPos.value = pos;
    selPos.onchange = () => {
      const chkRole = document.getElementById('editStaffRoleManager');
      if (chkRole && isAdmin) {
        chkRole.checked = (selPos.value === 'MANAGER');
      }
    };
  }

  // Quản lý checkbox Quyền Quản Lý (Role Manager)
  const chkRoleManager = document.getElementById('editStaffRoleManager');
  if (chkRoleManager) {
    chkRoleManager.checked = (acc.role === 'MANAGER' || pos === 'MANAGER');
    chkRoleManager.disabled = !isAdmin;
    const wrapRoleManager = document.getElementById('wrapEditStaffRoleManager');
    if (wrapRoleManager) {
      wrapRoleManager.style.opacity = isAdmin ? '1' : '0.65';
    }
  }

  const roles = Array.isArray(acc.allowed_roles) && acc.allowed_roles.length > 0
    ? acc.allowed_roles
    : [pos];

  if (chkServ) chkServ.checked = roles.includes('SERVICE') || pos === 'SERVICE';
  if (chkBar) chkBar.checked = roles.includes('BARISTA') || pos === 'BARISTA';

  const modal = document.getElementById('editStaffProfileModal');
  if (modal) modal.classList.add('active');
}

export function closeEditStaffModal() {
  const modal = document.getElementById('editStaffProfileModal');
  if (modal) modal.classList.remove('active');
}

export function setupEditStaffHandlers() {
  const btnSubmit = document.getElementById('btnSubmitEditStaff');
  const selSalaryType = document.getElementById('editStaffSalaryType');
  const wrapHourly = document.getElementById('editStaffHourlyRateWrap');
  const wrapFixed = document.getElementById('editStaffFixedSalaryWrap');

  if (selSalaryType) {
    selSalaryType.onchange = () => {
      const isFixed = selSalaryType.value === 'FIXED';
      if (wrapFixed) wrapFixed.style.display = isFixed ? 'block' : 'none';
      if (wrapHourly) wrapHourly.style.display = isFixed ? 'none' : 'block';
    };
  }

  if (!btnSubmit) return;

  btnSubmit.onclick = async () => {
    const inputUname = document.getElementById('editStaffUsername');
    const inputNewUname = document.getElementById('editStaffNewUsername');
    const inputFullName = document.getElementById('editStaffFullName');
    const inputPhone = document.getElementById('editStaffPhone');
    const radNu = document.getElementById('editGenderNu');
    const selPos = document.getElementById('editStaffPosition');
    const chkServ = document.getElementById('editRoleService');
    const chkBar = document.getElementById('editRoleBarista');
    const inputPin = document.getElementById('editStaffPin');
    const selFixedShift = document.getElementById('editStaffFixedShift');
    const inputHourlyRate = document.getElementById('editStaffHourlyRate');
    const inputFixedSalary = document.getElementById('editStaffFixedSalary');

    const uname = inputUname ? inputUname.value.trim() : '';
    const newUname = inputNewUname ? inputNewUname.value.trim().toLowerCase() : uname;
    const fullName = inputFullName ? inputFullName.value.trim() : '';
    const phone = inputPhone ? inputPhone.value.trim() : '';
    const pin = inputPin ? inputPin.value.trim() : '';
    const fixedShift = selFixedShift ? selFixedShift.value.trim() : '';
    const salaryType = selSalaryType ? selSalaryType.value : 'HOURLY';
    const hourlyRate = inputHourlyRate && inputHourlyRate.value ? parseInt(inputHourlyRate.value, 10) : 17000;
    const fixedSalary = inputFixedSalary && inputFixedSalary.value ? parseInt(inputFixedSalary.value, 10) : 6000000;

    if (!uname) return showToast('Thiếu thông tin tài khoản!', 'error');
    if (!newUname) return showToast('Vui lòng nhập tên đăng nhập!', 'warn');
    if (!/^[a-zA-Z0-9_\.\-]+$/.test(newUname)) {
      return showToast('Tên đăng nhập chỉ được chứa chữ cái, chữ số, dấu chấm hoặc gạch dưới!', 'warn');
    }
    if (!fullName) return showToast('Vui lòng nhập họ và tên!', 'warn');
    if (pin && (pin.length !== 4 || !/^\d{4}$/.test(pin))) {
      return showToast('Mã PIN phải gồm đúng 4 chữ số!', 'warn');
    }

    const gender = (radNu && radNu.checked) ? 'NU' : 'NAM';
    const position = selPos ? selPos.value : 'SERVICE';

    const allowed_roles = [];
    if (chkServ && chkServ.checked) allowed_roles.push('SERVICE');
    if (chkBar && chkBar.checked) allowed_roles.push('BARISTA');
    if (position === 'MANAGER' && !allowed_roles.includes('MANAGER')) {
      allowed_roles.push('MANAGER');
    }
    if (allowed_roles.length === 0) {
      return showToast('Vui lòng chọn ít nhất 1 vai trò có thể làm (Phục vụ hoặc Pha chế)!', 'warn');
    }

    btnSubmit.disabled = true;
    btnSubmit.textContent = 'Đang lưu...';

    const token = localStorage.getItem('vnaigc_jwt');
    const chkRoleManager = document.getElementById('editStaffRoleManager');
    const targetRole = (chkRoleManager && chkRoleManager.checked) ? 'MANAGER' : 'STAFF';

    try {
      const payload = {
        username: uname,
        new_username: (newUname && newUname !== uname.toLowerCase()) ? newUname : undefined,
        full_name: fullName,
        phone,
        gender,
        position,
        role: targetRole,
        allowed_roles,
        fixed_shift: fixedShift,
        salary_type: salaryType,
        hourly_rate: hourlyRate,
        fixed_salary: fixedSalary
      };
      if (pin) payload.pin = pin;

      const res = await fetch('/api/v1/cc/admin/update-staff-profile', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(payload)
      });

      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        const finalUname = (data.account && data.account.username) || newUname || uname;
        showToast(data.message || `Đã cập nhật hồ sơ cho @${finalUname}!`, 'success');
        if (state.adminStaffAccountsData && state.adminStaffAccountsData.staff_accounts) {
          const accounts = state.adminStaffAccountsData.staff_accounts;
          const oldAcc = accounts[uname] || {};
          if (finalUname !== uname && accounts[uname]) {
            delete accounts[uname];
          }
          accounts[finalUname] = {
            ...oldAcc,
            full_name: fullName,
            phone,
            role: targetRole,
            gender,
            position,
            allowed_roles,
            salary_type: salaryType,
            hourly_rate: hourlyRate,
            fixed_salary: fixedSalary,
            pin: pin || oldAcc.pin,
            fixed_shift: fixedShift
          };
        }
        closeEditStaffModal();
        const searchInput = document.getElementById('adminStaffSearchInput');
        renderAdminStaffList(searchInput ? searchInput.value : '');
      } else {
        showToast(safeErrorDetail(data, 'Lỗi cập nhật hồ sơ!'), 'error');
      }
    } catch (e) {
      showToast('Không thể kết nối đến máy chủ!', 'error');
    } finally {
      btnSubmit.disabled = false;
      btnSubmit.textContent = '✓ Lưu Thay Đổi';
    }
  };
}

// ==========================================================================
// ADMIN 3-TIER PROGRESSIVE LOCKOUT & POS WHITELIST MANAGEMENT (MOBILE)
// ==========================================================================

export async function openAdminLockoutsModalMobile() {
  const sheet = document.getElementById('adminLockoutsSheetMobile');
  if (sheet) sheet.classList.add('active');
  await fetchAndRenderAdminLockoutsMobile();
}

export async function fetchAndRenderAdminLockoutsMobile() {
  const listEl = document.getElementById('adminLockoutsListMobile');
  const ipEl = document.getElementById('adminLiveCafeIpMobile');
  const countEl = document.getElementById('txtTotalLockoutsMobile');
  const token = localStorage.getItem('vnaigc_jwt');

  if (listEl) {
    listEl.innerHTML = '<div style="text-align:center; padding:20px 0; color:var(--text-secondary); font-size:12px;">Đang tải danh sách...</div>';
    try {
      const res = await fetch('/api/v1/cc/admin/lockouts', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) {
        listEl.innerHTML = '<div style="text-align:center; padding:20px 0; color:#dc2626; font-size:12px;">Không có quyền truy cập hoặc lỗi kết nối.</div>';
        return;
      }
      const data = await res.json();
      const lockouts = data.lockouts || [];
      const cafeIp = data.cafe_ip || 'Chưa nhận diện';

      if (ipEl) ipEl.textContent = cafeIp;
      if (countEl) countEl.textContent = lockouts.length;

      if (lockouts.length === 0) {
        listEl.innerHTML = `
          <div style="text-align:center; padding:24px 10px; background:var(--bg-card); border:1px solid var(--border); border-radius:10px;">
            <div style="font-size:13px; font-weight:700; color:var(--accent-emerald);">Hệ Thống An Toàn</div>
            <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">Không có IP hay Username nào bị khóa.</div>
          </div>
        `;
        return;
      }

      let html = '';
      lockouts.forEach(item => {
        const isIp = item.type === 'IP' || (item.target_key && item.target_key.includes('.'));
        const tierBadge = item.tier === 3 
          ? '<span style="font-size:12px; font-weight:700; background:rgba(239,68,68,0.15); color:#dc2626; padding:2px 6px; border-radius:4px;">TẦNG 3 (5H)</span>'
          : (item.tier === 2 
            ? '<span style="font-size:12px; font-weight:700; background:rgba(245,158,11,0.15); color:#d97706; padding:2px 6px; border-radius:4px;">TẦNG 2 (30P)</span>'
            : '<span style="font-size:12px; font-weight:700; background:rgba(59,130,246,0.15); color:#2563eb; padding:2px 6px; border-radius:4px;">TẦNG 1 (60S)</span>');

        html += `
          <div style="background:var(--bg-card); border:1px solid rgba(239,68,68,0.3); border-radius:10px; padding:10px 12px; display:flex; justify-content:space-between; align-items:center;">
            <div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="font-size:13px; font-weight:700; font-family:var(--font-mono); color:var(--text-primary);">${item.target_key}</span>
                ${tierBadge}
              </div>
              <div style="font-size:12px; color:var(--text-secondary); margin-top:3px;">
                ${isIp ? 'Khóa Mạng IP' : 'Khóa Username'} • Còn lại: <strong style="color:var(--accent-coral); font-family:var(--font-mono);">${item.remaining_seconds}s</strong>
              </div>
            </div>
            <button onclick="window.handleAdminUnlockMobile('${item.target_key}')" class="sheet-btn secondary" style="width:auto; padding:6px 12px; font-size:12px; font-weight:700; color:#dc2626; border-color:#ef4444; background:rgba(239,68,68,0.06);">
              Mở Khóa
            </button>
          </div>
        `;
      });
      listEl.innerHTML = html;
    } catch (e) {
      listEl.innerHTML = `<div style="text-align:center; padding:20px 0; color:#dc2626; font-size:12px;">Lỗi kết nối: ${e.message}</div>`;
    }
  }
}

export async function handleAdminUnlockMobile(targetKey) {
  const ok = await showConfirmDialog({
    title: 'Mở Khóa Khẩn Cấp',
    message: `Xác nhận MỞ KHÓA NGAY LẬP TỨC cho mục tiêu:\n\n${targetKey}?`,
    confirmText: 'Mở Khóa Ngay',
    cancelText: 'Hủy',
    type: 'warning',
    icon: 'solar:lock-unlocked-bold'
  });
  if (!ok) return;
  const token = localStorage.getItem('vnaigc_jwt');
  try {
    const res = await fetch('/api/v1/cc/admin/lockouts/unlock', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ target_key: targetKey })
    });
    if (res.ok) {
      showToast(`Đã mở khóa thành công cho: ${targetKey}`, 'success');
      await fetchAndRenderAdminLockoutsMobile();
    } else {
      const data = await res.json().catch(() => ({}));
      showToast(data.detail || 'Không thể mở khóa. Vui lòng kiểm tra quyền Admin.', 'error');
    }
  } catch (e) {
    showToast('Lỗi kết nối máy chủ!', 'error');
  }
}

if (typeof window !== 'undefined') {
  window.handleAdminUnlockMobile = handleAdminUnlockMobile;
  window.openEditStaffModal = openEditStaffModal;
  window.closeEditStaffModal = closeEditStaffModal;
  window.setupEditStaffHandlers = setupEditStaffHandlers;
}


