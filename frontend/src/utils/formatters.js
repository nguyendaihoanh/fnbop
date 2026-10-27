// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// STRING & NUMBER FORMATTERS & CLIPBOARD
// ==========================================================================

import { showToast } from "./toast.js";

export const fmtMoney = new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" });
export const fmtNum = new Intl.NumberFormat("vi-VN");

export { escapeHtml, stripHtml, isSafeUrl } from "./sanitize.js";

export function removeAccents(str) {
  if (!str) return "";
  return str.normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
}

export function copyTextToClipboard(text, successToast = "Đã sao chép vào bộ nhớ tạm!") {
  if (!text) return;

  const fallbackTextarea = () => {
    try {
      if (typeof document !== "undefined" && document.createElement) {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        ta.style.top = "0";
        ta.setAttribute("readonly", "");
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, 999999);
        const successful = document.execCommand("copy");
        document.body.removeChild(ta);
        if (successful) {
          showToast(successToast, "success");
          return true;
        }
      }
    } catch (err) {
      console.warn("Fallback copy error:", err);
    }
    showToast("Không thể tự động sao chép văn bản.", "warn");
    return false;
  };

  if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      showToast(successToast, "success");
    }).catch(() => {
      fallbackTextarea();
    });
  } else {
    fallbackTextarea();
  }
}

if (typeof window !== "undefined") {
  window.copyTextFallback = copyTextToClipboard;
}

/**
 * Format số tiền chuyên biệt cho Bento KPI Cards:
 * - Khi amount >= 1 tỷ (1,000,000,000): Rút gọn thông minh "1.25 B" hoặc "1.25 Tỷ" kèm đơn vị nhỏ
 * - Khi amount >= 100 triệu (100,000,000): Rút gọn "125.5 Tr" kèm đơn vị nhỏ
 * - Dưới 100 triệu: Hiển thị đầy đủ số tiền chuẩn Việt Nam: "11.816.133 đ"
 * Trả về object: { formattedHtml, fullText, isCompact }
 */
export function fmtBentoMoney(amount) {
  const val = Math.round(Number(amount) || 0);
  const fullText = fmtMoney.format(val).replace('₫', 'đ');
  
  if (val >= 1000000000) {
    const compactVal = (val / 1000000000).toLocaleString('vi-VN', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 2
    });
    return {
      formattedHtml: `${compactVal} <small class="bento-unit">Tỷ</small>`,
      fullText,
      isCompact: true
    };
  }
  
  if (val >= 100000000) {
    const compactVal = (val / 1000000).toLocaleString('vi-VN', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1
    });
    return {
      formattedHtml: `${compactVal} <small class="bento-unit">Tr</small>`,
      fullText,
      isCompact: true
    };
  }

  // Dưới 100 triệu: hiển thị đầy đủ
  const numPart = fmtNum.format(val);
  return {
    formattedHtml: `${numPart} <small class="bento-unit">đ</small>`,
    fullText,
    isCompact: false
  };
}
