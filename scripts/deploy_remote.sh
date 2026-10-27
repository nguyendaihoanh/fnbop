#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# DEPLOY FNBOPS — Local Machine -> Remote Production Server
# Features: Quality Gates, Backup Rotation (5), Health Check, Rollback, Dry-run
# ==============================================================================

REMOTE_HOST="${REMOTE_HOST:-user@your-server-ip}"
WEB_DIR="${WEB_DIR:-/var/www/fnbops}"
BACKEND_DIR="${BACKEND_DIR:-/opt/fnbops/backend}"
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/etc/nginx/conf.d}"
BACKUP_BASE="${BACKUP_BASE:-/opt/fnbops/_backups}"
BACKUP_KEEP=5
PM2_PROCESS="${PM2_PROCESS:-fnbops-backend}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8100/health}"

# SAFETY SHIELD: NEVER allow deploying to shared multi-site directories (/websites/)
if [[ "$WEB_DIR" == *"/websites/"* ]] || [[ "$BACKEND_DIR" == *"/websites/"* ]]; then
  echo "CRITICAL ERROR: Deployment to shared production infrastructure (/websites/) is STRICTLY PROHIBITED!"
  echo "fnbops is an independent standalone project and must never overwrite shared server directories."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DEPLOY_LOG="$PROJECT_ROOT/deploy_history.log"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# --- Parse arguments ---
DRY_RUN=false
ROLLBACK=false
SKIP_GATES=false

for arg in "$@"; do
  case $arg in
    --dry-run)   DRY_RUN=true ;;
    --rollback)  ROLLBACK=true ;;
    --skip-gates) SKIP_GATES=true ;;
    --help)
      echo "Usage: $0 [--dry-run] [--rollback] [--skip-gates]"
      echo "  --dry-run     Show what would be deployed without actually deploying"
      echo "  --rollback    Restore from latest backup"
      echo "  --skip-gates  Skip quality gates (use with caution)"
      exit 0
      ;;
  esac
done

# --- Helper functions ---
log_deploy() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$DEPLOY_LOG"
}

remote_cmd() {
  ssh -q -o BatchMode=yes -o ConnectTimeout=10 "$REMOTE_HOST" \
    "export PATH=\$PATH:/opt/homebrew/bin:/usr/local/bin:\$HOME/.nvm/versions/node/\$(ls \$HOME/.nvm/versions/node 2>/dev/null | tail -1)/bin; $1"
}

# ==============================================================================
# ROLLBACK MODE
# ==============================================================================
if $ROLLBACK; then
  echo "=== [ROLLBACK] Restoring from latest backup ==="
  LATEST_BACKUP=$(remote_cmd "ls -1d $BACKUP_BASE/fnbops_20[0-9]* 2>/dev/null | sort | tail -1")
  if [ -z "$LATEST_BACKUP" ]; then
    echo "ERROR: No backup found in $BACKUP_BASE/"
    exit 1
  fi
  echo "Restoring from: $LATEST_BACKUP"
  remote_cmd "rsync -a --delete '$LATEST_BACKUP/frontend/' '$WEB_DIR/'"
  remote_cmd "rsync -a '$LATEST_BACKUP/backend/' '$BACKEND_DIR/'"
  remote_cmd "cp '$LATEST_BACKUP/backend/staff_auth.json' '$BACKEND_DIR/staff_auth.json' 2>/dev/null || true"
  remote_cmd "cp '$LATEST_BACKUP/backend/data/sop_templates.json' '$BACKEND_DIR/data/sop_templates.json' 2>/dev/null || true"
  remote_cmd "cp '$LATEST_BACKUP/backend/data/fnbop.db' '$BACKEND_DIR/data/fnbop.db' 2>/dev/null || true"
  remote_cmd "pm2 restart '$PM2_PROCESS' 2>/dev/null || true"
  log_deploy "ROLLBACK from $LATEST_BACKUP"
  echo "=== [ROLLBACK] Done. Verify: https://fnbops ==="
  exit 0
fi

# ==============================================================================
# DEPLOY MODE
# ==============================================================================
echo "=== [DEPLOY] fnbops — $TIMESTAMP ==="
log_deploy "DEPLOY START — dry_run=$DRY_RUN skip_gates=$SKIP_GATES"

# --- Step 0: SSH connectivity ---
echo "[0/6] Checking SSH connection..."
remote_cmd "echo 'SSH OK'" || {
  log_deploy "DEPLOY FAIL — SSH connection failed"
  echo "ERROR: Cannot connect to $REMOTE_HOST"
  exit 1
}

# --- Step 1: Quality Gates ---
if ! $SKIP_GATES; then
  echo "[1/6] Running Quality Gates..."
  "$PROJECT_ROOT/scripts/quality_gate.sh" || {
    log_deploy "DEPLOY FAIL — Quality Gates failed"
    echo "ERROR: Quality Gates failed. Fix issues before deploying."
    exit 1
  }
else
  echo "[1/6] Quality Gates SKIPPED (--skip-gates)"
fi

