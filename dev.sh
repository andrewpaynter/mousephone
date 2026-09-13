#!/bin/bash
# Dev loop: runs mouse_server.py directly (no build/install step) and
# auto-restarts it whenever mouse_server.py changes.
#
# Why this fixes the Accessibility-permission hassle: when the server is
# launched this way, macOS attributes the Accessibility request to whatever
# app launched this script (Terminal.app, iTerm, etc.), not to a freshly
# ad-hoc-signed mousephone.app. Grant it ONCE, to your terminal app, in
# System Settings > Privacy & Security > Accessibility -- it stays valid
# across every future edit and restart, since your terminal app's own
# signature never changes. Only run build.sh (which needs a fresh grant
# every time) when you actually want the packaged .app.
set -e
cd "$(dirname "$0")"

SCRIPT="mouse_server.py"
PID=""

cleanup() {
  [ -n "$PID" ] && kill "$PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM

start() {
  python3 "$SCRIPT" &
  PID=$!
}

mtime() {
  stat -f %m "$SCRIPT" 2>/dev/null
}

ensure_deps() {
  if ! python3 -c "import aiohttp, Quartz, qrcode, rumps" 2>/dev/null; then
    echo "Installing missing dependencies (one-time)..."
    pip3 install aiohttp pyobjc-framework-Quartz "qrcode[pil]" rumps
  fi
}

ensure_deps

echo "=================================================="
echo "Dev mode: running $SCRIPT directly, watching for changes."
echo ""
echo "First time only: grant Accessibility permission to your"
echo "TERMINAL APP (Terminal/iTerm), not to mousephone, in"
echo "System Settings > Privacy & Security > Accessibility."
echo "It'll keep working after every edit -- no rebuild, no"
echo "reinstall, no re-granting."
echo ""
echo "Ctrl+C to stop."
echo "=================================================="

start
last=$(mtime)

while true; do
  sleep 1

  if ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID" 2>/dev/null
    echo ""
    echo "Server exited. Waiting for a change to $SCRIPT to restart..."
    while [ "$(mtime)" = "$last" ]; do sleep 1; done
  fi

  current=$(mtime)
  if [ "$current" != "$last" ]; then
    echo ""
    echo "Change detected in $SCRIPT -- restarting..."
    kill "$PID" 2>/dev/null
    wait "$PID" 2>/dev/null
    last="$current"
    start
  fi
done
