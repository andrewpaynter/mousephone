#!/usr/bin/env python3
"""
Phone-as-Mouse server for Mac.

Run this on your Mac, then open the printed URL in your phone's browser
(while on the same Wi-Fi network) to use your phone as a trackpad.

Setup:
    pip3 install aiohttp pyobjc-framework-Quartz "qrcode[pil]"

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


# ---------- Mouse control (macOS Quartz) ----------

class Mouse:
    def __init__(self):
        bounds = CGDisplayBounds(CGMainDisplayID())
        self.width = bounds.size.width
        self.height = bounds.size.height
        self.x, self.y = self._current_location()
        self.dragging = False

    def _current_location(self):
        loc = CGEventGetLocation(CGEventCreate(None))
        return loc.x, loc.y

    def move(self, dx, dy):
        self.x = min(max(self.x + dx, 0), self.width - 1)
        self.y = min(max(self.y + dy, 0), self.height - 1)
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
    print("If the cursor doesn't move, grant Accessibility permission")
    print("to this app in System Settings > Privacy & Security > Accessibility")
    print("=" * 50)

    # Show the QR code (ASCII in the terminal if there is one, and an
    # image window either way — a double-clicked .app has no terminal).
    threading.Thread(target=show_qr, args=(url,), daemon=True).start()

    web.run_app(app, host="0.0.0.0", port=port, print=None)


if __name__ == "__main__":
    main()
