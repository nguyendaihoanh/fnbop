#!/usr/bin/env python3
"""
FnBOps Native macOS Launcher
Uses pywebview (WKWebView) for native window + uvicorn in background thread.
Bundled by PyInstaller into self-contained .app.
"""
import os
import sys
import shutil
import socket
import threading
import time
import webview  # Import early before any os.chdir() calls


def get_data_dir():
    """Create and return the persistent user data directory."""
    if sys.platform == "darwin":
        data_home = os.path.expanduser("~/Library/Application Support/FnBOps")
    else:
        data_home = os.path.expanduser("~/.fnbops")
    os.makedirs(os.path.join(data_home, "data", "logs"), exist_ok=True)
    os.makedirs(os.path.join(data_home, "data", "backups"), exist_ok=True)
    os.makedirs(os.path.join(data_home, "data", "outbox", "pdf"), exist_ok=True)
    return data_home


def get_app_source():
    """Get the bundled app source directory."""
    if getattr(sys, "frozen", False):
        # Running inside PyInstaller bundle
        return os.path.join(sys._MEIPASS, "app")
    else:
        # Running from source (dev mode)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def seed_first_run(app_source, data_home):
    """Copy seed config files on first run."""
    seeds = [
        ("data/store_config.json", "data/store_config.json"),
        ("data/staff_auth.json", "data/staff_auth.json"),
        ("data/data.json", "data/data.json"),
        (".env.example", ".env"),
    ]
    for src_rel, dst_rel in seeds:
        src = os.path.join(app_source, src_rel)
        dst = os.path.join(data_home, dst_rel)
        if not os.path.exists(dst) and os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def find_free_port():
    """Find a free port, preferring 8100."""
    for port in [8100, 8101, 8102, 8200, 0]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                chosen = s.getsockname()[1]
                return chosen
        except OSError:
            continue
    return 8100  # fallback


def start_server(app_source, data_home, port):
    """Start FastAPI/uvicorn server in a background thread."""
    # Set environment BEFORE importing backend
    os.environ["DATA_DIR"] = os.path.join(data_home, "data")
    os.environ["OUTBOX_DIR"] = os.path.join(data_home, "data", "outbox")
    os.environ["DATABASE_PATH"] = os.path.join(data_home, "data", "fnbop.db")
    os.environ["ON_PREMISE_MODE"] = "true"
    os.environ["FASTAPI_PORT"] = str(port)

    # Inject app source into Python path so backend modules resolve
    if app_source not in sys.path:
        sys.path.insert(0, app_source)
    backend_path = os.path.join(app_source, "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    # Change working directory inside thread only
    os.chdir(data_home)

    import uvicorn
    from backend.main import app

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    server.run()


def main():
    data_home = get_data_dir()
    app_source = get_app_source()
    seed_first_run(app_source, data_home)

    port = find_free_port()

    # Start server in background
    server_thread = threading.Thread(
        target=start_server,
        args=(app_source, data_home, port),
        daemon=True,
    )
    server_thread.start()

    # Wait for server to be ready (max 30 seconds)
    import urllib.request

    url = f"http://127.0.0.1:{port}/api/v1/main/ping"
    for _ in range(60):
        try:
            resp = urllib.request.urlopen(url, timeout=1)
            if resp.status == 200:
                break
        except Exception:
            time.sleep(0.5)

    # Create native window using pywebview (WKWebView on macOS)
    window = webview.create_window(
        "FnBOps — F&B Workforce OS",
        f"http://127.0.0.1:{port}",
        width=1280,
        height=860,
        min_size=(800, 600),
    )
    webview.start()
    # When window is closed, the daemon thread auto-terminates


if __name__ == "__main__":
    main()
