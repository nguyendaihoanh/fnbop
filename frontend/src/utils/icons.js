// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// FnBOps LUCIDE ICON SYSTEM (LIGHTWEIGHT SVG ENGINE)
// Standard Lucide: 24x24 viewBox, stroke="currentColor", fill="none"
// ==========================================================================

export const ICONS = {
  // Brand & Auth
  coffee: `
    <path d="M17 8h1a4 4 0 1 1 0 8h-1"/>
    <path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4Z"/>
    <line x1="6" x2="6" y1="2" y2="4"/>
    <line x1="10" x2="10" y1="2" y2="4"/>
    <line x1="14" x2="14" y1="2" y2="4"/>
  `,
  eye: `
    <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>
    <circle cx="12" cy="12" r="3"/>
  `,
  eyeOff: `
    <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"/>
    <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"/>
    <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"/>
    <line x1="2" x2="22" y1="2" y2="22"/>
  `,

  // Navigation & Actions
  moreHorizontal: `
    <circle cx="12" cy="12" r="1.5" fill="currentColor"/>
    <circle cx="19" cy="12" r="1.5" fill="currentColor"/>
    <circle cx="5" cy="12" r="1.5" fill="currentColor"/>
  `,
  chevronLeft: `
    <path d="m15 18-6-6 6-6"/>
  `,
  chevronRight: `
    <path d="m9 18 6-6-6-6"/>
  `,
  chevronDown: `
    <path d="m6 9 6 6 6-6"/>
  `,
  chevronUp: `
    <path d="m18 15-6-6-6 6"/>
  `,
  x: `
    <path d="M18 6 6 18"/>
    <path d="m6 6 12 12"/>
  `,
  check: `
    <polyline points="20 6 9 17 4 12"/>
  `,

  // Core Tabs & Concepts
  activity: `
    <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
  `,
  zap: `
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
  `,
  calendar: `
    <path d="M8 2v4"/>
    <path d="M16 2v4"/>
    <rect width="18" height="18" x="3" y="4" rx="2"/>
    <path d="M3 10h18"/>
  `,
  clock: `
    <circle cx="12" cy="12" r="10"/>
    <polyline points="12 6 12 12 16 14"/>
  `,
  fileText: `
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>
    <polyline points="14 2 14 8 20 8"/>
    <line x1="16" x2="8" y1="13" y2="13"/>
    <line x1="16" x2="8" y1="17" y2="17"/>
    <line x1="10" x2="8" y1="9" y2="9"/>
  `,

  // Incident & Security
  alertCircle: `
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" x2="12" y1="8" y2="12"/>
    <line x1="12" x2="12.01" y1="16" y2="16"/>
  `,
  fileWarning: `
    <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>
    <path d="M12 9v4"/>
    <path d="M12 17h.01"/>
    <path d="M14 2v5a2 2 0 0 0 2 2h5"/>
  `,
  shield: `
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/>
  `,
  key: `
    <circle cx="7.5" cy="15.5" r="5.5"/>
    <path d="m21 2-9.6 9.6"/>
    <path d="m15.5 7.5 3 3L22 7l-3-3"/>
  `,
  lock: `
    <rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>
    <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
  `,
  unlock: `
    <rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>
    <path d="M7 11V7a5 5 0 0 1 9.9-1"/>
  `,

  // Settings & Theme
  sunMoon: `
    <path d="M12 8a2.83 2.83 0 0 0 4 4 4 4 0 1 1-4-4"/>
    <path d="M12 2v2"/>
    <path d="M12 20v2"/>
    <path d="m4.9 4.9 1.4 1.4"/>
    <path d="m17.7 17.7 1.4 1.4"/>
    <path d="M2 12h2"/>
    <path d="M20 12h2"/>
    <path d="m6.3 17.7-1.4 1.4"/>
    <path d="m19.1 4.9-1.4 1.4"/>
  `,
  sun: `
    <circle cx="12" cy="12" r="4"/>
    <path d="M12 2v2"/>
    <path d="M12 20v2"/>
    <path d="m4.93 4.93 1.41 1.41"/>
    <path d="m17.66 17.66 1.41 1.41"/>
    <path d="M2 12h2"/>
    <path d="M20 12h2"/>
    <path d="m6.34 17.66-1.41 1.41"/>
    <path d="m19.07 4.93-1.41 1.41"/>
  `,
  moon: `
    <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
  `,
  logOut: `
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
    <polyline points="16 17 21 12 16 7"/>
    <line x1="21" x2="9" y1="12" y2="12"/>
  `,

  // Tools & External
  barChart3: `
    <path d="M3 3v18h18"/>
    <path d="M18 17V9"/>
    <path d="M13 17V5"/>
    <path d="M8 17v-3"/>
  `,
  monitor: `
    <rect width="20" height="14" x="2" y="3" rx="2"/>
    <line x1="8" x2="16" y1="21" y2="21"/>
    <line x1="12" x2="12" y1="17" y2="21"/>
  `,
  trash2: `
    <path d="M3 6h18"/>
    <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>
    <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
    <line x1="10" x2="10" y1="11" y2="17"/>
    <line x1="14" x2="14" y1="11" y2="17"/>
  `,
  refreshCw: `
    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>
    <path d="M21 3v5h-5"/>
    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>
    <path d="M8 16H3v5"/>
  `,
  externalLink: `
    <path d="M15 3h6v6"/>
    <path d="M10 14 21 3"/>
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
  `,
  user: `
    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
    <circle cx="12" cy="7" r="4"/>
  `,
  users: `
    <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
    <circle cx="9" cy="7" r="4"/>
    <path d="M22 21v-2a4 4 0 0 0-3-3.87"/>
    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
  `
};

/**
 * Render SVG icon element as HTML string
 * @param {string} name - Icon name from ICONS map
 * @param {Object} options - Configuration options
 * @param {number} [options.size=18] - Width and height in px
 * @param {string} [options.className=''] - Additional CSS classes
 * @param {number} [options.strokeWidth=1.75] - SVG stroke width
 * @returns {string} Clean SVG markup string
 */
export function getIconSvg(name, { size = 18, className = '', strokeWidth = 1.75 } = {}) {
  const content = ICONS[name];
  if (!content) {
    console.warn(`[icons] Icon "${name}" not found in icons library.`);
    return '';
  }
  const cleanClass = className ? ` class="${className}"` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${strokeWidth}" stroke-linecap="round" stroke-linejoin="round"${cleanClass}>${content.trim()}</svg>`;
}
