"""
macOS implementation: Quartz events for input, a rumps menu bar app for the
UI, and a codesign-verified .app bundle swap for updates.
"""

import ctypes
import io
import os
import socket
import subprocess
import sys
import tempfile

try:
    from Quartz import (
        CGEventCreateMouseEvent,
        CGEventCreateScrollWheelEvent,
        CGEventCreateKeyboardEvent,
        CGEventKeyboardSetUnicodeString,
        CGEventSetFlags,
        CGEventPost,
        CGEventCreate,
        CGEventGetLocation,
        CGMainDisplayID,
        CGDisplayBounds,
        CGGetActiveDisplayList,
        kCGHIDEventTap,
        kCGEventMouseMoved,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseUp,
        kCGEventLeftMouseDragged,
        kCGEventRightMouseDown,
        kCGEventRightMouseUp,
        kCGMouseButtonLeft,
        kCGMouseButtonRight,
        kCGScrollEventUnitPixel,
    )
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install pyobjc-framework-Quartz")
    sys.exit(1)

try:
    import rumps
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install rumps")
    sys.exit(1)

import qrcode
from AppKit import (
    NSFont,
    NSImage,
    NSImageScaleProportionallyUpOrDown,
    NSImageView,
    NSMakeRect,
    NSTextAlignmentCenter,
    NSTextField,
    NSView,
)
from Foundation import NSData
from PyObjCTools import AppHelper

from platforms.base import Installer, InputController, Platform, Tray, UpdateError


class MacPlatform(Platform):
    def computer_name(self):
        # The friendly name from Sharing settings ("Andrew's MacBook Air"),
        # rather than the hostname ("Andrews-MacBook-Air.local").
        result = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True)
        return result.stdout.strip() or socket.gethostname().removesuffix(".local")

    def data_dir(self):
        return os.path.expanduser("~/Library/Application Support/mousephone")

    def create_input(self):
        return MacInput()

    def create_tray(self, url, port, dev):
        return MacTray(url, port, dev, os.path.join(self.assets_dir, "menu_bar_icon.png"))

    def create_installer(self):
        return MacInstaller()


# ---------- Input (Quartz) ----------

def get_desktop_bounds():
    """Union of every active display's bounds — not just the main one.
    With an external monitor, the usable cursor area extends past the
    main display's own width/height, in whichever direction the second
    screen is arranged (often right and/or below)."""
    max_displays = 16
    err, display_ids, count = CGGetActiveDisplayList(max_displays, None, None)
    if err != 0 or not display_ids:
        bounds = CGDisplayBounds(CGMainDisplayID())
        return (
            bounds.origin.x,
            bounds.origin.y,
            bounds.origin.x + bounds.size.width,
            bounds.origin.y + bounds.size.height,
        )

    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for display_id in display_ids[:count]:
        b = CGDisplayBounds(display_id)
        min_x = min(min_x, b.origin.x)
        min_y = min(min_y, b.origin.y)
        max_x = max(max_x, b.origin.x + b.size.width)
        max_y = max(max_y, b.origin.y + b.size.height)
    return min_x, min_y, max_x, max_y


# Virtual key codes for the few non-character keys the phone sends.
KEY_CODES = {"backspace": 51, "return": 36}


