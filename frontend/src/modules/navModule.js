// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// NAVIGATION, THEME & CORE VIEW COORDINATION
// ==========================================================================

import { state, processData } from "../store/state.js";
import { showLoginSheet, applyRolePermissions, updateSheetScrollLock } from "../store/authStore.js";
import { renderTabOps } from "./opsModule.js";
import { renderTabRoster, fetchRosterWeekData } from "./rosterModule.js";
import { renderTabPayslip, renderStaffPortal } from "./payslipModule.js";
import { loadAttendanceTab } from "./attendanceModule.js";
import { getIconSvg } from "../utils/icons.js";
import { getRoleNavConfig } from "../config/navSchema.js";

function updateThemeSheetUI(theme) {
  const lbl = document.getElementById("themeCurrentLabel");
  if (lbl) {
    lbl.textContent = theme === "dark" ? "Tối" : "Sáng";
  }
  const iconSpan = document.getElementById("themeSheetIcon");
  if (iconSpan) {
    iconSpan.innerHTML = theme === "dark"
      ? getIconSvg("moon", { size: 18 })
      : getIconSvg("sun", { size: 18 });
  }
}

export function initTheme() {
  if (typeof document === "undefined") return;
  const saved = localStorage.getItem("wfm_theme") || localStorage.getItem("fnbops_theme") || "light";
  document.documentElement.setAttribute("data-theme", saved);
  updateThemeSheetUI(saved);

  const toggleTheme = () => {
    const curr = document.documentElement.getAttribute("data-theme") || "light";
    const next = curr === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("wfm_theme", next);
    localStorage.setItem("fnbops_theme", next);
    updateThemeSheetUI(next);
  };

  const btn = document.getElementById("btnTheme");
  if (btn) {
    btn.addEventListener("click", toggleTheme);
  }
  const btnSheet = document.getElementById("btnThemeSheet");
  if (btnSheet) {
    btnSheet.addEventListener("click", toggleTheme);
  }
}

export function updateViewModeSheetUI(mode) {
  const lbl = document.getElementById("fluidCurrentLabel");
  if (lbl) {
    lbl.textContent = mode === "fluid" ? "Mở rộng (1100px)" : "Khung 500px";
  }
}

export function toggleResponsiveViewMode(forceMode = null) {
  if (typeof document === "undefined") return "compact";
  const currentIsFluid = document.body.classList.contains("view-desktop-fluid");
  const nextMode = forceMode !== null ? forceMode : (currentIsFluid ? "compact" : "fluid");

  if (nextMode === "fluid") {
    document.body.classList.add("view-desktop-fluid");
    document.body.classList.remove("view-desktop-compact");
  } else {
    document.body.classList.remove("view-desktop-fluid");
    document.body.classList.add("view-desktop-compact");
  }

  if (typeof localStorage !== "undefined") {
    localStorage.setItem("wfm_view_mode", nextMode);
    localStorage.setItem("fnbops_view_mode", nextMode);
  }
  updateViewModeSheetUI(nextMode);
  return nextMode;
}

export function initResponsiveViewMode() {
  if (typeof document === "undefined") return;

  let saved = (typeof localStorage !== "undefined") ? (localStorage.getItem("fnbops_view_mode") || localStorage.getItem("wfm_view_mode")) : null;
  if (!saved) {
    const isLargeScreen = (typeof window !== "undefined" && typeof window.innerWidth === "number" && window.innerWidth >= 1024);
    saved = isLargeScreen ? "fluid" : "compact";
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("wfm_view_mode", saved);
      localStorage.setItem("fnbops_view_mode", saved);
    }
  }

  if (saved === "fluid") {
    document.body.classList.add("view-desktop-fluid");
    document.body.classList.remove("view-desktop-compact");
  } else {
    document.body.classList.remove("view-desktop-fluid");
    document.body.classList.add("view-desktop-compact");
  }
  updateViewModeSheetUI(saved);

  const btnSheet = document.getElementById("btnToggleFluidSheet");
  if (btnSheet) {
    btnSheet.addEventListener("click", () => {
      toggleResponsiveViewMode();
    });
  }
}

