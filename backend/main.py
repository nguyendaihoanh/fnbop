# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
from typing import Optional
from pydantic import BaseModel, Field
import json
import time
from datetime import datetime
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
try:
    from dotenv import load_dotenv
    load_dotenv(override=(os.getenv("TESTING") != "1"))
except ImportError:
    pass
import sys
import ipaddress
from contextlib import asynccontextmanager

# Ensure unified DATA_DIR is exported globally across all modules
_base_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(_base_dir)
if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

if not os.getenv("DATA_DIR"):
    os.environ["DATA_DIR"] = os.path.join(_project_dir, "data")

from routers import fnb_ops, attendance, roster, pos_closing, notification_routes, excel_routes, push_routes
from routers.fnb_ops import is_cloudflare_ingress_valid

docs_enabled = os.getenv("ENABLE_API_DOCS", "false").lower() in ("true", "1")
ON_PREMISE_MODE = os.getenv("ON_PREMISE_MODE", "false").lower() in ("true", "1")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    try:
        try:
            from services.db import init_db, bootstrap_sync_staff_auth_to_sqlite
        except ImportError:
            from backend.services.db import init_db, bootstrap_sync_staff_auth_to_sqlite
        init_db()
        bootstrap_sync_staff_auth_to_sqlite()
    except Exception:
        pass

    try:
        try:
            from services.demo_seed import seed_if_empty
        except ImportError:
            from backend.services.demo_seed import seed_if_empty
        seed_if_empty()
    except Exception:
        pass

    worker = None
    if os.getenv("DISABLE_BACKGROUND_WORKER", "false").lower() not in ("true", "1"):
        try:
            try:
                from services.background_worker import get_background_worker
            except ImportError:
                from backend.services.background_worker import get_background_worker
            worker = get_background_worker()
            await worker.start()
        except Exception:
            pass

    yield

    # Shutdown logic
    if worker:
        try:
            await worker.stop()
        except Exception:
            pass

app = FastAPI(
    title="FnBOps Operations API",
    version="1.0.0",
    contact={
        "name": "Nguyen Dai Hoanh (VNAIGC)",
        "email": "hoanh@vnaigc.com",
        "url": "https://github.com/nguyendaihoanh/fnbop",
    },
    license_info={
        "name": "GNU Affero General Public License v3.0 only (AGPL-3.0-only)",
        "identifier": "AGPL-3.0-only",
        "url": "https://www.gnu.org/licenses/agpl-3.0.html",
    },
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
    lifespan=lifespan,
)

ALLOWED_HOSTS = {
    "fnbops.local",
    "fnbops.lan",
    "localhost",
    "127.0.0.1",
    "::1",
    "testclient",
    "testserver",
    "host.docker.internal",
    "gateway.docker.internal",
}
if os.getenv("ALLOWED_HOSTS"):
    for h in os.getenv("ALLOWED_HOSTS", "").split(","):
        if h.strip():
            ALLOWED_HOSTS.add(h.strip().lower())

edge_ingress_host = os.getenv("EDGE_INGRESS_HOST")
if edge_ingress_host:
    ALLOWED_HOSTS.add(edge_ingress_host.strip().lower())

def is_allowed_host(host_header: str) -> bool:
    """Validate HTTP Host header to prevent DNS Rebinding and Localhost Pivoting attacks."""
    if not host_header:
        return False
    raw_host = host_header.strip()
    if raw_host.startswith("[") and "]" in raw_host:
        host = raw_host[1:raw_host.index("]")]
    else:
        host = raw_host.split(":")[0].strip().lower()

    if host in ALLOWED_HOSTS:
        return True

    # Cho phép Tailscale MagicDNS (*.ts.net)
    if host.endswith(".ts.net"):
        return True

    # Cho phép OrbStack local domains (*.orb.local)
    if host.endswith(".orb.local"):
        return True

    if ON_PREMISE_MODE:
        if host.endswith(".local") or host in ("pos", "fnbop", "wfm", "pos.lan", "fnbop.lan", "wfm.lan"):
            return True

    try:
        ip = ipaddress.ip_address(host)
        # Hỗ trợ mạng nội bộ LAN (RFC 1918), loopback, và mạng riêng Tailscale (100.64.0.0/10)
        tailscale_net = ipaddress.ip_network("100.64.0.0/10")
        if ip in tailscale_net or ip.is_loopback or ip.is_private:
            return True
    except ValueError:
        pass

    return False

@app.middleware("http")
async def dns_rebinding_shield_middleware(request: Request, call_next):
    host = request.headers.get("host", "")
    if not is_allowed_host(host):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid Host header. DNS Rebinding Protection Active."}
        )
    return await call_next(request)

