// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// WFM IN-APP REAL-TIME REMINDER & URGENT ALERT MODULE
// Hiển thị Banner/Modal cảnh báo đập vào mắt nhân sự khi quản lý bấm nhắc
// Chống spam: Chỉ hiển thị 1 lần, đóng xong không lặp lại
// ==========================================================================

import { triggerHaptic } from "../utils/haptics.js";
import { escapeHtml } from "../utils/formatters.js";
import { switchTab } from "./navModule.js";

let reminderPollInterval = null;
let activeReminderId = null;
let isCurrentlyShowing = false;

export function initInAppReminderMonitor() {
  if (reminderPollInterval) {
    clearInterval(reminderPollInterval);
  }

  // Check immediately
  checkMyReminders();

  // Poll gently every 8 seconds (anti-lag)
  reminderPollInterval = setInterval(checkMyReminders, 8000);

  // Check on tab re-focus / screen unlock
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && !isCurrentlyShowing) {
        checkMyReminders();
      }
    });
  }
}

export async function checkMyReminders() {
  // If modal is currently showing, do not poll or interrupt
  if (isCurrentlyShowing) return;

  const token = localStorage.getItem("vnaigc_jwt");
  if (!token) return;

  try {
    const res = await fetch("/api/v1/cc/notifications/push/my-reminders", {
      headers: {
        "Authorization": "Bearer " + token
      }
    });
    if (!res.ok) return;

    const data = await res.json();
    if (data.success && Array.isArray(data.reminders) && data.reminders.length > 0) {
      const latest = data.reminders[0];

      // Anti-spam persistent check: ignore if user already dismissed this reminder ID
      let dismissedIds = [];
      try {
        dismissedIds = JSON.parse(localStorage.getItem("wfm_dismissed_reminders") || localStorage.getItem("fnbop_dismissed_reminders") || "[]");
      } catch (e) {
        dismissedIds = [];
      }
      if (dismissedIds.map(String).includes(String(latest.id))) {
        return;
      }

      if (activeReminderId !== latest.id) {
        showInAppReminderModal(latest);
      }
    }
  } catch (err) {
    // Silent fail for polling
  }
}

