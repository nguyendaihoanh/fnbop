// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// POS CLOSING MODULE: CASH & TRANSFER RECONCILIATION WITH POS365
// ==========================================================================

import { fmtMoney, fmtNum, escapeHtml } from "../utils/formatters.js";
import { showToast, safeErrorDetail } from "../utils/toast.js";
import { getCurrentVNDate } from "../utils/dateUtils.js";
import { getAuthName, getAuthRole } from "../store/authStore.js";
import { submitDailyClosingApi, fetchDailyClosingsApi } from "../api/payrollApi.js";
import { t } from "../i18n/index.js";

export function formatThousands(val) {
  if (val === null || val === undefined || val === "") return "";
  const clean = String(val).replace(/\D/g, "");
  if (!clean) return "";
  return clean.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

export function parseNum(val) {
  if (!val) return 0;
  if (typeof val === "number") return val;
  const cleaned = String(val).replace(/\./g, "").replace(/,/g, "").replace(/\D/g, "");
  const n = parseFloat(cleaned);
  return isNaN(n) ? 0 : n;
}

export function moneyToVietnameseWords(num) {
  if (!num || isNaN(num) || num <= 0) return "";
  if (num >= 1e9) {
    const ty = (num / 1e9).toFixed(num % 1e9 === 0 ? 0 : 2);
    return t('pos.amount_billion', { ty }, `~ ${ty} tỷ đồng`);
  }
  if (num >= 1e6) {
    const tr = (num / 1e6).toFixed(num % 1e6 === 0 ? 0 : 2);
    return t('pos.amount_million', { tr }, `~ ${tr} triệu đồng`);
  }
  if (num >= 1e3) {
    const k = (num / 1e3).toFixed(num % 1e3 === 0 ? 0 : 0);
    return t('pos.amount_thousand', { k }, `${k} nghìn đồng`);
  }
  return t('pos.amount_dong', { num }, `${num} đồng`);
}

export function openDailyClosingModal() {
  const sheet = document.getElementById("dailyClosingSheet");
  if (!sheet) return;

  const now = new Date();
  const dateStr = getCurrentVNDate();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const timeStr = `${hh}:${mm}`;

  const elDate = document.getElementById("closingReportDate");
  if (elDate) elDate.value = dateStr;

  const elTime = document.getElementById("closingTime");
  if (elTime) elTime.value = timeStr;

  const senderInput = document.getElementById("closingSenderName");
  if (senderInput && !senderInput.value.trim()) {
    senderInput.value = getAuthName() || t('pos.cashier_default', {}, "Thu ngân");
  }

  // Reset amounts
  const billEl = document.getElementById("closingBillPos");
  const cashEl = document.getElementById("closingCashAmount");
  const transEl = document.getElementById("closingTransferAmount");
  const expEl = document.getElementById("closingExpenseAmount");
  const expDetailEl = document.getElementById("closingExpenseDetail");

  if (billEl && !billEl.value) billEl.value = "";
  if (cashEl && !cashEl.value) cashEl.value = "";
  if (transEl && !transEl.value) transEl.value = "";
  if (expEl && !expEl.value) expEl.value = "";
  if (expDetailEl && !expDetailEl.value) expDetailEl.value = "";

  [
    { id: "closingBillPos", hintId: "hintClosingBillPos" },
    { id: "closingCashAmount", hintId: "hintClosingCashAmount" },
    { id: "closingTransferAmount", hintId: "hintClosingTransferAmount" },
    { id: "closingExpenseAmount", hintId: "hintClosingExpenseAmount" }
  ].forEach(({ id, hintId }) => {
    const el = document.getElementById(id);
    const hint = document.getElementById(hintId);
    if (el && hint) {
      const num = parseNum(el.value);
      hint.textContent = num > 0 ? moneyToVietnameseWords(num) : "";
    }
  });

  recalculateClosingLive();
  loadClosingHistory();

  sheet.classList.add("active");
}

export function closeDailyClosingModal() {
  const sheet = document.getElementById("dailyClosingSheet");
  if (sheet) sheet.classList.remove("active");
}

export function recalculateClosingLive() {
  const billPos = parseNum(document.getElementById("closingBillPos")?.value);
  const cash = parseNum(document.getElementById("closingCashAmount")?.value);
  const transfer = parseNum(document.getElementById("closingTransferAmount")?.value);
  const expense = parseNum(document.getElementById("closingExpenseAmount")?.value);

  const totalReal = cash + transfer + expense;
  const diff = totalReal - billPos;

  // Format Total Real
  const elTotalReal = document.getElementById("closingTotalRealText");
  if (elTotalReal) {
    elTotalReal.textContent = fmtMoney.format(totalReal).replace("₫", "đ");
  }

  // Format Diff & Badge
  const elDiffText = document.getElementById("closingDiffText");
  const elDiffBadge = document.getElementById("closingDiffStatusBadge");
  const elWarning = document.getElementById("closingWarningBanner");

  if (elDiffText && elDiffBadge) {
    if (diff === 0) {
      elDiffText.textContent = "0 đ";
      elDiffText.style.color = "var(--accent-emerald)";
      elDiffBadge.textContent = t('pos.status_matched', {}, "KHỚP");
      elDiffBadge.className = "status-chip emerald";
    } else if (diff > 0) {
      elDiffText.textContent = `+${fmtMoney.format(diff).replace("₫", "đ")}`;
      elDiffText.style.color = "var(--accent-emerald)";
      elDiffBadge.textContent = `${t('pos.status_over_prefix', {}, 'DƯƠNG')} ${fmtMoney.format(diff).replace("₫", "đ")}`;
      elDiffBadge.className = "status-chip emerald";
    } else {
      elDiffText.textContent = `-${fmtMoney.format(Math.abs(diff)).replace("₫", "đ")}`;
      elDiffText.style.color = "var(--accent-coral)";
      elDiffBadge.textContent = `${t('pos.status_under_prefix', {}, 'ÂM')} ${fmtMoney.format(Math.abs(diff)).replace("₫", "đ")}`;
      elDiffBadge.className = "status-chip coral";
    }
  }

  // Large discrepancy warning (> 50,000 VND)
  if (elWarning) {
    if (Math.abs(diff) > 50000 && billPos > 0) {
      elWarning.style.display = "flex";
      const detailWarn = document.getElementById("closingWarningText");
      if (detailWarn) {
        const diffType = diff > 0 ? t('pos.diff_positive', {}, 'dương') : t('pos.diff_negative', {}, 'âm');
        const diffVal = fmtMoney.format(Math.abs(diff)).replace("₫", "đ");
        detailWarn.textContent = t('pos.warning_diff_detail', { type: diffType, amount: diffVal }, `Lệch két ${diffType} ${diffVal} (vượt ngưỡng 50,000đ). Vui lòng rà soát lại bill POS và quỹ tiền mặt!`);
      }
    } else {
      elWarning.style.display = "none";
    }
  }
}

export async function submitDailyClosing() {
  const dateStr = document.getElementById("closingReportDate")?.value.trim();
  const timeStr = document.getElementById("closingTime")?.value.trim();
  const billPos = parseNum(document.getElementById("closingBillPos")?.value);
  const cash = parseNum(document.getElementById("closingCashAmount")?.value);
  const transfer = parseNum(document.getElementById("closingTransferAmount")?.value);
  const expense = parseNum(document.getElementById("closingExpenseAmount")?.value);
  const expenseDetail = document.getElementById("closingExpenseDetail")?.value.trim() || null;
  const senderName = document.getElementById("closingSenderName")?.value.trim();
  const approverName = document.getElementById("closingApproverName")?.value.trim() || null;

  if (!dateStr || !timeStr) {
    showToast(t('pos.warn_select_datetime', {}, "Vui lòng chọn ngày và giờ chốt ca!"), "warn");
    return;
  }
  if (!senderName) {
    showToast(t('pos.warn_enter_sender', {}, "Vui lòng nhập tên người chốt ca!"), "warn");
    return;
  }
  if (billPos <= 0 && cash <= 0 && transfer <= 0) {
    showToast(t('pos.warn_enter_amounts', {}, "Vui lòng nhập doanh thu POS và số tiền đếm két!"), "warn");
    return;
  }

  const btnSubmit = document.getElementById("btnSubmitDailyClosing");
  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = `<span>⏳</span> ${t('common.loading', {}, 'Đang lưu chốt két...')}`;
  }

  try {
    const payload = {
      report_date: dateStr,
      closing_time: timeStr,
      bill_pos: billPos,
      cash_amount: cash,
      transfer_amount: transfer,
      expense_amount: expense,
      expense_detail: expenseDetail,
      sender_name: senderName,
      approver_name: approverName
    };

    const res = await submitDailyClosingApi(payload);
    const data = await res.json().catch(() => null);

    if (res.ok && data && data.status === "success") {
      showToast(data.message || t('pos.msg_submit_success', {}, 'Chốt ca thành công!'), "success");
      loadClosingHistory();
      setTimeout(() => {
        closeDailyClosingModal();
      }, 1200);
    } else {
      const err = data?.detail || t('pos.err_submit_failed', {}, "Không thể lưu chốt ca");
      showToast(err, "error");
    }
  } catch (err) {
    showToast(t('pos.err_network_submit', { error: err.message }, `Lỗi kết nối khi gửi dữ liệu chốt ca: ${err.message}`), "error");
  } finally {
    if (btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.innerHTML = t('pos.submit_btn', {}, 'Xác Nhận Chốt Két');
    }
  }
}

