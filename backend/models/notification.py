# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class PushSubscribeRequest(BaseModel):
    username: str = Field(..., min_length=1)
    subscription: Dict[str, Any]
    user_agent: Optional[str] = ""


class TriggerTestPushRequest(BaseModel):
    username: str = Field(..., min_length=1)
    template_type: str = Field(..., description="'CHECKIN', 'CHECKOUT', 'ROSTER'")
    custom_title: Optional[str] = None
    custom_body: Optional[str] = None


class ManagerRemindRequest(BaseModel):
    username: str = Field(..., min_length=1)
    remind_type: str = Field(..., description="'CHECKIN', 'CHECKOUT', 'ROSTER'")
    custom_message: Optional[str] = None


class SendPayslipEmailRequest(BaseModel):
    staff_name: str = Field(..., min_length=1)
    month: Optional[str] = None
    to_email: Optional[str] = None
    breakdown: Optional[Dict[str, Any]] = None


class SendEvalEmailRequest(BaseModel):
    eval_id: Optional[str] = None
    staff_name: Optional[str] = None
    to_email: Optional[str] = None
    eval_data: Optional[Dict[str, Any]] = None


class SendPayslipZaloCardRequest(BaseModel):
    staff_name: str = Field(..., min_length=1)
    month: Optional[str] = None
    phone: Optional[str] = None
    breakdown: Optional[Dict[str, Any]] = None


class SendBulkPayslipZaloCardsRequest(BaseModel):
    month: Optional[str] = None


class ZaloPayslipCard(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient_phone: str
    staff_name: str
    month: str
    net_salary: int
    details: Optional[Dict[str, Any]] = None


class TelegramAlert(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel_type: str = "DEV"  # DEV | PROD
    title: str
    message: str
    level: str = "INFO"        # INFO | WARNING | CRITICAL
