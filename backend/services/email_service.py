# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
# Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
"""
FnBOps - Email Service & Smart Outbox Queue
Uses standard library `smtplib` and `email.mime` (zero 3rd-party dependencies).
Supports asynchronous email sending via `asyncio.to_thread`.
Includes an intelligent dry-run Outbox engine: if SMTP is unconfigured or unavailable,
PDF attachments are automatically stored in `data/outbox/pdf/` and logged in `data/outbox/email_log.json`.
"""

import os
import ssl
import time
import uuid
import smtplib
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate, make_msgid

logger = logging.getLogger("email_service")

# ---------------------------------------------------------------------------
# Path Resolution
# ---------------------------------------------------------------------------

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_CURRENT_DIR)
_PROJECT_DIR = os.path.dirname(_BACKEND_DIR)

if os.getenv("OUTBOX_DIR"):
    OUTBOX_DIR = os.getenv("OUTBOX_DIR")
elif os.getenv("DATA_DIR"):
    DATA_DIR = os.getenv("DATA_DIR")
    OUTBOX_DIR = os.path.join(DATA_DIR, "outbox")
elif os.path.exists(os.path.join(_PROJECT_DIR, "data")):
    DATA_DIR = os.path.join(_PROJECT_DIR, "data")
    OUTBOX_DIR = os.path.join(DATA_DIR, "outbox")
elif os.path.exists(os.path.join(_BACKEND_DIR, "data")):
    DATA_DIR = os.path.join(_BACKEND_DIR, "data")
    OUTBOX_DIR = os.path.join(DATA_DIR, "outbox")
else:
    DATA_DIR = os.path.join(_PROJECT_DIR, "data")
    OUTBOX_DIR = os.path.join(DATA_DIR, "outbox")

OUTBOX_PDF_DIR = os.getenv("OUTBOX_PDF_DIR") or os.path.join(OUTBOX_DIR, "pdf")
EMAIL_LOG_FILE = os.getenv("EMAIL_LOG_FILE") or os.path.join(OUTBOX_DIR, "email_log.json")

try:
    os.makedirs(OUTBOX_PDF_DIR, exist_ok=True)
except Exception:
    pass



# ---------------------------------------------------------------------------
# Safe Storage Integration
# ---------------------------------------------------------------------------

def _load_email_logs() -> List[Dict[str, Any]]:
    """Loads email logs from JSON file with concurrency safety."""
    try:
        from backend.services.storage import safe_json_read
        return safe_json_read(EMAIL_LOG_FILE, default=[])
    except Exception:
        try:
            from services.storage import safe_json_read
            return safe_json_read(EMAIL_LOG_FILE, default=[])
        except Exception:
            pass

    import json
    if not os.path.exists(EMAIL_LOG_FILE):
        return []
    try:
        with open(EMAIL_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"Error loading {EMAIL_LOG_FILE}: {e}")
        return []


def _save_email_logs(logs: List[Dict[str, Any]]) -> bool:
    """Saves email logs to JSON file with process safety."""
    try:
        from backend.services.storage import safe_json_write
        return safe_json_write(EMAIL_LOG_FILE, logs)
    except Exception:
        try:
            from services.storage import safe_json_write
            return safe_json_write(EMAIL_LOG_FILE, logs)
        except Exception:
            pass

    import json
    try:
        os.makedirs(os.path.dirname(EMAIL_LOG_FILE), exist_ok=True)
        tmp_path = f"{EMAIL_LOG_FILE}.tmp.{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, EMAIL_LOG_FILE)
        return True
    except Exception as e:
        logger.error(f"Error saving {EMAIL_LOG_FILE}: {e}")
        return False


def _sanitize_filename(name: str) -> str:
    """Removes path traversal and non-safe characters from attachment filename."""
    base = os.path.basename(name).strip()
    import re
    cleaned = re.sub(r"[^a-zA-Z0-9._\-]", "_", base)
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return cleaned


# ---------------------------------------------------------------------------
# Core SMTP & Outbox Logic
# ---------------------------------------------------------------------------

def get_smtp_config() -> Dict[str, Any]:
    """Retrieves current SMTP configuration from environment variables."""
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASS", "").strip(),
        "from_addr": os.getenv("SMTP_FROM", "FnBOps <noreply@fnbops.local>").strip(),
        "use_tls": os.getenv("SMTP_TLS", "true").lower() in ("true", "1", "yes")
    }


def _save_to_outbox(
    to_email: str,
    subject: str,
    body_text: str,
    pdf_bytes: bytes,
    filename: str,
    status_tag: str = "queued_outbox",
    note: str = ""
) -> Dict[str, Any]:
    """
    Saves PDF file to data/outbox/pdf and appends record to email_log.json.
    Guarantees that files are never lost during dry-run or network outage.
    """
    os.makedirs(OUTBOX_PDF_DIR, exist_ok=True)
    clean_fn = _sanitize_filename(filename)
    
    # Avoid collisions if file already exists with same name
    target_path = os.path.join(OUTBOX_PDF_DIR, clean_fn)
    if os.path.exists(target_path):
        ts_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_part, ext = os.path.splitext(clean_fn)
        clean_fn = f"{name_part}_{ts_suffix}{ext}"
        target_path = os.path.join(OUTBOX_PDF_DIR, clean_fn)

    with open(target_path, "wb") as f:
        f.write(pdf_bytes)

    log_id = f"outbox_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    record = {
        "id": log_id,
        "to_email": to_email,
        "subject": subject,
        "body_preview": (body_text[:120] + "...") if len(body_text) > 120 else body_text,
        "filename": clean_fn,
        "path": target_path,
        "size_bytes": len(pdf_bytes),
        "status": status_tag,
        "note": note,
        "created_at": datetime.now().isoformat()
    }

    logs = _load_email_logs()
    logs.insert(0, record)
    _save_email_logs(logs)

    return {
        "status": status_tag,
        "message": note or "SMTP credentials not configured. Saved to outbox for dry-run/preview.",
        "to_email": to_email,
        "subject": subject,
        "filename": clean_fn,
        "path": target_path,
        "size_bytes": len(pdf_bytes),
        "id": log_id,
        "created_at": record["created_at"]
    }


