#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# FnBOps Oracle VPS Production Deploy & Rollback Script (Docker Compose)
# Runs on the target Oracle VPS host inside /home/ubuntu/fnbop (or DEPLOY_DIR).
# Fail-closed on missing .env, missing ALLOWED_HOSTS, weak JWT_SECRET_KEY, or dirty git tree.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DIR="$(dirname "$SCRIPT_DIR")"
DEPLOY_DIR="${DEPLOY_DIR:-$DEFAULT_DIR}"
BRANCH="${BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8100/health}"
PREV_COMMIT_FILE="${DEPLOY_DIR}/.deploy_prev_commit"
BACKUP_DIR="${DEPLOY_DIR}/data/backups"

DRY_RUN=false
ROLLBACK=false
SKIP_PULL=false

usage() {
  cat <<'EOF'
Usage: scripts/deploy_oracle.sh [OPTIONS]
  --dry-run        Validate .env preflight and print deployment actions without mutating containers
  --rollback       Roll back Git HEAD to previous recorded commit (.deploy_prev_commit) and restart
  --skip-pull      Skip git pull --ff-only (useful when invoked from CI after custom checkout)
  --branch NAME    Git branch to fast-forward pull (default: main)
  -h, --help       Show help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --rollback) ROLLBACK=true ;;
    --skip-pull) SKIP_PULL=true ;;
    --branch)
      shift
      BRANCH="${1:?Missing branch argument}"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

# Guard against accidentally overwriting shared multi-site directories
if [[ "$DEPLOY_DIR" == *"/websites/"* ]]; then
  echo "CRITICAL ERROR: Refusing deploy into shared /websites/ directory: $DEPLOY_DIR" >&2
  exit 1
fi

cd "$DEPLOY_DIR"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

read_env_var() {
  local key="$1"
  local file="$2"
  local line
  line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
  if [ -z "$line" ]; then
    return 0
  fi
  local val="${line#*=}"
  val="${val%\"}"
  val="${val#\"}"
  val="${val%\'}"
  val="${val#\'}"
  printf '%s' "$val"
}

preflight_env() {
  local env_file="${DEPLOY_DIR}/.env"
  if [ ! -f "$env_file" ]; then
    cat >&2 <<EOF
ERROR: Missing production ${env_file}.
Create it first with chmod 600 and set at minimum:
  ALLOWED_HOSTS=fnb.example.com,*.example.com
  JWT_SECRET_KEY=<64-char random hex>
  POS_SECRET=<32-char random hex>
EOF
    exit 1
  fi

  local perms
  perms="$(stat -c '%a' "$env_file" 2>/dev/null || stat -f '%Lp' "$env_file" 2>/dev/null || echo unknown)"
  if [ "$perms" != "600" ] && [ "$perms" != "unknown" ]; then
    log "WARN: ${env_file} mode is ${perms}; tightening to 600 recommended (chmod 600 .env)."
  fi

  local allowed_hosts edge_host jwt_key
  allowed_hosts="$(read_env_var "ALLOWED_HOSTS" "$env_file")"
  edge_host="$(read_env_var "EDGE_INGRESS_HOST" "$env_file")"
  jwt_key="$(read_env_var "JWT_SECRET_KEY" "$env_file")"

  if [ -z "$allowed_hosts" ] && [ -z "$edge_host" ]; then
    cat >&2 <<'EOF'
ERROR: Refusing deploy — ALLOWED_HOSTS and EDGE_INGRESS_HOST are both empty in .env.
Public Cloudflare/reverse-proxy hosts will receive HTTP 400 without ALLOWED_HOSTS!
Add e.g. ALLOWED_HOSTS=fnb.example.com,*.example.com to .env before deploying.
EOF
    exit 1
  fi

  if [ -z "$jwt_key" ] || [ "${#jwt_key}" -lt 32 ] || [[ "$jwt_key" == REPLACE_WITH* ]] || [[ "$jwt_key" == ci_test* ]]; then
    echo "ERROR: JWT_SECRET_KEY in .env is missing, placeholder, or shorter than 32 chars." >&2
    exit 1
  fi

  log "Preflight OK (.env present, ALLOWED_HOSTS configured, strong JWT_SECRET_KEY verified)."
}

