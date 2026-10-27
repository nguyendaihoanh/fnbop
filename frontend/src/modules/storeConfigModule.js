// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// STORE CONFIGURATION MODULE (MULTI-SHOP CUSTOMIZATION ENGINE)
// Allows Store Owners & Admins to dynamically configure:
// - Shifts (Hours, Standard Mins, Tolerance, Headcount per role)
// - Store Name & POS Mode (pos365 vs manual)
// - Gender & Physical Constraints (Male evening requirement toggle)
// - Holidays & Auto-Close rules
// ==========================================================================

import { showToast, safeErrorDetail } from "../utils/toast.js";
import { showConfirmDialog } from "../utils/dialog.js";
import { escapeHtml } from "../utils/formatters.js";
import { 
  fetchStoreConfigApi, 
  updateStoreConfigApi, 
  resetStoreConfigApi, 
  testTelegramApi, 
  fetchZaloQrApi, 
  fetchZaloStatusApi,
  fetchUpdateStatusApi,
  checkUpdateApi,
  applyUpdateApi,
  toggleAutoUpdateApi
} from "../api/authApi.js";
import { t } from "../i18n/index.js";

let currentStoreConfig = null;
let editingShiftKey = null;

export async function openStoreConfigModal() {
  const role = localStorage.getItem("vnaigc_role");
  if (role !== "ADMIN") {
    return showToast("Chỉ tài khoản Admin chính mới có quyền truy cập Cấu hình hệ thống quán.", "error");
  }
  setupStoreConfigEvents();
  const token = localStorage.getItem("vnaigc_jwt");
  if (!token) return showToast(t('common.login_required', {}, "Vui lòng đăng nhập trước"), "error");

  try {
    const data = await fetchStoreConfigApi();
    if (!data || !data.config) {
      return showToast(t('store.err_load_config', {}, "Không thể tải cấu hình quán"), "error");
    }
    currentStoreConfig = JSON.parse(JSON.stringify(data.config));
    renderStoreConfigForm(currentStoreConfig);

    const sheet = document.getElementById("storeConfigSheet");
    if (sheet) sheet.classList.add("active");
  } catch (err) {
    showToast(safeErrorDetail(err, t('store.err_conn_read_config', {}, "Lỗi kết nối máy chủ khi đọc cấu hình")), "error");
  }
}

export function closeStoreConfigModal() {
  const sheet = document.getElementById("storeConfigSheet");
  if (sheet) sheet.classList.remove("active");
  hideShiftEditForm();
  stopZaloStatusPolling();
}


export function renderStoreConfigForm(cfg) {
  if (!cfg) return;

  // 1. Tab 1: Shop & POS & WiFi info
  const txtName = document.getElementById("cfgStoreName");
  if (txtName) txtName.value = cfg.store_name || "FnBOps Store Lounge";

  const selPos = document.getElementById("cfgPosMode");
  if (selPos) selPos.value = cfg.pos_mode || "pos365";

  const selAutoClose = document.getElementById("cfgAutoCloseHours");
  if (selAutoClose) {
    const hours = cfg.auto_close_rules?.max_unclosed_hours || 24;
    selAutoClose.value = String(hours);
  }

  const txtWifi = document.getElementById("cfgWifiSSID");
  if (txtWifi) txtWifi.value = cfg.wifi_ssid || cfg.wifi_name || "";

  // Auto-Update Toggle & System Version
  const chkAutoUpdate = document.getElementById("cfgAutoUpdateToggle");
  if (chkAutoUpdate) {
    chkAutoUpdate.checked = cfg.updates?.auto_update !== false;
  }
  loadSystemUpdateStatus();

  // 2. Tab 2: Notifications & Gateway
  const txtTgToken = document.getElementById("cfgTelegramToken");
  if (txtTgToken) {
    txtTgToken.value = cfg.telegram_notifications?.bot_token || cfg.telegram_token || "";
  }

  const txtTgChat = document.getElementById("cfgTelegramChatId");
  if (txtTgChat) {
    txtTgChat.value = cfg.telegram_notifications?.chat_id || cfg.telegram_chat_id || "";
  }

  const chkZalo = document.getElementById("cfgZaloEnabled");
  const isZaloOn = !!(cfg.zalo_notifications?.enabled ?? cfg.zalo_enabled);
  if (chkZalo) {
    chkZalo.checked = isZaloOn;
    updateZaloStatusBadge(isZaloOn);
  }

  // Load 3 Zalo Automation Toggles
  const chkZaloAutoPayslip = document.getElementById("cfgZaloAutoPayslip");
  const chkZaloAutoShiftReminder = document.getElementById("cfgZaloAutoShiftReminder");
  const chkZaloAutoCheckoutAlert = document.getElementById("cfgZaloAutoCheckoutAlert");
  const zAuto = cfg.zalo_automation || {};
  if (chkZaloAutoPayslip) chkZaloAutoPayslip.checked = !!zAuto.enable_auto_payslip;
  if (chkZaloAutoShiftReminder) chkZaloAutoShiftReminder.checked = !!zAuto.enable_auto_shift_reminder;
  if (chkZaloAutoCheckoutAlert) chkZaloAutoCheckoutAlert.checked = !!zAuto.enable_auto_checkout_alert;

  const txtZaloShiftMsg = document.getElementById("cfgZaloShiftReminderMsg");
  const txtZaloCheckoutMsg = document.getElementById("cfgZaloCheckoutAlertMsg");
  if (txtZaloShiftMsg) txtZaloShiftMsg.value = zAuto.shift_reminder_message || "Sắp tới giờ vào ca làm việc! Vui lòng kết nối WiFi quán và bấm Check-in đúng giờ nghen.";
  if (txtZaloCheckoutMsg) txtZaloCheckoutMsg.value = zAuto.checkout_alert_message || "Thời gian làm việc ca đã kết thúc. Vui lòng bấm kết thúc ca (Check-out) nghen, hỗ trợ cái!";

  // 3. Tab 3: Shifts List & Roster
  renderShiftsList(cfg.shifts || {});

  // 3. Tab 3: Roster & Constraints
  const chkGender = document.getElementById("cfgGenderConstraint");
  const gConstraints = cfg.roster_rules?.gender_constraints || {};
  if (chkGender) {
    chkGender.checked = gConstraints.enabled !== false;
  }
  const chkShiftSang = document.getElementById("cfgGenderShift_sang");
  const chkShiftChieu = document.getElementById("cfgGenderShift_chieu");
  const chkShiftToi = document.getElementById("cfgGenderShift_toi");
  const shiftRules = gConstraints.shifts || {};
  if (chkShiftSang) {
    chkShiftSang.checked = shiftRules.sang !== undefined ? !!shiftRules.sang : !!gConstraints.require_male_morning;
  }
  if (chkShiftChieu) {
    chkShiftChieu.checked = !!shiftRules.chieu;
  }
  if (chkShiftToi) {
    chkShiftToi.checked = shiftRules.toi !== undefined ? !!shiftRules.toi : (gConstraints.require_male_evening !== false);
  }

  const numTargetShifts = document.getElementById("cfgTargetShifts");
  if (numTargetShifts) {
    numTargetShifts.value = cfg.roster_rules?.shifts_per_week?.default_target || 5;
  }

  const txtHolidays = document.getElementById("cfgHolidays");
  if (txtHolidays) {
    const hList = cfg.holiday_rules?.holidays || ["02/09"];
    txtHolidays.value = Array.isArray(hList) ? hList.join(", ") : "02/09";
  }

  const numHolidayRate = document.getElementById("cfgHolidayRate");
  if (numHolidayRate) {
    numHolidayRate.value = cfg.holiday_rules?.rate_multiplier || 2.0;
  }
}

