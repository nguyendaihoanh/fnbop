// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// TOAST NOTIFICATIONS & ALERT OVERRIDE (DYNAMIC ISLAND SLEEK DESIGN)
// ==========================================================================

export function showToast(msg, type = "info") {
  if (typeof document === "undefined") return;
  let toast = document.getElementById("vnaigc-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "vnaigc-toast";
    toast.className = "vnaigc-dynamic-toast";
    document.body.appendChild(toast);
  }

  // Choose icon based on type
  let iconSvg = '';
  if (type === "success") {
    iconSvg = '<svg viewBox="0 0 20 20" fill="currentColor" width="13" height="13"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>';
  } else if (type === "error") {
    iconSvg = '<svg viewBox="0 0 20 20" fill="currentColor" width="13" height="13"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/></svg>';
  } else if (type === "warn") {
    iconSvg = '<svg viewBox="0 0 20 20" fill="currentColor" width="13" height="13"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>';
  } else {
    iconSvg = '<svg viewBox="0 0 20 20" fill="currentColor" width="13" height="13"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/></svg>';
  }

  toast.className = `vnaigc-dynamic-toast toast-${type}`;
  toast.innerHTML = `
    <span class="toast-indicator">${iconSvg}</span>
    <span class="toast-message">${String(msg || '').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</span>
  `;

  // Tap to dismiss immediately
  toast.onclick = () => {
    toast.classList.remove('active');
  };

  // Trigger animation
  void toast.offsetWidth;
  toast.classList.add('active');

  if (typeof window !== "undefined") {
    clearTimeout(window._toastTimeout);
    const duration = type === "error" ? 3000 : 2200;
    window._toastTimeout = setTimeout(() => {
      toast.classList.remove('active');
    }, duration);
  }
}

const ERROR_TRANSLATIONS = {
  "Method Not Allowed": "Thao tác không được máy chủ hỗ trợ",
  "method not allowed": "Thao tác không được máy chủ hỗ trợ",
  "Not Found": "Không tìm thấy dữ liệu yêu cầu",
  "not found": "Không tìm thấy dữ liệu yêu cầu",
  "Unauthorized": "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại",
  "unauthorized": "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại",
  "Forbidden": "Bạn không có quyền thực hiện thao tác này",
  "forbidden": "Bạn không có quyền thực hiện thao tác này",
  "Internal Server Error": "Lỗi xử lý nội bộ máy chủ",
  "internal server error": "Lỗi xử lý nội bộ máy chủ",
  "Failed to fetch": "Mất kết nối mạng hoặc máy chủ chưa phản hồi",
  "NetworkError": "Mất kết nối mạng hoặc máy chủ chưa phản hồi"
};

export function safeErrorDetail(err, fallback = "Lỗi không xác định") {
  if (!err) return fallback;
  let raw = "";
  if (typeof err === "string") {
    raw = err;
  } else if (typeof err.detail === "string") {
    raw = err.detail;
  } else if (Array.isArray(err.detail)) {
    raw = err.detail.map(d => d.msg || (typeof d === "object" ? JSON.stringify(d) : String(d))).join("; ");
  } else if (typeof err.detail === "object" && err.detail !== null) {
    raw = err.detail.msg || err.detail.message || JSON.stringify(err.detail);
  } else {
    raw = err.message || fallback;
  }

  // Chuyển đổi mã lỗi kỹ thuật thô sang tiếng Việt thân thiện
  const trimmed = String(raw).trim();
  for (const [key, translated] of Object.entries(ERROR_TRANSLATIONS)) {
    if (trimmed === key || trimmed.toLowerCase() === key.toLowerCase()) {
      return translated;
    }
  }
  return raw;
}

// Override alert toan cuc de hien thi toast nhe nhang, khong bao gio chan UI hay gay treo web
if (typeof window !== "undefined") {
  window.alert = function(msg) {
    showToast(safeErrorDetail(msg), "info");
  };
}
