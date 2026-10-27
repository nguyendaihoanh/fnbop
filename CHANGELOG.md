# Changelog

All notable changes to **FnBOps** (`fnbop`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-29

### Added
- **Core Architecture:**
  - Standalone local-first SQLite 3 backend with Write-Ahead Logging (`WAL`), `busy_timeout = 30000ms`, and single-file database (`data/fnbop.db`).
  - FastAPI RESTful API v1 with 112 audited endpoints and strict route contracts.
  - Multi-tenant physical database isolation (`data/tenants/{tenant_id}.db`) and LRU connection pooling.
- **Attendance & Operations:**
  - WiFi Geofenced 1-Touch Attendance with access point BSSID verification and anti-remote punch detection.
  - POS cash closing reconciliation with thermal receipt raw socket printing (TCP port 9100 / ESC/POS) and RJ11 cash drawer kick pulses.
- **Smart Shift Roster Engine:**
  - Conflict-free automated scheduling using Minimum Remaining Values (MRV) heuristic and Kuhn's Augmenting Path algorithm (BFS depth 4).
  - 64-bit integer bitmasks for anti-clopening, skill coverage, and fair-share quota enforcement.
  - Two-step peer shift swap with manager approval workflow and auto-publish deadline enforcement (`threading.RLock`).
- **Payroll & Accounting:**
  - Append-only immutable payroll ledger (`so_cai_luong`) backed by SQLite triggers blocking direct `UPDATE` and `DELETE`.
  - Idempotent accounting entries with `idempotency_key` deduplication.
  - Integer VND arithmetic, progressive late fee rules, and 50% deduction safety cap.
  - High-res 1080x1440 dark luxury payslip PNG cards, VietQR dynamic payment codes, and A5 PDF export with bundled Inter fonts.
- **Frontend & PWA:**
  - Offline-capable Mobile PWA and Desktop Executive Dashboard (1440x900) built with vanilla ES Modules and bundled via esbuild.
  - Full bilingual support (Vietnamese & English) with modular i18n locales.
  - Solar Icons bundled offline with zero external CDN dependencies.
- **Legal & Governance:**
  - GNU Affero General Public License v3.0 (`AGPL-3.0-only`) with verbatim `LICENSE`.
  - Comprehensive `NOTICE` file specifying Section 7 additional terms (attribution, modified version marking, and trademark reservation).
  - Bilingual `COMMERCIAL_LICENSE.md` and `TRADEMARKS.md` for dual-licensing governance and Vietnam Intellectual Property Law compliance.
  - `llms.txt` and `AGENTS.md` for autonomous developer agent navigation.