@app.middleware("http")
async def cloudflare_ingress_shield_middleware(request: Request, call_next):
    if os.getenv("ON_PREMISE_MODE", "false").lower() in ("true", "1"):
        return await call_next(request)
    valid, _ = is_cloudflare_ingress_valid(request)
    if not valid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Direct IP access is prohibited. Requests must route through Cloudflare Edge."}
        )
    return await call_next(request)

BLOCKED_EXTENSIONS = {".db", ".db-wal", ".db-shm", ".lock", ".env", ".py", ".pyc", ".ps1", ".sh", ".bat", ".cmd", ".sql", ".sqlite"}
BLOCKED_STATIC_FILES = {"data.json", "staff_auth.json", "fnbop.db", "wfm.db", "shift_approvals.json", "eval_logs.json", "pos_heartbeat.json", "fnb_pos_heartbeat.ps1", "wfm_pos_heartbeat.ps1"}

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-FnBOps-License"] = "AGPL-3.0-only; Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>"
    p = request.url.path.lower()
    if not p.startswith(("/docs", "/redoc", "/openapi.json")):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'"
        )
    if p == "/" or p.endswith((".html", ".js", ".css", ".json")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

@app.middleware("http")
async def sensitive_file_shield_middleware(request: Request, call_next):
    path = request.url.path.lower()
    if not path.startswith("/api/") and path != "/ping":
        filename = path.split("/")[-1]
        _, ext = os.path.splitext(filename)
        if ext in BLOCKED_EXTENSIONS or filename in BLOCKED_STATIC_FILES:
            return JSONResponse(
                status_code=404,
                content={"detail": "Not Found"}
            )
    return await call_next(request)

MAX_BODY_BYTES = 5 * 1024 * 1024  # 5MB limit to prevent DoS/OOM

@app.middleware("http")
async def request_size_limit_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Payload Too Large. Kích thước gói tin vượt quá giới hạn cho phép (tối đa 5MB)."}
                )
        except ValueError:
            pass
    return await call_next(request)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import logging
    logger = logging.getLogger("backend_main")
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Đã xảy ra lỗi hệ thống nội bộ. Vui lòng liên hệ Quản trị viên."}
    )

@app.get("/ping")
def health_ping():
    return {"status": "ok", "service": "fnbops_backend"}


@app.get("/api/v1/main/ping")
def api_v1_main_ping():
    return {"status": "ok", "message": "FnBOps core API is running"}


# Alias for standard health check convention (Docker healthcheck, load balancers)
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "fnbops_backend"}


@app.get("/api/v1/license")
@app.get("/api/v1/cc/license")
def get_license_and_copyright_info():
    """
    Returns authoritative copyright ownership, AGPL-3.0-only Section 7(b) & Section 13 compliance terms,
    and commercial dual-licensing contact metadata.
    """
    return {
        "project": "FnBOps — F&B Workforce Management & Store Operations OS",
        "version": "1.0.0",
        "spdx_license": "AGPL-3.0-only",
        "license_name": "GNU Affero General Public License v3.0 only",
        "copyright_holder": "Nguyen Dai Hoanh (VNAIGC — VNAIGC DRONE & TECH CO., LTD)",
        "copyright_year": 2026,
        "commercial_license_contact": "hoanh@vnaigc.com",
        "source_repository": "https://github.com/nguyendaihoanh/fnbop",
        "agpl_section_7b_attribution_required": True,
        "agpl_section_13_network_source_disclosure_required": True,
        "additional_terms": "NOTICE (AGPL-3.0 Section 7(b) attribution, 7(c) modified-version marking, 7(e) no trademark grant)",
        "trademark_policy": "TRADEMARKS.md",
        "vn_ip_law_protection": "Protected as a computer program under Article 14, Article 22, and Article 28 of the Vietnam Intellectual Property Law (as amended in 2022) and Decree 17/2023/ND-CP.",
    }


@app.post("/api/ledger")
async def legacy_api_ledger(request: Request):
    from routers.fnb_ops import create_staff_ledger_entry, StaffLedgerCreateRequest
    body = await request.json()
    type_map = {"Ứng": "advance", "Thưởng": "bonus", "Phạt": "deduction"}
    raw_type = body.get("type", "bonus")
    clean_type = type_map.get(raw_type, str(raw_type).lower())
    payload = StaffLedgerCreateRequest(
        staff_name=body.get("staff") or body.get("staff_name", ""),
        type=clean_type,
        amount=int(body.get("amount") or 0),
        payment_method=body.get("payment_type") or body.get("payment_method") or "cash",
        reason=body.get("reason", ""),
        month=str(body.get("month", ""))
    )
    return create_staff_ledger_entry(request, payload)


