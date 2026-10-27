// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// ROSTER SCHEDULING & SHIFT REGISTRATION API CLIENT
// ==========================================================================

import { apiFetch, apiJson } from "./apiClient.js";

export async function fetchRosterWeekApi(weekId = "current") {
  return await apiFetch(`/api/v1/cc/roster/week?week_id=${encodeURIComponent(weekId)}`);
}

export async function registerShiftsApi(payload) {
  return await apiFetch("/api/v1/cc/roster/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function autoFillRosterApi(weekId) {
  return await apiFetch("/api/v1/cc/roster/auto-fill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ week_id: weekId })
  });
}

export async function publishRosterApi(weekId) {
  return await apiFetch("/api/v1/cc/roster/publish", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ week_id: weekId })
  });
}

export async function peerSwapApi(payload) {
  return await apiFetch("/api/v1/cc/roster/peer-swap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function updateShiftSlotApi(payload) {
  return await apiFetch("/api/v1/cc/roster/update-shift", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}
