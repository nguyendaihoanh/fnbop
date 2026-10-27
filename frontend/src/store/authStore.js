// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// AUTHENTICATION STORE & RBAC PERMISSIONS
// ==========================================================================

import { showToast, safeErrorDetail } from "../utils/toast.js";
import { getIconSvg } from "../utils/icons.js";
import { getRoleNavConfig } from "../config/navSchema.js";
import { t } from "../i18n/index.js";
import { resetState } from "./state.js";

export function getAuthToken() {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem("vnaigc_jwt") || localStorage.getItem("vnaigc_token") || null;
}

export function getAuthRole() {
  if (typeof localStorage === "undefined") return "STAFF";
  return localStorage.getItem("vnaigc_role") || "STAFF";
}

export function getAuthName() {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem("vnaigc_name") || "";
}

export function getAuthUsername() {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem("vnaigc_username") || "";
}

export function isAuthenticated() {
  const token = getAuthToken();
  return !!(token && token.trim().length > 0);
}

export function showAuthGate() {
  if (typeof document === "undefined") return;
  document.body.classList.remove("authenticated");
  const gate = document.getElementById("authGateScreen");
  if (gate) {
    gate.style.display = "flex";
  }
  const appContainer = document.getElementById("appContainer");
  if (appContainer) {
    appContainer.style.display = "none";
  }
  const errBanner = document.getElementById("authErrorBanner");
  if (errBanner) {
    errBanner.textContent = "";
    errBanner.classList.remove("active");
  }
}

export function hideAuthGate() {
  if (typeof document === "undefined") return;
  document.body.classList.add("authenticated");
  const gate = document.getElementById("authGateScreen");
  if (gate) {
    gate.style.display = "none";
  }
  const appContainer = document.getElementById("appContainer");
  if (appContainer) {
    appContainer.style.display = "";
  }
}

export function showLoginSheet() {
  showAuthGate();
}

export function hideLoginSheet() {
  hideAuthGate();
}

export function clearAuth() {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem("vnaigc_logged_out", "1");
    localStorage.removeItem("vnaigc_jwt");
    localStorage.removeItem("vnaigc_token");
    localStorage.removeItem("vnaigc_role");
    localStorage.removeItem("vnaigc_name");
    localStorage.removeItem("vnaigc_username");
    localStorage.removeItem("vnaigc_sheet_names");
  }
  // [C3-FIX] Reset in-memory state to prevent financial data leakage
  // between users on shared devices (e.g. POS terminal at the store).
  resetState();
  if (typeof window !== "undefined") {
    window.currentUser = "";
    window.currentStaffName = "";
  }
  showAuthGate();
}

export function updateSheetScrollLock() {
  if (typeof document === "undefined") return;
  const hasActive = !!document.querySelector(".sheet-overlay.active");
  document.body.style.overflow = hasActive ? "hidden" : "";
}

export function setupSheetBackdrops() {
  if (typeof document === "undefined") return;
  document.querySelectorAll(".sheet-overlay").forEach(sheet => {
    sheet.addEventListener("click", (e) => {
      if (e.target === sheet) {
        sheet.classList.remove("active");
        updateSheetScrollLock();
      }
    });
  });

  if (typeof window !== "undefined") {
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        const activeSheets = document.querySelectorAll(".sheet-overlay.active");
        if (activeSheets.length > 0) {
          activeSheets.forEach(s => s.classList.remove("active"));
          updateSheetScrollLock();
        }
      }
    });
  }

  if (typeof MutationObserver !== "undefined") {
    const observer = new MutationObserver(() => {
      updateSheetScrollLock();
    });
    document.querySelectorAll(".sheet-overlay").forEach(sheet => {
      observer.observe(sheet, { attributes: true, attributeFilter: ["class"] });
    });
  }

  setupSheetSwipeGestures();
}

