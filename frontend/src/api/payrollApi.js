// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// PAYROLL, OT APPROVAL & EVALUATION API CLIENT
// ==========================================================================

import { apiFetch, apiJson, getJwtToken } from "./apiClient.js";

export async function fetchPayrollDataApi() {
  return await apiFetch("/api/v1/cc/data?t=" + Date.now());
}

export async function confirmShiftOTApi(shiftKey, action, approvedMins, note = "") {
  return await apiFetch("/api/v1/cc/shifts/confirm-ot", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      shift_key: shiftKey,
      action: action,
      approved_mins: approvedMins,
      note: note
    })
  });
}

export async function fetchServerPayrollSummaryApi(month, staffName) {
  let url = `/api/v1/cc/payroll/summary?month=${encodeURIComponent(month)}`;
  if (staffName) url += `&staff_name=${encodeURIComponent(staffName)}`;
  return await apiFetch(url);
}

export async function sendPayslipTelegramApi(payload) {
  return await fetch("/api/send-payslip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function submitStaffEvaluationApi(backendPayload) {
  return await apiFetch("/api/v1/cc/admin/staff-evaluation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(backendPayload)
  });
}

export async function pushEvaluationWebhookApi(payload) {
  return await apiFetch("/api/v1/cc/admin/eval-webhook", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).catch(() => {});
}

export async function confirmStaffPayrollApi(payload) {
  return await apiFetch("/api/v1/cc/staff/confirm-payroll", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchStaffLedgersApi(month = "9", staffName = "") {
  let url = `/api/v1/cc/payroll/ledger?month=${encodeURIComponent(month)}`;
  if (staffName) url += `&staff_name=${encodeURIComponent(staffName)}`;
  return await apiFetch(url);
}

export async function createStaffLedgerApi(entry) {
  return await apiFetch("/api/v1/cc/payroll/ledger", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry)
  });
}

export async function deleteStaffLedgerApi(ledgerId, staffName = "", month = "", amount = 0) {
  let url = `/api/v1/cc/payroll/ledger/${encodeURIComponent(ledgerId)}`;
  const q = [];
  if (staffName) q.push(`staff_name=${encodeURIComponent(staffName)}`);
  if (month) q.push(`month=${encodeURIComponent(month)}`);
  if (amount) q.push(`amount=${encodeURIComponent(amount)}`);
  if (q.length > 0) url += `?${q.join("&")}`;
  return await apiFetch(url, {
    method: "DELETE"
  });
}

// --------------------------------------------------------------------------
// STANDALONE EXCEL & TEMPLATE APIS
// --------------------------------------------------------------------------

export function getExportPayrollUrl(month = "9") {
  const token = getJwtToken();
  const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
  return `/api/v1/cc/excel/export-payroll?month=${encodeURIComponent(month)}${tokenParam}`;
}

export function getStaffTemplateUrl() {
  const token = getJwtToken();
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : "";
  return `/api/v1/cc/excel/staff-template${tokenParam}`;
}

export async function importStaffExcelApi(file) {
  const formData = new FormData();
  formData.append("file", file);
  return await apiFetch("/api/v1/cc/excel/import-staff", {
    method: "POST",
    body: formData
  });
}

// --------------------------------------------------------------------------
// PDF & EMAIL NOTIFICATION APIS
// --------------------------------------------------------------------------

export async function sendPayslipEmailApi(payload) {
  return await apiFetch("/api/v1/cc/notifications/send-payslip-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function sendEvalEmailApi(payload) {
  return await apiFetch("/api/v1/cc/notifications/send-eval-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchOutboxApi(limit = 50) {
  return await apiFetch(`/api/v1/cc/notifications/outbox?limit=${limit}`);
}

export async function deleteOutboxPdfApi(filename) {
  return await apiFetch(`/api/v1/cc/notifications/outbox/pdf/${encodeURIComponent(filename)}`, {
    method: "DELETE"
  });
}

export function getPreviewPayslipPdfUrl(staffName, month = "9") {
  const token = getJwtToken();
  const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
  return `/api/v1/cc/notifications/preview-payslip-pdf?staff_name=${encodeURIComponent(staffName)}&month=${encodeURIComponent(month)}${tokenParam}`;
}

// --------------------------------------------------------------------------
// POS CASH CLOSING APIS
// --------------------------------------------------------------------------

export async function submitDailyClosingApi(payload) {
  return await apiFetch("/api/v1/cc/pos/daily-closing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function fetchDailyClosingsApi(limit = 20, date = "") {
  let url = `/api/v1/cc/pos/daily-closings?limit=${limit}`;
  if (date) url += `&date=${encodeURIComponent(date)}`;
  return await apiFetch(url);
}

