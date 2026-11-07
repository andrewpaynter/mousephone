"""
Windows implementation: SendInput for input, a pystray system tray icon
for the UI, and an Authenticode-verified Inno Setup installer for updates.
"""

import ctypes
import os
import subprocess
import sys
import tempfile
import threading
import webbrowser
from ctypes import c_int32, c_size_t, c_uint16, c_uint32

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("Missing dependency. Install with:\n  pip install pystray \"qrcode[pil]\"")
    sys.exit(1)

import qrcode

from platforms.base import Installer, InputController, Platform, Tray, UpdateError

user32 = ctypes.WinDLL("user32", use_last_error=True)


class WindowsPlatform(Platform):
    def __init__(self, assets_dir):
        super().__init__(assets_dir)
        _enable_dpi_awareness()

    def create_input(self):
        return WindowsInput()

    def create_tray(self, url, port, dev):
        return WindowsTray(url, port, dev, os.path.join(self.assets_dir, "mousephone.ico"))

    def create_installer(self):
        return WindowsInstaller()


def _enable_dpi_awareness():
    """Without this, on a scaled display (125%, 150%...) Windows reports
    scaled-down screen sizes to us, and absolute cursor positions land in
    the wrong place. Must happen before any window (the tray icon) exists."""
    try:
        per_monitor_aware_v2 = ctypes.c_void_p(-4)
        if user32.SetProcessDpiAwarenessContext(per_monitor_aware_v2):
            return
    except AttributeError:  # older than Windows 10 1703
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


# ---------- Input (SendInput) ----------
#
# The structs use fixed-width types rather than ctypes.wintypes so their
# layout matches Windows' exactly (and can be checked on any OS):
# sizeof(INPUT) must be 40 on 64-bit Windows, 28 on 32-bit.

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", c_int32),
        ("dy", c_int32),
        ("mouseData", c_int32),  # a DWORD, but wheel deltas are signed
        ("dwFlags", c_uint32),
        ("time", c_uint32),
        ("dwExtraInfo", c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", c_uint16),
        ("wScan", c_uint16),
        ("dwFlags", c_uint32),
        ("time", c_uint32),
        ("dwExtraInfo", c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", c_uint32), ("wParamL", c_uint16), ("wParamH", c_uint16)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", c_uint32), ("u", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", c_int32), ("y", c_int32)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# Virtual-key codes for the few non-character keys the phone sends.
VK_CODES = {"backspace": 0x08, "return": 0x0D}

# Wheel units per pixel of finger movement. One wheel "notch" is 120 units,
# which most apps scroll ~100px for. Apps that support smooth scrolling
# (browsers, most modern apps) honor smaller deltas; older ones only move
# once 120 units have accumulated. Tune this if scrolling feels off.
WHEEL_UNITS_PER_PIXEL = 1.2

user32.SendInput.argtypes = (c_uint32, ctypes.POINTER(INPUT), c_int32)
user32.SendInput.restype = c_uint32
user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
user32.GetSystemMetrics.argtypes = (c_int32,)
user32.GetSystemMetrics.restype = c_int32


def _send(*inputs):
    array = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    return INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=data, dwFlags=flags)))


def _key(vk=0, scan=0, flags=0):
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)))


def get_desktop_bounds():
    """The virtual screen: the bounding box of every display, which can start
    at negative coordinates if a monitor is arranged left of/above the main
    one. Read fresh each time, since monitors can change while running."""
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return left, top, width, height