export function getAvailableTabs() {
  const role = state.currentRole || (typeof localStorage !== "undefined" ? localStorage.getItem("vnaigc_role") : null) || "STAFF";
  return getRoleNavConfig(role).tabs;
}

export function updateNavPill() {
  if (typeof document === "undefined") return;
  const nav = document.getElementById("bottomNav");
  const pill = document.getElementById("navSlidingPill");
  if (!nav || !pill) return;
  const activeBtn = nav.querySelector(".nav-tab-btn.active");
  if (!activeBtn) {
    pill.style.opacity = "0";
    return;
  }
  // Nút Hero Action Capsule Bar độc lập (Staff View) -> Ẩn sliding pill để giữ trọn vẹn hào quang glow
  if (activeBtn.classList.contains("nav-hero-action")) {
    pill.style.opacity = "0";
    return;
  }

  // Dynamic Sub-pixel Auto-Centering Engine (Float Point Rect Alignment):
  // Triệt tiêu hoàn toàn sai số làm tròn số nguyên (Integer Rounding Error) của offsetLeft/offsetWidth.
  // Đồng bộ tâm đối xứng giữa Pill và Tab Button ở độ chính xác tuyệt đối (< 0.1px) trên mọi màn hình.
  const navRect = nav.getBoundingClientRect();
  const btnRect = activeBtn.getBoundingClientRect();
  const navBorderLeft = nav.clientLeft || 0;
  const inset = 4;
  const targetWidth = Math.max(0, Math.round((btnRect.width - (inset * 2)) * 100) / 100);
  const targetX = Math.round(((btnRect.left - navRect.left - navBorderLeft) + inset) * 100) / 100;

  pill.style.width = `${targetWidth}px`;
  pill.style.transform = `translateX(${targetX}px)`;
  pill.style.opacity = "1";
}
export function updateCradlePath() {
  if (typeof document === "undefined") return;
  const nav = document.getElementById("bottomNav");
  const path = document.getElementById("navCradlePath");
  if (!nav || !path) return;
  if (!nav.classList.contains("nav-cradle-mode")) return;
  const W = nav.offsetWidth || 361;
  const H = nav.offsetHeight || 66;
  const mid = W / 2;
  const r = 33;
  const dipW = 56;
  const d = [
    `M 0 ${r}`,
    `C 0 ${r * 0.45}, ${r * 0.45} 0, ${r} 0`,
    `L ${mid - dipW} 0`,
    `C ${mid - dipW + 12} 0, ${mid - dipW + 16} 8, ${mid - dipW + 21} 18`,
    `C ${mid - dipW + 27} 32, ${mid - 12.5} 37, ${mid} 37`,
    `C ${mid + 12.5} 37, ${mid + dipW - 27} 32, ${mid + dipW - 21} 18`,
    `C ${mid + dipW - 16} 8, ${mid + dipW - 12} 0, ${mid + dipW} 0`,
    `L ${W - r} 0`,
    `C ${W - r * 0.45} 0, ${W} ${r * 0.45}, ${W} ${r}`,
    `L ${W} ${H - r}`,
    `C ${W} ${H - r * 0.45}, ${W - r * 0.45} ${H}, ${W - r} ${H}`,
    `L ${r} ${H}`,
    `C ${r * 0.45} ${H}, 0 ${H - r * 0.45}, 0 ${H - r}`,
    "Z"
  ].join(" ");
  path.setAttribute("d", d);
  const svg = document.getElementById("navCradleSvg");
  if (svg) svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
}

export function updateScrollBottomPadding() {
  if (typeof document === "undefined") return;
  const nav = document.getElementById("bottomNav");
  if (!nav) return;
  const isCradle = nav.classList.contains("nav-cradle-mode");
  const bottomPadding = isCradle ? "44px" : "36px";
  if (document.documentElement && document.documentElement.style && typeof document.documentElement.style.setProperty === "function") {
    document.documentElement.style.setProperty("--tab-scroll-bottom-padding", bottomPadding);
  }
}

if (typeof window !== "undefined") {
  window.updateNavPill = updateNavPill;
  window.updateCradlePath = updateCradlePath;
  window.updateScrollBottomPadding = updateScrollBottomPadding;
}

