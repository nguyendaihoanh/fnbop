// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// AUTH & ADMIN STAFF ACCOUNTS API
// ==========================================================================

import { apiFetch, apiJson } from "./apiClient.js";

export async function loginApi(username, password) {
  const res = await fetch("/api/v1/cc/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  return res;
}

export async function fetchStaffAccountsApi() {
  return await apiJson("/api/v1/cc/admin/staff-accounts");
}

export async function toggleLockApi(month, status, message = "") {
  return await apiFetch("/api/v1/cc/admin/toggle-lock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ month, status, message })
  });
}

export async function toggleStaffStatusApi(uname, newStatus) {
  return await apiFetch("/api/v1/cc/admin/toggle-staff-status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: uname, status: newStatus })
  });
}

export async function updateStaffPinApi(uname, newPin) {
  return await apiFetch("/api/v1/cc/admin/update-pin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: uname, pin: newPin })
  });
}

export async function createStaffAccountApi(payload) {
  return await apiFetch("/api/v1/cc/admin/create-staff-account", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchStoreConfigApi() {
  return await apiJson("/api/v1/cc/store/config");
}

export async function updateStoreConfigApi(configData) {
  return await apiFetch("/api/v1/cc/store/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(configData)
  });
}

export async function resetStoreConfigApi() {
  return await apiFetch("/api/v1/cc/store/config/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" }
  });
}

export async function testTelegramApi(payload = {}) {
  return await apiFetch("/api/v1/cc/store/test-telegram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchZaloQrApi() {
  return await apiJson("/api/v1/cc/store/zalo-qr");
}

export async function fetchZaloStatusApi() {
  return await apiJson("/api/v1/cc/store/zalo-status");
}

export async function fetchUpdateStatusApi() {
  return await apiJson("/api/v1/cc/system/update-status");
}

export async function checkUpdateApi() {
  return await apiFetch("/api/v1/cc/system/check-update", {
    method: "POST"
  });
}

export async function applyUpdateApi() {
  return await apiFetch("/api/v1/cc/system/apply-update", {
    method: "POST"
  });
}

export async function toggleAutoUpdateApi(enabled) {
  return await apiFetch("/api/v1/cc/system/auto-update-toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: !!enabled })
  });
}



