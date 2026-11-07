#!/usr/bin/env bash
# One-time setup so Real Life Rail works on your Android phone anywhere, not just on home Wi-Fi.
#   1. runs the app as a user service on this PC (always on, restarts by itself)
#   2. runs Tailscale without root, and serves the app over HTTPS to your own devices only
# Then: install Tailscale on the phone, sign in with the same account, open the printed https:// address in Chrome,
# and choose "Install app". Nothing is exposed to the internet (tailscale serve, not funnel).
set -euo pipefail
cd "$(dirname "$0")/.."
SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/realliferail-tailscale/tailscaled.sock"
TS="tailscale --socket=$SOCK"

command -v tailscale >/dev/null || brew install tailscale
[ -x .venv/bin/realliferail ] || uv sync

mkdir -p ~/.config/systemd/user
cp scripts/systemd/realliferail.service scripts/systemd/realliferail-tailscaled.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now realliferail-tailscaled.service realliferail.service
loginctl enable-linger "$USER" 2>/dev/null || echo "(couldn't enable linger: services stop when you log out)"

for _ in $(seq 20); do [ -S "$SOCK" ] && break; sleep 0.5; done

if ! $TS status >/dev/null 2>&1; then
  echo
  echo "Sign this PC in to Tailscale (free personal plan). Open the link it prints:"
  $TS up --hostname=realliferail
fi

$TS serve --bg http://127.0.0.1:8765
NAME=$($TS status --json | .venv/bin/python -I -c "import json,sys; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))")
echo
echo "Done. On your phone:"
echo "  1. Install Tailscale from the Play Store and sign in with the same account."
echo "  2. Open https://$NAME in Chrome, then menu > Install app (or Add to home screen)."
echo "  3. Settings in the app shows your Realtime Trains plan."
