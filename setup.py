"""
py2app build script for mousephone.

This must be run ON A MAC (py2app builds native Mac app bundles and
can't cross-compile from another OS).

Usage:
    ./build.sh

...or manually:
    python3 -m venv build_env
    source build_env/bin/activate
    pip install aiohttp pyobjc-framework-Quartz "qrcode[pil]" rumps py2app
    python3 setup.py py2app

Result: dist/mousephone.app — drag it to /Applications and double-click
to run, no Terminal or Python install needed after that.
"""

from setuptools import setup

APP = ["mouse_server.py"]
OPTIONS = {
    "argv_emulation": False,
    "packages": ["aiohttp", "Quartz", "qrcode", "PIL", "rumps"],
    "includes": [
        "multidict",
        "yarl",
        "attr",
        "async_timeout",
        "aiosignal",
        "frozenlist",
        "charset_normalizer",
    ],
    "plist": {
        "CFBundleName": "mousephone",
        "CFBundleDisplayName": "mousephone",
        "CFBundleIdentifier": "com.local.mousephone",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,  # no Dock icon / app menu — runs quietly in the background
    },
}

setup(
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