export function showInAppReminderModal(reminder) {
  activeReminderId = reminder.id;
  isCurrentlyShowing = true;

  // Sound & Physical Haptic
  triggerHaptic("urgent");

  // Optional OS notification if permission is already granted
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      new Notification(reminder.title || "WFM", {
        body: reminder.message || "Bạn có thông báo mới từ Quản lý",
        icon: "/favicon.ico"
      });
    }
  } catch (e) {}

  let modalEl = document.getElementById("inAppUrgentReminderModal");
  if (!modalEl) {
    modalEl = document.createElement("div");
    modalEl.id = "inAppUrgentReminderModal";
    modalEl.className = "in-app-reminder-backdrop";
    document.body.appendChild(modalEl);
  }

  const rType = (reminder.remind_type || "GENERAL").toUpperCase();
  let badgeText = "THÔNG BÁO TỪ QUẢN LÝ";
  let primaryBtnText = "BẤM ĐIỂM DANH VÀO CA NGAY";
  let targetAction = "attendance";

  if (rType === "CHECKIN") {
    badgeText = "🚨 NHẮC VÀO CA KHẨN CẤP";
    primaryBtnText = "BẤM ĐIỂM DANH VÀO CA NGAY";
    targetAction = "attendance";
  } else if (rType === "CHECKOUT") {
    badgeText = "⏰ NHẮC KẾT THÚC CA";
    primaryBtnText = "BẤM KẾT THÚC CA NGAY";
    targetAction = "attendance";
  } else if (rType === "ROSTER") {
    badgeText = "📅 NHẮC ĐĂNG KÝ CA TUẦN";
    primaryBtnText = "MỞ ĐĂNG KÝ LỊCH NGAY";
    targetAction = "roster";
  }

  modalEl.innerHTML = `
    <div class="in-app-reminder-card">
      <div class="reminder-card-glow"></div>
      
      <div class="reminder-header">
        <div class="reminder-icon-box">
          <svg class="reminder-bell-icon" viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
          </svg>
        </div>
        <div class="reminder-meta">
          <span class="reminder-badge">${escapeHtml(badgeText)}</span>
          <span class="reminder-time">Vừa xong</span>
        </div>
      </div>

      <div class="reminder-body">
        <h3 class="reminder-title">${escapeHtml(reminder.title || "Thông báo từ Quản lý")}</h3>
        <p class="reminder-msg">${escapeHtml(reminder.message || "Bạn có ca làm việc hôm nay nhưng chưa Check-in.")}</p>
      </div>

      <div class="reminder-actions">
        <button type="button" id="btnReminderPrimaryAction" class="reminder-btn-primary">
          <span>${escapeHtml(primaryBtnText)}</span>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
        </button>
        <button type="button" id="btnReminderDismiss" class="reminder-btn-dismiss">
          Đã hiểu / Đóng
        </button>
      </div>
    </div>
  `;

  modalEl.classList.add("active");

  const handleDismiss = async () => {
    triggerHaptic("tick");
    // Remember dismissed reminder ID in localStorage permanently
    let dismissedIds = [];
    try {
      dismissedIds = JSON.parse(localStorage.getItem("wfm_dismissed_reminders") || localStorage.getItem("fnbop_dismissed_reminders") || "[]");
    } catch (e) {
      dismissedIds = [];
    }
    const idStr = String(reminder.id);
    if (!dismissedIds.map(String).includes(idStr)) {
      dismissedIds.push(idStr);
      if (dismissedIds.length > 50) dismissedIds = dismissedIds.slice(-50);
      try {
        localStorage.setItem("wfm_dismissed_reminders", JSON.stringify(dismissedIds));
        localStorage.setItem("fnbop_dismissed_reminders", JSON.stringify(dismissedIds));
      } catch (e) {}
    }

    closeReminderModal();
    // Acknowledge specific and all unread reminders on server in background
    if (reminder.id) {
      await ackReminder(reminder.id);
    }
    await ackAllReminders();
  };

  // Event handlers
  const btnPrimary = modalEl.querySelector("#btnReminderPrimaryAction");
  if (btnPrimary) {
    btnPrimary.onclick = async () => {
      await handleDismiss();

      if (targetAction === "attendance") {
        if (typeof switchTab === "function") switchTab("attendance");
        setTimeout(() => {
          const checkinCard = document.getElementById("attendanceCheckinCard") || document.getElementById("btnCheckinPrimary");
          if (checkinCard) {
            checkinCard.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        }, 150);
      } else if (targetAction === "roster") {
        if (typeof switchTab === "function") switchTab("roster");
      }
    };
  }

  const btnDismiss = modalEl.querySelector("#btnReminderDismiss");
  if (btnDismiss) {
    btnDismiss.onclick = async () => {
      await handleDismiss();
    };
  }
}

export function closeReminderModal() {
  const modalEl = document.getElementById("inAppUrgentReminderModal");
  if (modalEl) {
    modalEl.classList.remove("active");
  }
  isCurrentlyShowing = false;
  activeReminderId = null;
}

export async function ackAllReminders() {
  const token = localStorage.getItem("vnaigc_jwt");
  if (!token) return;

  try {
    await fetch("/api/v1/cc/notifications/push/ack-all-reminders", {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + token
      }
    });
  } catch (err) {
    console.warn("Failed to ack all reminders:", err);
  }
}

export async function ackReminder(reminderId) {
  const token = localStorage.getItem("vnaigc_jwt");
  if (!token || !reminderId) return;

  try {
    await fetch(`/api/v1/cc/notifications/push/ack-reminder/${reminderId}`, {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + token
      }
    });
  } catch (err) {
    console.warn("Failed to ack reminder:", err);
  }
}

// Expose to window for testing / manual triggering
if (typeof window !== "undefined") {
  window.initInAppReminderMonitor = initInAppReminderMonitor;
  window.checkMyReminders = checkMyReminders;
  window.showInAppReminderModal = showInAppReminderModal;
  window.closeReminderModal = closeReminderModal;
  window.ackAllReminders = ackAllReminders;
}
