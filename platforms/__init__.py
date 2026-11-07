"""
OS-specific code. See platforms/base.py for the interfaces each OS
implements; this module just picks the right one.
"""

import sys


def current(assets_dir):
    """Returns the Platform for the OS we're running on. Each one is
    imported only on its own OS, since it depends on that OS's libraries."""
    if sys.platform == "darwin":
        from platforms.mac import MacPlatform

        return MacPlatform(assets_dir)
    if sys.platform == "win32":
        from platforms.windows import WindowsPlatform

        return WindowsPlatform(assets_dir)
    print(f"mousephone doesn't support this OS ({sys.platform}) yet.")
    sys.exit(1)
