# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
FnBOps On-Premise Excel Routes
Workstream 1: SQLite Schema & Excel Manager
Endpoints for exporting payroll, downloading staff template, and importing staff accounts.
"""

import io
import datetime
import logging
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Request, UploadFile, File, Query, HTTPException, status
from fastapi.responses import StreamingResponse, JSONResponse

try:
    from backend.services.auth import get_current_user
except ImportError:
    from services.auth import get_current_user

try:
    from services.excel_manager import (
        export_payroll_excel,
        generate_staff_template,
        import_staff_from_excel
    )
except ImportError:
    from backend.services.excel_manager import (
        export_payroll_excel,
        generate_staff_template,
        import_staff_from_excel
    )

logger = logging.getLogger("excel_routes")

router = APIRouter(prefix="/api/v1/cc/excel", tags=["Excel Operations"])

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def require_excel_auth(
    request: Request,
    allowed_roles: Optional[List[str]] = None,
    token_param: Optional[str] = None
) -> dict:
    """
    Verifies authentication via Authorization Bearer header OR ?token= query param.
    Enforces role-based access control (RBAC).
    """
    token = None
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1].strip()
    elif token_param:
        token = token_param.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực tài khoản. Vui lòng đăng nhập."
        )

    user = get_current_user(token)
    if allowed_roles:
        u_role = str(user.get("role") or "").upper()
        if u_role not in [r.upper() for r in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản không có quyền truy cập chức năng này."
            )
    return user


@router.get("/export-payroll")
@router.head("/export-payroll", include_in_schema=False)
async def get_payroll_excel(
    request: Request,
    month: Optional[str] = Query(None, description="Tháng xuất bảng lương (ví dụ: '8', '9')"),
    token: Optional[str] = Query(None, description="JWT Token (dùng khi mở trực tiếp từ trình duyệt)")
):
    """
    Xuất bảng lương nhân sự FnBOps ra file Excel .xlsx có công thức tính và định dạng chuẩn Slate Navy.
    Bảo vệ RBAC: Chỉ ADMIN hoặc MANAGER mới được phép xuất.
    Chạy bất đồng bộ qua asyncio.to_thread để không nghẽn Event Loop.
    """
    require_excel_auth(request, allowed_roles=["ADMIN", "MANAGER"], token_param=token)
    month_str = str(month or datetime.datetime.now().month).strip()
    try:
        excel_bytes = await asyncio.to_thread(export_payroll_excel, month_str=month_str)
        filename = f"BangLuong_FnBOps_Thang_{month_str}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_bytes),
            media_type=EXCEL_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except RuntimeError as e:
        if "openpyxl" in str(e).lower():
            logger.warning(f"Tính năng xuất Excel chưa khả dụng: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(e)
            )
        logger.exception(f"Lỗi khi xuất bảng lương tháng {month_str}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể xuất file Excel bảng lương: {str(e)}"
        )
    except Exception as e:
        logger.exception(f"Lỗi khi xuất bảng lương tháng {month_str}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể xuất file Excel bảng lương: {str(e)}"
        )


@router.get("/staff-template")
@router.head("/staff-template", include_in_schema=False)
async def get_staff_excel_template(
    request: Request,
    token: Optional[str] = Query(None, description="JWT Token (dùng khi mở trực tiếp từ trình duyệt)")
):
    """
    Tải file mẫu danh sách nhân sự (.xlsx) kèm hướng dẫn để nhập liệu vào hệ thống.
    Bảo vệ RBAC: Chỉ ADMIN hoặc MANAGER mới được phép tải file mẫu.
    Chạy bất đồng bộ qua asyncio.to_thread để không nghẽn Event Loop.
    """
    require_excel_auth(request, allowed_roles=["ADMIN", "MANAGER"], token_param=token)
    try:
        template_bytes = await asyncio.to_thread(generate_staff_template)
        filename = "Mau_Nhan_Su_FnBOps.xlsx"
        return StreamingResponse(
            io.BytesIO(template_bytes),
            media_type=EXCEL_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except RuntimeError as e:
        if "openpyxl" in str(e).lower():
            logger.warning(f"Tính năng tải file mẫu chưa khả dụng: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(e)
            )
        logger.exception(f"Lỗi khi tạo file mẫu nhân sự: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể tạo file mẫu nhân sự: {str(e)}"
        )
    except Exception as e:
        logger.exception(f"Lỗi khi tạo file mẫu nhân sự: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không thể tạo file mẫu nhân sự: {str(e)}"
        )


@router.post("/import-staff")
async def post_import_staff(
    request: Request,
    file: UploadFile = File(...)
):
    """
    Tiếp nhận file Excel chứa danh sách nhân sự, phân tích và upsert vào CSDL SQLite `staff_accounts`.
    Bảo vệ RBAC: Chỉ ADMIN mới có quyền nhập dữ liệu tài khoản nhân sự từ Excel.
    Chạy phân tích Excel qua asyncio.to_thread để không làm chậm server.
    """
    require_excel_auth(request, allowed_roles=["ADMIN"])
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tên file không hợp lệ."
        )

    clean_name = file.filename.lower()
    if not (clean_name.endswith(".xlsx") or clean_name.endswith(".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ hỗ trợ file Excel định dạng .xlsx hoặc .xls."
        )

    try:
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File tải lên không có dữ liệu (rỗng)."
            )

        result = await asyncio.to_thread(import_staff_from_excel, content)
        status_code = status.HTTP_200_OK if result["success"] else status.HTTP_400_BAD_REQUEST
        return JSONResponse(status_code=status_code, content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Lỗi trong quá trình xử lý import nhân sự: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "count": 0, "errors": [f"Lỗi máy chủ: {str(e)}"]}
        )
