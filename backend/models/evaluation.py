# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class StaffEvaluationRequest(BaseModel):
    staff_name: str = Field(..., min_length=1)
    date: str = Field(..., min_length=1)
    shift: Optional[str] = "Ca Sáng"
    type: str = Field(default="Phạt", description="'Phạt' | 'Thưởng'")
    amount: int = 0
    reason: str = Field(..., min_length=1)
    notes: Optional[str] = ""
    ratings: Optional[Dict[str, Any]] = None
    red_flags: Optional[List[str]] = None


class ApproveEvaluationRequest(BaseModel):
    eval_id: str = Field(..., min_length=1)
    action: str = Field(..., description="'APPROVE' | 'REJECT'")
    admin_note: Optional[str] = ""


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    eval_id: Optional[str] = None
    staff_name: str
    date: str
    shift: Optional[str] = "Ca Sáng"
    type: str
    amount: int
    reason: str
    status: Optional[str] = "PENDING"
    notes: Optional[str] = ""


# Alias
EvaluationCreate = StaffEvaluationRequest
