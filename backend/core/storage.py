# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
FnBOps Core Storage Utilities
Thread-safe, atomic JSON read and write with file locking.
"""

from services.storage import safe_json_read, safe_json_write, get_file_lock

__all__ = ["safe_json_read", "safe_json_write", "get_file_lock"]