export function setupSheetSwipeGestures() {
  if (typeof document === "undefined") return;

  const overlays = document.querySelectorAll(".sheet-overlay");
  overlays.forEach(sheetOverlay => {
    const sheetModal = sheetOverlay.querySelector(".sheet-modal");
    if (!sheetModal || sheetModal.dataset.swipeSetup === "true") return;
    sheetModal.dataset.swipeSetup = "true";

    let startY = 0;
    let startX = 0;
    let deltaY = 0;
    let isDragging = false;
    let startTime = 0;
    let canDrag = false;

    // Helper to find whether an inner scrollable element has scrolled down
    const hasScrolledAncestor = (target) => {
      let curr = target;
      while (curr && curr !== sheetModal && curr !== document.body) {
        if (curr.scrollHeight > curr.clientHeight && curr.scrollTop > 0) {
          return true;
        }
        curr = curr.parentElement;
      }
      return sheetModal.scrollTop > 0;
    };

    const handleTouchStart = (e) => {
      if (!sheetOverlay.classList.contains("active")) return;
      if (!e.touches || e.touches.length !== 1) return;

      const target = e.target;
      const isGrabber = !!target.closest(".sheet-grabber");
      const isInteractive = !!target.closest("input, select, textarea, button, a, [contenteditable='true']");

      // Don't swallow taps on interactive buttons or form fields (unless grabber)
      if (isInteractive && !isGrabber) return;

      // Only allow drag if starting on .sheet-grabber OR content is at top (scrollTop === 0)
      if (!isGrabber && hasScrolledAncestor(target)) {
        canDrag = false;
        return;
      }

      canDrag = true;
      isDragging = false;
      startY = e.touches[0].clientY;
      startX = e.touches[0].clientX;
      startTime = Date.now();
      deltaY = 0;
    };

    const handleTouchMove = (e) => {
      if (!canDrag || !e.touches || e.touches.length !== 1) return;

      const currentY = e.touches[0].clientY;
      const currentX = e.touches[0].clientX;
      const diffY = currentY - startY;
      const diffX = currentX - startX;

      if (!isDragging) {
        // If swiping horizontally, cancel gesture
        if (Math.abs(diffX) > Math.abs(diffY)) {
          canDrag = false;
          return;
        }

        // Only start drag when finger moves DOWN (diffY > 6px) and content is at top
        const isGrabber = !!e.target.closest(".sheet-grabber");
        if (diffY > 6 && (isGrabber || !hasScrolledAncestor(e.target))) {
          isDragging = true;
          sheetModal.style.transition = 'none';
          sheetOverlay.style.transition = 'none';
        } else {
          return;
        }
      }

      if (isDragging) {
        if (e.cancelable) {
          e.preventDefault();
        }

        deltaY = Math.max(0, diffY);
        sheetModal.style.transform = `translateY(${deltaY}px)`;

        // Giảm nhẹ opacity của backdrop nền khi kéo modal xuống
        const opacityRatio = Math.max(0.35, 1 - (deltaY / 450));
        sheetOverlay.style.opacity = opacityRatio.toFixed(2);
      }
    };

    const handleTouchEnd = () => {
      if (!canDrag && !isDragging) return;
      canDrag = false;

      if (!isDragging) return;
      isDragging = false;

      const elapsed = Math.max(1, Date.now() - startTime);
      const velocity = deltaY / elapsed; // px per ms

      // Condition: deltaY > 75px OR quick downward swipe (velocity > 0.45 px/ms with deltaY > 20px)
      if (deltaY > 75 || (velocity > 0.45 && deltaY > 20)) {
        // Kéo modal trượt hẳn xuống dưới và đóng sheet
        sheetModal.style.transition = 'transform 0.22s cubic-bezier(0.2, 0.8, 0.2, 1)';
        sheetOverlay.style.transition = 'opacity 0.22s ease';
        sheetModal.style.transform = 'translateY(100%)';
        sheetOverlay.style.opacity = '0';

        setTimeout(() => {
          sheetOverlay.classList.remove('active');
          sheetModal.style.transform = '';
          sheetModal.style.transition = '';
          sheetOverlay.style.opacity = '';
          sheetOverlay.style.transition = '';
          updateSheetScrollLock();
        }, 230);
      } else {
        // Đưa modal đàn hồi trở lại vị trí ban đầu
        sheetModal.style.transition = 'transform 0.25s cubic-bezier(0.2, 0.8, 0.2, 1)';
        sheetOverlay.style.transition = 'opacity 0.25s ease';
        sheetModal.style.transform = '';
        sheetOverlay.style.opacity = '';

        setTimeout(() => {
          sheetModal.style.transition = '';
          sheetOverlay.style.transition = '';
        }, 260);
      }
    };

    sheetModal.addEventListener("touchstart", handleTouchStart, { passive: true });
    sheetModal.addEventListener("touchmove", handleTouchMove, { passive: false });
    sheetModal.addEventListener("touchend", handleTouchEnd, { passive: true });
    sheetModal.addEventListener("touchcancel", handleTouchEnd, { passive: true });
  });
}

