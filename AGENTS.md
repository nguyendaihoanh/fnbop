# AGENTS.md — Developer & AI Agent Architecture Guide

> **Quick Context for AI Agents & Engineers:** Read this file first before modifying code, running tests, or deploying `fnbop`.

---

## 1. System Overview & Tech Stack

- **Purpose:** Open-source F&B Workforce Management (WFM), 1-Touch Attendance, AI Shift Roster, POS Cash Closing, and Immutable Payroll OS.
- **Backend (`:8100`):** Python 3.11+ / FastAPI (`backend/main.py`), Uvicorn, Pydantic v2.
- **Primary Database:** SQLite 3 in Write-Ahead Logging (`WAL`) mode at **`data/fnbop.db`** (`busy_timeout = 30000ms`, `synchronous = NORMAL`).
- **Frontend PWA:** Vanilla ES Modules (`frontend/index.html`, `frontend/desktop.html`, `frontend/mobile.js`, `frontend/app.js`, `frontend/src/`), bundled via `node frontend/build.js` (`esbuild`).
- **Zalo Gateway (`:8177`):** Optional Node.js 18+ microservice (`backend/zalo_gateway/server.js`) for dispatching private payslip cards.

---

## 2. Repository Directory Map

```text
fnbop/
├── AGENTS.md                  # AI Agent & Developer technical guide (this file)
├── .cursorrules               # Strict Frontend UI/UX, Solar Icons & CSS token rules
├── README.md                  # Bilingual (EN/VI) project overview & quickstart
├── run_mac.command            # 1-Click macOS native launcher (auto venv + pip + browser)
├── run_windows.bat            # 1-Click Windows POS launcher (supports .venv & python_runtime)
├── backend/
│   ├── main.py                # FastAPI application entrypoint, middleware & lifespan worker
│   ├── routers/               # REST API routers (fnb_ops, attendance, roster, pos_closing, excel_routes...)
│   ├── services/
│   │   ├── db/                # Modular SQLite WAL DAL (base, connection, schema, *_repo.py)
│   │   ├── auth.py            # PBKDF2 PIN hashing, JWT HS256, token_version & .env auto-bootstrap
│   │   ├── payroll_calc.py    # Integer VND payroll calculation, OT buffer & progressive late rules
│   │   ├── roster_engine.py   # MRV heuristic + Kuhn's Augmenting Path (BFS-4) + 64-bit bitmask
│   │   ├── store_config.py    # Dynamic shift definitions & store configuration
│   │   └── storage.py         # Safe atomic file I/O & server-side shift computation
│   └── zalo_gateway/          # Optional Node.js Zalo messaging service (:8177)
├── frontend/
│   ├── index.html             # Mobile-first PWA interface (Staff, Manager, Admin)
│   ├── desktop.html           # Desktop Management Dashboard (1440x900 executive view)
│   ├── src/                   # Modular JS (i18n VI/EN, state store, UI modules)
│   ├── sop/                   # Role-based markdown checklists rendered in-app
│   └── vendor/                # Offline-bundled Solar Icons (zero external CDN dependency)
├── data/
│   ├── fnbop.db               # Canonical SQLite WAL database (Single Source of Truth)
│   ├── staff_auth.json        # Starter seed for 4 canonical accounts
│   ├── store_config.json      # Default store shift & policy configuration
│   └── data.json              # Minimal starter seed template
├── docs/
│   ├── ARCHITECTURE.md        # System architecture, database schema & core algorithms
│   ├── API.md                 # RESTful API v1 endpoint reference
│   └── DEPLOYMENT.md          # Standalone POS, Windows Service (NSSM), Docker & Hardware guide
├── scripts/                   # Quality gates, SQLite backup & maintenance scripts
└── tests/                     # 440+ automated pytest & E2E verification tests
    └── conftest.py            # Isolated sandbox fixtures (never mutates live data/fnbop.db)
```

---

## 3. Canonical Starter Accounts (4 Roles)

| Role | Username | Default PIN | Scope |
| :--- | :--- | :--- | :--- |
| **Store Owner (Admin)** | `admin` | `1234` | Full system config, staff management, payroll lock, ledger & audit |
| **Shift Manager** | `manager` | `8888` | Weekly roster generation, OT approval, peer-swap & attendance ops |
| **Barista** | `phache` | `2222` | Bar check-in/out, shift registration & personal payslip |
| **Floor Staff** | `nhanvien` | `1111` | Service check-in/out, shift registration & personal payslip |

---

## 4. Core Architectural & Security Invariants

1. **Database-First (`data/fnbop.db`):** All runtime mutations (attendance, roster, ledger, closings, evaluations, lockouts) are persisted in SQLite WAL (`data/fnbop.db`). Never introduce dual-write JSON side effects or hardcoded staff names.
2. **Append-Only Payroll Ledger (`so_cai_luong`):** Financial values use integer `VND` (`INTEGER`). SQLite triggers block `UPDATE` and `DELETE` on `so_cai_luong`; adjustments must use `REVERSAL` or adjustment entries.
3. **Zero-Config `.env` Auto-Bootstrap + Fail-Closed JWT:** On first startup, `ensure_bootstrap_jwt_secret()` in `backend/services/auth.py` automatically creates `.env` from `.env.example` with a random 256-bit `JWT_SECRET_KEY`. Explicitly empty `JWT_SECRET_KEY=""` raises `RuntimeError` (fail-closed).
4. **Frontend UI & i18n Rules:** Enforce `.cursorrules` strictly — no OS emojis for UI icons (use `<iconify-icon icon="solar:...">`), full bilingual `VI/EN` support (`frontend/src/i18n/`), and Light/Dark theme tokens.

---

## 5. Development, Build & Test Commands

```bash
# 0. Activate Git pre-push hook (blocks broken pushes, stale dist/ & schema drift)
bash scripts/install_git_hooks.sh

# 1. Run backend server locally (Port 8100)
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8100

# 2. Run SQL schema, OpenAPI route & launcher contract gate
PYTHONPATH=.:backend .venv/bin/python scripts/audit_schema_contracts.py

# 3. Run full automated test suite (440+ tests, sandboxed in /tmp)
PYTHONPATH=.:backend .venv/bin/pytest tests/ -q --ignore=tests/test_live_system_readiness.py

# 4. Rebuild frontend production bundle (if editing frontend/src/*, commit frontend/dist/*)
node frontend/build.js

# 5. Run full 8-tier quality gate
bash scripts/quality_gate.sh
```
