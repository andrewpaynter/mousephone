#!/usr/bin/env python3
"""
Phone-as-Mouse server for Mac.

Run this on your Mac, then open the printed URL in your phone's browser
(while on the same Wi-Fi network) to use your phone as a trackpad.

Setup:
    pip3 install aiohttp pyobjc-framework-Quartz "qrcode[pil]" rumps

Run:
    python3 mouse_server.py

You will likely need to grant Accessibility permission to Terminal (or
whatever app you run this from) in:
    System Settings > Privacy & Security > Accessibility
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading

try:
    from aiohttp import web, WSMsgType
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install aiohttp")
    sys.exit(1)

try:
    from Quartz import (
        CGEventCreateMouseEvent,
        CGEventCreateScrollWheelEvent,
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
    import qrcode
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install \"qrcode[pil]\"")
    sys.exit(1)

try:
    import rumps
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install rumps")
    sys.exit(1)


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


# ---------- Mouse control (macOS Quartz) ----------

class Mouse:
    def __init__(self):
        self.min_x, self.min_y, self.max_x, self.max_y = get_desktop_bounds()
        self.x, self.y = self._current_location()
        self.dragging = False

    def _current_location(self):
        loc = CGEventGetLocation(CGEventCreate(None))
        return loc.x, loc.y

    def move(self, dx, dy):
        self.x = min(max(self.x + dx, self.min_x), self.max_x - 1)
        self.y = min(max(self.y + dy, self.min_y), self.max_y - 1)
        event_type = kCGEventLeftMouseDragged if self.dragging else kCGEventMouseMoved
        event = CGEventCreateMouseEvent(
            None, event_type, (self.x, self.y), kCGMouseButtonLeft
        )
        CGEventPost(kCGHIDEventTap, event)

    def click(self, button="left"):
        if button == "left":
            down, up, btn = kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft
        else:
            down, up, btn = kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonRight
        for etype in (down, up):
            event = CGEventCreateMouseEvent(None, etype, (self.x, self.y), btn)
            CGEventPost(kCGHIDEventTap, event)

    def mouse_down(self):
        self.dragging = True
        event = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, (self.x, self.y), kCGMouseButtonLeft
        )
        CGEventPost(kCGHIDEventTap, event)

    def mouse_up(self):
        self.dragging = False
        event = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, (self.x, self.y), kCGMouseButtonLeft
        )
        CGEventPost(kCGHIDEventTap, event)

    def scroll(self, dx, dy):
        event = CGEventCreateScrollWheelEvent(
            None, kCGScrollEventUnitPixel, 2, int(dy), int(dx)
        )
        CGEventPost(kCGHIDEventTap, event)


mouse = Mouse()


# ---------- Web server ----------

async def index(request):
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except ValueError:
                continue

            t = data.get("type")
            if t == "move":
                mouse.move(data.get("dx", 0), data.get("dy", 0))
            elif t == "click":
                mouse.click(data.get("button", "left"))
            elif t == "down":
                mouse.mouse_down()
            elif t == "up":
                mouse.mouse_up()
            elif t == "scroll":
                mouse.scroll(data.get("dx", 0), data.get("dy", 0))
        elif msg.type == WSMsgType.ERROR:
            break

    return ws


def print_qr_ascii(url):
    """Print a scannable QR code as text — visible when run from Terminal
    or the .command launcher."""
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make()
    qr.print_ascii(invert=True)


def show_qr_image(url):
    """Open a QR code image window — needed because a double-clicked .app
    has no visible Terminal to print ASCII art to."""
    img = qrcode.make(url)
    path = os.path.join(tempfile.gettempdir(), "phone_mouse_qr.png")
    img.save(path)
    subprocess.run(["open", path], check=False)


def show_qr(url):
    try:
        print_qr_ascii(url)
    except Exception:
        pass
    try:
        show_qr_image(url)
    except Exception:
        pass


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Phone Mouse</title>
<style>
  html, body {
    margin: 0; padding: 0; height: 100%; width: 100%;
    background: #111; color: #eee; font-family: -apple-system, sans-serif;
    overflow: hidden; touch-action: none; -webkit-user-select: none; user-select: none;
  }
  #status {
    position: fixed; top: 8px; left: 0; right: 0; text-align: center;
    font-size: 13px; color: #888; z-index: 10;
  }
  #hint {
    position: fixed; top: 50%; left: 0; right: 0; text-align: center;
    font-size: 13px; color: #555; pointer-events: none;
  }
  #trackpad {
    position: absolute; top: 0; left: 0; right: 0; bottom: 70px;
    background: #1c1c1e;
  }
  #buttons {
    position: fixed; bottom: 0; left: 0; right: 0; height: 70px;
    display: flex;
  }
  .btn {
    flex: 1; display: flex; align-items: center; justify-content: center;
    background: #2c2c2e; color: #ccc; font-size: 16px;
    border-top: 1px solid #444;
  }
  .btn.active { background: #3a3a3c; }
  #left-btn { border-right: 1px solid #444; }
</style>
</head>
<body>
  <div id="status">connecting…</div>
  <div id="trackpad"><div id="hint">1 finger: move &middot; 2 fingers: scroll &middot; tap: click</div></div>
  <div id="buttons">
    <div class="btn" id="left-btn">Left Click</div>
    <div class="btn" id="right-btn">Right Click</div>
  </div>

<script>
const statusEl = document.getElementById('status');
const trackpad = document.getElementById('trackpad');
const leftBtn = document.getElementById('left-btn');
const rightBtn = document.getElementById('right-btn');

const SENSITIVITY = 1.6;
const SCROLL_SENSITIVITY = 1.2;

let ws;
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => statusEl.textContent = 'connected';
  ws.onclose = () => {
    statusEl.textContent = 'disconnected — retrying…';
    setTimeout(connect, 1500);
  };
  ws.onerror = () => ws.close();
}
connect();

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

// --- Trackpad touch handling ---
let touches = {};
let maxTouchCount = 0;
let startTime = 0;
let moved = false;

trackpad.addEventListener('touchstart', (e) => {
  e.preventDefault();
  document.getElementById('hint').style.display = 'none';
  for (const t of e.changedTouches) {
    touches[t.identifier] = { x: t.clientX, y: t.clientY };
  }
  const count = Object.keys(touches).length;
  maxTouchCount = Math.max(maxTouchCount, count);
  if (count === 1) {
    startTime = Date.now();
    moved = false;
  }
}, { passive: false });

trackpad.addEventListener('touchmove', (e) => {
  e.preventDefault();
  const ids = Object.keys(touches);

  if (ids.length === 1) {
    const id = ids[0];
    const t = [...e.touches].find(t => String(t.identifier) === id);
    if (!t) return;
    const prev = touches[id];
    const dx = t.clientX - prev.x;
    const dy = t.clientY - prev.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    send({ type: 'move', dx: dx * SENSITIVITY, dy: dy * SENSITIVITY });
    touches[id] = { x: t.clientX, y: t.clientY };
  } else if (ids.length === 2) {
    let dxSum = 0, dySum = 0, n = 0;
    for (const t of e.touches) {
      const id = String(t.identifier);
      if (touches[id]) {
        dxSum += t.clientX - touches[id].x;
        dySum += t.clientY - touches[id].y;
        touches[id] = { x: t.clientX, y: t.clientY };
        n++;
      }
    }
    if (n > 0) {
      moved = true;
      send({
        type: 'scroll',
        dx: (dxSum / n) * SCROLL_SENSITIVITY,
        dy: (dySum / n) * SCROLL_SENSITIVITY,
      });
    }
  }
}, { passive: false });

trackpad.addEventListener('touchend', (e) => {
  e.preventDefault();
  const wasTap = !moved && (Date.now() - startTime) < 300;
  if (wasTap) {
    if (maxTouchCount === 1) send({ type: 'click', button: 'left' });
    else if (maxTouchCount === 2) send({ type: 'click', button: 'right' });
  }
  for (const t of e.changedTouches) {
    delete touches[t.identifier];
  }
  if (Object.keys(touches).length === 0) {
    maxTouchCount = 0;
  }
}, { passive: false });

// --- Buttons (hold left button + move trackpad to drag) ---
function bindButton(el, button) {
  el.addEventListener('touchstart', (e) => {
    e.preventDefault();
    el.classList.add('active');
    if (button === 'left') send({ type: 'down' });
  }, { passive: false });
  el.addEventListener('touchend', (e) => {
    e.preventDefault();
    el.classList.remove('active');
    if (button === 'left') send({ type: 'up' });
    else send({ type: 'click', button: 'right' });
  }, { passive: false });
}
bindButton(leftBtn, 'left');
bindButton(rightBtn, 'right');
</script>
</body>
</html>
"""