export function applyRolePermissions(role, meta = {}) {
  if (typeof document === "undefined" || !document.body) return;
  if (!document.body.dataset) document.body.dataset = {};
  document.body.dataset.role = role || "STAFF";
  if (typeof document.body.setAttribute === "function") {
    document.body.setAttribute("data-role", role || "STAFF");
  }
  const isStaff = (role === "STAFF");
  const badge = document.getElementById("userRoleBadge");
  const btnEval = document.getElementById("btnOpenEval");
  const btnAdmin = document.getElementById("btnAdminStaff");
  const btnLockouts = document.getElementById("btnAdminLockoutsMobile");
  const btnAdminSheet = document.getElementById("btnAdminStaffSheet");
  const btnLockoutsSheet = document.getElementById("btnAdminLockoutsSheet");
  const linkMonthlySheet = document.getElementById("btnMonthlyReportSheet");
  const linkDesktopSheet = document.getElementById("btnDesktopSheet");
  const btnStoreConfigSheet = document.getElementById("btnStoreConfigSheet");
  const bottomNav = document.querySelector(".mobile-bottom-nav");
  const tabOps = document.getElementById("tabOps");
  const tabRoster = document.getElementById("tabRoster");
  const tabPayslip = document.getElementById("tabPayslip");
  const tabAttendance = document.getElementById("tabAttendance");
  const staffPortalContainer = document.getElementById("staffPortalContainer");
  const adminPayslipContainer = document.getElementById("adminPayslipContainer");
  const linkMonthly = document.querySelector('a[href="monthly-report.html"]');
  const linkDesktop = document.querySelector('a[href="desktop.html"]');

  const navOps = document.querySelector('.nav-tab-btn[data-tab="ops"]');
  const navRoster = document.querySelector('.nav-tab-btn[data-tab="roster"]');
  const navPayslip = document.querySelector('.nav-tab-btn[data-tab="payslip"]');
  const navAttendance = document.querySelector('.nav-tab-btn[data-tab="attendance"]');
  const navRosterLabel = document.getElementById("navRosterLabel");
  const rosterWeeklyKpis = document.getElementById("rosterWeeklyKpis");
  const cardWeeklyAnomalies = document.getElementById("cardWeeklyAnomalies");
  const cardWeeklyWorkload = document.getElementById("cardWeeklyWorkload");
  const staffMyScheduleCard = document.getElementById("staffMyScheduleCard");

  const switchTabFn = (typeof window !== "undefined" && window.switchTab) || function() {};
  const navConfig = getRoleNavConfig(role);

  // Áp dụng cấu hình Navigation tập trung (Schema-Driven)
  if (bottomNav) {
    bottomNav.style.display = "flex";
    bottomNav.classList.toggle("staff-nav-layout", isStaff);
    bottomNav.classList.toggle("nav-cradle-mode", isStaff);
  }
  if (typeof window !== "undefined" && typeof window.updateCradlePath === "function") {
    setTimeout(window.updateCradlePath, 20);
  }
  if (navAttendance) {
    navAttendance.classList.toggle("nav-hero-action", !!navConfig.heroTab);
  }
  document.querySelectorAll(".mobile-bottom-nav .nav-tab-btn").forEach(btn => {
    const tabKey = btn.getAttribute("data-tab");
    const isVisible = navConfig.tabs.includes(tabKey);
    btn.classList.toggle("nav-tab-hidden", !isVisible);
    if (btn.style && typeof btn.style.setProperty === "function") {
      btn.style.setProperty("display", isVisible ? "flex" : "none", "important");
    } else if (btn.style) {
      btn.style.display = isVisible ? "flex" : "none";
    }
  });
  if (navRosterLabel) {
    navRosterLabel.textContent = (typeof t === "function" ? t(navConfig.rosterLabelKey) : null) || navConfig.rosterDefaultLabel;
  }
  const brandTitle = document.getElementById("brandTitle") || document.querySelector(".brand-title");
  const sName = (typeof window !== "undefined" && window.currentStoreConfig && window.currentStoreConfig.store_name) ||
                (typeof localStorage !== "undefined" && localStorage.getItem("vnaigc_store_name")) ||
                "";

  if (isStaff) {
    if (brandTitle) {
      const rawName = meta.full_name || localStorage.getItem("vnaigc_name") || "";
      const firstName = rawName.trim().split(" ").pop();
      const prefix = sName || "WFM";
      brandTitle.textContent = firstName ? `${prefix} • Chào ${firstName}` : `${prefix} Chấm Công`;
      brandTitle.title = brandTitle.textContent;
    }
    if (badge) {
      badge.textContent = "NV";
      badge.title = meta.full_name || localStorage.getItem("vnaigc_name") || "Nhân Viên";
      badge.style.background = "var(--accent-emerald-sub)";
      badge.style.color = "var(--accent-emerald)";
    }
    if (btnEval) btnEval.style.display = "none";
    if (btnAdmin) btnAdmin.style.display = "none";
    if (btnLockouts) btnLockouts.style.display = "none";
    if (linkMonthly) linkMonthly.style.display = "none";
    if (linkDesktop) linkDesktop.style.display = "none";
    if (btnAdminSheet) btnAdminSheet.style.display = "none";
    if (btnLockoutsSheet) btnLockoutsSheet.style.display = "none";
    if (linkMonthlySheet) linkMonthlySheet.style.display = "none";
    if (linkDesktopSheet) linkDesktopSheet.style.display = "none";
    if (btnStoreConfigSheet) btnStoreConfigSheet.style.display = "none";

    if (cardWeeklyAnomalies) cardWeeklyAnomalies.style.display = "none";
    if (cardWeeklyWorkload) cardWeeklyWorkload.style.display = "none";
    if (rosterWeeklyKpis) rosterWeeklyKpis.style.display = "none";
    if (staffMyScheduleCard) staffMyScheduleCard.style.display = "block";

    const matrixCard = document.querySelector(".weekly-matrix-card");
    const dayDetailCard = document.querySelector(".roster-day-detail-card");
    if (matrixCard) matrixCard.style.display = "none";
    if (dayDetailCard) dayDetailCard.style.display = "none";

    const staffRosterBanner = document.getElementById("staffRosterBanner");
    const managerRosterToolbar = document.getElementById("managerRosterToolbar");
    if (staffRosterBanner) staffRosterBanner.style.display = "block";
    if (managerRosterToolbar) managerRosterToolbar.style.display = "none";

    if (staffPortalContainer) staffPortalContainer.style.display = "flex";
    if (adminPayslipContainer) adminPayslipContainer.style.display = "none";
    const mgrPayslipSegStaff = document.getElementById("managerPayslipSegmentedControl");
    if (mgrPayslipSegStaff) mgrPayslipSegStaff.style.display = "none";

    const managerAttendancePanel = document.getElementById("managerAttendancePanel");
    if (managerAttendancePanel) managerAttendancePanel.style.display = "none";

    const quickOpsCard = document.getElementById("quickOpsTogglesCard");
    if (quickOpsCard) quickOpsCard.style.display = "none";

    // Kích hoạt tab mặc định từ Schema
    if (typeof window !== "undefined" && !window._initialTabSwitched) {
      window._initialTabSwitched = true;
      switchTabFn(navConfig.defaultTab);
    }
  } else if (role === "MANAGER") {
    // Quản lý ca
    if (brandTitle) {
      brandTitle.textContent = sName || "WFM Vận Hành";
      brandTitle.title = brandTitle.textContent;
    }
    if (badge) {
      badge.textContent = "QL";
      badge.title = "Quản Lý • " + (meta.full_name || localStorage.getItem("vnaigc_name") || "Quản Lý Ca");
      badge.style.background = "rgba(245, 158, 11, 0.15)";
      badge.style.color = "#d97706";
    }
    if (btnEval) btnEval.style.display = "inline-flex";
    if (btnAdmin) btnAdmin.style.display = "inline-flex";
    if (btnLockouts) btnLockouts.style.display = "none";
    if (linkMonthly) linkMonthly.style.display = "none";
    if (linkDesktop) linkDesktop.style.display = "inline-flex";
    if (btnAdminSheet) btnAdminSheet.style.display = "flex";
    if (btnLockoutsSheet) btnLockoutsSheet.style.display = "none";
    if (linkMonthlySheet) linkMonthlySheet.style.display = "none";
    if (linkDesktopSheet) linkDesktopSheet.style.display = "flex";
    if (btnStoreConfigSheet) btnStoreConfigSheet.style.display = "none";

    if (cardWeeklyAnomalies) cardWeeklyAnomalies.style.display = "block";
    if (cardWeeklyWorkload) cardWeeklyWorkload.style.display = "block";
    if (staffMyScheduleCard) staffMyScheduleCard.style.display = "none";

    const matrixCardMgr = document.querySelector(".weekly-matrix-card");
    const dayDetailCardMgr = document.querySelector(".roster-day-detail-card");
    if (matrixCardMgr) matrixCardMgr.style.display = "block";
    if (dayDetailCardMgr) dayDetailCardMgr.style.display = "block";

    const staffRosterBanner = document.getElementById("staffRosterBanner");
    const managerRosterToolbar = document.getElementById("managerRosterToolbar");
    if (staffRosterBanner) staffRosterBanner.style.display = "none";
    if (managerRosterToolbar) managerRosterToolbar.style.display = "flex";

    // Phân luồng Tab Phiếu Lương cho Quản Lý: Segmented Control 2 chế độ
    const mgrPayslipSeg = document.getElementById("managerPayslipSegmentedControl");
    if (mgrPayslipSeg) {
      mgrPayslipSeg.style.display = "flex";
      setupManagerPayslipSegmentedControl();
    } else {
      if (staffPortalContainer) staffPortalContainer.style.display = "flex";
      if (adminPayslipContainer) adminPayslipContainer.style.display = "none";
    }

    const managerAttendancePanel = document.getElementById("managerAttendancePanel");
    if (managerAttendancePanel) managerAttendancePanel.style.display = "block";

    const quickOpsCardMgr = document.getElementById("quickOpsTogglesCard");
    if (quickOpsCardMgr) {
      quickOpsCardMgr.style.display = "block";
      if (typeof window.loadOpsToggles === "function") window.loadOpsToggles();
    }

    // Thu gọn #sopChecklistCard thành accordion 1 thanh cho Quản lý
    const sopQuick = document.getElementById("sopQuickPreview");
    const sopBody = document.getElementById("sopBodyContent");
    const txtToggleSop = document.getElementById("txtToggleSop");
    const iconToggleSop = document.getElementById("iconToggleSop");
    if (sopQuick) sopQuick.style.display = "none";
    if (sopBody) sopBody.style.display = "none";
    if (txtToggleSop) txtToggleSop.textContent = "Mở xem checklist";
    if (iconToggleSop) iconToggleSop.textContent = "▾";

    // Quản lý: Kích hoạt tab mặc định từ Schema
    if (typeof window !== "undefined" && !window._initialTabSwitched) {
      window._initialTabSwitched = true;
      switchTabFn(navConfig.defaultTab);
    }
  } else {
    // Admin
    if (brandTitle) {
      brandTitle.textContent = sName || "WFM Vận Hành";
      brandTitle.title = brandTitle.textContent;
    }
    if (badge) {
      badge.textContent = "ADMIN";
      badge.title = "Quản Trị Viên (Admin)";
      badge.style.background = "var(--accent-coral-sub)";
      badge.style.color = "var(--accent-coral)";
    }
    if (btnEval) btnEval.style.display = "inline-flex";
    if (btnAdmin) btnAdmin.style.display = "inline-flex";
    if (btnLockouts) btnLockouts.style.display = "inline-flex";
    if (linkMonthly) linkMonthly.style.display = "inline-flex";
    if (linkDesktop) linkDesktop.style.display = "inline-flex";
    if (btnAdminSheet) btnAdminSheet.style.display = "flex";
    if (btnLockoutsSheet) btnLockoutsSheet.style.display = "flex";
    if (linkMonthlySheet) linkMonthlySheet.style.display = "flex";
    if (linkDesktopSheet) linkDesktopSheet.style.display = "flex";
    if (btnStoreConfigSheet) btnStoreConfigSheet.style.display = "flex";

    if (rosterWeeklyKpis) rosterWeeklyKpis.style.display = "grid";
    if (cardWeeklyAnomalies) cardWeeklyAnomalies.style.display = "block";
    if (cardWeeklyWorkload) cardWeeklyWorkload.style.display = "block";
    if (staffMyScheduleCard) staffMyScheduleCard.style.display = "none";

    const matrixCardAdmin = document.querySelector(".weekly-matrix-card");
    const dayDetailCardAdmin = document.querySelector(".roster-day-detail-card");
    if (matrixCardAdmin) matrixCardAdmin.style.display = "block";
    if (dayDetailCardAdmin) dayDetailCardAdmin.style.display = "block";

    const staffRosterBannerAdmin = document.getElementById("staffRosterBanner");
    const managerRosterToolbarAdmin = document.getElementById("managerRosterToolbar");
    if (staffRosterBannerAdmin) staffRosterBannerAdmin.style.display = "none";
    if (managerRosterToolbarAdmin) managerRosterToolbarAdmin.style.display = "flex";

    if (staffPortalContainer) staffPortalContainer.style.display = "none";
    if (adminPayslipContainer) adminPayslipContainer.style.display = "block";
    const mgrPayslipSegAdmin = document.getElementById("managerPayslipSegmentedControl");
    if (mgrPayslipSegAdmin) mgrPayslipSegAdmin.style.display = "none";
    const payrollSummaryAdmin = document.getElementById("payrollDisbursementSummary");
    const btnAdvanceAdmin = document.getElementById("btnOpenToolbarAdvance");
    const btnExportAdmin = document.getElementById("btnExportPayrollExcelMobile");
    if (payrollSummaryAdmin) payrollSummaryAdmin.style.display = "block";
    if (btnAdvanceAdmin) btnAdvanceAdmin.style.display = "inline-flex";
    if (btnExportAdmin) btnExportAdmin.style.display = "inline-flex";
    const managerAttendancePanel = document.getElementById("managerAttendancePanel");
    if (managerAttendancePanel) managerAttendancePanel.style.display = "block";
    const activeShiftCardAdmin = document.getElementById("activeShiftCard");
    if (activeShiftCardAdmin) activeShiftCardAdmin.style.display = "none";

    const quickOpsCardAdmin = document.getElementById("quickOpsTogglesCard");
    if (quickOpsCardAdmin) {
      quickOpsCardAdmin.style.display = "block";
      if (typeof window.loadOpsToggles === "function") window.loadOpsToggles();
    }

    // Admin: Mặc định vào tab Vận Hành (Ops)
    if (typeof window !== "undefined" && !window._initialTabSwitched) {
      window._initialTabSwitched = true;
      switchTabFn("ops");
    }
  }

  if (typeof window !== "undefined" && typeof window.updateNavPill === "function") {
    setTimeout(window.updateNavPill, 40);
  }
}

