// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// PULSE CONFIRM & ACTION DIALOG (PREMIUM NATIVE-FEELING MOBILE DIALOG)
// Replaces ugly, archaic native browser alert() & confirm() dialogs
// ==========================================================================

import { triggerHaptic } from './haptics.js';

let activeDialogResolve = null;

export function showConfirmDialog({
  title = '',
  message = '',
  confirmText = 'Đồng ý',
  cancelText = 'Hủy',
  type = 'warning', // 'danger' | 'warning' | 'telegram' | 'zalo' | 'success' | 'info'
  icon = null
} = {}) {
  return new Promise((resolve) => {
    if (typeof document === 'undefined') {
      return resolve(true);
    }

    if (typeof window !== 'undefined') {
      if (typeof window.__mockConfirmResult === 'boolean') {
        return resolve(window.__mockConfirmResult);
      }
      if (typeof window.confirm === 'function') {
        const fnStr = window.confirm.toString();
        if (!fnStr.includes('[native code]')) {
          return resolve(Boolean(window.confirm(message || title)));
        }
      }
    }

    // Auto-detect intent if not explicitly configured
    const textLower = (title + ' ' + message).toLowerCase();
    if (!icon) {
      if (textLower.includes('telegram')) {
        type = 'telegram';
        icon = 'solar:plain-bold';
        if (!title) title = 'Công Bố Lịch Ca Telegram';
        if (confirmText === 'Đồng ý') confirmText = 'Chốt & Công Bố';
      } else if (textLower.includes('zalo')) {
        type = 'zalo';
        icon = 'solar:chat-round-dots-bold';
        if (!title) title = 'Gửi Phiếu Lương Zalo';
        if (confirmText === 'Đồng ý') confirmText = 'Gửi Ngay';
      } else if (textLower.includes('xóa') || textLower.includes('hủy') || textLower.includes('cảnh báo')) {
        type = 'danger';
        icon = 'solar:trash-bin-trash-bold';
        if (!title) title = 'Xác Nhận Xóa';
        if (confirmText === 'Đồng ý') confirmText = 'Xóa Vĩnh Viễn';
      } else if (textLower.includes('khóa kỳ lương') || textLower.includes('mở lại')) {
        type = 'warning';
        icon = 'solar:lock-keyhole-bold';
        if (!title) title = 'Thay Đổi Trạng Thái Kỳ Lương';
      } else if (textLower.includes('kết thúc ca') || textLower.includes('check-out')) {
        type = 'warning';
        icon = 'solar:alarm-bold';
        if (!title) title = 'Xác Nhận Kết Thúc Ca';
        if (confirmText === 'Đồng ý') confirmText = 'Chốt Giờ Ca';
      } else {
        if (!title) title = 'Xác Nhận Thao Tác';
        icon = type === 'danger' ? 'solar:danger-triangle-bold' : 'solar:question-circle-bold';
      }
    }

    let overlay = document.getElementById('pulseConfirmModal');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'pulseConfirmModal';
      overlay.className = 'pulse-dialog-overlay';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      document.body.appendChild(overlay);
    }

    // Color and icon styles based on type
    let colorTheme = {
      iconBg: 'rgba(238, 93, 54, 0.12)',
      iconColor: 'var(--accent-coral)',
      btnBg: 'var(--accent-coral)',
      btnColor: '#ffffff'
    };

    if (type === 'telegram') {
      colorTheme = {
        iconBg: 'rgba(0, 136, 204, 0.15)',
        iconColor: '#0088cc',
        btnBg: '#0088cc',
        btnColor: '#ffffff'
      };
    } else if (type === 'zalo') {
      colorTheme = {
        iconBg: 'rgba(0, 104, 255, 0.15)',
        iconColor: '#0068ff',
        btnBg: '#0068ff',
        btnColor: '#ffffff'
      };
    } else if (type === 'success') {
      colorTheme = {
        iconBg: 'rgba(52, 199, 89, 0.15)',
        iconColor: '#34c759',
        btnBg: '#34c759',
        btnColor: '#ffffff'
      };
    } else if (type === 'info') {
      colorTheme = {
        iconBg: 'rgba(0, 122, 255, 0.12)',
        iconColor: '#007aff',
        btnBg: '#007aff',
        btnColor: '#ffffff'
      };
    }

    // Convert newlines in message to clean paragraph/breaks
    const safeMsg = String(message || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>');

    overlay.innerHTML = `
      <div class="pulse-dialog-card pulse-dialog-${type}">
        <div class="pulse-dialog-icon-wrap" style="background: ${colorTheme.iconBg}; color: ${colorTheme.iconColor};">
          <iconify-icon icon="${icon}" width="30" height="30"></iconify-icon>
        </div>
        <h3 class="pulse-dialog-title">${title}</h3>
        <div class="pulse-dialog-body">${safeMsg}</div>
        <div class="pulse-dialog-actions">
          <button type="button" class="pulse-dialog-btn cancel" id="btnPulseCancel">${cancelText}</button>
          <button type="button" class="pulse-dialog-btn confirm" id="btnPulseConfirm" style="background: ${colorTheme.btnBg}; color: ${colorTheme.btnColor};">
            ${confirmText}
          </button>
        </div>
      </div>
    `;

    // Trigger haptic alert
    try {
      triggerHaptic(type === 'danger' ? 'alert' : 'tick');
    } catch (e) {}

    const closeDialog = (result) => {
      overlay.classList.remove('active');
      document.removeEventListener('keydown', handleKeyDown);
      setTimeout(() => {
        if (overlay && !overlay.classList.contains('active')) {
          overlay.style.display = 'none';
        }
      }, 250);
      resolve(result);
    };

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        closeDialog(false);
      } else if (e.key === 'Enter') {
        closeDialog(true);
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    overlay.style.display = 'flex';
    // Force reflow for CSS transition
    void overlay.offsetWidth;
    overlay.classList.add('active');

    const btnConfirm = overlay.querySelector('#btnPulseConfirm');
    const btnCancel = overlay.querySelector('#btnPulseCancel');

    if (btnConfirm) {
      if (typeof btnConfirm.focus === 'function') btnConfirm.focus();
      btnConfirm.onclick = () => {
        try { triggerHaptic('tap'); } catch (e) {}
        closeDialog(true);
      };
    }

    if (btnCancel) {
      btnCancel.onclick = () => {
        try { triggerHaptic('micro'); } catch (e) {}
        closeDialog(false);
      };
    }

    // Tap outside to cancel
    overlay.onclick = (e) => {
      if (e.target === overlay) {
        closeDialog(false);
      }
    };
  });
}

// Global exposure for non-module scripts if needed
if (typeof window !== 'undefined') {
  window.showConfirmDialog = showConfirmDialog;
}