class MacInput(InputController):
    def __init__(self):
        loc = CGEventGetLocation(CGEventCreate(None))
        self.x, self.y = loc.x, loc.y
        self.dragging = False

    def move(self, dx, dy):
        # Recomputed on every move rather than cached at startup: monitors
        # can be connected, disconnected, or rearranged while mousephone
        # keeps running (it's a persistent menu-bar app), and a stale
        # cached bound would make part of the desktop unreachable until
        # restart.
        min_x, min_y, max_x, max_y = get_desktop_bounds()
        self.x = min(max(self.x + dx, min_x), max_x - 1)
        self.y = min(max(self.y + dy, min_y), max_y - 1)
        event_type = kCGEventLeftMouseDragged if self.dragging else kCGEventMouseMoved
        self._post_mouse(event_type, kCGMouseButtonLeft)

    def click(self, button):
        if button == "left":
            down, up, btn = kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft
        else:
            down, up, btn = kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonRight
        for etype in (down, up):
            self._post_mouse(etype, btn)

    def mouse_down(self):
        self.dragging = True
        self._post_mouse(kCGEventLeftMouseDown, kCGMouseButtonLeft)

    def mouse_up(self):
        self.dragging = False
        self._post_mouse(kCGEventLeftMouseUp, kCGMouseButtonLeft)

    def scroll(self, dx, dy):
        event = CGEventCreateScrollWheelEvent(
            None, kCGScrollEventUnitPixel, 2, int(dy), int(dx)
        )
        CGEventPost(kCGHIDEventTap, event)

    def type_text(self, text):
        # Attaches the characters to a synthetic key event, rather than
        # mapping each one to a physical key on a particular layout.
        for ch in text:
            length = len(ch.encode("utf-16-le")) // 2  # emoji are 2 UTF-16 units
            for key_down in (True, False):
                event = CGEventCreateKeyboardEvent(None, 0, key_down)
                CGEventSetFlags(event, 0)  # ignore any modifiers held on the Mac
                CGEventKeyboardSetUnicodeString(event, length, ch)
                CGEventPost(kCGHIDEventTap, event)

    def press_key(self, key, count=1):
        code = KEY_CODES.get(key)
        if code is None:
            return
        for _ in range(max(1, min(int(count), 500))):
            for key_down in (True, False):
                event = CGEventCreateKeyboardEvent(None, code, key_down)
                CGEventSetFlags(event, 0)
                CGEventPost(kCGHIDEventTap, event)

    def _post_mouse(self, event_type, button):
        event = CGEventCreateMouseEvent(None, event_type, (self.x, self.y), button)
        CGEventPost(kCGHIDEventTap, event)


# ---------- Accessibility permission ----------

ACCESSIBILITY_MESSAGE = (
    "mousephone can't move the cursor without this.\n\n"
    "In the Accessibility list, remove any existing "
    "“mousephone” entry first (select it, click −), "
    "then add this app back and turn it on. Then quit and "
    "reopen mousephone."
)


def is_accessibility_trusted():
    """Check Accessibility permission without needing an extra pip package —
    calls AXIsProcessTrusted() straight from the system framework via ctypes."""
    try:
        app_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        return bool(app_services.AXIsProcessTrusted())
    except Exception:
        return True  # can't check — don't block startup over it


def open_accessibility_settings():
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        check=False,
    )


# ---------- Menu bar app (rumps) ----------

PERMISSION_ITEM = "Check Accessibility Permission"


def build_qr_menu_item(url):
    """A menu item whose body is the QR code image itself, so scanning it
    is just: click the menu bar icon. No separate window, no Preview."""
    qr_img = qrcode.make(url, box_size=6, border=2)
    buf = io.BytesIO()
    qr_img.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    ns_image = NSImage.alloc().initWithData_(data)

    qr_size = 176
    padding = 14
    label_h = 18
    view_w = qr_size + padding * 2
    view_h = qr_size + padding * 2 + label_h

    view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, view_w, view_h))

    image_view = NSImageView.alloc().initWithFrame_(
        NSMakeRect(padding, label_h, qr_size, qr_size)
    )
    image_view.setImage_(ns_image)
    image_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
    view.addSubview_(image_view)

    label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, view_w, label_h))
    label.setStringValue_(url)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setEditable_(False)
    label.setSelectable_(True)
    label.setAlignment_(NSTextAlignmentCenter)
    label.setFont_(NSFont.systemFontOfSize_(11))
    view.addSubview_(label)

    item = rumps.MenuItem("")
    item._menuitem.setView_(view)
    return item


