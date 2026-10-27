// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// XSS SANITIZATION & SECURITY UTILITIES
// FnBOps
// Enforces Zero-Trust DOM rendering against Stored & Reflected XSS
// ==========================================================================

/**
 * Escapes characters with special meaning in HTML to prevent XSS injection.
 * Safely handles strings, numbers, null, and undefined.
 *
 * @param {*} str - Value to escape
 * @returns {string} - Escaped safe HTML string
 */
export function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Strips all HTML tags from a string, keeping only plain text.
 * Useful for titles, notification banners, or plain text contexts.
 *
 * @param {*} str - Value to strip
 * @returns {string} - Plain text without HTML tags
 */
export function stripHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/<[^>]*>?/gm, '');
}

/**
 * Validates whether a URL is safe for navigation or iframe embedding.
 * Blocks dangerous pseudo-protocols like javascript:, data:, vbscript:.
 *
 * @param {string} url - URL to check
 * @returns {boolean} - True if safe HTTP/HTTPS URL
 */
export function isSafeUrl(url) {
  if (!url) return false;
  const clean = String(url).trim().toLowerCase();
  if (clean.startsWith('javascript:') || clean.startsWith('data:') || clean.startsWith('vbscript:')) {
    return false;
  }
  return true;
}