@app.post("/api/send-payslip")
async def legacy_send_payslip(request: Request):
    from routers.notification_routes import api_send_payslip_email, SendPayslipEmailRequest
    body = await request.json()
    staff_name = body.get("staffName") or body.get("staff_name") or ""
    month = str(body.get("monthTitle") or body.get("month") or "9")
    clean_m = "".join(filter(str.isdigit, month)) or "9"
    payload = SendPayslipEmailRequest(staff_name=staff_name, month=clean_m)
    return await api_send_payslip_email(payload, request)


@app.post("/api/danh-gia")
async def legacy_danh_gia(request: Request):
    from routers.fnb_ops import proxy_eval_webhook
    return await proxy_eval_webhook(request)


@app.get("/api/store-config")
@app.get("/api/v1/store-config")
async def legacy_store_config(request: Request):
    from routers.fnb_ops import get_store_configuration
    return get_store_configuration(request)


@app.post("/store/test-telegram")
async def root_store_test_telegram(request: Request):
    from routers.fnb_ops import test_telegram_notification
    try:
        body = await request.json()
    except Exception:
        body = {}
    return test_telegram_notification(request, body)


@app.get("/system/update-status")
async def root_system_update_status(request: Request):
    from routers.fnb_ops import get_system_update_status
    return await get_system_update_status(request)


@app.post("/system/check-update")
async def root_system_check_update(request: Request):
    from routers.fnb_ops import check_system_update
    return await check_system_update(request)


@app.post("/system/apply-update")
async def root_system_apply_update(request: Request):
    from routers.fnb_ops import apply_system_update
    return await apply_system_update(request)


@app.post("/system/auto-update-toggle")
async def root_system_auto_update_toggle(request: Request):
    from routers.fnb_ops import toggle_auto_update, AutoUpdateTogglePayload
    try:
        data = await request.json()
        payload = AutoUpdateTogglePayload(**data)
    except Exception:
        payload = AutoUpdateTogglePayload(enabled=True)
    return await toggle_auto_update(payload, request)


@app.get("/system/installers-info")
async def root_system_installers_info():
    from routers.fnb_ops import get_installers_info
    return await get_installers_info()


@app.get("/system/download-installer/{target_os}")
async def root_system_download_installer(target_os: str):
    from routers.fnb_ops import download_installer
    return await download_installer(target_os)






cors_origins = [
    "http://localhost:8100", 
    "http://127.0.0.1:8100",
    "http://localhost:8108",
    "http://127.0.0.1:8108",
    "http://localhost:8000",
    "http://127.0.0.1:8000"
]
if os.getenv("CORS_ORIGINS"):
    for o in os.getenv("CORS_ORIGINS", "").split(","):
        if o.strip():
            cors_origins.append(o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|.*\.local)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import os
from fastapi.staticfiles import StaticFiles

app.include_router(fnb_ops.router)
app.include_router(attendance.router)
app.include_router(roster.router)
app.include_router(pos_closing.router)
app.include_router(notification_routes.router)
app.include_router(push_routes.router)
app.include_router(push_routes.alias_router)
app.include_router(excel_routes.router)

_frontend_dir = os.path.realpath(
    os.getenv("FRONTEND_DIR")
    or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
)


def _get_dynamic_store_name() -> str:
    try:
        try:
            from services.store_config import get_store_config
        except ImportError:
            from backend.services.store_config import get_store_config
        cfg = get_store_config()
        return (cfg.get("store_name") or "FnBOps Store Lounge").strip()
    except Exception:
        return "FnBOps Store Lounge"


@app.get("/manifest.json")
def dynamic_web_manifest():
    store_name = _get_dynamic_store_name()
    manifest_data = {
        "name": store_name,
        "short_name": store_name,
        "description": f"{store_name} - Hệ thống Chấm Công, Phân Ca & Kết Ca",
        "start_url": "/?pwa=1",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#FAF7F2",
        "theme_color": "#FAF7F2",
        "icons": [
            {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": "/icons/favicon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}
        ]
    }
    return JSONResponse(content=manifest_data, media_type="application/manifest+json")


@app.get("/")
@app.get("/index.html")
def serve_pwa_index():
    from starlette.responses import HTMLResponse
    import html as html_lib
    index_path = os.path.join(_frontend_dir, "index.html")
    if not os.path.exists(index_path):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    with open(index_path, "r", encoding="utf-8") as f:
        raw_html = f.read()
    safe_name = html_lib.escape(_get_dynamic_store_name(), quote=True)
    raw_html = raw_html.replace("__DYNAMIC_STORE_NAME__", safe_name)
    return HTMLResponse(content=raw_html)


@app.get("/v2.html")
@app.head("/v2.html")
def redirect_v2_to_root():
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/", status_code=301)



if os.path.exists(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True, follow_symlink=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    raw_port = os.getenv("FASTAPI_PORT") or os.getenv("PORT") or "8100"
    if str(raw_port) == "8005":
        raw_port = "8100"
    listen_port = int(raw_port)
    listen_host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run(app, host=listen_host, port=listen_port)

