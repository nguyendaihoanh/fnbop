// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// ATTENDANCE & SOP API CLIENT
// ==========================================================================

import { apiFetch, apiJson } from "./apiClient.js";

export async function fetchAttendanceStatusApi(username, devMode = false) {
  return await apiFetch(`/api/v1/cc/attendance/status?username=${encodeURIComponent(username)}&dev_mode=${devMode}`);
}

export async function checkInAttendanceApi(payload) {
  return await apiFetch("/api/v1/cc/attendance/checkin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function checkOutAttendanceApi(payload) {
  return await apiFetch("/api/v1/cc/attendance/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchSOPApi(roleKey) {
  return await apiFetch(`/api/v1/cc/attendance/sop?role=${encodeURIComponent(roleKey)}`);
}

export async function fetchPendingManagerCheckoutsApi() {
  return await apiFetch("/api/v1/cc/attendance/manager/pending");
}

export async function managerDeleteShiftApi(payload) {
  return await apiFetch("/api/v1/cc/attendance/manager/delete-shift", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function managerReopenShiftApi(payload) {
  return await apiFetch("/api/v1/cc/attendance/manager/reopen-shift", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function managerManualCloseShiftApi(payload) {
  return await apiFetch("/api/v1/cc/attendance/manager/manual-close", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function autoCloseCheckApi() {
  return await apiFetch("/api/v1/cc/attendance/manager/auto-close-check", { method: "POST" });
}

export async function resetDevLogsApi() {
  return await apiFetch("/api/v1/cc/attendance/dev/reset-logs", { method: "POST" });
}