export function setupAuth(onLoginSuccess = null) {
  if (typeof document === "undefined") return;
  const btnLogin = document.getElementById("btnLoginSubmit");
  const btnLogout = document.getElementById("btnLogout");
  const userInput = document.getElementById("loginUser");
  const passInput = document.getElementById("loginPass");
  const btnTogglePwd = document.getElementById("btnTogglePassword");
  const errBanner = document.getElementById("authErrorBanner");

  const setAuthError = (msg) => {
    if (errBanner) {
      if (msg) {
        errBanner.textContent = msg;
        errBanner.classList.add("active");
      } else {
        errBanner.textContent = "";
        errBanner.classList.remove("active");
      }
    } else if (msg) {
      showToast(msg, "error");
    }
  };

  if (btnTogglePwd && passInput) {
    btnTogglePwd.addEventListener("click", () => {
      const isPwd = passInput.getAttribute("type") === "password";
      passInput.setAttribute("type", isPwd ? "text" : "password");
      btnTogglePwd.innerHTML = isPwd 
        ? getIconSvg("eyeOff", { size: 18 }) 
        : getIconSvg("eye", { size: 18 });
    });
  }

  if (userInput) {
    userInput.addEventListener("input", () => setAuthError(""));
  }
  if (passInput) {
    passInput.addEventListener("input", () => setAuthError(""));
  }

  if (btnLogin) {
    btnLogin.addEventListener("click", async () => {
      const u = userInput ? userInput.value.trim() : "";
      const p = passInput ? passInput.value.trim() : "";
      if (!u || !p) {
        setAuthError("Vui lòng nhập đầy đủ tài khoản và mật khẩu/mã PIN!");
        return;
      }

      setAuthError("");
      btnLogin.disabled = true;
      const originalText = btnLogin.textContent;
      btnLogin.textContent = "Đang xác thực...";

      try {
        const res = await fetch("/api/v1/cc/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: u, password: p })
        });
        if (res.ok) {
          const data = await res.json();
          localStorage.removeItem("vnaigc_logged_out");
          localStorage.setItem("vnaigc_jwt", data.access_token);
          localStorage.setItem("vnaigc_token", data.access_token);
          localStorage.setItem("vnaigc_role", data.role);
          localStorage.setItem("vnaigc_name", data.name);
          const uname = (data.username || u).toLowerCase().trim();
          localStorage.setItem("vnaigc_username", uname);
          localStorage.setItem("vnaigc_sheet_names", JSON.stringify(data.sheet_names || []));
          if (typeof window !== "undefined") {
            window.currentUser = uname;
            window.currentStaffName = data.name;
            window._initialTabSwitched = false;
          }
          hideAuthGate();
          applyRolePermissions(data.role, { full_name: data.name });
          if (typeof onLoginSuccess === "function") {
            onLoginSuccess();
          } else if (typeof window !== "undefined" && typeof window.loadData === "function") {
            window.loadData();
          }
        } else {
          const err = await res.json().catch(() => ({}));
          setAuthError(err.detail || "Sai tên đăng nhập hoặc mã PIN!");
        }
      } catch (e) {
        setAuthError("Lỗi kết nối máy chủ! Vui lòng thử lại.");
      } finally {
        btnLogin.disabled = false;
        btnLogin.textContent = originalText;
      }
    });

    const handleEnter = (e) => {
      if (e.key === "Enter") btnLogin.click();
    };
    if (userInput) userInput.addEventListener("keydown", handleEnter);
    if (passInput) passInput.addEventListener("keydown", handleEnter);
  }

  const handleLogout = () => {
    const moreSheet = document.getElementById("topbarMoreSheet");
    if (moreSheet) moreSheet.classList.remove("active");
    clearAuth();
    updateSheetScrollLock();
  };

  if (btnLogout) {
    btnLogout.addEventListener("click", handleLogout);
  }
  const btnLogoutSheet = document.getElementById("btnLogoutSheet");
  if (btnLogoutSheet) {
    btnLogoutSheet.addEventListener("click", handleLogout);
  }

  const btnAdminStaff = document.getElementById("btnAdminStaff");
  if (btnAdminStaff) {
    btnAdminStaff.addEventListener("click", () => {
      if (typeof window !== "undefined" && typeof window.openAdminStaffModal === "function") {
        window.openAdminStaffModal();
      }
    });
  }

  const btnAdminStaffSheet = document.getElementById("btnAdminStaffSheet");
  if (btnAdminStaffSheet) {
    btnAdminStaffSheet.addEventListener("click", () => {
      const moreSheet = document.getElementById("topbarMoreSheet");
      if (moreSheet) moreSheet.classList.remove("active");
      if (typeof window !== "undefined" && typeof window.openAdminStaffModal === "function") {
        window.openAdminStaffModal();
      }
    });
  }

  const btnAdminLockoutsSheet = document.getElementById("btnAdminLockoutsSheet");
  if (btnAdminLockoutsSheet) {
    btnAdminLockoutsSheet.addEventListener("click", () => {
      const moreSheet = document.getElementById("topbarMoreSheet");
      if (moreSheet) moreSheet.classList.remove("active");
      if (typeof window !== "undefined" && typeof window.openAdminLockoutsModalMobile === "function") {
        window.openAdminLockoutsModalMobile();
      }
    });
  }

  const btnCloseAdminStaff = document.getElementById("btnCloseAdminStaff");
  if (btnCloseAdminStaff) {
    btnCloseAdminStaff.addEventListener("click", () => {
      const sheet = document.getElementById("adminStaffSheet");
      if (sheet) sheet.classList.remove("active");
    });
  }
  const adminStaffSearchInput = document.getElementById("adminStaffSearchInput");
  if (adminStaffSearchInput) {
    adminStaffSearchInput.addEventListener("input", (e) => {
      if (typeof window !== "undefined" && typeof window.renderAdminStaffList === "function") {
        window.renderAdminStaffList(e.target.value);
      }
    });
  }
}