export function setupNav() {
  if (typeof document === "undefined") return;
  const nav = document.getElementById("bottomNav");
  if (!nav) return;
  if (!nav.dataset) nav.dataset = {};
  if (nav.dataset.bound) return;
  nav.dataset.bound = "true";

  document.querySelectorAll(".nav-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const tabKey = btn.getAttribute("data-tab");
      switchTab(tabKey);
    });
  });

  // Reactive Observers: Tự động cập nhật toạ độ khi kích thước hoặc DOM thay đổi
  if (typeof window !== "undefined") {
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        updateNavPill();
        updateCradlePath();
        updateScrollBottomPadding();
      });
      ro.observe(nav);
    }
    if (window.MutationObserver) {
      const mo = new MutationObserver(() => {
        updateNavPill();
        updateCradlePath();
        updateScrollBottomPadding();
      });
      mo.observe(nav, { attributes: true, subtree: true, attributeFilter: ["class"] });
    }
    window.addEventListener("resize", () => {
      updateNavPill();
      updateCradlePath();
      updateScrollBottomPadding();
    });
    window.addEventListener("orientationchange", () => {
      setTimeout(() => {
        updateNavPill();
        updateCradlePath();
        updateScrollBottomPadding();
      }, 120);
    });
  }

  setTimeout(() => {
    updateNavPill();
    updateCradlePath();
    updateScrollBottomPadding();
  }, 60);

  setupAutoRefreshEngine();
}

export function refreshCurrentActiveTab() {
  const tabKey = state.currentTabKey || "attendance";
  const role = (state.currentRole || localStorage.getItem("vnaigc_role") || "STAFF").toUpperCase();

  if (tabKey === "attendance") {
    if (typeof loadAttendanceTab === "function") loadAttendanceTab();
  } else if (tabKey === "roster") {
    if (typeof fetchRosterWeekData === "function") {
      fetchRosterWeekData("current", true);
      fetchRosterWeekData("next", true);
    }
    if (typeof renderTabRoster === "function") renderTabRoster();
  } else if (tabKey === "payslip") {
    if (role === "STAFF") {
      if (typeof renderStaffPortal === "function") renderStaffPortal();
    } else {
      if (typeof renderTabPayslip === "function") renderTabPayslip();
    }
  } else if (tabKey === "ops") {
    if (typeof renderTabOps === "function") renderTabOps();
  }
}

export function setupAutoRefreshEngine() {
  if (typeof document === "undefined") return;
  if (window._autoRefreshEngineInitialized) return;
  window._autoRefreshEngineInitialized = true;

  // 1. Tự động làm mới khi người dùng mở lại tab hoặc quay lại app điện thoại
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      refreshCurrentActiveTab();
    }
  });

  if (typeof window !== "undefined") {
    window.addEventListener("focus", () => {
      refreshCurrentActiveTab();
    });
  }

  // 2. Tự động kiểm tra làm mới ngầm chu kỳ 25 giây khi màn hình đang bật
  setInterval(() => {
    if (typeof document !== "undefined" && document.visibilityState === "visible") {
      const tabKey = state.currentTabKey || "attendance";
      if (tabKey === "roster" || tabKey === "attendance") {
        refreshCurrentActiveTab();
      }
    }
  }, 25000);
}

