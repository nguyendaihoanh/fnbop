# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
FnBOps DB Module: schema
Forwarding alias for services.db.schema
"""
try:
    from services.db.schema import *
except ImportError:
    from backend.services.db.schema import *