# --- Step 2: Drift detection ---
echo "[2/6] Detecting drift (repo vs live)..."
DRIFT_COUNT=0
for file in frontend/mobile.js frontend/app.js frontend/index.html backend/routers/attendance.py backend/routers/fnb_ops.py backend/routers/n8n_webhooks.py backend/routers/roster.py backend/main.py; do
  LOCAL_FILE="$PROJECT_ROOT/$file"
  if [[ "$file" == frontend/* ]]; then
    REMOTE_FILE="$WEB_DIR/$(basename "$file")"
  else
    REMOTE_FILE="$BACKEND_DIR/${file#backend/}"
  fi
  if [ -f "$LOCAL_FILE" ]; then
    LOCAL_MD5=$(md5 -q "$LOCAL_FILE" 2>/dev/null || md5sum "$LOCAL_FILE" | awk '{print $1}')
    REMOTE_MD5=$(remote_cmd "md5 -q '$REMOTE_FILE' 2>/dev/null" || echo "missing")
    if [ "$LOCAL_MD5" != "$REMOTE_MD5" ]; then
      echo "  DRIFT: $file (local=$LOCAL_MD5 remote=$REMOTE_MD5)"
      DRIFT_COUNT=$((DRIFT_COUNT + 1))
    fi
  fi
done
if [ "$DRIFT_COUNT" -eq 0 ]; then
  echo "  No drift detected — repo and live are in sync."
fi

if $DRY_RUN; then
  echo "=== [DRY-RUN] Would deploy $DRIFT_COUNT changed files. Exiting. ==="
  log_deploy "DRY-RUN complete — $DRIFT_COUNT files would change"
  exit 0
fi

# --- Step 3: Backup current live ---
echo "[3/6] Creating backup: fnbops_$TIMESTAMP..."
BACKUP_DIR="$BACKUP_BASE/fnbops_$TIMESTAMP"
remote_cmd "mkdir -p '$BACKUP_DIR/frontend' '$BACKUP_DIR/backend/data' '$BACKUP_DIR/backend/routers' '$BACKUP_DIR/backend/services'"
remote_cmd "rsync -a '$WEB_DIR/' '$BACKUP_DIR/frontend/'"
remote_cmd "rsync -a '$BACKEND_DIR/routers/' '$BACKUP_DIR/backend/routers/'"
remote_cmd "rsync -a '$BACKEND_DIR/services/' '$BACKUP_DIR/backend/services/' 2>/dev/null || true"
remote_cmd "rsync -a '$BACKEND_DIR/main.py' '$BACKUP_DIR/backend/main.py'"
remote_cmd "cp '$BACKEND_DIR/staff_auth.json' '$BACKUP_DIR/backend/staff_auth.json' 2>/dev/null || true"
remote_cmd "cp '$BACKEND_DIR/shift_approvals.json' '$BACKUP_DIR/backend/shift_approvals.json' 2>/dev/null || true"
remote_cmd "cp '$BACKEND_DIR/eval_logs.json' '$BACKUP_DIR/backend/eval_logs.json' 2>/dev/null || true"
remote_cmd "cp '$BACKEND_DIR/roster_schedule.json' '$BACKUP_DIR/backend/roster_schedule.json' 2>/dev/null || true"
remote_cmd "cp '$BACKEND_DIR/data/fnbop.db' '$BACKUP_DIR/backend/data/fnbop.db' 2>/dev/null || true"
remote_cmd "cp '$BACKEND_DIR/data/sop_templates.json' '$BACKUP_DIR/backend/data/sop_templates.json' 2>/dev/null || true"
echo "  Backup saved: $BACKUP_DIR"

# --- Step 3b: Rotate old backups (keep latest N) ---
echo "  Rotating backups (keeping latest $BACKUP_KEEP)..."
remote_cmd "
  cd '$BACKUP_BASE' 2>/dev/null || exit 0
  ls -1d fnbops_20[0-9]* 2>/dev/null | sort -r | tail -n +$((BACKUP_KEEP + 1)) | while read old; do
    if [ -n "\$old" ]; then
      rm -rf \"\$old\"
      echo \"  Removed old backup: \$old\"
    fi
  done
"

# --- Step 4: Deploy ---
# Create deploy lock so guard_live_folder.sh ignores changes during deploy
DEPLOY_LOCK="/tmp/fnbops_deploying.lock"
remote_cmd "echo '$TIMESTAMP' > '$DEPLOY_LOCK'"
trap 'remote_cmd "rm -f $DEPLOY_LOCK" 2>/dev/null' EXIT

echo "[4/6] Deploying frontend..."
rsync -avz --delete \
  --exclude="data.json" \
  --exclude="sheet_data.json" \
  --exclude="*.lock" \
  --exclude="*.bak*" \
  --exclude="*.py" \
  --exclude="*.ps1" \
  --exclude="*.log" \
  --exclude="server.log" \
  --exclude="scratch" \
  --exclude="node_modules" \
  "$PROJECT_ROOT/frontend/" "$REMOTE_HOST:$WEB_DIR/"

echo "[4/6] Deploying backend main & routers..."
rsync -avz \
  "$PROJECT_ROOT/backend/main.py" "$REMOTE_HOST:$BACKEND_DIR/main.py"
rsync -avz --exclude="__pycache__" \
  "$PROJECT_ROOT/backend/routers/" "$REMOTE_HOST:$BACKEND_DIR/routers/"

if [ -d "$PROJECT_ROOT/backend/services" ]; then
  rsync -avz --exclude="__pycache__" \
    "$PROJECT_ROOT/backend/services/" "$REMOTE_HOST:$BACKEND_DIR/services/"
fi

if [ -d "$PROJECT_ROOT/backend/models" ]; then
  rsync -avz --exclude="__pycache__" \
    "$PROJECT_ROOT/backend/models/" "$REMOTE_HOST:$BACKEND_DIR/models/"
fi

if [ -d "$PROJECT_ROOT/backend/core" ]; then
  rsync -avz --exclude="__pycache__" \
    "$PROJECT_ROOT/backend/core/" "$REMOTE_HOST:$BACKEND_DIR/core/"
fi

if [ -d "$PROJECT_ROOT/backend/db" ]; then
  rsync -avz --exclude="__pycache__" \
    "$PROJECT_ROOT/backend/db/" "$REMOTE_HOST:$BACKEND_DIR/db/"
fi

if [ -d "$PROJECT_ROOT/scripts" ]; then
  remote_cmd "mkdir -p '$BACKEND_DIR/scripts'"
  rsync -avz \
    --exclude="__pycache__" \
    "$PROJECT_ROOT/scripts/" "$REMOTE_HOST:$BACKEND_DIR/scripts/"
fi

echo "[4/6] Deploying data configs (sop_templates only — staff_auth & databases preserved)..."
# ZERO-DATA-LOSS: staff_auth.json, fnbop.db, shift_approvals.json are living production state on remote server and NEVER overwritten
if [ -f "$PROJECT_ROOT/data/sop_templates.json" ]; then
  remote_cmd "mkdir -p '$BACKEND_DIR/data'"
  rsync -avz "$PROJECT_ROOT/data/sop_templates.json" "$REMOTE_HOST:$BACKEND_DIR/data/sop_templates.json"
fi

echo "[4/6] Deploying Nginx reverse proxy configuration..."
if [ -f "$PROJECT_ROOT/config/nginx/fnbops.conf" ]; then
  rsync -avz "$PROJECT_ROOT/config/nginx/fnbops.conf" "$REMOTE_HOST:$NGINX_CONF_DIR/fnbops.conf"
fi

# --- Step 5: Restart backend & Reload Nginx ---
echo "[5/6] Restarting PM2 process '$PM2_PROCESS'..."
remote_cmd "pm2 restart '$PM2_PROCESS' 2>/dev/null || true"
sleep 2

echo "[5/6] Testing and reloading Docker Nginx container..."
NGINX_CONTAINER="${NGINX_CONTAINER:-fnbops-proxy}"
remote_cmd "docker exec '$NGINX_CONTAINER' nginx -t 2>/dev/null && docker exec '$NGINX_CONTAINER' nginx -s reload 2>/dev/null || true"
sleep 1

# --- Step 6: Health check ---
echo "[6/6] Health check..."
HTTP_CODE=$(remote_cmd "curl -s -o /dev/null -w '%{http_code}' '$HEALTH_URL' 2>/dev/null" || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  echo "  Health check PASSED (HTTP $HTTP_CODE)"
  log_deploy "DEPLOY SUCCESS — backup=$BACKUP_DIR drift=$DRIFT_COUNT health=OK"
else
  echo "  Health check FAILED (HTTP $HTTP_CODE) — AUTO ROLLBACK..."
  log_deploy "DEPLOY FAIL — health check HTTP $HTTP_CODE — rolling back"
  remote_cmd "rsync -a --delete '$BACKUP_DIR/frontend/' '$WEB_DIR/'"
  remote_cmd "rsync -a '$BACKUP_DIR/backend/' '$BACKEND_DIR/'"
  remote_cmd "cp '$BACKUP_DIR/backend/staff_auth.json' '$BACKEND_DIR/staff_auth.json' 2>/dev/null || true"
  remote_cmd "cp '$BACKUP_DIR/backend/data/sop_templates.json' '$BACKEND_DIR/data/sop_templates.json' 2>/dev/null || true"
  remote_cmd "cp '$BACKUP_DIR/backend/data/fnbop.db' '$BACKEND_DIR/data/fnbop.db' 2>/dev/null || true"
  remote_cmd "pm2 restart '$PM2_PROCESS' 2>/dev/null || true"
  echo "  Rollback complete from: $BACKUP_DIR"
  exit 1
fi

echo ""
echo "================================================================="
echo "  DEPLOY COMPLETE — fnbops"
echo "  Timestamp : $TIMESTAMP"
echo "  Backup    : $BACKUP_DIR"
echo "  Drift     : $DRIFT_COUNT files updated"
echo "  Health    : HTTP $HTTP_CODE OK"
echo "================================================================="
