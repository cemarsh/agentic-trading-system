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

# The pull above may have rewritten THIS script; bash is still running the old
# in-memory copy, so re-exec the freshly-pulled version once (guarded against loops)
# so newly-added units/steps actually run on the first deploy.
if [ -z "${DEPLOY_REEXECED:-}" ]; then
  export DEPLOY_REEXECED=1
  exec bash "$0" "$@"
fi

echo "==> Installing Python deps"
./venv/bin/pip install -q -r requirements.txt

# VM 117 advertises a global IPv6 address (ULA + Tailscale) but has NO IPv6
# default route. glibc's default RFC 3484 ordering therefore hands dual-stack
# hosts (api.anthropic.com, Alpaca, Resend, Slack, SEC EDGAR) their dead IPv6
# address first, causing intermittent "Connection error" (notably the daily
# Claude journal synthesis). Force IPv4 precedence in gai.conf. Idempotent;
# host-local so it must be re-applied on every rebuild.
echo "==> Ensuring IPv4-first DNS resolution (/etc/gai.conf)"
if grep -qE '^[[:space:]]*precedence ::ffff:0:0/96[[:space:]]+100' /etc/gai.conf 2>/dev/null; then
  echo "    gai.conf: IPv4 precedence already set"
elif grep -qE '^#precedence ::ffff:0:0/96[[:space:]]+100' /etc/gai.conf 2>/dev/null; then
  sudo sed -i 's|^#precedence ::ffff:0:0/96  100|precedence ::ffff:0:0/96  100|' /etc/gai.conf
  echo "    gai.conf: uncommented IPv4 precedence line"
else
  echo 'precedence ::ffff:0:0/96  100' | sudo tee -a /etc/gai.conf >/dev/null
  echo "    gai.conf: appended IPv4 precedence line"
fi

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