class MacTray(Tray):
    """A rumps menu bar app. Running its Cocoa run loop on the main thread
    is also what makes the .app respond to Launch Services at startup —
    without it, a double-clicked .app that never touches AppKit can trigger
    "You can't open mousephone.app because it is not responding," even
    though the server itself is running fine."""

    def __init__(self, url, port, dev, icon_path):
        self.app = rumps.App(
            "mousephone",
            title="DEV" if dev else None,
            icon=icon_path,
            template=True,
            quit_button="Quit",
        )
        items = [build_qr_menu_item(url), None, rumps.MenuItem(PERMISSION_ITEM, callback=self._check_permission)]
        if dev:
            items[:0] = [rumps.MenuItem(f"Dev server · port {port}"), None]
        self.app.menu = items
        self.update_item = None
        self.timers = []

    def add_choice_menu(self, title, choices, selected, on_select):
        submenu = rumps.MenuItem(title)

        def pick(sender):
            for item in submenu.values():
                item.state = int(item is sender)
            on_select(sender.title)

        for label in choices:
            item = rumps.MenuItem(label, callback=pick)
            item.state = int(label == selected)
            submenu.add(item)
        self.app.menu.insert_before(PERMISSION_ITEM, submenu)

    def set_update_item(self, title, callback):
        if self.update_item is None:
            self.update_item = rumps.MenuItem(title, callback=lambda _: callback())
            self.app.menu.insert_before(PERMISSION_ITEM, self.update_item)
        else:
            self.update_item.title = title

    def alert(self, title, message):
        rumps.alert(title=title, message=message)

    def confirm(self, title, message, ok, cancel):
        return rumps.alert(title=title, message=message, ok=ok, cancel=cancel) == 1

    def call_on_main(self, fn, *args):
        AppHelper.callAfter(fn, *args)

    def every(self, seconds, fn):
        timer = rumps.Timer(lambda _: fn(), seconds)
        timer.start()
        self.timers.append(timer)  # rumps timers stop if garbage-collected

    def open_url(self, url):
        subprocess.run(["open", url], check=False)

    def quit(self):
        rumps.quit_application()

    def run(self):
        if not is_accessibility_trusted():
            print("Accessibility permission NOT granted — the cursor will not move.")
            print("System Settings > Privacy & Security > Accessibility")
            rumps.alert(title="Accessibility Permission Needed", message=ACCESSIBILITY_MESSAGE)
            open_accessibility_settings()
        self.app.run()

    def _check_permission(self, _):
        if is_accessibility_trusted():
            rumps.alert(title="mousephone", message="Accessibility permission is granted. You're all set.")
        else:
            rumps.alert(title="Accessibility Permission Needed", message=ACCESSIBILITY_MESSAGE)
            open_accessibility_settings()


# ---------- Updates (.app bundle swap) ----------

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


class MacInstaller(Installer):
    def asset_name(self, version):
        return f"mousephone-{version}.zip"

    def current_install(self):
        if not getattr(sys, "frozen", False):
            return None
        path = os.path.abspath(sys.executable)
        while path != "/" and not path.endswith(".app"):
            path = os.path.dirname(path)
        return path if path.endswith(".app") else None

    def can_install(self):
        app = self.current_install()
        return app is not None and os.access(os.path.dirname(app), os.W_OK)

    def make_staging_dir(self):
        # Next to the app, so the final swap is a rename, not a
        # cross-volume copy.
        return tempfile.mkdtemp(
            prefix=".mousephone-update-", dir=os.path.dirname(self.current_install())
        )

    def prepare(self, download_path, staging_dir):
        extracted = os.path.join(staging_dir, "extracted")
        subprocess.run(["ditto", "-x", "-k", download_path, extracted], check=True)
        apps = [n for n in os.listdir(extracted) if n.endswith(".app")]
        if len(apps) != 1:
            raise UpdateError("The download didn't contain the app.")
        new_app = os.path.join(extracted, apps[0])

        # Only install an app signed by the same certificate as this one.
        # That rejects a tampered or unrelated download, and guarantees the
        # update keeps this app's Accessibility permission.
        requirement = self._designated_requirement(self.current_install())
        verify = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", "-R", "=" + requirement, new_app],
            capture_output=True, text=True,
        )
        if verify.returncode != 0:
            raise UpdateError(
                "The update isn't signed the same way as this copy of mousephone, "
                "so it wasn't installed. Download it manually from the release page."
            )
        return staging_dir, new_app

    def install_and_relaunch(self, prepared):
        staging_dir, new_app = prepared
        subprocess.Popen(
            ["/bin/sh", "-c", _SWAP_SCRIPT, "sh",
             str(os.getpid()), self.current_install(), new_app, staging_dir],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def _designated_requirement(app_path):
        result = subprocess.run(
            ["codesign", "-d", "-r-", app_path], capture_output=True, text=True
        )
        for line in (result.stdout + result.stderr).splitlines():
            if line.startswith("designated => "):
                return line[len("designated => "):]
        raise UpdateError("Couldn't read this app's code signature.")