def is_accessibility_trusted():
    """Check Accessibility permission without needing an extra pip package —
    calls AXIsProcessTrusted() straight from the system framework via ctypes."""
    try:
        import ctypes

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


def main():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket_handler)

    port = 8765
    ip = get_local_ip()
    url = f"http://{ip}:{port}"

    print("=" * 50)
    print("Phone-as-Mouse server running")
    print(f"On your phone (same Wi-Fi), scan this QR code, or open:\n  {url}")
    print("=" * 50)

    trusted = is_accessibility_trusted()
    if not trusted:
        print("Accessibility permission NOT granted — the cursor will not move.")
        print("System Settings > Privacy & Security > Accessibility")
    print("=" * 50)

    # Run the web/WebSocket server on a background thread. handle_signals=False
    # is required here — aiohttp's signal handling only works on the main
    # thread, which we're reserving for the Cocoa run loop below.
    def _run_server():
        web.run_app(app, host="0.0.0.0", port=port, print=None, handle_signals=False)

    threading.Thread(target=_run_server, daemon=True).start()

    # Show the QR code once at launch.
    threading.Thread(target=show_qr, args=(url,), daemon=True).start()

    # Hand the main thread to a minimal Cocoa run loop via rumps. This is
    # what makes the app respond to Launch Services at startup — without
    # it, a double-clicked .app that never touches AppKit can trigger
    # "You can't open Phone Mouse.app because it is not responding," even
    # though the server itself is running fine. It also adds a menu bar
    # icon so there's a visible way to re-show the QR code or quit.
    class PhoneMouseApp(rumps.App):
        def __init__(self):
            super().__init__("🖱" if trusted else "🖱⚠️", quit_button="Quit")
            self.menu = ["Show QR Code", "Check Accessibility Permission"]

        @rumps.clicked("Show QR Code")
        def show_qr_clicked(self, _):
            threading.Thread(target=show_qr, args=(url,), daemon=True).start()

        @rumps.clicked("Check Accessibility Permission")
        def check_permission_clicked(self, _):
            if is_accessibility_trusted():
                rumps.alert(title="Phone Mouse", message="Accessibility permission is granted. You're all set.")
            else:
                rumps.alert(
                    title="Accessibility Permission Needed",
                    message=(
                        "Phone Mouse can't move the cursor without this.\n\n"
                        "In the Accessibility list, remove any existing "
                        "\u201cPhone Mouse\u201d entry first (select it, click \u2212), "
                        "then add this app back and turn it on. Then quit and "
                        "reopen Phone Mouse."
                    ),
                )
                open_accessibility_settings()

    if not trusted:
        rumps.alert(
            title="Accessibility Permission Needed",
            message=(
                "Phone Mouse can't move the cursor without this.\n\n"
                "In the Accessibility list, remove any existing "
                "\u201cPhone Mouse\u201d entry first (select it, click \u2212), "
                "then add this app back and turn it on. Then quit and "
                "reopen Phone Mouse."
            ),
        )
        open_accessibility_settings()

    PhoneMouseApp().run()


if __name__ == "__main__":
    main()
