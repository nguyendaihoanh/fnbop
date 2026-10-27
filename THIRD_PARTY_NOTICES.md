# Third-Party Notices, Open-Source Attribution & Legal Disclaimers

**Project:** FnBOps — Open-Source F&B Workforce Management & Store Operations OS  
**Copyright:** Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) `<hoanh@vnaigc.com>`  
**Primary License:** [GNU Affero General Public License v3.0 only (`AGPL-3.0-only`)](LICENSE)  
**Commercial Dual-Licensing:** Enterprise / OEM / Proprietary SaaS licenses are available directly from the copyright holder via `hoanh@vnaigc.com`.

---

## 1. Visual Assets, Typography & Offline Vendor Bundles (Mandatory Notice)

### Inter Typeface (`backend/assets/fonts/Inter-*.ttf`)
- **Author / Creator:** Rasmus Andersson & The Inter Project Authors (`https://github.com/rsms/inter`)
- **Copyright:** `Copyright (c) 2016 The Inter Project Authors`
- **License:** [SIL Open Font License, Version 1.1 (`SIL OFL-1.1`)](backend/assets/fonts/OFL.txt)
- **Usage:** Bundled static TrueType font files (`Inter-Regular.ttf`, `Inter-Bold.ttf`, `Inter-Italic.ttf`) used on-premise by `backend/services/payslip_card_generator.py` and `backend/services/pdf_generator.py` for offline Vietnamese payslip cards and PDFs without proprietary font dependencies.