class WindowsInput(InputController):
    def __init__(self):
        # Sub-pixel/sub-notch remainders, so slow finger movement isn't
        # lost to rounding.
        self._move_rem = [0.0, 0.0]
        self._wheel_rem = [0.0, 0.0]

    def move(self, dx, dy):
        self._move_rem[0] += dx
        self._move_rem[1] += dy
        step_x, step_y = int(self._move_rem[0]), int(self._move_rem[1])
        if not step_x and not step_y:
            return
        self._move_rem[0] -= step_x
        self._move_rem[1] -= step_y

        # Absolute positioning from the real cursor position, rather than a
        # relative move: relative moves get Windows' pointer acceleration
        # ("Enhance pointer precision") applied on top of the phone's own
        # sensitivity, and they'd drift from where the cursor actually is.
        pos = POINT()
        user32.GetCursorPos(ctypes.byref(pos))
        left, top, width, height = get_desktop_bounds()
        x = min(max(pos.x + step_x, left), left + width - 1)
        y = min(max(pos.y + step_y, top), top + height - 1)
        # Absolute coordinates are normalized to 0..65535 across the virtual desktop.
        nx = round((x - left) * 65535 / max(width - 1, 1))
        ny = round((y - top) * 65535 / max(height - 1, 1))
        # No separate "drag" event on Windows: moving with the button held is a drag.
        _send(_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny))

    def click(self, button):
        if button == "left":
            _send(_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP))
        else:
            _send(_mouse(MOUSEEVENTF_RIGHTDOWN), _mouse(MOUSEEVENTF_RIGHTUP))

    def mouse_down(self):
        _send(_mouse(MOUSEEVENTF_LEFTDOWN))

    def mouse_up(self):
        _send(_mouse(MOUSEEVENTF_LEFTUP))

    def scroll(self, dx, dy):
        # Positive WHEEL scrolls up (content moves down), matching positive
        # dy. Positive HWHEEL scrolls right (content moves left), so dx flips.
        self._wheel_rem[0] += -dx * WHEEL_UNITS_PER_PIXEL
        self._wheel_rem[1] += dy * WHEEL_UNITS_PER_PIXEL
        h, v = int(self._wheel_rem[0]), int(self._wheel_rem[1])
        self._wheel_rem[0] -= h
        self._wheel_rem[1] -= v
        events = []
        if v:
            events.append(_mouse(MOUSEEVENTF_WHEEL, data=v))
        if h:
            events.append(_mouse(MOUSEEVENTF_HWHEEL, data=h))
        if events:
            _send(*events)

    def type_text(self, text):
        # KEYEVENTF_UNICODE types a UTF-16 code unit directly, independent
        # of the keyboard layout. Characters outside the BMP (most emoji)
        # are two code units, sent as two key presses — which is how
        # Windows expects them.
        data = text.encode("utf-16-le")
        units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
        events = []
        for unit in units:
            events.append(_key(scan=unit, flags=KEYEVENTF_UNICODE))
            events.append(_key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        if events:
            _send(*events)

    def press_key(self, key, count=1):
        vk = VK_CODES.get(key)
        if vk is None:
            return
        events = []
        for _ in range(max(1, min(int(count), 500))):
            events.append(_key(vk=vk))
            events.append(_key(vk=vk, flags=KEYEVENTF_KEYUP))
        _send(*events)


# ---------- Dialogs ----------

MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONQUESTION = 0x20
MB_ICONINFORMATION = 0x40
MB_SETFOREGROUND = 0x10000
MB_TOPMOST = 0x40000
IDYES = 6

user32.MessageBoxW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, c_uint32)
user32.MessageBoxW.restype = c_int32


def _message_box(title, message, flags):
    # Tray apps have no window of their own, so without these flags the
    # dialog can open behind whatever the user has focused.
    return user32.MessageBoxW(None, message, title, flags | MB_SETFOREGROUND | MB_TOPMOST)


# ---------- System tray app (pystray) ----------

def render_qr_card(url):
    """The QR code with the URL printed under it, as an image."""
    qr = qrcode.make(url, box_size=10, border=3).convert("RGB")
    label_h = 40
    card = Image.new("RGB", (qr.width, qr.height + label_h), "white")
    card.paste(qr, (0, 0))
    draw = ImageDraw.Draw(card)
    text_w = draw.textlength(url)
    draw.text(((card.width - text_w) / 2, qr.height + 8), url, fill="black")
    return card


class WindowsTray(Tray):
    """A system tray icon. Windows 11 hides new tray icons in the overflow
    (^) menu by default, so the QR code also opens on launch — otherwise a
    first-time user might not find the app at all."""

    def __init__(self, url, port, dev, icon_path):
        self.url = url
        self.port = port
        self.dev = dev
        self.update_item = None  # (title, callback)
        # Per port, so a dev server and the installed app don't overwrite
        # each other's QR code.
        self.qr_path = os.path.join(tempfile.gettempdir(), f"mousephone-qr-{port}.png")
        render_qr_card(url).save(self.qr_path)

        tooltip = f"mousephone (DEV · port {port})" if dev else "mousephone"
        self.icon = pystray.Icon(
            "mousephone",
            Image.open(icon_path),
            tooltip,
            # A callable menu is rebuilt whenever update_menu() is called,
            # which is how the update item's title changes.
            menu=pystray.Menu(self._menu_items),
        )

    def _menu_items(self):
        items = []
        if self.dev:
            items += [pystray.MenuItem(f"Dev server · port {self.port}", lambda: None, enabled=False),
                      pystray.Menu.SEPARATOR]
        # default=True: also what a click on the tray icon itself does.
        items.append(pystray.MenuItem("Show QR Code", self._show_qr, default=True))
        if self.update_item:
            title, callback = self.update_item
            items.append(pystray.MenuItem(title, lambda: callback()))
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Quit", self.quit)]
        return items

    def _show_qr(self):
        os.startfile(self.qr_path)

    def set_update_item(self, title, callback):
        self.update_item = (title, callback)
        self.icon.update_menu()

    def alert(self, title, message):
        _message_box(title, message, MB_OK | MB_ICONINFORMATION)

    def confirm(self, title, message, ok, cancel):
        # MessageBox can't relabel its buttons, so this is Yes/No and the
        # title is phrased as the question.
        return _message_box(title, message, MB_YESNO | MB_ICONQUESTION) == IDYES

    def call_on_main(self, fn, *args):
        # pystray's menu and MessageBox are safe to use from any thread on
        # Windows, so there's no UI thread to hop to.
        fn(*args)

    def every(self, seconds, fn):
        def loop():
            stop = threading.Event()
            while not stop.wait(seconds):
                fn()

        threading.Thread(target=loop, daemon=True).start()

    def open_url(self, url):
        webbrowser.open(url)

    def quit(self):
        self.icon.stop()

    def run(self):
        def setup(icon):
            icon.visible = True
            self._show_qr()
            try:
                icon.notify("mousephone is running. Find it in the system tray to show the QR code again.")
            except Exception:
                pass  # notifications can be turned off; not essential

        self.icon.run(setup=setup)