export function setupManagerPayslipSegmentedControl() {
  const btnSelf = document.getElementById("btnMgrPayslipSelf");
  const btnStaff = document.getElementById("btnMgrPayslipStaff");
  const staffPortalContainer = document.getElementById("staffPortalContainer");
  const adminPayslipContainer = document.getElementById("adminPayslipContainer");
  const payrollSummary = document.getElementById("payrollDisbursementSummary");
  const btnAdvance = document.getElementById("btnOpenToolbarAdvance");
  const btnExport = document.getElementById("btnExportPayrollExcelMobile");

  if (!btnSelf || !btnStaff) return;

  const switchToSelf = () => {
    btnSelf.style.background = "var(--bg-card)";
    btnSelf.style.color = "var(--text-primary)";
    btnSelf.style.boxShadow = "0 1px 3px rgba(0,0,0,0.08)";
    btnSelf.style.fontWeight = "700";

    btnStaff.style.background = "transparent";
    btnStaff.style.color = "var(--text-secondary)";
    btnStaff.style.boxShadow = "none";
    btnStaff.style.fontWeight = "600";

    if (staffPortalContainer) staffPortalContainer.style.display = "flex";
    if (adminPayslipContainer) adminPayslipContainer.style.display = "none";
    if (typeof window.renderStaffPortal === "function") window.renderStaffPortal();
  };

  const switchToStaff = () => {
    btnStaff.style.background = "var(--bg-card)";
    btnStaff.style.color = "var(--text-primary)";
    btnStaff.style.boxShadow = "0 1px 3px rgba(0,0,0,0.08)";
    btnStaff.style.fontWeight = "700";

    btnSelf.style.background = "transparent";
    btnSelf.style.color = "var(--text-secondary)";
    btnSelf.style.boxShadow = "none";
    btnSelf.style.fontWeight = "600";

    if (staffPortalContainer) staffPortalContainer.style.display = "none";
    if (adminPayslipContainer) adminPayslipContainer.style.display = "block";

    // Quản lý kiểm công: READ-ONLY ẩn 3 thẻ giải ngân quỹ quán, ẩn tạm ứng, ẩn xuất excel
    if (payrollSummary) payrollSummary.style.display = "none";
    if (btnAdvance) btnAdvance.style.display = "none";
    if (btnExport) btnExport.style.display = "none";

    if (typeof window.renderTabPayslip === "function") window.renderTabPayslip();
  };

  btnSelf.onclick = switchToSelf;
  btnStaff.onclick = switchToStaff;

  // Mặc định chọn chế độ Xem Lương Của Tôi
  switchToSelf();
}