export function switchTab(tabKey) {
  if (typeof document === "undefined") return;
  const role = (state.currentRole || localStorage.getItem("vnaigc_role") || "STAFF").toUpperCase();
  if (role === "STAFF" && tabKey === "ops") {
    tabKey = "attendance";
  }

  const avail = getAvailableTabs();
  if (!avail.includes(tabKey)) {
    tabKey = avail[0] || "attendance";
  }
  state.currentTabKey = tabKey;

  // Native Tactile Haptics
  if (typeof window !== "undefined" && window.navigator && typeof window.navigator.vibrate === "function") {
    try { window.navigator.vibrate(8); } catch (_) {}
  }

  document.querySelectorAll(".nav-tab-btn").forEach(b => {
    b.classList.toggle("active", b.getAttribute("data-tab") === tabKey);
  });

  const targetId = `tab${tabKey.charAt(0).toUpperCase() + tabKey.slice(1)}`;
  document.querySelectorAll(".tab-view").forEach(v => {
    const isActive = (v.id === targetId);
    v.classList.toggle("active", isActive);
    v.style.display = isActive ? "flex" : "none";
    v.style.opacity = isActive ? "1" : "0";
    v.style.visibility = isActive ? "visible" : "hidden";
    v.style.pointerEvents = isActive ? "auto" : "none";
  });

  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(updateNavPill);
  } else if (typeof updateNavPill === "function") {
    updateNavPill();
  }

  if (tabKey === "attendance") {
    loadAttendanceTab();
  } else if (tabKey === "roster") {
    // Tự động kích hoạt làm tươi mới dữ liệu ca tuần ngay khi vào tab
    fetchRosterWeekData("current", true);
    fetchRosterWeekData("next", true);
    renderTabRoster();
  } else if (tabKey === "ops") {
    renderTabOps();
  } else if (tabKey === "payslip") {
    if (role === "STAFF") {
      renderStaffPortal();
    } else {
      renderTabPayslip();
    }
  }
}

export function setupSwipe() {
  if (typeof document === "undefined") return;
  let touchStartX = 0;
  let touchStartY = 0;
  let touchEndX = 0;
  let touchEndY = 0;
  const container = document.getElementById("viewportContainer");
  if (!container) return;

  container.addEventListener("touchstart", (e) => {
    touchStartX = e.changedTouches[0].screenX;
    touchStartY = e.changedTouches[0].screenY;
  }, { passive: true });

  container.addEventListener("touchend", (e) => {
    touchEndX = e.changedTouches[0].screenX;
    touchEndY = e.changedTouches[0].screenY;
    handleSwipe();
  }, { passive: true });

  function handleSwipe() {
    const diffX = touchEndX - touchStartX;
    const diffY = touchEndY - touchStartY;

    if (Math.abs(diffX) > Math.abs(diffY) * 1.5 && Math.abs(diffX) > 50) {
      const avail = getAvailableTabs();
      const currIdx = avail.indexOf(state.currentTabKey);
      if (currIdx === -1) return;

      if (diffX < 0 && currIdx < avail.length - 1) {
        switchTab(avail[currIdx + 1]);
      } else if (diffX > 0 && currIdx > 0) {
        switchTab(avail[currIdx - 1]);
      }
    }
  }
}

export async function loadData() {
  const token = localStorage.getItem("vnaigc_jwt");
  if (!token) {
    showLoginSheet();
    return;
  }

  try {
    const res = await fetch("/api/v1/cc/data?t=" + Date.now(), {
      headers: {
        "Authorization": `Bearer ${token}`
      }
    });

    if (res.status === 401) {
      localStorage.removeItem("vnaigc_jwt");
      localStorage.removeItem("vnaigc_token");
      showLoginSheet();
      return;
    }

    if (!res.ok) throw new Error("API failed with status " + res.status);

    state.rawData = await res.json();
    processData();
    setupMonthFilter();
    updateAllViews();
  } catch (err) {
    console.error("Data error:", err);
    showLoginSheet();
  }
}

export function updateMonthFilterLabel() {
  const lbl = document.getElementById("monthFilterLabel");
  if (!lbl) return;
  if (state.currentMonth === "all") {
    lbl.textContent = "Cả năm";
  } else if (state.currentMonth) {
    lbl.textContent = `T.${state.currentMonth}`;
  }
}

export function openMonthPickerSheet() {
  if (typeof document === "undefined") return;
  const sheet = document.getElementById("monthPickerSheet");
  if (!sheet) return;
  renderMonthPickerList();
  sheet.classList.add("active");
  if (typeof updateSheetScrollLock === "function") updateSheetScrollLock();
}

export function closeMonthPickerSheet() {
  if (typeof document === "undefined") return;
  const sheet = document.getElementById("monthPickerSheet");
  if (!sheet) return;
  sheet.classList.remove("active");
  if (typeof updateSheetScrollLock === "function") updateSheetScrollLock();
}

