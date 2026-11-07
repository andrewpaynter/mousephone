"""
Self-update from GitHub Releases.

The app checks the repo's latest release; if its version is newer and it
has a download for this OS, the update menu item offers it. Installing
downloads it, has the platform's Installer verify it's signed by the same
certificate as the running app, and swaps it in.

The flow itself is shared; everything OS-specific (where the app lives,
how it's verified and replaced) is behind platforms.base.Installer, and
all UI goes through platforms.base.Tray.
"""

import json
import os
import re
import shutil
import ssl
import threading
import urllib.error
import urllib.request

from platforms.base import UpdateError

REPO = "andrewpaynter/mousephone"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"

UPDATE_CHECK_INTERVAL = 6 * 60 * 60  # seconds


def parse_version(text):
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def _ssl_context():
    # A bundled Python (py2app, PyInstaller) often can't find the system's
    # root certificates, so HTTPS fails unless we hand it certifi's bundle.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "mousephone-updater"})
    return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())


def check_for_update(current_version, installer):
    """Returns {"version", "download_url", "page_url"} for a newer release
    that has a download for this OS, or None."""
    try:
        with _open(LATEST_RELEASE_API, timeout=15) as response:
            release = json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # no releases published yet
            return None
        raise

    version = release.get("tag_name", "").lstrip("v")
    if not version or parse_version(version) <= parse_version(current_version):
        return None

    # Each OS's build is attached under its own name; a release whose build
    # for this OS hasn't been uploaded yet just isn't offered until it is.
    wanted = installer.asset_name(version)
    download_url = next(
        (a["browser_download_url"] for a in release.get("assets", [])
         if a.get("name") == wanted),
        None,
    )
    if download_url is None:
        return None
    return {"version": version, "download_url": download_url, "page_url": release.get("html_url")}


def download_and_prepare(update, installer):
    """Downloads the update and has the installer verify and unpack it.
    Returns what installer.install_and_relaunch() needs."""
    staging = installer.make_staging_dir()
    try:
        download_path = os.path.join(staging, installer.asset_name(update["version"]))
        with _open(update["download_url"], timeout=60) as response, open(download_path, "wb") as f:
            shutil.copyfileobj(response, f)
        return installer.prepare(download_path, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


class UpdateController:
    """Drives the update menu item: periodic background checks, the
    on-demand check, and the confirm → download → install flow.

    Network work runs on background threads; anything touching the menu or
    showing a dialog is handed back to the UI thread via tray.call_on_main.
    """

    def __init__(self, tray, installer, current_version):
        self.tray = tray
        self.installer = installer
        self.current_version = current_version
        self.available = None
        self.updating = False

        tray.set_update_item("Check for Updates", self.clicked)
        tray.every(UPDATE_CHECK_INTERVAL, self.background_check)
        self.background_check()

    def background_check(self):
        self._start(self._check, False)

    def clicked(self):
        if self.updating:
            return
        if self.available:
            self._prompt_install()
        else:
            self._start(self._check, True)

    @staticmethod
    def _start(fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _check(self, manual):
        try:
            update = check_for_update(self.current_version, self.installer)
        except Exception:
            if manual:
                self.tray.call_on_main(
                    self.tray.alert, "mousephone",
                    "Couldn't check for updates. Check your internet connection and try again.",
                )
            return
        self.tray.call_on_main(self._on_check_result, update, manual)

    def _on_check_result(self, update, manual):
        if self.updating:
            return
        self.available = update
        self.tray.set_update_item(
            f"Update to v{update['version']}…" if update else "Check for Updates",
            self.clicked,
        )
        if manual:
            if update:
                self._prompt_install()
            else:
                self.tray.alert("mousephone", f"You're up to date (v{self.current_version}).")

    def _prompt_install(self):
        update = self.available
        if not self.installer.can_install():
            self.tray.alert(
                f"mousephone {update['version']} is available",
                "mousephone can't replace itself where it's installed. "
                "Download the new version from the release page and install it.",
            )
            self.tray.open_url(update["page_url"])
            return
        if not self.tray.confirm(
            f"Update to mousephone {update['version']}?",
            "mousephone will download the update and restart. It only takes a few seconds.",
            ok="Update",
            cancel="Not Now",
        ):
            return

        self.updating = True
        self.tray.set_update_item("Downloading update…", self.clicked)
        self._start(self._download, update)

    def _download(self, update):
        try:
            prepared = download_and_prepare(update, self.installer)
        except Exception as e:
            self.tray.call_on_main(self._on_install_failed, e)
            return
        self.tray.call_on_main(self._finish_install, prepared)

    def _finish_install(self, prepared):
        self.installer.install_and_relaunch(prepared)
        self.tray.quit()

    def _on_install_failed(self, error):
        self.updating = False
        self.tray.set_update_item(f"Update to v{self.available['version']}…", self.clicked)
        message = (
            str(error) if isinstance(error, UpdateError)
            else "The download failed. Check your internet connection and try again."
        )
        self.tray.alert("Update failed", message)