export function renderShiftsList(shifts) {
  const container = document.getElementById("shiftsListContainer");
  if (!container) return;

  const keys = Object.keys(shifts);
  if (keys.length === 0) {
    container.innerHTML = `
      <div class="empty-state-card text-center p-16" style="background:var(--bg-card-sub); border-radius:12px; border:1px dashed var(--border);">
        <p class="text-secondary-13 mb-4">${t('store.no_shifts_configured', {}, 'Chưa có ca làm việc nào được cấu hình.')}</p>
        <span class="text-muted-12">${t('store.add_shift_hint', {}, 'Bấm nút "+ Thêm Ca Mới" bên dưới để thiết lập ca cho quán.')}</span>
      </div>
    `;
    return;
  }

  let html = "";
  for (const key of keys) {
    const s = shifts[key];
    const roles = s.roles || {};
    const wkRoles = s.weekday_roles || roles;
    const weRoles = s.weekend_roles || wkRoles;

    const baristas = wkRoles.barista ?? roles.barista ?? 0;
    const services = wkRoles.service ?? roles.service ?? 0;
    const managers = wkRoles.manager ?? roles.manager ?? 0;

    const weBaristas = weRoles.barista ?? baristas;
    const weServices = weRoles.service ?? services;
    const weManagers = weRoles.manager ?? managers;

    const wStart = s.window?.start || s.official_start || "--";
    const wEnd = s.window?.end || s.official_end || "--";

    html += `
      <div class="shift-config-card" style="background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:12px 14px; margin-bottom:10px; box-shadow:0 1px 4px rgba(0,0,0,0.04);">
        <div class="flex-between mb-6">
          <div class="flex-items-center gap-8">
            <span style="font-weight:700; font-size:14px; color:var(--text-primary);">${escapeHtml(s.name || key)}</span>
            <span class="badge-sub-info" style="font-size:11px; font-family:var(--font-mono); text-transform:uppercase;">${escapeHtml(key)}</span>
          </div>
          <div class="flex-items-center gap-6">
            <button type="button" class="btn-edit-shift sheet-btn secondary" data-key="${escapeHtml(key)}" style="width:auto; padding:4px 9px; font-size:11px; font-weight:700; border-radius:6px;">
              ${t('common.edit', {}, 'Sửa')}
            </button>
            <button type="button" class="btn-delete-shift sheet-btn" data-key="${escapeHtml(key)}" style="width:auto; padding:4px 9px; font-size:11px; font-weight:700; border-radius:6px; color:var(--accent-coral); background:rgba(238,93,54,0.08); border:none;" ${keys.length <= 1 ? `disabled title="${t('store.min_one_shift_required', {}, 'Cần tối thiểu 1 ca')}"` : ""}>
              ${t('common.delete', {}, 'Xóa')}
            </button>
          </div>
        </div>

        <div class="grid-sub-info" style="display:grid; grid-template-columns: 1fr 1fr; gap:6px 12px; font-size:12px;">
          <div>
            <span class="text-muted-12">${t('store.shift_hours_label', {}, 'Giờ ca:')}</span>
            <strong class="tabular-nums" style="color:var(--text-secondary); margin-left:4px;">${s.official_start || "--"} - ${s.official_end || "--"}</strong>
          </div>
          <div>
            <span class="text-muted-12">${t('store.late_tolerance_label', {}, 'Dung sai trễ:')}</span>
            <strong class="tabular-nums" style="color:var(--text-secondary); margin-left:4px;">${s.tolerance_limit || "--"}</strong>
          </div>
          <div>
            <span class="text-muted-12">${t('store.standard_duration_label', {}, 'Thời lượng chuẩn:')}</span>
            <strong class="tabular-nums" style="color:var(--accent-emerald); margin-left:4px;">${s.standard_mins || 0} ${t('common.minute_unit_full', {}, 'phút')}</strong>
          </div>
          <div>
            <span class="text-muted-12">${t('store.attendance_window_label', {}, 'Khung giờ chấm công:')}</span>
            <span class="tabular-nums text-muted-12" style="margin-left:4px;">${wStart} - ${wEnd}</span>
          </div>
        </div>

        <div style="margin-top:8px; padding-top:8px; border-top:1px dashed var(--border); display:flex; flex-direction:column; gap:6px; font-size:11px;">
          <div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">
            <span style="font-weight:700; color:var(--text-secondary);">📅 T2-T6:</span>
            <span style="background:var(--bg-card-sub); padding:2px 7px; border-radius:5px;">☕ Bar: <strong>${baristas}</strong></span>
            <span style="background:var(--bg-card-sub); padding:2px 7px; border-radius:5px;">🛎️ PV: <strong>${services}</strong></span>
            <span style="background:var(--bg-card-sub); padding:2px 7px; border-radius:5px;">👔 QL: <strong>${managers}</strong></span>
          </div>
          <div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">
            <span style="font-weight:700; color:var(--accent-coral);">🔥 T7-CN:</span>
            <span style="background:rgba(238,93,54,0.08); color:var(--accent-coral); padding:2px 7px; border-radius:5px;">☕ Bar: <strong>${weBaristas}</strong></span>
            <span style="background:rgba(238,93,54,0.08); color:var(--accent-coral); padding:2px 7px; border-radius:5px;">🛎️ PV: <strong>${weServices}</strong></span>
            <span style="background:rgba(238,93,54,0.08); color:var(--accent-coral); padding:2px 7px; border-radius:5px;">👔 QL: <strong>${weManagers}</strong></span>
          </div>
        </div>
      </div>
    `;
  }

  container.innerHTML = html;

  // Bind edit & delete buttons
  container.querySelectorAll(".btn-edit-shift").forEach(btn => {
    btn.addEventListener("click", () => {
      const k = btn.getAttribute("data-key");
      openShiftEditForm(k);
    });
  });

  container.querySelectorAll(".btn-delete-shift").forEach(btn => {
    btn.addEventListener("click", () => {
      const k = btn.getAttribute("data-key");
      handleDeleteShift(k);
    });
  });
}

