#!/usr/bin/env bash
#
# Report whether the VM's deployed code matches origin/main.
# Run ON the VM (e.g. from startup checks):
#     ssh workstation 'cd ~/projects/trading && bash deploy/sync-check.sh'
# Exits 0 if in sync, 1 if drifted.
set -uo pipefail

cd "$(dirname "$0")/.."
git fetch origin --quiet 2>/dev/null || true
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
DIRTY=$(git status --porcelain --untracked-files=no | wc -l | tr -d ' ')

if [ "$LOCAL" = "$REMOTE" ] && [ "$DIRTY" -eq 0 ]; then
  echo "IN SYNC: HEAD == origin/main ($(git rev-parse --short HEAD)), tree clean"
  exit 0
fi

echo "DRIFT DETECTED:"
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "  HEAD $(git rev-parse --short HEAD) != origin/main $(git rev-parse --short origin/main)" \
       "($(git rev-list --count HEAD..origin/main) behind)"
fi
if [ "$DIRTY" -ne 0 ]; then
  echo "  $DIRTY tracked file(s) modified:"
  git status --porcelain --untracked-files=no | sed 's/^/    /'
fi
exit 1
