# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
Staff Management Router for FnBOps
Endpoints:
- GET  /admin/staff-accounts
- POST /admin/update-pin
- POST /admin/toggle-staff-status
- POST /admin/update-staff-profile
- POST /admin/create-staff-account
- GET  /admin/lockouts
- POST /admin/lockouts/unlock
"""

import os
import sys
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, HTTPException

from models.staff import (
    UpdatePinData,
    ToggleStaffStatusData,
    CreateStaffAccountData,
    UpdateStaffProfileData,
    AdminUnlockRequest,
)
from services.auth import (
    get_current_user,
    load_staff_auth,
    save_staff_auth,
    normalize_str,
    VALID_ADMIN_SUBS,
)
from services.storage import hash_pin, needs_rehash
from services.db import (
    upsert_staff_account,
    get_active_lockouts,
    admin_unlock_target,
    get_db_connection,
)
from services.attendance_service import get_current_cafe_ip

logger = logging.getLogger("staff_router")
router = APIRouter(prefix="", tags=["Staff Management"])


@router.get("/admin/staff-accounts")
def get_staff_accounts(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền truy cập")
    
    auth = load_staff_auth()
    res_auth = json.loads(json.dumps(auth))
    for uname_acc, acc_data in res_auth.get("staff_accounts", {}).items():
        pin_val = str(acc_data.get("pin", "")).strip()
        acc_data["has_pin"] = bool(pin_val)
        acc_data.pop("pin", None)
    return res_auth


@router.post("/admin/update-pin")
def update_pin(request: Request, data: UpdatePinData):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền đổi PIN")

    new_pin = str(data.new_pin).strip()
    if not new_pin.isalnum() or not (4 <= len(new_pin) <= 8):
        raise HTTPException(status_code=400, detail="Mã PIN/Mật khẩu phải từ 4 đến 8 ký tự (chữ hoặc số)")

    auth = load_staff_auth()
    accounts = auth.get("staff_accounts", {})
    raw_u = data.username.strip()
    norm_u = normalize_str(raw_u)
    target_u = raw_u if raw_u in accounts else norm_u
    
    if target_u not in accounts:
        found_key = None
        for k, acc in accounts.items():
            if raw_u.lower() == k.lower() or norm_u == normalize_str(k) or norm_u in [normalize_str(a) for a in acc.get("aliases", [])]:
                found_key = k
                break
        if found_key:
            target_u = found_key
        else:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản nhân viên")

    caller_role = user.get("role")
    caller_uname = (user.get("username") or user.get("sub") or "").lower()
    target_role = accounts[target_u].get("role", "STAFF")
    if caller_role == "MANAGER":
        if target_role in ["ADMIN", "MANAGER"] and target_u.lower() != caller_uname:
            raise HTTPException(status_code=403, detail="Quản lý không có quyền đổi PIN của Quản trị viên hoặc Quản lý khác.")

    hashed_pin = hash_pin(new_pin) if needs_rehash(new_pin) else new_pin
    accounts[target_u]["pin"] = hashed_pin
    accounts[target_u]["token_version"] = int(accounts[target_u].get("token_version", 1)) + 1
    new_token_ver = accounts[target_u]["token_version"]
    save_staff_auth(auth)
    try:
        upsert_staff_account(
            username=target_u,
            full_name=accounts[target_u].get("full_name", target_u),
            pin_hash=hashed_pin,
            role=accounts[target_u].get("role", "STAFF"),
            status=accounts[target_u].get("status", "ACTIVE"),
            token_version=new_token_ver
        )
    except Exception:
        pass
    return {
        "success": True, 
        "message": f"Đã cập nhật mã PIN mới cho {accounts[target_u]['full_name']}.",
        "username": target_u
    }


@router.post("/admin/toggle-staff-status")
def toggle_staff_status(request: Request, data: ToggleStaffStatusData):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền đổi trạng thái nhân sự")

    st = data.status.strip().upper()
    if st not in ["ACTIVE", "INACTIVE"]:
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ (ACTIVE hoặc INACTIVE)")

    auth = load_staff_auth()
    accounts = auth.get("staff_accounts", {})
    raw_u = data.username.strip()
    norm_u = normalize_str(raw_u)
    target_u = raw_u if raw_u in accounts else norm_u
    
    if target_u not in accounts:
        found_key = None
        for k, a in accounts.items():
            if raw_u.lower() == k.lower() or norm_u == normalize_str(k) or norm_u in [normalize_str(al) for al in a.get("aliases", [])]:
                found_key = k
                break
        if found_key:
            target_u = found_key
        else:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản nhân sự")

    caller_role = user.get("role")
    target_role = accounts[target_u].get("role", "STAFF")
    if caller_role == "MANAGER":
        if target_role in ["ADMIN", "MANAGER"]:
            raise HTTPException(status_code=403, detail="Quản lý không có quyền thay đổi trạng thái của Quản trị viên hoặc Quản lý khác.")

    accounts[target_u]["status"] = st
    accounts[target_u]["token_version"] = int(accounts[target_u].get("token_version", 1)) + 1
    new_token_ver = accounts[target_u]["token_version"]
    save_staff_auth(auth)
    try:
        upsert_staff_account(
            username=target_u,
            full_name=accounts[target_u].get("full_name", target_u),
            status=st,
            is_active=(st == "ACTIVE"),
            token_version=new_token_ver
        )
    except Exception:
        pass
    return {
        "success": True, 
        "message": f"Đã chuyển trạng thái của {accounts[target_u].get('full_name', target_u)} sang: {st}",
        "username": target_u,
        "status": st
    }


@router.post("/admin/update-staff-profile")
def update_staff_profile(request: Request, data: UpdateStaffProfileData):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền chỉnh sửa hồ sơ nhân sự")

    auth = load_staff_auth()
    accounts = auth.get("staff_accounts", {})
    raw_u = data.username.strip()
    norm_u = normalize_str(raw_u)
    target_u = raw_u if raw_u in accounts else norm_u

    if target_u not in accounts:
        found_key = None
        for k, a in accounts.items():
            if raw_u.lower() == k.lower() or norm_u == normalize_str(k) or norm_u in [normalize_str(al) for al in a.get("aliases", [])]:
                found_key = k
                break
        if found_key:
            target_u = found_key
        else:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản nhân sự")

    acc = accounts[target_u]
    caller_role = str(user.get("role") or "").upper()
    caller_uname = (user.get("username") or user.get("sub") or "").lower()
    target_role = str(acc.get("role", "STAFF")).upper()
    if caller_role == "MANAGER":
        if target_role in ["ADMIN", "MANAGER"] and target_u.lower() != caller_uname:
            raise HTTPException(
                status_code=403, 
                detail="Quản lý không có quyền chỉnh sửa hồ sơ của Quản trị viên hoặc Quản lý khác."
            )

    final_username = target_u
    if data.new_username:
        new_u = normalize_str(data.new_username)
        if new_u and new_u != normalize_str(target_u):
            if len(new_u) < 2:
                raise HTTPException(status_code=400, detail="Tên đăng nhập tối thiểu 2 ký tự (viết liền không dấu)")
            for existing_k in accounts.keys():
                if normalize_str(existing_k) == new_u and normalize_str(existing_k) != normalize_str(target_u):
                    raise HTTPException(status_code=400, detail=f"Tên đăng nhập @{new_u} đã được sử dụng bởi nhân viên khác")
            acc = accounts.pop(target_u)
            aliases = acc.setdefault("aliases", [])
            if target_u not in aliases:
                aliases.append(target_u)
            accounts[new_u] = acc
            final_username = new_u

    if data.gender:
        g = str(data.gender).strip().upper()
        if g in ["NAM", "NU"]:
            acc["gender"] = g
    if data.position:
        p = str(data.position).strip().upper()
        if p in ["BARISTA", "SERVICE", "MANAGER"]:
            acc["position"] = p
    if data.full_name:
        fn = str(data.full_name).strip()
        if fn:
            acc["full_name"] = fn
    if data.phone is not None:
        acc["phone"] = str(data.phone).strip()
    if data.pin:
        p_val = str(data.pin).strip()
        if p_val:
            acc["pin"] = hash_pin(p_val) if needs_rehash(p_val) else p_val
    if data.fixed_shift is not None:
        acc["fixed_shift"] = str(data.fixed_shift).strip()
    caller_role = user.get("role")
    if caller_role == "ADMIN":
        if data.hourly_rate is not None:
            try:
                hr = int(data.hourly_rate)
                if hr > 0:
                    acc["hourly_rate"] = hr
            except (ValueError, TypeError):
                pass
        if data.salary_type is not None:
            stype = str(data.salary_type).strip().upper()
            if stype in ["HOURLY", "FIXED"]:
                acc["salary_type"] = stype
        if data.fixed_salary is not None:
            try:
                fsal = int(data.fixed_salary)
                if fsal >= 0:
                    acc["fixed_salary"] = fsal
            except (ValueError, TypeError):
                pass
        if data.role is not None:
            r = str(data.role).strip().upper()
            if r in ["STAFF", "MANAGER"]:
                acc["role"] = r
                acc["token_version"] = int(acc.get("token_version", 1)) + 1

    if data.allowed_roles is not None:
        valid_roles = [str(r).strip().upper() for r in data.allowed_roles if str(r).strip().upper() in ["BARISTA", "SERVICE", "MANAGER"]]
        acc["allowed_roles"] = valid_roles

    save_staff_auth(auth)
    try:
        if final_username != target_u:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE staff_accounts SET username = ? WHERE username = ?", (final_username, target_u))
            cur.execute("UPDATE staff_accounts SET username = ? WHERE username = ?", (final_username, target_u.lower()))
            conn.commit()
            conn.close()
    except Exception:
        pass
    try:
        upsert_staff_account(
            username=final_username,
            full_name=acc.get("full_name", final_username),
            gender=acc.get("gender", "NAM"),
            position=acc.get("position", "SERVICE"),
            role=acc.get("role", "STAFF"),
            phone=acc.get("phone", ""),
            hourly_rate=acc.get("hourly_rate", 17000),
            allowed_roles=acc.get("allowed_roles", []),
            salary_type=acc.get("salary_type", "HOURLY"),
            fixed_salary=acc.get("fixed_salary", 0),
            token_version=acc.get("token_version", 1)
        )
    except Exception:
        pass
    acc["username"] = final_username
    return {
        "success": True,
        "message": f"Đã cập nhật thông tin nhân viên {acc.get('full_name', final_username)}",
        "account": acc
    }


@router.post("/admin/create-staff-account")
def create_staff_account(request: Request, data: CreateStaffAccountData):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") not in ["ADMIN", "MANAGER"]:
        raise HTTPException(status_code=403, detail="Chỉ Quản lý hoặc Admin mới có quyền tạo tài khoản nhân viên")

    u_norm = normalize_str(data.username)
    if not u_norm or len(u_norm) < 2:
        raise HTTPException(status_code=400, detail="Tên đăng nhập tối thiểu 2 ký tự (viết liền không dấu)")

    raw_reserved = {"admin", "chu_quan", "administrator", "root", "system"} | {str(s).lower() for s in VALID_ADMIN_SUBS}
    reserved_names = {normalize_str(s) for s in raw_reserved if normalize_str(s)}
    if u_norm.lower() in reserved_names:
        raise HTTPException(status_code=400, detail=f"Tên đăng nhập '{data.username}' là danh tính dành riêng cho quản trị hệ thống")

    pin = str(data.pin).strip()
    if not pin.isalnum() or not (4 <= len(pin) <= 8):
        raise HTTPException(status_code=400, detail="Mã PIN/Mật khẩu phải từ 4 đến 8 ký tự (chữ hoặc số)")

    full_name = str(data.full_name).strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="Vui lòng nhập họ và tên nhân sự")

    sheet_names = [str(sn).strip() for sn in data.sheet_names if str(sn).strip()]
    if not sheet_names:
        sheet_names = [full_name]

    gender = str(data.gender).strip().upper() if data.gender else "NAM"
    if gender not in ["NAM", "NU"]:
        gender = "NAM"

    position = str(data.position).strip().upper() if data.position else "SERVICE"
    if position not in ["BARISTA", "SERVICE", "MANAGER"]:
        position = "SERVICE"

    auth = load_staff_auth()
    accounts = auth.setdefault("staff_accounts", {})

    if u_norm in accounts:
        raise HTTPException(status_code=400, detail=f"Tên đăng nhập '{u_norm}' đã tồn tại")

    aliases = [normalize_str(a) for a in data.aliases if normalize_str(a)]
    if u_norm not in aliases:
        aliases.append(u_norm)

    allowed_roles = [str(r).strip().upper() for r in (data.allowed_roles or []) if str(r).strip().upper() in ["BARISTA", "SERVICE", "MANAGER"]]
    if not allowed_roles:
        allowed_roles = [position]

    caller_role = user.get("role")
    rate = 17000
    salary_type = "HOURLY"
    fixed_salary = 0
    if caller_role == "ADMIN":
        if data.hourly_rate is not None:
            try:
                hr = int(data.hourly_rate)
                if hr > 0:
                    rate = hr
            except (ValueError, TypeError):
                pass
        if data.salary_type:
            stype = str(data.salary_type).strip().upper()
            if stype in ["HOURLY", "FIXED"]:
                salary_type = stype
        if data.fixed_salary is not None:
            try:
                fixed_salary = max(0, int(data.fixed_salary))
            except (ValueError, TypeError):
                pass

    phone = str(data.phone or "").strip()
    fixed_shift = str(data.fixed_shift or "").strip()

    target_role = "STAFF"
    if caller_role == "ADMIN" and data.role:
        r = str(data.role).strip().upper()
        if r in ["STAFF", "MANAGER"]:
            target_role = r

    hashed_new_pin = hash_pin(pin) if needs_rehash(pin) else pin
    new_acc = {
        "full_name": full_name,
        "sheet_names": sheet_names,
        "pin": hashed_new_pin,
        "role": target_role,
        "gender": gender,
        "position": position,
        "allowed_roles": allowed_roles,
        "status": "ACTIVE",
        "aliases": aliases,
        "hourly_rate": rate,
        "salary_type": salary_type,
        "fixed_salary": fixed_salary,
        "phone": phone,
        "fixed_shift": fixed_shift,
        "confirmations": {}
    }
    accounts[u_norm] = new_acc
    save_staff_auth(auth)
    try:
        upsert_staff_account(
            username=u_norm,
            full_name=full_name,
            pin_hash=hashed_new_pin,
            role=target_role,
            gender=gender,
            position=position,
            status="ACTIVE",
            hourly_rate=rate,
            phone=phone,
            allowed_roles=allowed_roles,
            is_active=True,
            salary_type=salary_type,
            fixed_salary=fixed_salary
        )
    except Exception:
        pass

    return {
        "success": True,
        "message": f"Đã tạo tài khoản thành công cho {full_name} ({gender} - {position}, Mã PIN: {pin})",
        "username": u_norm,
        "account": new_acc
    }


def _get_live_cafe_ip() -> str:
    for mod_name in ("routers.fnb_ops", "backend.routers.fnb_ops", "routers.staff", "backend.routers.staff"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_get_live_cafe_ip"):
            fn = getattr(mod, "_get_live_cafe_ip")
            if fn is not _get_live_cafe_ip:
                try:
                    res = fn()
                    if res:
                        return res
                except Exception:
                    pass
    return get_current_cafe_ip()


@router.get("/admin/lockouts")
def get_admin_lockouts(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ duy nhất Chủ quán (Admin) mới có quyền kiểm tra và quản lý khóa truy cập")
    
    lockouts = get_active_lockouts()
    cafe_ip = _get_live_cafe_ip()
    return {
        "status": "success",
        "lockouts": lockouts,
        "cafe_ip": cafe_ip,
        "total_locked": len(lockouts)
    }


@router.post("/admin/lockouts/unlock")
def admin_unlock(request: Request, data: AdminUnlockRequest):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = get_current_user(auth_header.split(" ")[1])
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ duy nhất Chủ quán (Admin) mới có quyền duyệt mở khóa")
    
    target_key = data.target_key.strip()
    if not target_key:
        raise HTTPException(status_code=400, detail="Mục tiêu mở khóa không được để trống")
        
    success = admin_unlock_target(target_key)
    return {
        "status": "success",
        "message": f"Đã mở khóa thành công cho: {target_key}",
        "target_key": target_key,
        "unlocked": success
    }