export function openShiftEditForm(key = null) {
  editingShiftKey = key;
  const formBox = document.getElementById("shiftEditFormBox");
  const formTitle = document.getElementById("shiftEditFormTitle");
  if (!formBox) return;

  formBox.style.display = "block";
  formBox.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const inputKey = document.getElementById("shiftEditKey");
  const inputName = document.getElementById("shiftEditName");
  const inputStart = document.getElementById("shiftEditStart");
  const inputEnd = document.getElementById("shiftEditEnd");
  const inputTolerance = document.getElementById("shiftEditTolerance");
  const inputMins = document.getElementById("shiftEditMins");
  const inputBarista = document.getElementById("shiftEditBarista");
  const inputService = document.getElementById("shiftEditService");
  const inputManager = document.getElementById("shiftEditManager");
  const inputWeekendBarista = document.getElementById("shiftEditWeekendBarista");
  const inputWeekendService = document.getElementById("shiftEditWeekendService");
  const inputWeekendManager = document.getElementById("shiftEditWeekendManager");
  const inputWinStart = document.getElementById("shiftEditWinStart");
  const inputWinEnd = document.getElementById("shiftEditWinEnd");

  if (key && currentStoreConfig?.shifts?.[key]) {
    const s = currentStoreConfig.shifts[key];
    const roles = s.roles || {};
    const wk = s.weekday_roles || roles;
    const we = s.weekend_roles || wk;

    if (formTitle) formTitle.textContent = t('store.edit_shift_title', { name: s.name || key }, `Chỉnh Sửa Ca: ${s.name || key}`);
    if (inputKey) {
      inputKey.value = key;
      inputKey.disabled = true; // Key cannot be edited
    }
    if (inputName) inputName.value = s.name || "";
    if (inputStart) inputStart.value = s.official_start || "06:00";
    if (inputEnd) inputEnd.value = s.official_end || "11:30";
    if (inputTolerance) inputTolerance.value = s.tolerance_limit || "06:10";
    if (inputMins) inputMins.value = s.standard_mins || 330;
    if (inputBarista) inputBarista.value = wk.barista ?? roles.barista ?? 1;
    if (inputService) inputService.value = wk.service ?? roles.service ?? 2;
    if (inputManager) inputManager.value = wk.manager ?? roles.manager ?? 1;
    if (inputWeekendBarista) inputWeekendBarista.value = we.barista ?? wk.barista ?? roles.barista ?? 1;
    if (inputWeekendService) inputWeekendService.value = we.service ?? wk.service ?? roles.service ?? 2;
    if (inputWeekendManager) inputWeekendManager.value = we.manager ?? wk.manager ?? roles.manager ?? 1;
    if (inputWinStart) inputWinStart.value = s.window?.start || s.official_start || "05:55";
    if (inputWinEnd) inputWinEnd.value = s.window?.end || s.official_end || "13:00";
  } else {
    // Add new shift
    if (formTitle) formTitle.textContent = t('store.add_new_shift_title', {}, "Thêm Ca Làm Việc Mới");
    if (inputKey) {
      inputKey.value = "";
      inputKey.disabled = false;
    }
    if (inputName) inputName.value = "";
    if (inputStart) inputStart.value = "12:00";
    if (inputEnd) inputEnd.value = "17:00";
    if (inputTolerance) inputTolerance.value = "12:10";
    if (inputMins) inputMins.value = "300";
    if (inputBarista) inputBarista.value = "1";
    if (inputService) inputService.value = "2";
    if (inputManager) inputManager.value = "1";
    if (inputWeekendBarista) inputWeekendBarista.value = "2";
    if (inputWeekendService) inputWeekendService.value = "3";
    if (inputWeekendManager) inputWeekendManager.value = "1";
    if (inputWinStart) inputWinStart.value = "11:45";
    if (inputWinEnd) inputWinEnd.value = "18:00";
  }
}

export function hideShiftEditForm() {
  editingShiftKey = null;
  const formBox = document.getElementById("shiftEditFormBox");
  if (formBox) formBox.style.display = "none";
}

export function handleSaveShiftFromForm() {
  const inputKey = document.getElementById("shiftEditKey");
  const inputName = document.getElementById("shiftEditName");
  const inputStart = document.getElementById("shiftEditStart");
  const inputEnd = document.getElementById("shiftEditEnd");
  const inputTolerance = document.getElementById("shiftEditTolerance");
  const inputMins = document.getElementById("shiftEditMins");
  const inputBarista = document.getElementById("shiftEditBarista");
  const inputService = document.getElementById("shiftEditService");
  const inputManager = document.getElementById("shiftEditManager");
  const inputWeekendBarista = document.getElementById("shiftEditWeekendBarista");
  const inputWeekendService = document.getElementById("shiftEditWeekendService");
  const inputWeekendManager = document.getElementById("shiftEditWeekendManager");
  const inputWinStart = document.getElementById("shiftEditWinStart");
  const inputWinEnd = document.getElementById("shiftEditWinEnd");

  let key = (inputKey?.value || "").trim().toLowerCase();
  if (!key) {
    return showToast(t('store.warn_enter_shift_key', {}, "Vui lòng nhập Mã Ca (viết liền không dấu)"), "warning");
  }
  key = key.replace(/[^a-z0-9_]/g, "_");

  const name = (inputName?.value || "").trim() || t('store.default_shift_name', { key: key.toUpperCase() }, `Ca ${key.toUpperCase()}`);
  const start = (inputStart?.value || "06:00").trim();
  const end = (inputEnd?.value || "11:30").trim();
  const tolerance = (inputTolerance?.value || start).trim();
  const mins = parseInt(inputMins?.value || "300", 10);
  const barista = parseInt(inputBarista?.value || "0", 10);
  const service = parseInt(inputService?.value || "1", 10);
  const manager = parseInt(inputManager?.value || "0", 10);
  const weekendBarista = parseInt(inputWeekendBarista?.value || String(barista), 10);
  const weekendService = parseInt(inputWeekendService?.value || String(service), 10);
  const weekendManager = parseInt(inputWeekendManager?.value || String(manager), 10);
  const winStart = (inputWinStart?.value || start).trim();
  const winEnd = (inputWinEnd?.value || end).trim();

  if (!currentStoreConfig) currentStoreConfig = { shifts: {} };
  if (!currentStoreConfig.shifts) currentStoreConfig.shifts = {};

  const shiftData = {
    key: key,
    name: name,
    official_start: start,
    official_end: end,
    tolerance_limit: tolerance,
    min_checkout: start,
    standard_mins: mins,
    roles: {
      manager: manager,
      barista: barista,
      service: service
    },
    weekday_roles: {
      manager: manager,
      barista: barista,
      service: service
    },
    weekend_roles: {
      manager: weekendManager,
      barista: weekendBarista,
      service: weekendService
    },
    window: {
      start: winStart,
      end: winEnd
    }
  };

  currentStoreConfig.shifts[key] = shiftData;
  renderShiftsList(currentStoreConfig.shifts);
  hideShiftEditForm();
  showToast(t('store.msg_shift_draft_saved', { name }, `Đã lưu thiết lập ca "${name}" vào bản nháp`), "success");
}

