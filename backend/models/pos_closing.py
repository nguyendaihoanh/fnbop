# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class DailyClosingPayload(BaseModel):
    report_date: str = Field(..., description="Ngày chốt định dạng DD/MM/YYYY")
    closing_time: Optional[str] = Field(default=None, description="Giờ chốt định dạng HH:MM (Mặc định lấy giờ hiện tại)")
    bill_pos: Optional[float] = Field(default=0.0, description="Doanh thu máy POS365 (0 nếu chờ hệ thống tự lấy lúc 23h hoặc Admin điền sau)")
    cash_amount: float = Field(..., description="Tiền mặt đếm két")
    transfer_amount: Optional[float] = Field(default=0.0, description="Chuyển khoản thực nhận (Admin hoặc POS tự động nạp)")
    expense_amount: Optional[float] = Field(default=0.0, description="Chi quầy")
    expense_detail: Optional[str] = Field(default=None, description="Lý do chi")
    sender_name: str = Field(..., description="Tên nhân viên bàn giao/chốt ca")
    approver_name: Optional[str] = Field(default=None, description="Quản lý/người kiểm tra")
    shift_key: Optional[str] = Field(default="daily", description="Mã ca chốt: 'daily', 'sang', 'toi'...")

    @field_validator("report_date")
    @classmethod
    def validate_report_date(cls, v: str) -> str:
        v = v.strip()
        # Hỗ trợ linh hoạt: nếu client/POS gửi định dạng ISO YYYY-MM-DD thì tự động chuyển sang DD/MM/YYYY
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            try:
                dt = datetime.strptime(v, "%Y-%m-%d")
                return dt.strftime("%d/%m/%Y")
            except ValueError:
                raise ValueError("report_date không phải ngày hợp lệ")

        if not re.match(r"^\d{2}/\d{2}/\d{4}$", v):
            raise ValueError("report_date phải đúng định dạng DD/MM/YYYY hoặc YYYY-MM-DD")
        try:
            datetime.strptime(v, "%d/%m/%Y")
        except ValueError:
            raise ValueError("report_date không phải ngày hợp lệ")
        return v

    @field_validator("closing_time")
    @classmethod
    def validate_closing_time(cls, v: Optional[str]) -> str:
        if not v or not str(v).strip():
            return datetime.now().strftime("%H:%M")
        v = str(v).strip()
        # Hỗ trợ linh hoạt: nếu có giây HH:MM:SS thì tự động cắt lấy HH:MM
        if re.match(r"^\d{2}:\d{2}:\d{2}$", v):
            v = v[:5]
        if not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError("closing_time phải đúng định dạng HH:MM")
        try:
            parts = v.split(":")
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError()
        except Exception:
            raise ValueError("closing_time không phải giờ hợp lệ (00:00 - 23:59)")
        return v

    @field_validator("bill_pos", "cash_amount", "transfer_amount", "expense_amount")
    @classmethod
    def validate_amounts(cls, v: Optional[float]) -> float:
        if v is None:
            return 0.0
        if v < 0:
            raise ValueError("Số tiền không được âm")
        return float(v)

    @field_validator("sender_name")
    @classmethod
    def validate_sender_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("sender_name không được để trống")
        return v


class ReconcileClosingPayload(BaseModel):
    closing_id: int = Field(..., description="ID bản ghi chốt ca cần đối soát")
    bill_pos: Optional[float] = Field(default=None, description="Doanh thu máy POS cập nhật")
    transfer_amount: Optional[float] = Field(default=None, description="Số tiền chuyển khoản thực tế")
    approver_name: Optional[str] = Field(default=None, description="Admin/Người duyệt")
    notes: Optional[str] = Field(default=None, description="Ghi chú đối soát")
