# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class StaffLedgerCreateRequest(BaseModel):
    staff_name: str = Field(..., min_length=1)
    month: Optional[str] = None
    type: str = Field(..., description="'bonus', 'advance', 'deduction'")
    amount: int = Field(..., ge=0)
    payment_method: str = "cash"   # 'cash', 'bank'
    reason: str = ""


class ToggleLockData(BaseModel):
    month: str = Field(..., min_length=1)
    status: str = Field(..., description="'LOCKED' | 'UNLOCKED'")
    message: str = ""


class ConfirmPayrollData(BaseModel):
    month: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    note: str = ""


class DisbursementToggleRequest(BaseModel):
    month: str = Field(..., min_length=1)
    staff_name: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    amount: Optional[int] = Field(default=0, ge=0)


class ConfirmOTData(BaseModel):
    shift_key: str = Field(..., min_length=1)
    action: str = Field(..., description="APPROVE | CUT | RESET")
    approved_mins: int = Field(default=300, ge=0)
    manager_note: str = ""


class LedgerEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entry_id: Optional[int] = None
    staff_name: str
    month: str
    type: str
    amount: int
    payment_method: Optional[str] = "cash"
    reason: Optional[str] = ""
    created_at: Optional[str] = None


class PayslipBreakdown(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    staff_name: str
    month: str
    total_hours: float = 0.0
    base_salary: int = 0
    bonus: int = 0
    advance: int = 0
    deduction: int = 0
    net_salary: int = 0


class DisbursementStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    staff_name: str
    month: str
    is_paid: bool = False
    paid_amount: int = 0
    paid_at: Optional[str] = None