# ---------- Updates (Inno Setup installer) ----------

# Runs detached after the app quits: waits for it to exit, runs the new
# installer silently (it relaunches the app when done), then cleans up.
_UPDATE_SCRIPT = """
param([int]$AppPid, [string]$Installer, [string]$Staging)
Wait-Process -Id $AppPid -ErrorAction SilentlyContinue
Start-Process -FilePath $Installer -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait
Remove-Item -LiteralPath $Staging -Recurse -Force -ErrorAction SilentlyContinue
"""

# Prints "<status> <thumbprint>" for the file in $env:MOUSEPHONE_VERIFY.
# The path goes through the environment so it never needs quoting.
_SIGNATURE_SCRIPT = (
    "$s = Get-AuthenticodeSignature -LiteralPath $env:MOUSEPHONE_VERIFY; "
    "if ($s.SignerCertificate) { \"$($s.Status) $($s.SignerCertificate.Thumbprint)\" }"
)

# Statuses that still mean "the file is intact and was signed by this
# certificate". Ours is self-signed, so Windows can't chain it to a trusted
# root and reports UnknownError/NotTrusted rather than Valid; tampering
# shows up as HashMismatch, which is rejected.
_INTACT_STATUSES = {"Valid", "UnknownError", "NotTrusted"}

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _signature(path):
    """(status, thumbprint) of a file's Authenticode signature, or None if unsigned."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _SIGNATURE_SCRIPT],
        env={**os.environ, "MOUSEPHONE_VERIFY": path},
        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
    )
    parts = result.stdout.strip().split()
    return (parts[0], parts[1]) if len(parts) == 2 else None


class WindowsInstaller(Installer):
    def asset_name(self, version):
        # Deliberately not a .zip: Mac builds up to 1.2.0 take the first
        # .zip in a release as their update.
        return f"mousephone-{version}-windows-setup.exe"

    def current_install(self):
        if not getattr(sys, "frozen", False):
            return None
        return os.path.abspath(sys.executable)

    def can_install(self):
        # Installed per-user (no admin), so the app's own folder is writable.
        exe = self.current_install()
        return exe is not None and os.access(os.path.dirname(exe), os.W_OK)

    def make_staging_dir(self):
        return tempfile.mkdtemp(prefix="mousephone-update-")

    def prepare(self, download_path, staging_dir):
        # Only run an installer signed by the same certificate as this app.
        # That rejects a tampered or unrelated download.
        ours = _signature(self.current_install())
        theirs = _signature(download_path)
        if ours is None:
            raise UpdateError(
                "This copy of mousephone isn't signed, so it can't verify updates. "
                "Download the new version manually from the release page."
            )
        if theirs is None or theirs[0] not in _INTACT_STATUSES or theirs[1] != ours[1]:
            raise UpdateError(
                "The update isn't signed the same way as this copy of mousephone, "
                "so it wasn't installed. Download it manually from the release page."
            )
        return download_path, staging_dir

    def install_and_relaunch(self, prepared):
        installer, staging_dir = prepared
        script = os.path.join(staging_dir, "update.ps1")
        with open(script, "w", encoding="utf-8") as f:
            f.write(_UPDATE_SCRIPT)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-WindowStyle", "Hidden", "-File", script,
             "-AppPid", str(os.getpid()), "-Installer", installer, "-Staging", staging_dir],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True,
        )