export async function handleDeleteShift(key) {
  if (!currentStoreConfig?.shifts?.[key]) return;
  const sName = currentStoreConfig.shifts[key].name || key;
  const ok = await showConfirmDialog({
    title: 'Xác Nhận Xóa Ca',
    message: t('store.confirm_delete_shift', { name: sName }, `Bạn có chắc chắn muốn XÓA ca "${sName}" khỏi hệ thống cửa hàng?`),
    confirmText: 'Xóa Ca',
    cancelText: 'Hủy',
    type: 'danger',
    icon: 'solar:trash-bin-trash-bold'
  });
  if (!ok) return;

  delete currentStoreConfig.shifts[key];
  renderShiftsList(currentStoreConfig.shifts);
  if (editingShiftKey === key) hideShiftEditForm();
  showToast(t('store.msg_shift_deleted', { name: sName }, `Đã xóa ca "${sName}"`), "warning");
}

export async function handleSaveStoreConfig() {
  if (!currentStoreConfig) return;

  // 1. Collect Shop & POS & WiFi
  const txtName = document.getElementById("cfgStoreName");
  if (txtName) currentStoreConfig.store_name = txtName.value.trim() || "FnBOps Store Lounge";

  const selPos = document.getElementById("cfgPosMode");
  if (selPos) currentStoreConfig.pos_mode = selPos.value || "pos365";

  const selAutoClose = document.getElementById("cfgAutoCloseHours");
  if (selAutoClose) {
    if (!currentStoreConfig.auto_close_rules) currentStoreConfig.auto_close_rules = {};
    currentStoreConfig.auto_close_rules.max_unclosed_hours = parseInt(selAutoClose.value || "24", 10);
  }

  const txtWifi = document.getElementById("cfgWifiSSID");
  if (txtWifi) {
    currentStoreConfig.wifi_ssid = txtWifi.value.trim() || "WFM_Store_WiFi";
  }

  // Collect Auto-Update Toggle
  const chkAutoUpdate = document.getElementById("cfgAutoUpdateToggle");
  if (chkAutoUpdate) {
    if (!currentStoreConfig.updates) currentStoreConfig.updates = {};
    currentStoreConfig.updates.auto_update = !!chkAutoUpdate.checked;
  }

  // 2. Collect Notification Gateway (Telegram & Zalo)
  const txtTgToken = document.getElementById("cfgTelegramToken");
  const txtTgChat = document.getElementById("cfgTelegramChatId");
  const chkZalo = document.getElementById("cfgZaloEnabled");

  if (!currentStoreConfig.telegram_notifications) currentStoreConfig.telegram_notifications = {};
  if (txtTgToken) currentStoreConfig.telegram_notifications.bot_token = txtTgToken.value.trim();
  if (txtTgChat) currentStoreConfig.telegram_notifications.chat_id = txtTgChat.value.trim();
  currentStoreConfig.telegram_token = currentStoreConfig.telegram_notifications.bot_token;
  currentStoreConfig.telegram_chat_id = currentStoreConfig.telegram_notifications.chat_id;

  if (!currentStoreConfig.zalo_notifications) currentStoreConfig.zalo_notifications = {};
  if (chkZalo) currentStoreConfig.zalo_notifications.enabled = chkZalo.checked;
  currentStoreConfig.zalo_enabled = !!chkZalo?.checked;

  if (!currentStoreConfig.zalo_automation) currentStoreConfig.zalo_automation = {};
  const chkZaloAutoPayslip = document.getElementById("cfgZaloAutoPayslip");
  const chkZaloAutoShiftReminder = document.getElementById("cfgZaloAutoShiftReminder");
  const chkZaloAutoCheckoutAlert = document.getElementById("cfgZaloAutoCheckoutAlert");
  currentStoreConfig.zalo_automation.enable_auto_payslip = !!chkZaloAutoPayslip?.checked;
  currentStoreConfig.zalo_automation.enable_auto_shift_reminder = !!chkZaloAutoShiftReminder?.checked;
  currentStoreConfig.zalo_automation.enable_auto_checkout_alert = !!chkZaloAutoCheckoutAlert?.checked;

  const txtZaloShiftMsg = document.getElementById("cfgZaloShiftReminderMsg");
  const txtZaloCheckoutMsg = document.getElementById("cfgZaloCheckoutAlertMsg");
  if (txtZaloShiftMsg) currentStoreConfig.zalo_automation.shift_reminder_message = txtZaloShiftMsg.value.trim();
  if (txtZaloCheckoutMsg) currentStoreConfig.zalo_automation.checkout_alert_message = txtZaloCheckoutMsg.value.trim();

  // 3. Collect Roster Rules
  if (!currentStoreConfig.roster_rules) currentStoreConfig.roster_rules = {};
  if (!currentStoreConfig.roster_rules.gender_constraints) currentStoreConfig.roster_rules.gender_constraints = {};
  const chkGender = document.getElementById("cfgGenderConstraint");
  const chkShiftSang = document.getElementById("cfgGenderShift_sang");
  const chkShiftChieu = document.getElementById("cfgGenderShift_chieu");
  const chkShiftToi = document.getElementById("cfgGenderShift_toi");

  const isGenderEnabled = chkGender ? chkGender.checked : true;
  const isSang = chkShiftSang ? chkShiftSang.checked : false;
  const isChieu = chkShiftChieu ? chkShiftChieu.checked : false;
  const isToi = chkShiftToi ? chkShiftToi.checked : true;

  currentStoreConfig.roster_rules.gender_constraints.enabled = isGenderEnabled;
  currentStoreConfig.roster_rules.gender_constraints.shifts = {
    sang: isSang,
    chieu: isChieu,
    toi: isToi
  };
  currentStoreConfig.roster_rules.gender_constraints.require_male_morning = isSang;
  currentStoreConfig.roster_rules.gender_constraints.require_male_evening = isToi;

  if (!currentStoreConfig.roster_rules.shifts_per_week) currentStoreConfig.roster_rules.shifts_per_week = {};
  const numTargetShifts = document.getElementById("cfgTargetShifts");
  if (numTargetShifts) {
    currentStoreConfig.roster_rules.shifts_per_week.default_target = parseInt(numTargetShifts.value || "5", 10);
  }

  // 3. Collect Holidays
  if (!currentStoreConfig.holiday_rules) currentStoreConfig.holiday_rules = {};
  const txtHolidays = document.getElementById("cfgHolidays");
  if (txtHolidays) {
    const raw = txtHolidays.value || "";
    const list = raw.split(",").map(s => s.trim()).filter(Boolean);
    currentStoreConfig.holiday_rules.holidays = list.length > 0 ? list : ["02/09"];
  }
  const numHolidayRate = document.getElementById("cfgHolidayRate");
  if (numHolidayRate) {
    currentStoreConfig.holiday_rules.rate_multiplier = parseFloat(numHolidayRate.value || "2.0");
  }

  // 4. Send API POST /api/v1/cc/store/config
  const btnSave = document.getElementById("btnSaveStoreConfig");
  if (btnSave) {
    btnSave.disabled = true;
    btnSave.textContent = t('common.loading', {}, 'Đang lưu...');
  }

  try {
    const res = await updateStoreConfigApi(currentStoreConfig);
    if (res.ok) {
      const data = await res.json();
      currentStoreConfig = data.config;
      showToast(t('store.msg_config_saved_success', {}, "Đã lưu cấu hình quán & ca làm việc thành công!"), "success");
      closeStoreConfigModal();

      // Refresh app view header & branding cleanly
      applyStoreBrandUI(currentStoreConfig);
    } else {
      const err = await res.json();
      showToast(err.detail || t('store.err_save_config', {}, "Không thể lưu cấu hình"), "error");
    }
  } catch (err) {
    showToast(safeErrorDetail(err, t('store.err_conn_save_config', {}, "Lỗi kết nối khi lưu cấu hình")), "error");
  } finally {
    if (btnSave) {
      btnSave.disabled = false;
      btnSave.textContent = t('store.save_btn', {}, 'Lưu Cấu Hình Cửa Hàng');
    }
  }
}

