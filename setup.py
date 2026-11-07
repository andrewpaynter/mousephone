"""
py2app build script for mousephone.

This must be run ON A MAC (py2app builds native Mac app bundles and
can't cross-compile from another OS).

Usage:
    ./build.sh

...or manually:
    python3 -m venv build_env
    source build_env/bin/activate
    pip install aiohttp pyobjc-framework-Quartz "qrcode[pil]" rumps certifi py2app
    python3 setup.py py2app

Result: dist/mousephone.app — drag it to /Applications and double-click
to run, no Terminal or Python install needed after that.
"""

import re

from setuptools import setup

# Single source of truth for the version: __version__ in mouse_server.py.
with open("mouse_server.py") as f:
    VERSION = re.search(r'^__version__ = "([^"]+)"', f.read(), re.M).group(1)

APP = ["mouse_server.py"]
OPTIONS = {
    "argv_emulation": False,
    "packages": ["aiohttp", "Quartz", "qrcode", "PIL", "rumps", "certifi"],
    "includes": [
        "multidict",
        "yarl",
        "attr",
        "async_timeout",
        "aiosignal",
        "frozenlist",
        "charset_normalizer",
    ],
    "iconfile": "assets/mousephone.icns",
    "plist": {
        "CFBundleName": "mousephone",
        "CFBundleDisplayName": "mousephone",
        "CFBundleIdentifier": "com.local.mousephone",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,  # no Dock icon / app menu — runs quietly in the background
    },
}

setup(
    app=APP,
    data_files=[("assets", ["assets/menu_bar_icon.png"])],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
