# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Notification Router
Forwarding router to notification_routes.py for OpenSource Specification compliance.
"""
from routers.notification_routes import router

__all__ = ["router"]
