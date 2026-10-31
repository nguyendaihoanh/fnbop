# -*- mode: python ; coding: utf-8 -*-
"""
FnBOps PyInstaller Spec — macOS Native App Bundle
Packages Python + FastAPI + pywebview into self-contained FnBOps.app
"""
import os
import sys

block_cipher = None
PROJECT_ROOT = os.path.dirname(os.path.abspath(SPEC))

def collect_clean_tree(src_dir, dst_prefix):
    items = []
    skip_dirs = {'node_modules', '__pycache__', '.git', '.pytest_cache', 'backups', 'logs', 'outbox', 'zalo_session'}
    skip_exts = {'.pyc', '.pyo', '.db', '.db-shm', '.db-wal', '.log', '.lock', '.bak', '.map'}
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in files:
            if any(fn.endswith(ext) for ext in skip_exts) or fn == '.DS_Store':
                continue
            full_src = os.path.join(root, fn)
            rel_dir = os.path.relpath(root, src_dir)
            target_dir = dst_prefix if rel_dir == '.' else os.path.join(dst_prefix, rel_dir)
            items.append((full_src, target_dir))
    return items

a = Analysis(
    [os.path.join(PROJECT_ROOT, 'scripts', 'app_launcher.py')],
    pathex=[PROJECT_ROOT, os.path.join(PROJECT_ROOT, 'backend')],
    binaries=[],
    datas=(
        collect_clean_tree(os.path.join(PROJECT_ROOT, 'backend'), os.path.join('app', 'backend'))
        + collect_clean_tree(os.path.join(PROJECT_ROOT, 'frontend'), os.path.join('app', 'frontend'))
        + [
            (os.path.join(PROJECT_ROOT, 'data', 'store_config.json'), os.path.join('app', 'data')),
            (os.path.join(PROJECT_ROOT, 'data', 'staff_auth.json'), os.path.join('app', 'data')),
            (os.path.join(PROJECT_ROOT, 'data', 'data.json'), os.path.join('app', 'data')),
            (os.path.join(PROJECT_ROOT, 'data', 'sop_templates.json'), os.path.join('app', 'data')),
            (os.path.join(PROJECT_ROOT, '.env.example'), 'app'),
        ]
    ),
    hiddenimports=[
        # FastAPI / Starlette / Uvicorn core
        'fastapi',
        'fastapi.applications',
        'fastapi.routing',
        'fastapi.staticfiles',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.responses',
        'fastapi.security',
        'starlette',
        'starlette.applications',
        'starlette.routing',
        'starlette.middleware',
        'starlette.staticfiles',
        'starlette.responses',
        'starlette.websockets',
        'starlette.formparsers',
        'uvicorn',
        'uvicorn.config',
        'uvicorn.main',
        'uvicorn.server',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        # Pydantic
        'pydantic',
        'pydantic.fields',
        'pydantic._internal',
        'pydantic._internal._core_utils',
        'pydantic._internal._validators',
        'pydantic._internal._generate_schema',
        'pydantic_core',
        'annotated_types',
        # Backend routers
        'backend.routers',
        'backend.routers.fnb_ops',
        'backend.routers.attendance',
        'backend.routers.roster',
        'backend.routers.payroll',
        'backend.routers.pos_closing',
        'backend.routers.staff',
        'backend.routers.excel_routes',
        'backend.routers.evaluation',
        'backend.routers.disbursement',
        'backend.routers.health',
        'backend.routers.notification',
        'backend.routers.notification_routes',
        'backend.routers.push_routes',
        # Backend services
        'backend.services',
        'backend.services.auth',
        'backend.services.storage',
        'backend.services.store_config',
        'backend.services.payroll_calc',
        'backend.services.roster_engine',
        'backend.services.roster_service',
        'backend.services.attendance_service',
        'backend.services.background_worker',
        'backend.services.demo_seed',
        'backend.services.email_service',
        'backend.services.excel_manager',
        'backend.services.mdns_service',
        'backend.services.payslip_card_generator',
        'backend.services.pdf_generator',
        'backend.services.send_telegram',
        'backend.services.sop_service',
        'backend.services.updater',
        'backend.services.webpush_service',
        # Backend DB layer
        'backend.services.db',
        'backend.services.db.connection',
        'backend.services.db.schema',
        'backend.services.db.attendance_repo',
        'backend.services.db.notification_repo',
        'backend.services.db.ops_repo',
        'backend.services.db.payroll_repo',
        'backend.services.db.roster_repo',
        'backend.services.db.security_repo',
        'backend.services.db.staff_repo',
        # Backend main
        'backend.main',
        # Dependencies
        'jwt',
        'jwt.algorithms',
        'dotenv',
        'multipart',
        'openpyxl',
        'reportlab',
        'reportlab.lib',
        'reportlab.lib.pagesizes',
        'reportlab.lib.units',
        'reportlab.pdfgen',
        'reportlab.pdfgen.canvas',
        'reportlab.pdfbase',
        'reportlab.pdfbase.ttfonts',
        'reportlab.platypus',
        'PIL',
        'PIL.Image',
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'certifi',
        'filelock',
        'pywebpush',
        'requests',
        # SQLite (builtin but ensure bundled)
        'sqlite3',
        # pywebview native backend
        'webview',
        'webview.platforms',
        'webview.platforms.cocoa',
        # Standard lib needed
        'json',
        'csv',
        'email',
        'email.mime',
        'email.mime.text',
        'email.mime.multipart',
        'email.mime.base',
        'decimal',
        'fractions',
        'statistics',
        'multiprocessing',
        'concurrent.futures',
        # h11 (uvicorn HTTP parser)
        'h11',
        'h11._connection',
        'h11._events',
        'h11._state',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
        'unittest',
        'pytest',
        'setuptools',
        'pip',
        'distutils',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FnBOps',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    console=False,  # No terminal window
    target_arch='arm64',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,
    name='FnBOps',
)

app = BUNDLE(
    coll,
    name='FnBOps.app',
    icon=os.path.join(PROJECT_ROOT, 'frontend', 'icons', 'icon-512.png'),
    bundle_identifier='com.vnaigc.fnbops',
    info_plist={
        'CFBundleName': 'FnBOps',
        'CFBundleDisplayName': 'FnBOps — F&B Workforce OS',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '12.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.business',
    },
)