export async function handleResetStoreConfig() {
  const ok = await showConfirmDialog({
    title: 'Khôi Phục Cấu Hình Chuẩn',
    message: t('store.confirm_reset_config', {}, "Khôi phục toàn bộ cấu hình ca và cài đặt về chuẩn mặc định ban đầu của WFM?"),
    confirmText: 'Khôi Phục Mặc Định',
    cancelText: 'Hủy',
    type: 'warning',
    icon: 'solar:restart-bold'
  });
  if (!ok) return;

  try {
    const res = await resetStoreConfigApi();
    if (res.ok) {
      const data = await res.json();
      currentStoreConfig = data.config;
      renderStoreConfigForm(currentStoreConfig);
      hideShiftEditForm();
      showToast(t('store.msg_reset_success', {}, "Đã khôi phục cấu hình mặc định WFM!"), "success");
    } else {
      showToast(t('store.err_reset_failed', {}, "Lỗi khi khôi phục cấu hình"), "error");
    }
  } catch (err) {
    showToast(safeErrorDetail(err, t('common.err_connection', {}, "Lỗi kết nối")), "error");
  }
}

export function updateZaloStatusBadge(enabled, text) {
  const badge = document.getElementById("zaloStatusBadge");
  if (!badge) return;
  if (enabled) {
    badge.className = "badge-sub-info status-active";
    badge.style.color = "var(--accent-emerald)";
    badge.style.background = "rgba(48, 209, 88, 0.12)";
    badge.style.borderColor = "rgba(48, 209, 88, 0.28)";
    badge.textContent = text || t('store.zalo_status_connected', {}, "● Đã kích hoạt Gateway");
  } else {
    badge.className = "badge-sub-info status-off";
    badge.style.color = "var(--text-muted)";
    badge.style.background = "var(--bg-card-sub)";
    badge.style.borderColor = "var(--border)";
    badge.textContent = text || t('store.zalo_status_disconnected', {}, "○ Chưa kích hoạt");
  }
}

