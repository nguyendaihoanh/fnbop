# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
FnBOps Core Module
Shared cross-cutting concerns: storage, utilities, constants.
"""

from core.constants import DEFAULT_TIMEZONE, DEFAULT_CURRENCY, API_V1_PREFIX
from core.storage import safe_json_read, safe_json_write, get_file_lock
from core.utils import normalize_str, removeDiacritics

__all__ = [
    "DEFAULT_TIMEZONE",
    "DEFAULT_CURRENCY",
    "API_V1_PREFIX",
    "safe_json_read",
    "safe_json_write",
    "get_file_lock",
    "normalize_str",
    "removeDiacritics"
]
