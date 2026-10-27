// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// API CLIENT WRAPPER (JWT AUTH, HEADERS, ERROR HANDLING)
// ==========================================================================

import { safeErrorDetail } from "../utils/toast.js";

export function getJwtToken() {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem("vnaigc_jwt") || localStorage.getItem("vnaigc_token") || null;
}

export function getAuthHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders };
  const token = getJwtToken();
  if (token && !headers["Authorization"]) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

export async function apiFetch(url, options = {}) {
  const opts = { ...options };
  opts.headers = getAuthHeaders(opts.headers || {});

  const res = await fetch(url, opts);

  if (res.status === 401) {
    if (typeof window !== "undefined" && typeof window.clearAuth === "function") {
      window.clearAuth();
    } else if (typeof localStorage !== "undefined") {
      localStorage.removeItem("vnaigc_jwt");
      localStorage.removeItem("vnaigc_token");
    }
  }

  return res;
}

export async function apiJson(url, options = {}) {
  const opts = { ...options };
  if (!opts.headers) opts.headers = {};
  if (!opts.headers["Content-Type"] && opts.method && opts.method.toUpperCase() !== "GET") {
    opts.headers["Content-Type"] = "application/json";
  }

  const res = await apiFetch(url, opts);
  const data = await res.json().catch(() => null);

  if (!res.ok) {
    const msg = safeErrorDetail(data, `HTTP ${res.status}`);
    const error = new Error(msg);
    error.status = res.status;
    error.data = data;
    throw error;
  }

  return data;
}