export async function handleTestTelegram() {
  const btn = document.getElementById("btnTestTelegram");
  const txtToken = document.getElementById("cfgTelegramToken");
  const txtChat = document.getElementById("cfgTelegramChatId");

  const token = (txtToken?.value || "").trim();
  const chatId = (txtChat?.value || "").trim();

  const originalContent = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span style="display:inline-block; animation:spin 1s linear infinite;">⏳</span> ${t('common.sending', {}, 'Đang gửi...')}`;
  }

  try {
    const payload = {
      telegram_token: token,
      telegram_chat_id: chatId
    };
    const res = await testTelegramApi(payload);
    if (res.ok) {
      const data = await res.json();
      showToast(data.message || t('store.telegram_test_success', {}, "Đã gửi tin nhắn thử nghiệm Telegram thành công!"), "success");
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || t('store.telegram_test_failed', {}, "Gửi tin nhắn Telegram thất bại!"), "error");
    }
  } catch (err) {
    showToast(safeErrorDetail(err, t('store.telegram_test_failed', {}, "Lỗi kết nối khi gửi Telegram")), "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalContent;
    }
  }
}

let zaloPollInterval = null;

export function stopZaloStatusPolling() {
  if (zaloPollInterval) {
    clearInterval(zaloPollInterval);
    zaloPollInterval = null;
  }
}

export function startZaloStatusPolling() {
  stopZaloStatusPolling();
  const startTime = Date.now();
  zaloPollInterval = setInterval(async () => {
    // Tự động dừng sau 120s
    if (Date.now() - startTime > 120000) {
      stopZaloStatusPolling();
      updateZaloStatusBadge(false, t('store.zalo_status_expired', {}, "● Mã QR đã hết hạn, vui lòng bấm lấy mã mới"));
      return;
    }
    try {
      const res = await fetchZaloStatusApi();
      if (res && res.status === 'scanned') {
        updateZaloStatusBadge(true, t('store.zalo_status_scanned', {}, "● Đã quét! Vui lòng bấm Xác nhận trên điện thoại..."));
      } else if (res && (res.connected || res.status === 'ready')) {
        stopZaloStatusPolling();
        const userName = res.user?.name || "Chủ quán";
        updateZaloStatusBadge(true, `● Đã liên kết Zalo Web (${userName})`);
        const qrBox = document.getElementById("zaloQrContainer");
        if (qrBox) qrBox.style.display = "none";
        showToast(t('store.zalo_linked_success', {}, `Đã liên kết Zalo Web thành công (${userName})!`), "success");
      }
    } catch (e) {
      // bỏ qua lỗi polling
    }
  }, 2500);
}

export async function handleScanZaloQR() {
  const btn = document.getElementById("btnScanZaloQR");
  const qrBox = document.getElementById("zaloQrContainer");
  const qrImg = document.getElementById("zaloQrImg");

  const originalContent = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span style="display:inline-block; animation:spin 1s linear infinite;">⏳</span> ${t('common.loading', {}, 'Đang kết nối Zalo...')}`;
  }

  try {
    const data = await fetchZaloQrApi();
    if (data && data.success && (data.qr || data.qr_code)) {
      const qrSource = data.qr || data.qr_code;
      if (qrBox) qrBox.style.display = "block";
      if (qrImg) qrImg.src = qrSource;
      updateZaloStatusBadge(true, t('store.zalo_status_qr_ready', {}, "● Sẵn sàng quét mã"));
      showToast(data.message || t('store.zalo_qr_ready', {}, "Mã QR Zalo Web đã sẵn sàng!"), "success");
      startZaloStatusPolling();
    } else if (data && data.connected) {
      updateZaloStatusBadge(true, `● Đã liên kết Zalo Web (${data.user?.name || 'Chủ quán'})`);
      if (qrBox) qrBox.style.display = "none";
      showToast(data.message || "Tài khoản Zalo đã được kết nối sẵn", "success");
    } else {
      showToast(data?.message || "Không thể tạo mã QR đăng nhập Zalo", "error");
    }
  } catch (err) {
    showToast(safeErrorDetail(err, t('store.zalo_qr_failed', {}, "Không thể kết nối Zalo Gateway")), "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalContent;
    }
  }
}


export function setupStoreConfigEvents() {
  // Modal Open buttons
  const btnStoreConfigSheet = document.getElementById("btnStoreConfigSheet");
  if (btnStoreConfigSheet) {
    btnStoreConfigSheet.addEventListener("click", () => {
      const moreSheet = document.getElementById("topbarMoreSheet");
      if (moreSheet) moreSheet.classList.remove("active");
      openStoreConfigModal();
    });
  }

  const btnQuickStoreConfig = document.getElementById("btnQuickStoreConfig");
  if (btnQuickStoreConfig) {
    btnQuickStoreConfig.addEventListener("click", openStoreConfigModal);
  }

  // Close buttons
  const btnClose = document.getElementById("btnCloseStoreConfig");
  if (btnClose) btnClose.addEventListener("click", closeStoreConfigModal);

  // Tab switching inside Store Config modal
  const tabBtns = document.querySelectorAll(".cfg-tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => {
        b.classList.remove("active");
        b.style.borderBottom = "none";
        b.style.fontWeight = "600";
        b.style.color = "var(--text-secondary)";
      });
      btn.classList.add("active");
      btn.style.borderBottom = "2.5px solid var(--accent-coral)";
      btn.style.fontWeight = "800";
      btn.style.color = "var(--accent-coral)";

      const targetId = btn.getAttribute("data-target");
      document.querySelectorAll(".cfg-tab-pane").forEach(pane => {
        pane.style.display = "none";
      });
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.style.display = "block";
    });
  });

  // Shifts management buttons
  const btnAddShift = document.getElementById("btnAddShift");
  if (btnAddShift) {
    btnAddShift.addEventListener("click", () => openShiftEditForm(null));
  }

  const btnCancelShiftEdit = document.getElementById("btnCancelShiftEdit");
  if (btnCancelShiftEdit) {
    btnCancelShiftEdit.addEventListener("click", hideShiftEditForm);
  }

  const btnSaveShiftEdit = document.getElementById("btnSaveShiftEdit");
  if (btnSaveShiftEdit) {
    btnSaveShiftEdit.addEventListener("click", handleSaveShiftFromForm);
  }

  // Auto calculate standard mins when start & end time change in shift form
  const inputStart = document.getElementById("shiftEditStart");
  const inputEnd = document.getElementById("shiftEditEnd");
  const inputMins = document.getElementById("shiftEditMins");
  const autoCalcMins = () => {
    if (!inputStart?.value || !inputEnd?.value || !inputMins) return;
    try {
      const [sh, sm] = inputStart.value.split(":").map(Number);
      const [eh, em] = inputEnd.value.split(":").map(Number);
      let diff = (eh * 60 + em) - (sh * 60 + sm);
      if (diff < 0) diff += 24 * 60; // Cross-midnight
      if (diff > 0) inputMins.value = diff;
    } catch (e) {}
  };
  if (inputStart) inputStart.addEventListener("change", autoCalcMins);
  if (inputEnd) inputEnd.addEventListener("change", autoCalcMins);

  // Telegram Test button
  const btnTestTelegram = document.getElementById("btnTestTelegram");
  if (btnTestTelegram) {
    btnTestTelegram.addEventListener("click", handleTestTelegram);
  }

  // Zalo Scan QR button
  const btnScanZaloQR = document.getElementById("btnScanZaloQR");
  if (btnScanZaloQR) {
    btnScanZaloQR.addEventListener("click", handleScanZaloQR);
  }

  // Zalo Toggle Change
  const chkZalo = document.getElementById("cfgZaloEnabled");
  if (chkZalo) {
    chkZalo.addEventListener("change", (e) => {
      updateZaloStatusBadge(e.target.checked);
    });
  }

  // Safe WAL SQLite Database Backup Action
  const btnTriggerSafeBackup = document.getElementById("btnTriggerSafeBackup");
  if (btnTriggerSafeBackup) {
    btnTriggerSafeBackup.addEventListener("click", handleTriggerSafeBackup);
  }

  // System Auto-Update Toggle & 1-Click Update Actions
  const chkAutoUpdate = document.getElementById("cfgAutoUpdateToggle");
  if (chkAutoUpdate) {
    chkAutoUpdate.addEventListener("change", handleToggleAutoUpdate);
  }

  const btnCheckUpdate = document.getElementById("btnCheckUpdate");
  if (btnCheckUpdate) {
    btnCheckUpdate.addEventListener("click", handleCheckUpdate);
  }

  const btnApplyUpdate = document.getElementById("btnApplyUpdate");
  if (btnApplyUpdate) {
    btnApplyUpdate.addEventListener("click", handleApplyUpdate);
  }

  // PWA Install Action
  const btnInstallPwa = document.getElementById("btnInstallPwa");
  if (btnInstallPwa) {
    btnInstallPwa.addEventListener("click", handleTriggerPwaInstall);
  }

  // Modal Actions
  const btnSaveConfig = document.getElementById("btnSaveStoreConfig");
  if (btnSaveConfig) {
    btnSaveConfig.addEventListener("click", handleSaveStoreConfig);
  }

  const btnResetConfig = document.getElementById("btnResetStoreConfig");
  if (btnResetConfig) {
    btnResetConfig.addEventListener("click", handleResetStoreConfig);
  }
}