### Solar Icons Set (`frontend/vendor/solar-icons-bundle.js`)
- **Author / Creator:** **480 Design**
- **Upstream Source:** [Solar Icons on Figma Community](https://www.figma.com/community/file/1166831539721848736) / [`@iconify-json/solar`](https://github.com/iconify/icon-sets)
- **License:** [Creative Commons Attribution 4.0 International (`CC BY 4.0`)](https://creativecommons.org/licenses/by/4.0/)
- **Modification / Adaptation Notice:** Pursuant to Section 3(a) of CC BY 4.0, SVG glyph paths from the Solar Icons collection were extracted and packaged into a self-contained JavaScript collection (`frontend/vendor/solar-icons-bundle.js`) to support 100% offline execution on store POS terminals without external CDN requests. No endorsement by 480 Design is implied.

### Iconify Web Component (`frontend/vendor/iconify-icon.min.js`)
- **Author:** CyberAlien / Iconify Contributors (`https://github.com/iconify/iconify`)
- **License:** `MIT` License

### Chart.js (`frontend/vendor/chart.umd.min.js`)
- **Version:** `4.4.8`
- **Author:** Chart.js Contributors (`https://www.chartjs.org`)
- **Copyright:** `(c) 2025 Chart.js Contributors`
- **License:** `MIT` License (bundled locally for 100% Zero-CDN offline execution on executive dashboards)

---

## 2. Python Backend Dependencies (`backend/` & `pyproject.toml`)

FnBOps incorporates or depends upon the following open-source Python packages, each governed by its respective upstream license:

| Package | Upstream License | Upstream Project |
| :--- | :--- | :--- |
| `fastapi` | `MIT` | https://github.com/fastapi/fastapi |
| `uvicorn` | `BSD-3-Clause` | https://github.com/encode/uvicorn |
| `pydantic` | `MIT` | https://github.com/pydantic/pydantic |
| `PyJWT` | `MIT` | https://github.com/jpadilla/pyjwt |
| `python-dotenv` | `BSD-3-Clause` | https://github.com/theskumar/python-dotenv |
| `requests` | `Apache-2.0` | https://github.com/psf/requests |
| `filelock` | `MIT` / `Unlicense` | https://github.com/tox-dev/filelock |
| `openpyxl` | `MIT` | https://foss.heptapod.net/openpyxl/openpyxl |
| `python-multipart` | `Apache-2.0` | https://github.com/Kludex/python-multipart |
| `pywebpush` | `MPL-2.0` | https://github.com/web-push-libs/pywebpush |
| `py-vapid` | `MPL-2.0` | https://github.com/web-push-libs/vapid |
| `http-ece` | `MIT` | https://github.com/martinthomson/encrypted-content-encoding |
| `httpx` | `BSD-3-Clause` | https://github.com/encode/httpx |
| `reportlab` | `BSD-3-Clause` | https://hg.reportlab.com/hg-public/reportlab |
| `pillow` | `HPND (MIT-CMU)` | https://github.com/python-pillow/Pillow |
| `cryptography` | `Apache-2.0 OR BSD-3-Clause` | https://github.com/pyca/cryptography |

*Note on `MPL-2.0` libraries (`pywebpush`, `py-vapid`): FnBOps uses these packages unmodified via standard Python package imports. Their source code remains available from their respective upstream repositories under Mozilla Public License 2.0.*

---

## 3. Optional Zalo Gateway Microservice & Build Tooling

### Optional Node.js Zalo Bridge (`backend/zalo_gateway/`)
The `backend/zalo_gateway/` microservice itself is licensed under **`AGPL-3.0-only`** (`Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC)`), and utilizes the following open-source npm packages:

| Package | Upstream License | Upstream Project |
| :--- | :--- | :--- |
| `express` | `MIT` | https://github.com/expressjs/express |
| `cors` | `MIT` | https://github.com/expressjs/cors |
| `qrcode` | `MIT` | https://github.com/soldair/node-qrcode |
| `dotenv` | `BSD-2-Clause` | https://github.com/motdotla/dotenv |
| `zca-js` | `MIT` | https://github.com/RFS-ADRENO/zca-js |

### Frontend Build & Test Tooling (`frontend/package.json`)
- `esbuild` (`MIT` — https://github.com/evanw/esbuild)
- `puppeteer-core` (`Apache-2.0` — https://github.com/puppeteer/puppeteer)

---

## 4. Trademark Policy, Third-Party Messaging (`zca-js`) & Data Protection Disclaimers

1. **Project Trademarks (`FnBOps`, `VNAIGC`):**
   - The `AGPL-3.0-only` license grants rights solely to source code copyright and patents as stated in the license text. It does **not** grant permission to use the `FnBOps` or `VNAIGC` names, logos, or trade dress to market commercial products or imply official endorsement without written permission from `Nguyen Dai Hoanh (VNAIGC)` (`hoanh@vnaigc.com`).

2. **Third-Party Trademarks & Non-Affiliation (`Zalo` / `VNG`):**
   - **"Zalo"** is a registered trademark of **VNG Corporation**. FnBOps and VNAIGC are strictly independent and are **not affiliated with, endorsed by, sponsored by, or certified by VNG Corporation or Zalo**.

3. **Unofficial Messaging Protocol Risk & Safe-Harbor (`zca-js`):**
   - `backend/zalo_gateway` is an **optional, disabled-by-default** out-of-process microservice (`:8177`). Core FnBOps operations run 100% standalone using built-in W3C VAPID Web Push, Telegram Bot API, or SMTP without requiring Zalo Gateway.
   - `zca-js` emulates personal Zalo Web sessions rather than official Zalo Cloud ZNS / Official Account (OA) APIs. Automated messaging via personal accounts may violate Zalo's Terms of Service and result in rate-limiting, verification checkpoints, or account suspension. Operators who enable this optional connector assume 100% sole responsibility and risk. For high-volume or multi-store enterprise deployments, integrating official **Zalo Cloud ZNS / Zalo OA APIs** via the standard HTTP webhook boundary (`ZALO_GATEWAY_URL`) is strongly recommended.

4. **Personal Data Protection Compliance (Vietnam Decree 13/2023/ND-CP & GDPR):**
   - FnBOps is self-hosted software; neither the authors nor VNAIGC collect, host, or process store employee data.
   - Each deploying store or enterprise acts as the **Data Controller (Bên Kiểm soát Dữ liệu Cá nhân)** and is solely responsible for obtaining lawful employee consent before transmitting payslips, attendance alerts, or personal phone numbers over third-party messaging channels.