def send_email_with_pdf_sync(
    to_email: str,
    subject: str,
    body_text: str,
    pdf_bytes: bytes,
    filename: str,
    is_html: bool = False
) -> Dict[str, Any]:
    """
    Synchronous implementation of sending an email with a PDF attachment.
    If SMTP credentials are not configured, automatically routes to Outbox dry-run.
    If sending fails due to network/auth error, falls back to Outbox safely.
    """
    cfg = get_smtp_config()

    # Dry-run check: If user or pass is blank, save to outbox immediately
    if not cfg["user"] or not cfg["password"]:
        logger.info(f"SMTP credentials missing. Redirecting email for '{to_email}' to outbox.")
        return _save_to_outbox(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            pdf_bytes=pdf_bytes,
            filename=filename,
            status_tag="queued_outbox",
            note="SMTP credentials not configured. Saved to outbox for dry-run/preview."
        )

    # Prepare MIME Message
    clean_fn = _sanitize_filename(filename)
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"] or cfg["user"]
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    # Body part
    body_part = MIMEText(body_text, "html" if is_html else "plain", "utf-8")
    msg.attach(body_part)

    # PDF Attachment part
    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=clean_fn)
    msg.attach(attachment)

    try:
        if cfg["port"] == 465:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=20)
        else:
            server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=20)
            server.ehlo()
            if cfg["use_tls"]:
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.ehlo()

        server.login(cfg["user"], cfg["password"])
        server.send_message(msg)
        server.quit()

        # Log successful delivery
        log_id = f"sent_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        record = {
            "id": log_id,
            "to_email": to_email,
            "subject": subject,
            "body_preview": (body_text[:120] + "...") if len(body_text) > 120 else body_text,
            "filename": clean_fn,
            "path": "",
            "size_bytes": len(pdf_bytes),
            "status": "sent",
            "note": f"Delivered via {cfg['host']}:{cfg['port']}",
            "created_at": datetime.now().isoformat()
        }
        logs = _load_email_logs()
        logs.insert(0, record)
        _save_email_logs(logs)

        return {
            "status": "sent",
            "message": f"Email successfully sent to {to_email}",
            "to_email": to_email,
            "subject": subject,
            "filename": clean_fn,
            "size_bytes": len(pdf_bytes),
            "id": log_id,
            "created_at": record["created_at"]
        }

    except Exception as exc:
        err_msg = f"SMTP error ({type(exc).__name__}): {exc}"
        logger.error(f"Failed to send email to {to_email}. Fallback to outbox. {err_msg}")
        return _save_to_outbox(
            to_email=to_email,
            subject=subject,
            body_text=body_text,
            pdf_bytes=pdf_bytes,
            filename=filename,
            status_tag="queued_outbox_fallback",
            note=err_msg
        )


async def send_email_with_pdf(
    to_email: str,
    subject: str,
    body_text: str,
    pdf_bytes: bytes,
    filename: str,
    is_html: bool = False
) -> Dict[str, Any]:
    """
    Asynchronous non-blocking wrapper for send_email_with_pdf_sync.
    Offloads blocking network/file I/O to a background thread pool via asyncio.to_thread.
    """
    return await asyncio.to_thread(
        send_email_with_pdf_sync,
        to_email,
        subject,
        body_text,
        pdf_bytes,
        filename,
        is_html
    )


# ---------------------------------------------------------------------------
# Outbox Queries & Inspection
# ---------------------------------------------------------------------------

def list_outbox_records() -> List[Dict[str, Any]]:
    """Returns the history of outbox emails and dry-run dispatches."""
    return _load_email_logs()


def get_outbox_pdf_file(filename: str) -> Optional[str]:
    """Returns the absolute path to an outbox PDF if it exists on disk."""
    clean_fn = _sanitize_filename(filename)
    path = os.path.join(OUTBOX_PDF_DIR, clean_fn)
    return path if os.path.exists(path) else None


def clear_outbox_data(keep_logs: bool = False) -> Dict[str, Any]:
    """Cleans up outbox pdfs and optionally clears email_log.json."""
    removed_files = 0
    if os.path.exists(OUTBOX_PDF_DIR):
        for f in os.listdir(OUTBOX_PDF_DIR):
            if f.endswith(".pdf"):
                try:
                    os.remove(os.path.join(OUTBOX_PDF_DIR, f))
                    removed_files += 1
                except Exception:
                    pass
    if not keep_logs:
        _save_email_logs([])
    return {"success": True, "removed_files": removed_files}
