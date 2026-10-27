# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Payroll Router
Forwarding router to disbursement.py for OpenSource Specification compliance.
"""
from routers.disbursement import router

__all__ = ["router"]
