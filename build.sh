#!/bin/bash
# One-time build script — turns mouse_server.py into dist/Phone Mouse.app
# Run this ON YOUR MAC, from the folder containing mouse_server.py and setup.py.

set -e
cd "$(dirname "$0")"

echo "Setting up a temporary build environment..."
python3 -m venv build_env
source build_env/bin/activate

echo "Installing dependencies..."
pip install --upgrade pip >/dev/null
pip install aiohttp pyobjc-framework-Quartz "qrcode[pil]" rumps py2app

echo "Building the app..."
rm -rf build dist
python3 setup.py py2app

deactivate

echo ""
echo "=================================================="
echo "Done! Your app is at: dist/Phone Mouse.app"
echo "Drag it into /Applications, then double-click to run."
echo ""
echo "First launch: macOS will warn it's from an unidentified"
echo "developer. Right-click the app > Open > Open, to allow it"
echo "(only needed the first time)."
echo "=================================================="
