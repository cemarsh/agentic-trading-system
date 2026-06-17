#!/usr/bin/env bash
#
# Deploy the agentic trading system on home-workstation (VM 117).
# Run ON the VM:
#     ssh workstation 'cd ~/projects/trading && bash deploy/deploy.sh'
#
# Idempotent. Syncs the checkout to origin/main (discarding redundant local
# working-tree edits — these are hand-applied hotfixes already committed to
# main), refreshes deps, installs/updates systemd units, and restarts.
# .env is gitignored and is never touched.
set -euo pipefail

cd "$(dirname "$0")/.."
echo "==> Repo: $(pwd)"

echo "==> Fetching origin/main"
git fetch origin --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" != "$REMOTE" ] || [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "==> Syncing to origin/main ($REMOTE) — stashing any local edits first"
  git stash push -u -m "deploy-autostash-$(date +%s)" || true
  git checkout main --quiet 2>/dev/null || git checkout -B main origin/main
  git reset --hard origin/main
else
  echo "==> Already in sync at $LOCAL"
fi

echo "==> Installing Python deps"
./venv/bin/pip install -q -r requirements.txt

echo "==> Installing systemd units"
for unit in trading.service trading-alert.service trading-heartbeat.service trading-heartbeat.timer \
            breakeven-monitor.service breakeven-monitor.timer; do
  sudo cp "deploy/$unit" "/etc/systemd/system/$unit"
  echo "    installed $unit"
done
sudo systemctl daemon-reload
sudo systemctl enable --now trading-heartbeat.timer
sudo systemctl enable --now breakeven-monitor.timer
sudo systemctl reset-failed trading || true
sudo systemctl restart trading

echo "==> Post-deploy status"
sleep 5
echo "    trading:            $(systemctl is-active trading)"
echo "    heartbeat.timer:    $(systemctl is-active trading-heartbeat.timer)"
echo "    HEAD:               $(git rev-parse --short HEAD)"
echo "==> Deploy complete."
