# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class ShiftDefinition(BaseModel):
    name: str
    start_time: str
    end_time: str
    is_overnight: Optional[bool] = False
    grace_period_mins: Optional[int] = 15


class StoreConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    store_name: Optional[str] = None
    address: Optional[str] = None
    shifts: Optional[Dict[str, Any]] = None
    late_grace_period_mins: Optional[int] = None
    wifi_whitelist: Optional[List[str]] = None
    emergency_remote_checkin: Optional[bool] = None


class StoreConfig(BaseModel):
    model_config = ConfigDict(extra="allow", from_attributes=True)

    store_name: str = "FnBOps Store Lounge"
    address: Optional[str] = None
    shifts: Optional[Dict[str, Any]] = None
    late_grace_period_mins: int = 15
    wifi_whitelist: List[str] = []


class UpdateOpsTogglePayload(BaseModel):
    key: str = Field(..., min_length=1)
    value: Optional[Any] = None
    enabled: Optional[bool] = None
