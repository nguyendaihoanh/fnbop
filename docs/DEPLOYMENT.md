# FnBOps Deployment & Hardware Integration Guide

## 1. Deployment Topologies

FnBOps supports three deployment modes on port **`8100`**:
1. **1-Click Standalone Desktop / POS:** Run directly via [`run_windows.bat`](../run_windows.bat) on Windows or [`run_mac.command`](../run_mac.command) on macOS.
2. **24/7 Background Service (Windows POS / Linux Systemd):** Managed as an OS service using `nssm.exe` on Windows or `systemd` on Linux.
3. **Docker Compose Stack:** Containerized deployment with FastAPI (`:8100`), Nginx/Caddy reverse proxy, and optional Zalo Gateway (`:8177`).

---

## 2. Standalone & Windows POS Service Deployment

### 2.1. 1-Click Native Run
- **Windows:** Double-click `run_windows.bat`. The launcher automatically detects either `.venv` or an embedded portable Python runtime (`python_runtime\python.exe`), installs missing packages from `requirements.txt`, initializes `.env` with a 256-bit `JWT_SECRET_KEY`, and starts Uvicorn on `http://localhost:8100`.
- **macOS:** Double-click `run_mac.command`.

### 2.2. Installing as a 24/7 Windows POS Service (`nssm.exe`)
For dedicated store POS terminals using portable Python (`python_runtime\python.exe`):
```cmd
nssm.exe install FnBOpsPOS "C:\FnBOps\python_runtime\python.exe"
nssm.exe set FnBOpsPOS AppDirectory "C:\FnBOps"
nssm.exe set FnBOpsPOS AppParameters "-m uvicorn backend.main:app --host 0.0.0.0 --port 8100"
nssm.exe set FnBOpsPOS AppEnvironmentExtra ON_PREMISE_MODE=true PYTHONPATH=C:\FnBOps;C:\FnBOps\backend PYTHONIOENCODING=utf-8 PYTHONUTF8=1
nssm.exe start FnBOpsPOS
```
Verify service health:
```bash
curl http://localhost:8100/health
# Expected: {"status":"ok","service":"fnbops_backend"}
```

---

## 3. Docker Compose Deployment

```bash
# 1. Start stack (auto-generates .env if not present)
docker compose up -d --build

# 2. Check container status and health
docker compose ps
curl http://localhost:8100/health
```

### Core Environment Variables (`.env`)
| Variable | Description | Default |
| :--- | :--- | :--- |
| `JWT_SECRET_KEY` | 256-bit HS256 signing key (auto-generated on first boot if absent) | Auto-generated (64 hex chars) |
| `ON_PREMISE_MODE` | Enables local LAN/POS mode without Cloudflare header enforcement | `true` (local) / `false` (cloud) |
| `DATA_DIR` | Directory containing `fnbop.db` and runtime configs | `./data` |
| `ZALO_GATEWAY_URL` | Optional Zalo microservice endpoint | `http://127.0.0.1:8177` |
| `ENABLE_API_DOCS` | Expose Swagger UI at `/docs` | `false` |

---

## 4. POS Hardware & Network Integration

### 4.1. ESC/POS Thermal Receipt Printers (LAN Port `9100` & USB)
- **LAN RAW Socket:** Configure thermal printers (Epson, Xprinter, Star, Birch K80/K58) with a static LAN IP (e.g., `192.168.1.200`) listening on TCP port `9100`.
- **Connectivity Test:**
  ```bash
  nc -zv 192.168.1.200 9100
  ```

### 4.2. RJ11 Cash Drawer Kick-Out Pulse
Cash drawers connect to the thermal printer's **DK (Drawer Kick) RJ11 port**. To trigger the 24V solenoid pulse on Pin 2 (`ESC p 0 25 250`):
- **Hex Payload:** `1B 70 00 19 FA` (`b"\x1b\x70\x00\x19\xfa"`)
- **Pin 5 Fallback:** `1B 70 01 19 FA` (`b"\x1b\x70\x01\x19\xfa"`)

### 4.3. Store WiFi Geofence & Local mDNS
- **WAN IP & BSSID Verification:** Staff check-in validates client IP against the store's WAN IP / LAN subnet and optional Access Point BSSID whitelist configured in Store Settings.
- **Local mDNS Discovery:** On LAN networks, `backend/services/mdns_service.py` broadcasts Zeroconf mDNS on port `8100` so staff devices on store WiFi can access the POS directly.

---

## 5. Database Backup & Recovery (`data/fnbop.db`)

FnBOps stores all operational data in `data/fnbop.db` (SQLite WAL mode). To create a hot, ACID-safe backup without stopping the server:
```bash
python3 scripts/backup_production_data.py
```
On-demand JSON state snapshots can also be exported via `python3 scripts/export_sqlite_snapshot.py` into `data/snapshots/`.
