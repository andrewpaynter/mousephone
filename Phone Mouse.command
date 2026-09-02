#!/bin/bash
# Double-click this in Finder to launch the server.
# (Still requires: pip3 install aiohttp pyobjc-framework-Quartz "qrcode[pil]", done once.)
cd "$(dirname "$0")"
python3 mouse_server.py
