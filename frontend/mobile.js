// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// FNBOPS MOBILE JAVASCRIPT ENGINE V8.0 (MODULAR ES ARCHITECTURE)
// ==========================================================================

import { showToast, safeErrorDetail } from "./src/utils/toast.js";
import { getIconSvg } from "./src/utils/icons.js";
import { fmtMoney, fmtNum, escapeHtml, removeAccents, copyTextToClipboard } from "./src/utils/formatters.js";
import {
  isHolidayDate,
  parseVNDate,
  isoToVNDate,
  vnToISODate,
  getCurrentVNDate,
  getCurrentISOWeekDays,
  getDayOfWeekVN
} from "./src/utils/dateUtils.js";
import {
  state,
  POLICY,
  loadLedgers,
  getStaffBonuses,
  getStaffBonusSummary,
  getStaffAdvances,
  getStaffAdvanceSummary,
  getStaffDeductions,
  getStaffDeductionSummary,
  getStaffRole,
  getIdx,
  getCanonicalStaffName,
  processData
} from "./src/store/state.js";
import {
  getAuthToken,
  getAuthRole,
  getAuthName,
  getAuthUsername,
  clearAuth,
  showAuthGate,
  hideAuthGate,
  isAuthenticated,
  showLoginSheet,
  hideLoginSheet,
  updateSheetScrollLock,
  setupSheetBackdrops,
  setupSheetSwipeGestures,
  applyRolePermissions,
  setupAuth
} from "./src/store/authStore.js";
import {
  renderTabOps,
  confirmShiftOT,
  renderAggAlerts,
  setupAggAlertToggles,
  setupBentoInteractions,
  toggleOTProcessedHistory,
  setupQuickOpsToggles,
  loadOpsToggles
} from "./src/modules/opsModule.js";
import {
  fetchRosterWeekData,
  updateStaffRegStatus,
  checkIsShiftRegistrationOpen,
  updateRosterCountdown,
  openShiftRegistrationModal,
  submitShiftRegistration,
  loadAndRenderManagerRegProgress,
  openShiftRegDetailModal,
  openAutoRosterConfirmModal,
  closeAutoRosterConfirmModal,
  executeRosterAutoFill,
  handleRosterAutoFill,
  handleClonePreviousWeek,
  handleRosterPublish,
  openPeerSwapModal,
  closePeerSwapModal,
  handlePeerSwapSubmit,
  handleRespondPeerSwap,
  fetchAndRenderPendingPeerSwaps,
  openUpdateShiftModal,
  closeUpdateShiftModal,
  handleUpdateShiftSlotSubmit,
  openShiftDetailModal,
  closeShiftDetailModal,
  handleRequestSwapShift,
  getInitialsAvatar,
  setupRosterNav,
  renderTabRoster,
  renderStaffMySchedule,
  renderWeeklyRosterAnalytics
} from "./src/modules/rosterModule.js";
import {
  renderTabPayslip,
  fetchServerPayrollSummary,
  generatePayslipHtml,
  openPayslipModal,
  setupEvalModal,
  setupPayslipActionButtons,
  getStaffShiftsList,
  openStaffShiftsDetailModal,
  closeStaffShiftsModal,
  setupStaffShiftsModalEvents,
  renderStaffPortal,
  handleStaffConfirm,
  handleStaffDispute,
  toggleStaffDisbursement,
  openLedgerEntryModal,
  closeLedgerEntryModal,
  setupLedgerEntryModal
} from "./src/modules/payslipModule.js";
import {
  setupAttendanceModule,
  loadAttendanceTab,
  getActiveShiftElapsedMinutes,
  resetCheckoutSlider,
  openEarlyCheckoutModal,
  executeStaffCheckout,
  initCheckoutSlider,
  resetPressHoldCheckout,
  initPressHoldCheckout,
  handleQuickAttendanceAction,
  handleAttendanceAction,
  renderSOPContent,
  loadPendingManagerCheckouts,
  promptManagerDeleteShift,
  promptManagerReopenShift,
  promptManagerCloseShift,
  executeReopenShift,
  executeDeleteShift,
  promptManagerUnlockShift
} from "./src/modules/attendanceModule.js";
import {
  initInAppReminderMonitor
} from "./src/modules/reminderModule.js";
import {
  openAdminStaffModal,
  updateAdminLockBox,
  setAdminStaffFilter,
  handleToggleStaffStatus,
  renderAdminStaffList,
  handleUpdatePin,
  copyZaloInvite,
  populateSheetStaffDropdown,
  setupCreateStaffHandlers,
  openEditStaffModal,
  closeEditStaffModal,
  setupEditStaffHandlers,
  openAdminLockoutsModalMobile,
  fetchAndRenderAdminLockoutsMobile,
  handleAdminUnlockMobile
} from "./src/modules/adminModule.js";
import {
  initTheme,
  initResponsiveViewMode,
  toggleResponsiveViewMode,
  getAvailableTabs,
  setupNav,
  switchTab,
  setupSwipe,
  loadData,
  setupMonthFilter,
  updateAllViews,
  openMonthPickerSheet,
  closeMonthPickerSheet,
  selectMonth,
  refreshCurrentActiveTab,
  setupAutoRefreshEngine
} from "./src/modules/navModule.js";
import {
  openStoreConfigModal,
  closeStoreConfigModal,
  setupStoreConfigEvents,
  loadAndApplyStoreBrand
} from "./src/modules/storeConfigModule.js";