backup_sqlite_db() {
  local db_file="${DEPLOY_DIR}/data/fnbop.db"
  if [ ! -f "$db_file" ]; then
    log "INFO: ${db_file} does not exist yet (first start will initialize SQLite WAL)."
    return 0
  fi

  mkdir -p "$BACKUP_DIR"
  local ts backup_target
  ts="$(date '+%Y%m%d_%H%M%S')"
  backup_target="${BACKUP_DIR}/fnbop_pre_deploy_${ts}.db"

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$db_file" "$backup_target" <<'PY'
import sqlite3, sys
src_path, dst_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path, timeout=30.0)
dst = sqlite3.connect(dst_path)
try:
    with dst:
        src.backup(dst)
finally:
    dst.close()
    src.close()
PY
    log "SQLite online backup created: ${backup_target}"
  else
    cp -a "$db_file" "$backup_target"
    log "Copied SQLite snapshot to ${backup_target} (python3 unavailable for sqlite3.backup)."
  fi
}

wait_for_health() {
  local primary_host="$1"
  local curl_args=(-fsS "$HEALTH_URL")
  if [ -n "$primary_host" ]; then
    curl_args+=(-H "Host: ${primary_host}")
  fi

  for i in $(seq 1 30); do
    if curl "${curl_args[@]}" | grep -q '"status":"ok"'; then
      log "Health check passed on attempt #${i} (${HEALTH_URL})."
      return 0
    fi
    sleep 2
  done

  log "ERROR: Health check failed after 60s on ${HEALTH_URL}!"
  docker compose logs --tail=60 fnbops-api || true
  return 1
}

perform_rollback() {
  if [ ! -f "$PREV_COMMIT_FILE" ]; then
    echo "ERROR: Cannot rollback — ${PREV_COMMIT_FILE} does not exist." >&2
    exit 1
  fi
  local prev_sha
  prev_sha="$(tr -d '[:space:]' < "$PREV_COMMIT_FILE")"
  if [ -z "$prev_sha" ]; then
    echo "ERROR: Empty previous commit SHA in ${PREV_COMMIT_FILE}." >&2
    exit 1
  fi

  log "Rolling back repository to ${prev_sha}..."
  if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] Would run: git checkout ${prev_sha} && docker compose up -d --build"
    return 0
  fi

  git checkout "$prev_sha"
  docker compose up -d --build --remove-orphans
  wait_for_health ""
  log "Rollback to ${prev_sha} completed cleanly."
}

preflight_env

if [ "$ROLLBACK" = true ]; then
  perform_rollback
  exit 0
fi

ALLOWED_HOSTS_RAW="$(read_env_var "ALLOWED_HOSTS" "${DEPLOY_DIR}/.env")"
FIRST_HOST="$(printf '%s' "$ALLOWED_HOSTS_RAW" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^\*\.' | head -n 1 || true)"
CURRENT_SHA="$(git rev-parse HEAD)"

if [ "$DRY_RUN" = true ]; then
  log "[DRY-RUN] DEPLOY_DIR=${DEPLOY_DIR}, BRANCH=${BRANCH}, CURRENT_SHA=${CURRENT_SHA}, SKIP_PULL=${SKIP_PULL}"
  log "[DRY-RUN] Would backup data/fnbop.db, pull origin/${BRANCH} --ff-only, run 'docker compose up -d --build --remove-orphans', and verify ${HEALTH_URL}."
  exit 0
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "ERROR: Tracked files in ${DEPLOY_DIR} have local modifications. Clean or stash before deploying." >&2
  git status --short --untracked-files=no >&2
  exit 1
fi

printf '%s\n' "$CURRENT_SHA" > "$PREV_COMMIT_FILE"
backup_sqlite_db

if [ "$SKIP_PULL" = false ]; then
  log "Pulling origin/${BRANCH} (fast-forward only)..."
  git pull --ff-only origin "$BRANCH"
fi

NEW_SHA="$(git rev-parse HEAD)"
log "Deploying commit ${NEW_SHA} via Docker Compose..."
docker compose up -d --build --remove-orphans

if ! wait_for_health "${FIRST_HOST:-}"; then
  log "Deploy health verification failed — initiating automatic rollback to ${CURRENT_SHA}!"
  git checkout "$CURRENT_SHA"
  docker compose up -d --build --remove-orphans
  exit 1
fi

log "Deploy complete: ${CURRENT_SHA:0:7} -> ${NEW_SHA:0:7}"