export async function handleTriggerSafeBackup() {
  const btn = document.getElementById("btnTriggerSafeBackup");
  const resText = document.getElementById("safeBackupResultText");
  const token = localStorage.getItem("vnaigc_jwt");
  if (!token) return showToast(t('common.login_required', {}, "Vui lòng đăng nhập trước"), "error");

  const origHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳ Đang sao lưu SQLite WAL an toàn...</span>';
  }

  try {
    const res = await fetch('/api/v1/cc/admin/safe-backup', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      }
    });
    const d = await res.json();
    if (res.ok && (d.success || d.status === 'success')) {
      const sizeKb = Math.round((d.file_size_bytes || 0) / 1024);
      const msg = `✓ Đã sao lưu: ${d.backup_file} (${sizeKb} KB)`;
      showToast(msg, 'success');
      if (resText) {
        resText.textContent = msg;
        resText.style.display = 'block';
      }
    } else {
      showToast(safeErrorDetail(d, 'Không thể sao lưu Database'), 'error');
    }
  } catch (err) {
    showToast(`Lỗi sao lưu: ${err.message}`, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml || '<span>📦 Sao lưu Database ngay</span>';
    }
  }
}

export async function loadSystemUpdateStatus() {
  const badge = document.getElementById("cfgCurrentVersionBadge");
  const statusText = document.getElementById("updateStatusText");
  const notesRow = document.getElementById("updateNotesRow");
  const notesText = document.getElementById("updateReleaseNotesText");
  const chkToggle = document.getElementById("cfgAutoUpdateToggle");
  const btnApply = document.getElementById("btnApplyUpdate");

  try {
    const data = await fetchUpdateStatusApi();
    if (data) {
      if (badge && data.current_version) {
        badge.textContent = `v${data.current_version} (FOSS)`;
      }
      if (chkToggle && typeof data.auto_update === "boolean") {
        chkToggle.checked = data.auto_update;
      }
      if (statusText) {
        if (data.update_available) {
          statusText.textContent = `Có bản mới: v${data.latest_version}`;
          statusText.style.color = "var(--accent-coral, #ea580c)";
          if (btnApply) {
            btnApply.style.background = "#ea580c";
          }
        } else {
          statusText.textContent = `Đã ở phiên bản mới nhất (v${data.current_version})`;
          statusText.style.color = "var(--accent-emerald, #059669)";
          if (btnApply) {
            btnApply.style.background = "#7c3aed";
          }
        }
      }
      if (notesRow && notesText) {
        if (data.release_notes && data.update_available) {
          notesText.textContent = data.release_notes;
          notesRow.style.display = "block";
        } else {
          notesRow.style.display = "none";
        }
      }
    }
  } catch (err) {
    console.warn("Could not load system update status:", err);
  }
}

export async function handleToggleAutoUpdate(e) {
  const enabled = e.target.checked;
  const token = localStorage.getItem("vnaigc_jwt");
  if (!token) return showToast(t('common.login_required', {}, "Vui lòng đăng nhập trước"), "error");

  try {
    const res = await toggleAutoUpdateApi(enabled);
    if (res && (res.success || res.status === "success")) {
      showToast(res.message || (enabled ? "Đã bật tự động cập nhật." : "Đã tắt tự động cập nhật."), "success");
    } else {
      showToast(safeErrorDetail(res, "Không thể lưu cài đặt tự động cập nhật"), "error");
      e.target.checked = !enabled;
    }
  } catch (err) {
    showToast(`Lỗi: ${err.message}`, "error");
    e.target.checked = !enabled;
  }
}

