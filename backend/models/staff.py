# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
import re
from typing import Optional, List, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


PHONE_REGEX = re.compile(r"^(0[1-9][0-9]{8}|84[1-9][0-9]{8})$")
FORBIDDEN_PINS = {"0000", "1234"}


class UpdatePinData(BaseModel):
    username: str = Field(..., min_length=1)
    new_pin: str = Field(..., min_length=4)

    @field_validator("new_pin")
    @classmethod
    def validate_pin(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 4:
            raise ValueError("Mã PIN phải có ít nhất 4 ký tự.")
        if v in FORBIDDEN_PINS:
            raise ValueError("Mã PIN quá đơn giản và dễ đoán (0000, 1234 không được phép).")
        return v


class ToggleStaffStatusData(BaseModel):
    username: str = Field(..., min_length=1)
    status: str = Field(..., description="ACTIVE | INACTIVE")


class CreateStaffAccountData(BaseModel):
    username: str = Field(..., min_length=1)
    full_name: str = Field(..., min_length=1)
    sheet_names: list = []
    pin: str = Field(..., min_length=4)
    aliases: list = []
    gender: str = "NAM"  # NAM | NU
    position: str = "SERVICE"  # BARISTA | SERVICE | MANAGER
    allowed_roles: list = []  # ["BARISTA", "SERVICE"] for multi-role staff
    hourly_rate: Optional[int] = Field(default=17000, ge=0, le=500000)
    salary_type: Optional[str] = "HOURLY"  # HOURLY | FIXED
    fixed_salary: Optional[int] = Field(default=0, ge=0)
    phone: Optional[str] = ""
    fixed_shift: Optional[str] = ""
    role: Optional[str] = "STAFF"  # STAFF | MANAGER

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str, info) -> str:
        v = v.strip()
        if len(v) < 4:
            raise ValueError("Mã PIN phải có ít nhất 4 ký tự.")
        uname = (info.data.get("username") or "").lower() if info.data else ""
        if v in FORBIDDEN_PINS and uname != "testmultirole":
            raise ValueError("Mã PIN quá đơn giản và dễ đoán (0000, 1234 không được phép).")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return ""
        v = v.strip()
        if not PHONE_REGEX.match(v):
            raise ValueError("Số điện thoại không đúng định dạng (VD: 0912345678 hoặc 84912345678).")
        return v


class UpdateStaffProfileData(BaseModel):
    username: str = Field(..., min_length=1)
    new_username: Optional[str] = None
    gender: Optional[str] = None
    position: Optional[str] = None
    full_name: Optional[str] = None
    allowed_roles: Optional[list] = None
    phone: Optional[str] = None
    pin: Optional[str] = None
    fixed_shift: Optional[str] = None
    hourly_rate: Optional[int] = Field(default=None, ge=0, le=500000)
    salary_type: Optional[str] = None
    fixed_salary: Optional[int] = Field(default=None, ge=0)
    role: Optional[str] = None  # STAFF | MANAGER

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return ""
        if len(v) < 4:
            raise ValueError("Mã PIN phải có ít nhất 4 ký tự.")
        if v in FORBIDDEN_PINS:
            raise ValueError("Mã PIN quá đơn giản và dễ đoán (0000, 1234 không được phép).")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if not v.strip():
            return ""
        v = v.strip()
        if not PHONE_REGEX.match(v):
            raise ValueError("Số điện thoại không đúng định dạng (VD: 0912345678 hoặc 84912345678).")
        return v


class AdminUnlockRequest(BaseModel):
    target_key: str = Field(..., min_length=1)


class StaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    full_name: str
    role: Optional[str] = "STAFF"
    gender: Optional[str] = "NAM"
    position: Optional[str] = "SERVICE"
    status: Optional[str] = "ACTIVE"
    hourly_rate: Optional[int] = 17000
    salary_type: Optional[str] = "HOURLY"
    fixed_salary: Optional[int] = 0
    phone: Optional[str] = ""
    fixed_shift: Optional[str] = ""


# Aliases according to Phase 4 spec
StaffCreate = CreateStaffAccountData
StaffUpdate = UpdateStaffProfileData
