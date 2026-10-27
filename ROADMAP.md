# FnBOps Development Roadmap

**Project:** `fnbop` — Open-Source F&B Operations & Workforce Management OS  
**License:** GNU Affero General Public License v3.0 only (`AGPL-3.0-only`) + Commercial Dual-Licensing ([`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md))  
**Vision:** An edge-first, SaaS-ready operating system for coffee shops, restaurants, bars, and bakeries.

---

## 1. Phase 1: Core Foundation & Storefront Operations [COMPLETED]
- **Offline-First POS & 1-Touch Attendance:** SQLite WAL mode with physical WiFi Access Point BSSID and IP geofencing.
- **Automated Payroll Engine:** Integer arithmetic calculation, progressive late discipline, 50% deduction safety cap.
- **Thermal Payslip & Retina Card Generator:** ESC/POS, 1080x1440 PNG Card (VietQR), and A5 PDF dispatch using open-source `Inter v4.1 (SIL OFL-1.1)` fonts.
- **8-Tier Quality Gates:** Full automated regression test suite (`440+` tests) covering RBAC, concurrency, schema contracts, legal compliance, and Real Chrome Headless E2E.

---

## 2. Phase 2: SaaS Modularization & Multi-Tenant Core [COMPLETED]
- **Physical Database-per-Tenant Isolation:** Central control DB with tenant-scoped connection pools.
- **RESTful API v1 Standardization:** Unified endpoints for `/api/v1/attendance`, `/api/v1/roster`, `/api/v1/payroll`, `/api/v1/pos-closings`.
- **Heuristic MRV & Kuhn's Augmenting Path Roster Engine:** Sub-50ms conflict-free scheduling with 64-bit bitmasks.
- **Append-Only Immutable Ledgers:** Double-entry audit trails with reversal entries (`REVERSAL`).
- **Responsive Mobile PWA & Desktop Kiosk:** Dark/Light theme design token architecture.

---

## 3. Phase 3: Hardware Ecosystem & Commercial Distribution [IN PROGRESS]
- **1-Click Packaging & Distribution:**
  - Standalone macOS (`run_mac.command`) and Windows POS (`run_windows.bat`) with auto-environment bootstrap.
  - Production Docker Compose stack with Caddy automated SSL (Let's Encrypt).
- **Interactive CLI Wizard (`fnbops`):**
  - `fnbops init`: Interactive store configuration and master admin setup.
  - `fnbops seed --preset [cafe|restaurant|boba]`: Realistic demo dataset generator.
  - `fnbops backup`: Atomic online SQLite database backup.
  - `fnbops serve`: High-concurrency Uvicorn server launcher.
- **Hardware Integration Drivers:**
  - ESC/POS LAN/USB thermal receipt printers (Port 9100).
  - RJ11 cash drawer kick-out pulses (`\x1b\x70\x00\x19\xfa`).
  - Automated POS Heartbeat watchdog and WAN IP syncer.