export async function handleCheckUpdate() {
  const btn = document.getElementById("btnCheckUpdate");
  const statusText = document.getElementById("updateStatusText");
  const notesRow = document.getElementById("updateNotesRow");
  const notesText = document.getElementById("updateReleaseNotesText");
  const origHtml = btn ? btn.innerHTML : "";

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳ Đang kiểm tra...</span>';
  }

  try {
    const data = await checkUpdateApi();
    if (data) {
      if (data.update_available) {
        showToast(`Tìm thấy bản phát hành mới: v${data.latest_version}`, "info");
        if (statusText) {
          statusText.textContent = `Có bản mới: v${data.latest_version}`;
          statusText.style.color = "var(--accent-coral, #ea580c)";
        }
        if (notesRow && notesText && data.release_notes) {
          notesText.textContent = data.release_notes;
          notesRow.style.display = "block";
        }
      } else {
        showToast(`Hệ thống đang ở phiên bản mới nhất (v${data.current_version}).`, "success");
        if (statusText) {
          statusText.textContent = `Đã ở phiên bản mới nhất (v${data.current_version})`;
          statusText.style.color = "var(--accent-emerald, #059669)";
        }
        if (notesRow) notesRow.style.display = "none";
      }
    }
  } catch (err) {
    showToast(`Lỗi kiểm tra cập nhật: ${err.message}`, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

export async function handleApplyUpdate() {
  const token = localStorage.getItem("vnaigc_jwt");
  if (!token) return showToast(t('common.login_required', {}, "Vui lòng đăng nhập trước"), "error");

  const confirmed = await showConfirmDialog({
    title: "Xác Nhận Cập Nhật Hệ Thống",
    message: "Hệ thống sẽ tự động sao lưu an toàn CSDL SQLite và cập nhật tính năng mới nhất. Toàn bộ dữ liệu quán (data/) được bảo toàn 100%. Bạn có muốn tiếp tục?",
    confirmText: "Cập nhật ngay",
    cancelText: "Hủy bỏ"
  });
  if (!confirmed) return;

  const btn = document.getElementById("btnApplyUpdate");
  const resText = document.getElementById("applyUpdateResultText");
  const origHtml = btn ? btn.innerHTML : "";

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳ Đang cập nhật & sao lưu...</span>';
  }
  if (resText) {
    resText.style.display = "none";
  }

  try {
    const data = await applyUpdateApi();
    if (data && data.success) {
      const msg = data.message || `Cập nhật thành công lên v${data.current_version}! Dữ liệu quán được bảo toàn.`;
      showToast(msg, "success");
      if (resText) {
        resText.textContent = msg;
        resText.style.color = "var(--accent-emerald, #059669)";
        resText.style.display = "block";
      }
      await loadSystemUpdateStatus();
    } else {
      const errMsg = (data && data.output) || "Không thể thực hiện cập nhật.";
      showToast(errMsg, "error");
      if (resText) {
        resText.textContent = errMsg;
        resText.style.color = "var(--accent-coral, #ea580c)";
        resText.style.display = "block";
      }
    }
  } catch (err) {
    showToast(`Lỗi cập nhật: ${err.message}`, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

// Apply Store Brand UI across topbar, document title and modals
export function applyStoreBrandUI(cfg) {
  if (!cfg) return;
  const storeName = cfg.store_name || (typeof localStorage !== 'undefined' && localStorage.getItem('vnaigc_store_name')) || t('brand.title', {}, 'WFM Vận Hành');

  if (typeof window !== "undefined") {
    window.currentStoreConfig = cfg;
  }
  if (typeof localStorage !== "undefined" && cfg.store_name) {
    try {
      localStorage.setItem("vnaigc_store_name", cfg.store_name);
    } catch (_) {}
  }

  // 1. Cập nhật tiêu đề Topbar mà không làm mất / vỡ icon và role badge
  const brandTitle = document.getElementById("topbarBrandTitle") || document.querySelector(".topbar-brand .brand-title");
  if (brandTitle) {
    brandTitle.textContent = storeName;
    brandTitle.title = storeName;
  }

  // 2. Cập nhật tiêu đề document & PWA Home Screen Title
  document.title = storeName;
  const metaAppTitle = document.getElementById("metaAppTitle");
  if (metaAppTitle) {
    metaAppTitle.setAttribute("content", storeName);
  }

  // 3. Cập nhật tiêu đề màn hình Auth Gate nếu có
  const authTitle = document.getElementById("authGateBrandTitle") || document.querySelector(".auth-gate-title");
  if (authTitle) {
    authTitle.textContent = storeName;
  }

  // 4. Cập nhật input & phụ đề trong Modal nếu có
  const inputStoreName = document.getElementById("cfgStoreName");
  if (inputStoreName && document.activeElement !== inputStoreName) {
    inputStoreName.value = storeName;
  }
  const modalSub = document.getElementById("storeConfigModalSubtitle");
  if (modalSub) {
    modalSub.textContent = t('store.modal_sub_fmt', { name: storeName }, `${storeName} • Tùy biến ca, định biên & quy tắc vận hành`);
  }
  const moreSub = document.getElementById("topbarMoreSubTitle") || document.querySelector(".action-sheet-sub");
  if (moreSub) {
    moreSub.textContent = t('settings.sub_fmt', { name: storeName }, `${storeName} • Chức năng mở rộng`);
  }
}

export async function loadAndApplyStoreBrand() {
  // 1. Áp dụng ngay từ localStorage để không bị giật / nháy tên cũ
  if (typeof localStorage !== "undefined") {
    let cachedName = localStorage.getItem("vnaigc_store_name");
    if (cachedName) {
      applyStoreBrandUI({ store_name: cachedName });
    }
  }

  try {
    const data = await fetchStoreConfigApi();
    if (data && data.config) {
      currentStoreConfig = data.config;
      if (typeof window !== "undefined") {
        window.currentStoreConfig = data.config;
      }
      applyStoreBrandUI(data.config);
    }
  } catch (e) {
    // Non-blocking fallback
  }
}

export async function handleTriggerPwaInstall() {
  const guideBox = document.getElementById("pwaInstallGuideBox");
  if (typeof window !== "undefined" && window.deferredPwaPrompt) {
    try {
      window.deferredPwaPrompt.prompt();
      const choiceResult = await window.deferredPwaPrompt.userChoice;
      if (choiceResult && choiceResult.outcome === "accepted") {
        showToast("Đã chấp nhận cài đặt FnBOps App!", "success");
      }
      window.deferredPwaPrompt = null;
    } catch (err) {
      if (guideBox) guideBox.style.display = "block";
    }
  } else {
    // Trường hợp iOS Safari hoặc trình duyệt không hỗ trợ prompt trực tiếp
    if (guideBox) {
      guideBox.style.display = guideBox.style.display === "block" ? "none" : "block";
    }
    showToast("Trên Safari iPhone/iPad: Nhấn nút Chia sẻ -> Chọn 'Thêm vào MH chính'", "info");
  }
}

// Bắt sự kiện beforeinstallprompt toàn cục cho PWA
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    window.deferredPwaPrompt = e;
  });
}

// Expose to window for global access
if (typeof window !== "undefined") {
  window.openStoreConfigModal = openStoreConfigModal;
  window.closeStoreConfigModal = closeStoreConfigModal;
  window.applyStoreBrandUI = applyStoreBrandUI;
  window.loadAndApplyStoreBrand = loadAndApplyStoreBrand;
  window.handleScanZaloQR = handleScanZaloQR;
  window.setupStoreConfigEvents = setupStoreConfigEvents;
  window.handleTriggerSafeBackup = handleTriggerSafeBackup;
  window.loadSystemUpdateStatus = loadSystemUpdateStatus;
  window.handleToggleAutoUpdate = handleToggleAutoUpdate;
  window.handleCheckUpdate = handleCheckUpdate;
  window.handleApplyUpdate = handleApplyUpdate;
  window.handleTriggerPwaInstall = handleTriggerPwaInstall;
}




