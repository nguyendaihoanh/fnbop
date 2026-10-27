# ==============================================================================
# FNBOPS - PRODUCTION MULTI-STAGE DOCKERFILE
# Python 3.12-slim runtime, non-root appuser, zero-dependency SQLite WAL
# ==============================================================================

# Stage 1: Build dependencies & virtual environment
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Minimalist, hardened production runner
FROM python:3.12-slim-bookworm AS runner

LABEL org.opencontainers.image.title="FnBOps Workforce & Store Operations OS" \
      org.opencontainers.image.vendor="Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.source="https://github.com/nguyendaihoanh/fnbop"

WORKDIR /app

# Create non-privileged service user and grant ownership of /app & /data
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser && \
    mkdir -p /data && chown -R appuser:appgroup /app /data

# Copy compiled python wheels/dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/backend:/app

# Copy application source code
COPY --chown=appuser:appgroup backend /app/backend
COPY --chown=appuser:appgroup frontend /app/frontend
COPY --chown=appuser:appgroup data /app/data
COPY --chown=appuser:appgroup pyproject.toml .env.example LICENSE THIRD_PARTY_NOTICES.md /app/

USER appuser

EXPOSE 8100

HEALTHCHECK --interval=20s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/health')" || exit 1

CMD ["python3", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8100"]