export async function loadClosingHistory() {
  const container = document.getElementById("closingHistoryList");
  if (!container) return;

  try {
    container.innerHTML = `<div class="text-muted-12" style="text-align: center; padding: 12px;">${t('common.loading_history', {}, 'Đang tải lịch sử...')}</div>`;
    const res = await fetchDailyClosingsApi(15);
    const json = await res.json().catch(() => null);

    if (!res.ok || !json || !Array.isArray(json.records) || json.records.length === 0) {
      container.innerHTML = `<div class="text-muted-12" style="text-align: center; padding: 12px;">${t('pos.no_history', {}, 'Chưa có bản ghi chốt két nào gần đây.')}</div>`;
      return;
    }

    container.innerHTML = json.records.map(r => {
      const isMatch = r.diff_status === "KHỚP" || r.diff === 0;
      const isWarn = r.is_warning || Math.abs(r.diff || 0) > 50000;
      const statusClass = isMatch ? "emerald" : (isWarn ? "coral" : "amber");
      const diffFormatted = isMatch ? "0 đ" : `${r.diff > 0 ? "+" : ""}${fmtMoney.format(r.diff).replace("₫", "đ")}`;
      let statusText = r.diff_status;
      if (r.diff_status === "KHỚP") {
        statusText = t('pos.status_matched', {}, 'KHỚP');
      } else if (r.diff_status && r.diff_status.startsWith("DƯƠNG")) {
        statusText = `${t('pos.status_over_prefix', {}, 'DƯƠNG')} ${r.diff_status.replace(/^DƯƠNG\s*/, '')}`;
      } else if (r.diff_status && r.diff_status.startsWith("ÂM")) {
        statusText = `${t('pos.status_under_prefix', {}, 'ÂM')} ${r.diff_status.replace(/^ÂM\s*/, '')}`;
      }

      return `
        <div style="background: var(--bg-card-sub); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px;">
          <div class="flex-between mb-4">
            <span style="font-size: 13px; font-weight: 700; color: var(--text-primary);">
              📅 ${escapeHtml(r.report_date)} • ${escapeHtml(r.closing_time || "--:--")}
            </span>
            <span class="status-chip ${statusClass}">
              ${escapeHtml(statusText)} (${diffFormatted})
            </span>
          </div>
          <div style="font-size: 12px; color: var(--text-secondary); line-height: 1.5;">
            <div>${t('pos.bill_pos_short', {}, 'POS:')} <strong>${fmtMoney.format(r.bill_pos || 0).replace("₫", "đ")}</strong> • ${t('pos.total_real_short', {}, 'Thực thu:')} <strong style="color:var(--text-primary);">${fmtMoney.format(r.total_real || 0).replace("₫", "đ")}</strong></div>
            <div class="text-muted-12" style="margin-top: 2px;">
              ${t('pos.cash_label', {}, 'Tiền mặt:')} ${fmtMoney.format(r.cash_amount || 0).replace("₫", "đ")} | ${t('pos.transfer_label', {}, 'CK:')} ${fmtMoney.format(r.transfer_amount || 0).replace("₫", "đ")} ${r.expense_amount > 0 ? `| ${t('pos.expense_label', {}, 'Chi:')} ${fmtMoney.format(r.expense_amount).replace("₫", "đ")}` : ""}
            </div>
            <div class="text-muted-12" style="margin-top: 2px;">
              ${t('pos.sender_label', {}, 'Người chốt:')} <strong>${escapeHtml(r.sender_name || t('pos.cashier_default', {}, "Thu ngân"))}</strong> ${r.approver_name ? `• ${t('pos.approver_label', {}, 'Duyệt:')} ${escapeHtml(r.approver_name)}` : ""}
            </div>
            ${r.expense_detail ? `<div class="text-muted-12" style="color:var(--accent-coral); margin-top: 2px;">${t('pos.expense_detail_label', {}, 'Chi tiết chi:')} ${escapeHtml(r.expense_detail)}</div>` : ""}
          </div>
        </div>
      `;
    }).join("");
  } catch (err) {
    container.innerHTML = `<div class="text-muted-12" style="text-align: center; color: var(--accent-coral); padding: 12px;">${t('pos.err_load_history', { error: err.message }, `Lỗi tải lịch sử: ${err.message}`)}</div>`;
  }
}

