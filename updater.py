"""
Self-update from GitHub Releases.

The app checks the repo's latest release; if its version is newer, it can
download the attached .zip, check the new app is signed with the same
certificate as the running one, and swap it in place of the running app.

Only does anything when running as the built mousephone.app — under
dev.sh or Terminal there's no bundle to replace.
"""

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

REPO = "andrewpaynter/mousephone"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"


class UpdateError(Exception):
    pass


def current_app_path():
    """Path to the running .app bundle, or None when not running from one."""
    if not getattr(sys, "frozen", False):
        return None
    path = os.path.abspath(sys.executable)
    while path != "/" and not path.endswith(".app"):
        path = os.path.dirname(path)
    return path if path.endswith(".app") else None


def parse_version(text):
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def _ssl_context():
    # A py2app-bundled Python often can't find the system's root
    # certificates, so HTTPS fails unless we hand it certifi's bundle.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "mousephone-updater"})
    return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())


def check_for_update(current_version):
    """Returns {"version", "zip_url", "page_url"} for a newer release, or None."""
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

    zip_url = next(
        (a["browser_download_url"] for a in release.get("assets", [])
         if a.get("name", "").endswith(".zip")),
        None,
    )
    if zip_url is None:
        return None
    return {"version": version, "zip_url": zip_url, "page_url": release.get("html_url")}


def can_install(app_path):
    return app_path is not None and os.access(os.path.dirname(app_path), os.W_OK)


def _designated_requirement(app_path):
    result = subprocess.run(
        ["codesign", "-d", "-r-", app_path], capture_output=True, text=True
    )
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("designated => "):
            return line[len("designated => "):]
    raise UpdateError("Couldn't read this app's code signature.")


def download_update(update, app_path):
    """Downloads and verifies the update next to the running app. Returns
    (staging_dir, new_app_path) for install_and_relaunch()."""
    # Staged in the same folder as the app so the final swap is a rename,
    # not a cross-volume copy.
    staging = tempfile.mkdtemp(prefix=".mousephone-update-", dir=os.path.dirname(app_path))
    try:
        zip_path = os.path.join(staging, "update.zip")
        with _open(update["zip_url"], timeout=60) as response, open(zip_path, "wb") as f:
            shutil.copyfileobj(response, f)

        extracted = os.path.join(staging, "extracted")
        subprocess.run(["ditto", "-x", "-k", zip_path, extracted], check=True)
        apps = [n for n in os.listdir(extracted) if n.endswith(".app")]
        if len(apps) != 1:
            raise UpdateError("The download didn't contain the app.")
        new_app = os.path.join(extracted, apps[0])

        # Only install an app signed by the same certificate as this one.
        # That rejects a tampered or unrelated download, and guarantees the
        # update keeps this app's Accessibility permission.
        requirement = _designated_requirement(app_path)
        verify = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", "-R", "=" + requirement, new_app],
            capture_output=True, text=True,
        )
        if verify.returncode != 0:
            raise UpdateError(
                "The update isn't signed the same way as this copy of mousephone, "
                "so it wasn't installed. Download it manually from the release page."
            )
        return staging, new_app
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


# Runs detached after the app quits: waits for it to exit, swaps the new
# bundle in (restoring the old one if anything fails), then relaunches.
_SWAP_SCRIPT = """
pid="$1"; app="$2"; new_app="$3"; staging="$4"
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
if mv "$app" "$staging/old.app"; then
  if ! mv "$new_app" "$app"; then
    mv "$staging/old.app" "$app"
  fi
fi
open "$app"
rm -rf "$staging"
"""


def install_and_relaunch(app_path, staging, new_app):
    """Starts the swap helper. The caller must quit the app right after."""
    subprocess.Popen(
        ["/bin/sh", "-c", _SWAP_SCRIPT, "sh", str(os.getpid()), app_path, new_app, staging],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