// ==========================================================================
// EXPOSE TO WINDOW FOR HTML ONCLICK & LEGACY INTEROPERABILITY
// ==========================================================================
if (typeof window !== "undefined") {
  window.state = state;
  window.POLICY = POLICY;
  window.rawData = state.rawData;
  window.employeesMap = state.employeesMap;
  window.records = state.records;
  window.monthsAvailable = state.monthsAvailable;
  window.currentMonth = state.currentMonth;

  window.showToast = showToast;
  window.safeErrorDetail = safeErrorDetail;
  window.fmtMoney = fmtMoney;
  window.fmtNum = fmtNum;
  window.escapeHtml = escapeHtml;
  window.removeAccents = removeAccents;
  window.copyTextToClipboard = copyTextToClipboard;
  window.copyTextFallback = copyTextToClipboard;
  window.isHolidayDate = isHolidayDate;
  window.parseVNDate = parseVNDate;
  window.isoToVNDate = isoToVNDate;
  window.vnToISODate = vnToISODate;
  window.getCurrentVNDate = getCurrentVNDate;
  window.getCurrentISOWeekDays = getCurrentISOWeekDays;
  window.getDayOfWeekVN = getDayOfWeekVN;

  window.getAuthToken = getAuthToken;
  window.getAuthRole = getAuthRole;
  window.getAuthName = getAuthName;
  window.getAuthUsername = getAuthUsername;
  window.clearAuth = clearAuth;
  window.showAuthGate = showAuthGate;
  window.hideAuthGate = hideAuthGate;
  window.isAuthenticated = isAuthenticated;
  window.showLoginSheet = showLoginSheet;
  window.hideLoginSheet = hideLoginSheet;
  window.updateSheetScrollLock = updateSheetScrollLock;
  window.setupSheetBackdrops = setupSheetBackdrops;
  window.setupSheetSwipeGestures = setupSheetSwipeGestures;
  window.applyRolePermissions = applyRolePermissions;
  window.setupAuth = setupAuth;

  window.loadLedgers = loadLedgers;
  window.getStaffBonuses = getStaffBonuses;
  window.getStaffBonusSummary = getStaffBonusSummary;
  window.getStaffAdvances = getStaffAdvances;
  window.getStaffAdvanceSummary = getStaffAdvanceSummary;
  window.getStaffDeductions = getStaffDeductions;
  window.getStaffDeductionSummary = getStaffDeductionSummary;
  window.getStaffRole = getStaffRole;
  window.getIdx = getIdx;
  window.getCanonicalStaffName = getCanonicalStaffName;
  window.processData = processData;

  window.renderTabOps = renderTabOps;
  window.confirmShiftOT = confirmShiftOT;
  window.renderAggAlerts = renderAggAlerts;
  window.setupAggAlertToggles = setupAggAlertToggles;
  window.setupBentoInteractions = setupBentoInteractions;
  window.toggleOTProcessedHistory = toggleOTProcessedHistory;

  window.fetchRosterWeekData = fetchRosterWeekData;
  window.updateStaffRegStatus = updateStaffRegStatus;
  window.checkIsShiftRegistrationOpen = checkIsShiftRegistrationOpen;
  window.updateRosterCountdown = updateRosterCountdown;
  window.openShiftRegistrationModal = openShiftRegistrationModal;
  window.submitShiftRegistration = submitShiftRegistration;
  window.loadAndRenderManagerRegProgress = loadAndRenderManagerRegProgress;
  window.openShiftRegDetailModal = openShiftRegDetailModal;
  window.openAutoRosterConfirmModal = openAutoRosterConfirmModal;
  window.closeAutoRosterConfirmModal = closeAutoRosterConfirmModal;
  window.executeRosterAutoFill = executeRosterAutoFill;
  window.handleRosterAutoFill = handleRosterAutoFill;
  window.handleClonePreviousWeek = handleClonePreviousWeek;
  window.handleRosterPublish = handleRosterPublish;
  window.openPeerSwapModal = openPeerSwapModal;
  window.closePeerSwapModal = closePeerSwapModal;
  window.handlePeerSwapSubmit = handlePeerSwapSubmit;
  window.handleRespondPeerSwap = handleRespondPeerSwap;
  window.fetchAndRenderPendingPeerSwaps = fetchAndRenderPendingPeerSwaps;
  window.openUpdateShiftModal = openUpdateShiftModal;
  window.closeUpdateShiftModal = closeUpdateShiftModal;
  window.handleUpdateShiftSlotSubmit = handleUpdateShiftSlotSubmit;
  window.openShiftDetailModal = openShiftDetailModal;
  window.closeShiftDetailModal = closeShiftDetailModal;
  window.handleRequestSwapShift = handleRequestSwapShift;
  window.getInitialsAvatar = getInitialsAvatar;
  window.setupRosterNav = setupRosterNav;
  window.renderTabRoster = renderTabRoster;
  window.renderStaffMySchedule = renderStaffMySchedule;
  window.renderWeeklyRosterAnalytics = renderWeeklyRosterAnalytics;

  window.renderTabPayslip = renderTabPayslip;
  window.fetchServerPayrollSummary = fetchServerPayrollSummary;
  window.generatePayslipHtml = generatePayslipHtml;
  window.openPayslipModal = openPayslipModal;
  window.setupEvalModal = setupEvalModal;
  window.getStaffShiftsList = getStaffShiftsList;
  window.openStaffShiftsDetailModal = openStaffShiftsDetailModal;
  window.closeStaffShiftsModal = closeStaffShiftsModal;
  window.renderStaffPortal = renderStaffPortal;
  window.handleStaffConfirm = handleStaffConfirm;
  window.handleStaffDispute = handleStaffDispute;
  window.toggleStaffDisbursement = toggleStaffDisbursement;
  window.openLedgerEntryModal = openLedgerEntryModal;
  window.closeLedgerEntryModal = closeLedgerEntryModal;

  window.setupAttendanceModule = setupAttendanceModule;
  window.loadAttendanceTab = loadAttendanceTab;
  window.getActiveShiftElapsedMinutes = getActiveShiftElapsedMinutes;
  window.resetCheckoutSlider = resetCheckoutSlider;
  window.openEarlyCheckoutModal = openEarlyCheckoutModal;
  window.executeStaffCheckout = executeStaffCheckout;
  window.initCheckoutSlider = initCheckoutSlider;
  window.resetPressHoldCheckout = resetPressHoldCheckout;
  window.initPressHoldCheckout = initPressHoldCheckout;
  window.handleQuickAttendanceAction = handleQuickAttendanceAction;
  window.handleAttendanceAction = handleAttendanceAction;
  window.renderSOPContent = renderSOPContent;
  window.loadPendingManagerCheckouts = loadPendingManagerCheckouts;
  window.promptManagerDeleteShift = promptManagerDeleteShift;
  window.promptManagerReopenShift = promptManagerReopenShift;
  window.promptManagerCloseShift = promptManagerCloseShift;
  window.executeReopenShift = executeReopenShift;
  window.executeDeleteShift = executeDeleteShift;
  window.promptManagerUnlockShift = promptManagerUnlockShift;

  window.openAdminStaffModal = openAdminStaffModal;
  window.updateAdminLockBox = updateAdminLockBox;
  window.setAdminStaffFilter = setAdminStaffFilter;
  window.handleToggleStaffStatus = handleToggleStaffStatus;
  window.renderAdminStaffList = renderAdminStaffList;
  window.handleUpdatePin = handleUpdatePin;
  window.copyZaloInvite = copyZaloInvite;
  window.populateSheetStaffDropdown = populateSheetStaffDropdown;
  window.setupCreateStaffHandlers = setupCreateStaffHandlers;
  window.openEditStaffModal = openEditStaffModal;
  window.closeEditStaffModal = closeEditStaffModal;
  window.setupEditStaffHandlers = setupEditStaffHandlers;
  window.openAdminStaffModal = openAdminStaffModal;
  window.openAdminLockoutsModalMobile = openAdminLockoutsModalMobile;
  window.fetchAndRenderAdminLockoutsMobile = fetchAndRenderAdminLockoutsMobile;
  window.handleAdminUnlockMobile = handleAdminUnlockMobile;

  window.getIconSvg = getIconSvg;
  window.initTheme = initTheme;
  window.initResponsiveViewMode = initResponsiveViewMode;
  window.toggleResponsiveViewMode = toggleResponsiveViewMode;
  window.getAvailableTabs = getAvailableTabs;
  window.setupNav = setupNav;
  window.switchTab = switchTab;
  window.setupSwipe = setupSwipe;
  window.loadData = loadData;
  window.setupMonthFilter = setupMonthFilter;
  window.updateAllViews = updateAllViews;
  window.openMonthPickerSheet = openMonthPickerSheet;
  window.closeMonthPickerSheet = closeMonthPickerSheet;
  window.selectMonth = selectMonth;
  window.refreshCurrentActiveTab = refreshCurrentActiveTab;
  window.setupAutoRefreshEngine = setupAutoRefreshEngine;

  window.openStoreConfigModal = openStoreConfigModal;
  window.closeStoreConfigModal = closeStoreConfigModal;
}