export function setupDailyClosingEvents() {
  const btnOpen = document.getElementById("btnOpenDailyClosing");
  if (btnOpen) {
    btnOpen.addEventListener("click", openDailyClosingModal);
  }

  const btnClose = document.getElementById("btnCloseDailyClosing");
  if (btnClose) {
    btnClose.addEventListener("click", closeDailyClosingModal);
  }

  const btnSubmit = document.getElementById("btnSubmitDailyClosing");
  if (btnSubmit) {
    btnSubmit.addEventListener("click", submitDailyClosing);
  }

  const btnRefreshHistory = document.getElementById("btnRefreshClosingHistory");
  if (btnRefreshHistory) {
    btnRefreshHistory.addEventListener("click", loadClosingHistory);
  }

  // Live recalculate & auto format numbers with thousands dot (.)
  const moneyInputs = [
    { id: "closingBillPos", hintId: "hintClosingBillPos" },
    { id: "closingCashAmount", hintId: "hintClosingCashAmount" },
    { id: "closingTransferAmount", hintId: "hintClosingTransferAmount" },
    { id: "closingExpenseAmount", hintId: "hintClosingExpenseAmount" }
  ];

  moneyInputs.forEach(({ id, hintId }) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", () => {
      const raw = el.value.replace(/\D/g, "");
      if (!raw) {
        el.value = "";
      } else {
        el.value = raw.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
      }
      const num = parseFloat(raw) || 0;
      const hint = document.getElementById(hintId);
      if (hint) {
        hint.textContent = num > 0 ? moneyToVietnameseWords(num) : "";
      }
      recalculateClosingLive();
    });
    el.addEventListener("change", recalculateClosingLive);
  });
}
