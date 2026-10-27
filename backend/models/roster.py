# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class ShiftPreference(BaseModel):
    preferences: Dict[str, Any]
    target_shifts: int = 5
    note: str = ""
    week_id: Optional[str] = None
    role_preference: Optional[str] = "BOTH"


class AutoFillRequest(BaseModel):
    week_id: str = Field(..., min_length=1)


class ClonePreviousWeekRequest(BaseModel):
    target_week_id: str = Field(..., min_length=1)
    source_week_id: Optional[str] = None


class UpdateShiftSlotRequest(BaseModel):
    week_id: str = Field(..., min_length=1)
    date: str = Field(..., min_length=1)
    shift_period: str = Field(..., min_length=1)  # morning | evening
    slot_type: str = Field(..., min_length=1)     # manager | barista | service_1 | service_2 | service_17 | service_18
    username: Optional[str] = None


class PublishWeekRequest(BaseModel):
    week_id: str = Field(..., min_length=1)


class PeerSwapRequest(BaseModel):
    week_id: str = Field(..., min_length=1)
    date: str = Field(..., min_length=1)
    shift_period: str = Field(..., min_length=1)  # morning | evening
    slot_type: str = Field(..., min_length=1)
    target_username: str = Field(..., min_length=1)
    reason: str = ""
    force_admin_override: bool = False


class PeerSwapRespondRequest(BaseModel):
    swap_id: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)        # ACCEPT | REJECT
    week_id: Optional[str] = None


class CreateOpenShiftRequest(BaseModel):
    date: str = Field(..., min_length=1)
    shift_key: str = "sang"                       # "sang" | "toi"
    slot_type: str = "service"
    role_required: str = "SERVICE"
    week_key: Optional[str] = ""
    note: Optional[str] = ""


class ShiftSlot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slot_type: str
    username: Optional[str] = None
    role_required: Optional[str] = "SERVICE"
    is_confirmed: Optional[bool] = False


class WeekSchedule(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week_id: str
    status: Optional[str] = "DRAFT"               # DRAFT | PUBLISHED
    schedule_data: Optional[Dict[str, Any]] = None


# Alias
SwapRequest = PeerSwapRequest