// ==========================================================================
// TOPBAR ACTION SHEET SETUP
// ==========================================================================
function setupTopbarMore() {
  const btnMore = document.getElementById("btnTopbarMore");
  const moreSheet = document.getElementById("topbarMoreSheet");
  const btnCloseMore = document.getElementById("btnCloseTopbarMore");

  if (btnMore && moreSheet) {
    btnMore.addEventListener("click", () => {
      moreSheet.classList.add("active");
      updateSheetScrollLock();
    });
  }

  if (btnCloseMore && moreSheet) {
    btnCloseMore.addEventListener("click", () => {
      moreSheet.classList.remove("active");
      updateSheetScrollLock();
    });
  }
}

// ==========================================================================
// APPLICATION BOOTSTRAP
// ==========================================================================
function bootApp() {
  initTheme();
  initResponsiveViewMode();
  setupSheetBackdrops();
  setupTopbarMore();
  setupNav();
  setupStoreConfigEvents();
  loadAndApplyStoreBrand();

  const btnAdminStaff = document.getElementById("btnAdminStaff");
  if (btnAdminStaff) {
    btnAdminStaff.addEventListener("click", openAdminStaffModal);
  }
  const btnLockouts = document.getElementById("btnAdminLockoutsMobile");
  if (btnLockouts) {
    btnLockouts.addEventListener("click", openAdminLockoutsModalMobile);
  }
  const btnRefreshLockouts = document.getElementById("btnRefreshAdminLockoutsMobile");
  if (btnRefreshLockouts) {
    btnRefreshLockouts.addEventListener("click", fetchAndRenderAdminLockoutsMobile);
  }

  const handleSuccessfulAuth = () => {
    hideAuthGate();
    const role = getAuthRole();
    const name = getAuthName();
    applyRolePermissions(role, { full_name: name });

    setupNav();
    setupSwipe();
    setupRosterNav();
    setupEvalModal();
    setupPayslipActionButtons();
    setupStaffShiftsModalEvents();
    setupBentoInteractions();
    setupAggAlertToggles();
    setupQuickOpsToggles();
    setupCreateStaffHandlers();
    setupEditStaffHandlers();
    setupAttendanceModule();
    setupStoreConfigEvents();
    loadAndApplyStoreBrand();
    initInAppReminderMonitor();
    setupModalKeyboardScrollProtection();
    loadLedgers();
    loadData();

    const defaultTab = (role === "ADMIN" || role === "MANAGER") ? "ops" : "attendance";
    if (typeof window.switchTab === "function") {
      window.switchTab(defaultTab);
    }
  };

  setupAuth(handleSuccessfulAuth);

  if (isAuthenticated()) {
    handleSuccessfulAuth();
  } else {
    showAuthGate();
  }
}

export function setupModalKeyboardScrollProtection() {
  if (typeof document === 'undefined') return;
  document.addEventListener('focusin', (e) => {
    const modal = e.target.closest('.sheet-modal');
    if (modal && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT')) {
      setTimeout(() => {
        try {
          e.target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } catch (_) {}
      }, 280);
    }
  });
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootApp);
  } else {
    bootApp();
  }
}

export {
  state,
  POLICY,
  getIconSvg,
  showToast,
  safeErrorDetail,
  fmtMoney,
  fmtNum,
  escapeHtml,
  removeAccents,
  copyTextToClipboard,
  initTheme,
  initResponsiveViewMode,
  toggleResponsiveViewMode,
  setupNav,
  switchTab,
  loadData,
  updateAllViews,
  renderTabOps,
  renderTabRoster,
  renderTabPayslip,
  loadAttendanceTab,
  setupSheetSwipeGestures,
  refreshCurrentActiveTab,
  setupAutoRefreshEngine
};
