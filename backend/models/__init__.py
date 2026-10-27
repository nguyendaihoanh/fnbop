# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
# Authentication models
from .auth import (
    LoginRequest,
    LoginData,
    TokenResponse,
    TokenPayload,
)

# Staff models
from .staff import (
    UpdatePinData,
    ToggleStaffStatusData,
    CreateStaffAccountData,
    UpdateStaffProfileData,
    AdminUnlockRequest,
    StaffResponse,
    StaffCreate,
    StaffUpdate,
)

# Attendance models
from .attendance import (
    HeartbeatPayload,
    HeartbeatRequest,
    CheckinPayload,
    CheckinRequest,
    CheckoutPayload,
    CheckoutRequest,
    ManualClosePayload,
    ManualCloseRequest,
    ShiftActionPayload,
    ShiftActionRequest,
    ReviewHangingShiftPayload,
    ReviewHangingShiftRequest,
    AttendanceRequestCreate,
    AttendanceRequestReview,
    AttendanceLog,
)

# Roster models
from .roster import (
    ShiftPreference,
    AutoFillRequest,
    ClonePreviousWeekRequest,
    UpdateShiftSlotRequest,
    PublishWeekRequest,
    PeerSwapRequest,
    PeerSwapRespondRequest,
    CreateOpenShiftRequest,
    ShiftSlot,
    WeekSchedule,
    SwapRequest,
)

# Payroll & Ledger models
from .payroll import (
    StaffLedgerCreateRequest,
    ToggleLockData,
    ConfirmPayrollData,
    DisbursementToggleRequest,
    ConfirmOTData,
    LedgerEntry,
    PayslipBreakdown,
    DisbursementStatus,
)

# Evaluation models
from .evaluation import (
    StaffEvaluationRequest,
    ApproveEvaluationRequest,
    EvaluationResponse,
    EvaluationCreate,
)

# Store Configuration & Ops models
from .store_config import (
    ShiftDefinition,
    StoreConfig,
    StoreConfigUpdate,
    UpdateOpsTogglePayload,
)

# Notification models
from .notification import (
    PushSubscribeRequest,
    TriggerTestPushRequest,
    ManagerRemindRequest,
    SendPayslipEmailRequest,
    SendEvalEmailRequest,
    SendPayslipZaloCardRequest,
    SendBulkPayslipZaloCardsRequest,
    ZaloPayslipCard,
    TelegramAlert,
)

# POS Daily Closing models
from .pos_closing import (
    DailyClosingPayload,
    ReconcileClosingPayload,
)

__all__ = [
    # Auth
    "LoginRequest",
    "LoginData",
    "TokenResponse",
    "TokenPayload",
    # Staff
    "UpdatePinData",
    "ToggleStaffStatusData",
    "CreateStaffAccountData",
    "UpdateStaffProfileData",
    "AdminUnlockRequest",
    "StaffResponse",
    "StaffCreate",
    "StaffUpdate",
    # Attendance
    "HeartbeatPayload",
    "HeartbeatRequest",
    "CheckinPayload",
    "CheckinRequest",
    "CheckoutPayload",
    "CheckoutRequest",
    "ManualClosePayload",
    "ManualCloseRequest",
    "ShiftActionPayload",
    "ShiftActionRequest",
    "ReviewHangingShiftPayload",
    "ReviewHangingShiftRequest",
    "AttendanceRequestCreate",
    "AttendanceRequestReview",
    "AttendanceLog",
    # Roster
    "ShiftPreference",
    "AutoFillRequest",
    "ClonePreviousWeekRequest",
    "UpdateShiftSlotRequest",
    "PublishWeekRequest",
    "PeerSwapRequest",
    "PeerSwapRespondRequest",
    "CreateOpenShiftRequest",
    "ShiftSlot",
    "WeekSchedule",
    "SwapRequest",
    # Payroll
    "StaffLedgerCreateRequest",
    "ToggleLockData",
    "ConfirmPayrollData",
    "DisbursementToggleRequest",
    "ConfirmOTData",
    "LedgerEntry",
    "PayslipBreakdown",
    "DisbursementStatus",
    # Evaluation
    "StaffEvaluationRequest",
    "ApproveEvaluationRequest",
    "EvaluationResponse",
    "EvaluationCreate",
    # Store Config
    "ShiftDefinition",
    "StoreConfig",
    "StoreConfigUpdate",
    "UpdateOpsTogglePayload",
    # Notification
    "PushSubscribeRequest",
    "TriggerTestPushRequest",
    "ManagerRemindRequest",
    "SendPayslipEmailRequest",
    "SendEvalEmailRequest",
    "SendPayslipZaloCardRequest",
    "SendBulkPayslipZaloCardsRequest",
    "ZaloPayslipCard",
    "TelegramAlert",
    # POS Closing
    "DailyClosingPayload",
    "ReconcileClosingPayload",
]
