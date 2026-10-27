// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// LOCALE BARREL [RU] — MODULAR DOMAIN ARCHITECTURE
// ==========================================================================

import META from './meta.js';
import common from './common.js';
import ops from './ops.js';
import roster from './roster.js';
import attendance from './attendance.js';
import payslip from './payslip.js';
import admin from './admin.js';
import { TOKENS, translateTokens, PATTERNS } from './patterns.js';
import { EXACT_PHRASE_MAP } from './domMap.js';

export const dictionary = {
  ...common,
  ...ops,
  ...roster,
  ...attendance,
  ...payslip,
  ...admin
};

export {
  META,
  common,
  ops,
  roster,
  attendance,
  payslip,
  admin,
  TOKENS,
  translateTokens,
  PATTERNS,
  EXACT_PHRASE_MAP
};

export default dictionary;
