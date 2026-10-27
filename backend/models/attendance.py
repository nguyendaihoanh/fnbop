# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, ConfigDict, Field


class HeartbeatPayload(BaseModel):
    pos_secret: Optional[str] = None
    override_ip: Optional[str] = None


class CheckinPayload(BaseModel):
    username: str = Field(..., min_length=1)
    display_name: Optional[str] = None
    role: Optional[str] = None
    shift_override: Optional[str] = None
    dev_override_wifi: Optional[bool] = False
    custom_time_str: Optional[str] = None  # e.g. "06:15"


class CheckoutPayload(BaseModel):
    username: str = Field(..., min_length=1)
    dev_override_wifi: Optional[bool] = False
    custom_time_str: Optional[str] = None
    confirm_early: Optional[bool] = False


class ManualClosePayload(BaseModel):
    record_id: Union[str, int] = Field(..., description="ID bản ghi (chuỗi hoặc số)")
    manual_checkout: str = Field(..., min_length=1)
    manager_note: Optional[str] = None


class ShiftActionPayload(BaseModel):
    record_id: Optional[Union[str, int]] = None
    username: Optional[str] = None
    manager_pin: Optional[str] = None
    manager_note: Optional[str] = None


class ReviewHangingShiftPayload(BaseModel):
    record_id: Union[str, int] = Field(..., description="ID bản ghi (chuỗi hoặc số)")
    approved_checkout_time: str = Field(..., min_length=1)
    approved_minutes: int = Field(..., ge=0)
    note: Optional[str] = "Quản lý duyệt giờ ra thực tế cho ca quên checkout"


class AttendanceRequestCreate(BaseModel):
    date: str = Field(..., min_length=1)
    shift_key: str = "sang"
    request_type: str = "FORGOT_CHECKOUT"
    requested_checkin: Optional[str] = ""
    requested_checkout: Optional[str] = ""
    reason: Optional[str] = ""


class AttendanceRequestReview(BaseModel):
    action: str = Field(..., min_length=1)  # APPROVE | REJECT
    review_note: Optional[str] = ""


class AttendanceLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    record_id: Optional[str] = None
    username: str
    date: str
    shift_name: Optional[str] = None
    checkin_time: Optional[str] = None
    checkout_time: Optional[str] = None
    total_minutes: Optional[int] = 0
    effective_minutes: Optional[int] = 0
    status: Optional[str] = "COMPLETED"


# Aliases per Phase 4 Spec
HeartbeatRequest = HeartbeatPayload
CheckinRequest = CheckinPayload
CheckoutRequest = CheckoutPayload
ManualCloseRequest = ManualClosePayload
ShiftActionRequest = ShiftActionPayload
ReviewHangingShiftRequest = ReviewHangingShiftPayload