export function selectMonth(monthValue) {
  state.currentMonth = String(monthValue);
  state.currentWeekPage = 0;
  state.selectedDateStr = "";

  const sel = document.getElementById("monthFilter");
  if (sel) sel.value = String(monthValue);

  updateMonthFilterLabel();
  closeMonthPickerSheet();
  updateAllViews();
}

export function renderMonthPickerList() {
  const container = document.getElementById("monthPickerOptions");
  if (!container) return;
  container.innerHTML = "";

  const availableSet = new Set((state.monthsAvailable || []).map(m => Number(m)));

  // Lưới 12 tháng gọn gàng (4 cột x 3 hàng)
  for (let m = 1; m <= 12; m++) {
    const hasData = availableSet.has(m);
    const isAct = String(m) === String(state.currentMonth);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `month-picker-pill ${isAct ? "active" : ""} ${hasData ? "has-data" : "no-data"}`;
    btn.title = hasData ? `Tháng ${m} (Có dữ liệu)` : `Tháng ${m}`;
    btn.innerHTML = `
      <span class="pill-month-title">Thg ${m}</span>
      ${isAct ? '<span class="pill-badge-active">✓</span>' : (hasData ? '<span class="pill-dot"></span>' : '<span class="pill-dot-empty"></span>')}
    `;
    btn.onclick = () => selectMonth(m);
    container.appendChild(btn);
  }

  // Nút chọn Toàn Bộ / Cả Năm full-width
  const isAll = state.currentMonth === "all";
  const btnAll = document.createElement("button");
  btnAll.type = "button";
  btnAll.className = `month-picker-all-btn ${isAll ? "active" : ""}`;
  btnAll.innerHTML = `
    <span>Toàn Bộ / Cả Năm</span>
    ${isAll ? '<span class="pill-badge-active" style="display:inline-block; margin-left:6px;">✓</span>' : ''}
  `;
  btnAll.onclick = () => selectMonth("all");
  container.appendChild(btnAll);
}

export function setupMonthFilter() {
  if (typeof document === "undefined") return;
  const sel = document.getElementById("monthFilter");
  if (sel) {
    sel.innerHTML = "";
    (state.monthsAvailable || []).forEach(m => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = `Tháng ${m}`;
      if (String(m) === String(state.currentMonth)) opt.selected = true;
      sel.appendChild(opt);
    });
    const optAll = document.createElement("option");
    optAll.value = "all";
    optAll.textContent = "Cả năm";
    if (state.currentMonth === "all") optAll.selected = true;
    sel.appendChild(optAll);

    sel.addEventListener("change", (e) => {
      selectMonth(e.target.value);
    });
  }

  updateMonthFilterLabel();

  const triggerBtn = document.getElementById("monthFilterBtn");
  if (triggerBtn && !triggerBtn.dataset.bound) {
    triggerBtn.dataset.bound = "true";
    triggerBtn.addEventListener("click", (e) => {
      e.preventDefault();
      openMonthPickerSheet();
    });
  }

  const sheet = document.getElementById("monthPickerSheet");
  if (sheet && !sheet.dataset.bound) {
    sheet.dataset.bound = "true";
    sheet.addEventListener("click", (e) => {
      if (e.target === sheet) {
        closeMonthPickerSheet();
      }
    });
  }
}

export function updateAllViews() {
  if (typeof window !== "undefined") {
    window.currentUser = localStorage.getItem("vnaigc_username") || (typeof currentUser !== "undefined" ? currentUser : "");
    window.currentStaffName = localStorage.getItem("vnaigc_name") || "";
  }
  const role = localStorage.getItem("vnaigc_role") || (state.rawData._meta && state.rawData._meta.role) || "STAFF";
  state.currentRole = role;
  const meta = state.rawData._meta || {};

  applyRolePermissions(role, meta);

  if (role === "STAFF") {
    renderStaffPortal();
    renderTabRoster();
  } else {
    renderTabOps();
    renderTabRoster();
    renderTabPayslip();
  }
}

if (typeof window !== "undefined") {
  window.refreshCurrentActiveTab = refreshCurrentActiveTab;
  window.setupAutoRefreshEngine = setupAutoRefreshEngine;
}

