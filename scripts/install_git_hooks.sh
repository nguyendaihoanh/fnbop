#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chmod +x "$REPO_ROOT/.githooks/pre-push"

GLOBAL_HOOKS_PATH="$(git config --global --get core.hooksPath 2>/dev/null || true)"
if [ -n "$GLOBAL_HOOKS_PATH" ] && [ -x "${GLOBAL_HOOKS_PATH/#\~/$HOME}/pre-push" ]; then
    git -C "$REPO_ROOT" config --unset core.hooksPath >/dev/null 2>&1 || true
    echo "Global SOP hooksPath active (${GLOBAL_HOOKS_PATH}); it chains automatically to .githooks/pre-push."
else
    git -C "$REPO_ROOT" config core.hooksPath .githooks
    echo "Configured git core.hooksPath -> .githooks (pre-push gate active)."
fi
