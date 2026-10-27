# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, description="Tên đăng nhập hoặc mã nhân viên")
    password: Optional[str] = Field(None, description="Mật khẩu đăng nhập (tùy chọn nếu có pin)")
    pin: Optional[str] = Field(None, description="Mã PIN đăng nhập (tùy chọn nếu có password)")

    @property
    def credential(self) -> str:
        return (self.password or self.pin or "").strip()


# Backward compatibility alias
LoginData = LoginRequest


class TokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
    full_name: Optional[str] = None
    shift_role: Optional[str] = None


class TokenPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sub: str
    role: str
    full_name: Optional[str] = None
    shift_role: Optional[str] = None
    exp: Optional[int] = None
