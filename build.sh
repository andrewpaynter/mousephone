#!/bin/bash
# One-time build script — turns mouse_server.py into dist/mousephone.app
# Run this ON YOUR MAC, from the folder containing mouse_server.py and setup.py.

set -e
cd "$(dirname "$0")"

SIGNING_IDENTITY="mousephone Code Signing"
if ! security find-certificate -c "$SIGNING_IDENTITY" >/dev/null 2>&1; then
  echo "No \"$SIGNING_IDENTITY\" certificate in your keychain."
  echo "Run tools/create_signing_cert.sh once first (or import your backup)."
  exit 1
fi

echo "Setting up a temporary build environment..."
python3 -m venv build_env
source build_env/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip >/dev/null
pip install aiohttp pyobjc-framework-Quartz "qrcode[pil]" rumps certifi py2app

echo "Building the app..."
rm -rf build dist
python3 setup.py py2app

echo "Signing the app..."
# Signed with the same certificate every time (see
# tools/create_signing_cert.sh) rather than ad-hoc. macOS ties
# Accessibility permission to the signing identity, so a stable identity
# means permission survives rebuilds and updates, and the in-app updater
# only installs builds signed with this same certificate.
codesign --force --deep --sign "$SIGNING_IDENTITY" "dist/mousephone.app"
codesign --verify --deep --strict "dist/mousephone.app"

deactivate

echo ""
echo "=================================================="
echo "Done! Your app is at: dist/mousephone.app"
echo "Drag it into /Applications, then double-click to run."
echo ""
echo "First launch: macOS will warn it's from an unidentified"
echo "developer. Right-click the app > Open > Open, to allow it"
echo "(only needed the first time)."
echo "=================================================="
