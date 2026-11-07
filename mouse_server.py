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

import io
import json
import os
import socket
import subprocess
import sys
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
    import qrcode
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install \"qrcode[pil]\"")
    sys.exit(1)

try:
    import rumps
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install rumps")
    sys.exit(1)

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

import updater

# Bump this in a PR before running tools/release.sh. setup.py reads it for
# the app's Info.plist, and the updater compares it to the latest release.
__version__ = "1.1.0"

UPDATE_CHECK_INTERVAL = 6 * 60 * 60  # seconds

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
MENU_BAR_ICON = os.path.join(ASSETS_DIR, "menu_bar_icon.png")


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
        self.x, self.y = self._current_location()
        self.dragging = False

    def _current_location(self):
        loc = CGEventGetLocation(CGEventCreate(None))
        return loc.x, loc.y

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


# ---------- Keyboard (macOS Quartz) ----------

# Virtual key codes for the few non-character keys the phone sends.
KEY_CODES = {"backspace": 51, "return": 36}


class Keyboard:
    def type_text(self, text):
        """Type arbitrary text (accents, emoji, any language) by attaching
        the characters to a synthetic key event, rather than mapping each
        one to a physical key on a particular keyboard layout."""
        for ch in text:
            length = len(ch.encode("utf-16-le")) // 2  # emoji are 2 UTF-16 units
            for key_down in (True, False):
                event = CGEventCreateKeyboardEvent(None, 0, key_down)
                CGEventSetFlags(event, 0)  # ignore any modifiers held on the Mac
                CGEventKeyboardSetUnicodeString(event, length, ch)
                CGEventPost(kCGHIDEventTap, event)

    def press(self, key, count=1):
        code = KEY_CODES.get(key)
        if code is None:
            return
        for _ in range(max(1, min(int(count), 500))):
            for key_down in (True, False):
                event = CGEventCreateKeyboardEvent(None, code, key_down)
                CGEventSetFlags(event, 0)
                CGEventPost(kCGHIDEventTap, event)


keyboard = Keyboard()


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
            elif t == "text":
                keyboard.type_text(str(data.get("text", "")))
            elif t == "key":
                keyboard.press(data.get("key"), data.get("count", 1))
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
<title>mousephone</title>
<style>
  html, body {
    margin: 0; padding: 0; height: 100%; width: 100%;
    background: #111; color: #eee; font-family: -apple-system, sans-serif;
    overflow: hidden; touch-action: none; -webkit-user-select: none; user-select: none;
  }
  /* Everything lives in #app, which JS sizes to the visual viewport so the
     layout shrinks to fit above the phone's keyboard instead of being
     covered by it. */
  #app { position: fixed; top: 0; left: 0; right: 0; height: 100%; }
  #status {
    position: absolute; top: 8px; left: 0; right: 0; text-align: center;
    font-size: 13px; color: #888; z-index: 10; pointer-events: none;
  }
  #hint {
    position: absolute; top: 50%; left: 0; right: 0; text-align: center;
    font-size: 13px; color: #555; pointer-events: none;
  }
  #trackpad {
    position: absolute; top: 0; left: 0; right: 0; bottom: 70px;
    background: #1c1c1e;
  }
  body.typing #trackpad { bottom: 118px; }
  #buttons {
    position: absolute; bottom: 0; left: 0; right: 0; height: 70px;
    display: flex;
  }

  /* Keyboard toggle: opening takes a press-and-hold, closing a single tap. */
  #kbd-btn {
    position: absolute; top: 12px; right: 12px; width: 48px; height: 48px;
    border-radius: 14px; background: #2c2c2e; border: 1px solid #444;
    display: flex; align-items: center; justify-content: center;
    color: #888; z-index: 20;
  }
  #kbd-btn svg.icon { width: 26px; height: 26px; }
  #kbd-btn .ring {
    position: absolute; inset: -4px; width: 56px; height: 56px;
    pointer-events: none;
  }
  #kbd-btn .ring rect {
    fill: none; stroke: #0a84ff; stroke-width: 3;
    stroke-dasharray: 200; stroke-dashoffset: 200;
  }
  #kbd-btn.holding .ring rect {
    stroke-dashoffset: 0; transition: stroke-dashoffset 500ms linear;
  }
  #kbd-btn.ready, body.typing #kbd-btn { color: #fff; background: #0a84ff; border-color: #0a84ff; }
  #kbd-tip {
    position: absolute; top: 68px; right: 12px; padding: 6px 10px;
    border-radius: 8px; background: #3a3a3c; color: #ddd; font-size: 13px;
    opacity: 0; transition: opacity 200ms; pointer-events: none; z-index: 20;
  }
  #kbd-tip.show { opacity: 1; }
  #kbd-bar {
    position: absolute; bottom: 70px; left: 0; right: 0; height: 48px;
    display: none; align-items: center; justify-content: space-between;
    padding: 0 0 0 16px; background: #2c2c2e; border-top: 1px solid #444;
    font-size: 14px; color: #888;
  }
  body.typing #kbd-bar { display: flex; }
  #kbd-done {
    height: 100%; padding: 0 24px; display: flex; align-items: center;
    color: #0a84ff; font-size: 17px; font-weight: 600;
  }
  /* Hidden but focusable: it has to be a real text field for the phone to
     show its keyboard. 16px font stops iOS from zooming in on focus. */
  #kbd-input {
    position: fixed; top: 0; left: 0; width: 1px; height: 1px;
    opacity: 0; border: 0; padding: 0; resize: none; font-size: 16px;
    caret-color: transparent;
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
  <textarea id="kbd-input" autocomplete="off" autocapitalize="sentences"></textarea>
  <div id="app">
    <div id="status">connecting…</div>
    <div id="trackpad"><div id="hint">1 finger: move &middot; 2 fingers: scroll &middot; tap: click</div></div>
    <div id="kbd-btn" aria-label="Hold to open keyboard">
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
        <rect x="2.5" y="6" width="19" height="12" rx="2"/>
        <path d="M6 9.5h.01M9 9.5h.01M12 9.5h.01M15 9.5h.01M18 9.5h.01M6 12.5h.01M18 12.5h.01M9 12.5h6M8 15h8"/>
      </svg>
      <svg class="ring" viewBox="0 0 56 56"><rect x="2" y="2" width="52" height="52" rx="16"/></svg>
    </div>
    <div id="kbd-tip">Hold to open keyboard</div>
    <div id="kbd-bar">Typing on Mac<div id="kbd-done">Done</div></div>
    <div id="buttons">
      <div class="btn" id="left-btn">Left Click</div>
      <div class="btn" id="right-btn">Right Click</div>
    </div>
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

// --- Scroll momentum ---
// While two fingers are moving we keep a short rolling history of scroll
// deltas with timestamps. On lift-off we derive a release velocity from
// that history and let it decay over a few frames, so the scroll carries
// on a little past the fingers lifting instead of stopping dead.
const MOMENTUM_HISTORY_MS = 80;   // how far back to look when computing release velocity
const MOMENTUM_HALF_LIFE_MS = 120; // velocity halves this often while coasting
const MOMENTUM_MIN_VELOCITY = 0.02; // px/ms — below this, stop
const MOMENTUM_MAX_VELOCITY = 3;    // px/ms — clamp noisy release velocities
let scrollHistory = [];
let momentumFrame = null;

function stopMomentum() {
  if (momentumFrame !== null) {
    cancelAnimationFrame(momentumFrame);
    momentumFrame = null;
  }
}

function clampVelocity(v) {
  return Math.max(-MOMENTUM_MAX_VELOCITY, Math.min(MOMENTUM_MAX_VELOCITY, v));
}

function startMomentum(vx, vy) {
  vx = clampVelocity(vx);
  vy = clampVelocity(vy);
  if (Math.abs(vx) < MOMENTUM_MIN_VELOCITY && Math.abs(vy) < MOMENTUM_MIN_VELOCITY) return;

  stopMomentum();
  let lastTime = performance.now();
  const step = (now) => {
    const dt = now - lastTime;
    lastTime = now;
    const decay = Math.pow(0.5, dt / MOMENTUM_HALF_LIFE_MS);
    vx *= decay;
    vy *= decay;
    if (Math.abs(vx) < MOMENTUM_MIN_VELOCITY && Math.abs(vy) < MOMENTUM_MIN_VELOCITY) {
      momentumFrame = null;
      return;
    }
    send({
      type: 'scroll',
      dx: vx * dt * SCROLL_SENSITIVITY,
      dy: vy * dt * SCROLL_SENSITIVITY,
    });
    momentumFrame = requestAnimationFrame(step);
  };
  momentumFrame = requestAnimationFrame(step);
}

function releaseVelocity() {
  if (scrollHistory.length < 2) return { vx: 0, vy: 0 };
  const first = scrollHistory[0];
  const last = scrollHistory[scrollHistory.length - 1];
  const dt = last.t - first.t;
  if (dt <= 0) return { vx: 0, vy: 0 };
  let sumDx = 0, sumDy = 0;
  for (let i = 1; i < scrollHistory.length; i++) {
    sumDx += scrollHistory[i].dx;
    sumDy += scrollHistory[i].dy;
  }
  return { vx: sumDx / dt, vy: sumDy / dt };
}

trackpad.addEventListener('touchstart', (e) => {
  e.preventDefault();
  document.getElementById('hint').style.display = 'none';
  stopMomentum();
  for (const t of e.changedTouches) {
    touches[t.identifier] = { x: t.clientX, y: t.clientY };
  }
  const count = Object.keys(touches).length;
  maxTouchCount = Math.max(maxTouchCount, count);
  if (count === 1) {
    startTime = Date.now();
    moved = false;
  }
  if (count === 2) {
    scrollHistory = [];
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
      const dx = dxSum / n, dy = dySum / n;
      const now = performance.now();
      scrollHistory.push({ dx, dy, t: now });
      while (scrollHistory.length > 1 && now - scrollHistory[0].t > MOMENTUM_HISTORY_MS) {
        scrollHistory.shift();
      }
      send({
        type: 'scroll',
        dx: dx * SCROLL_SENSITIVITY,
        dy: dy * SCROLL_SENSITIVITY,
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
    if (maxTouchCount === 2 && moved) {
      const { vx, vy } = releaseVelocity();
      startMomentum(vx, vy);
    }
    maxTouchCount = 0;
    scrollHistory = [];
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

// --- Keyboard ---
// Uses the phone's own keyboard via a hidden textarea. Rather than trying
// to interpret individual key presses (mobile keyboards mostly don't
// report them), every change to the textarea is diffed against its
// previous contents and replayed on the Mac as backspaces + typed text.
// That makes autocorrect, predictive text, swipe typing and dictation all
// just work: a correction is "delete the old word, type the new one."
const app = document.getElementById('app');
const kbdBtn = document.getElementById('kbd-btn');
const kbdTip = document.getElementById('kbd-tip');
const kbdDone = document.getElementById('kbd-done');
const kbdInput = document.getElementById('kbd-input');

const KBD_HOLD_MS = 500;      // must match the ring's CSS transition
const KBD_HOLD_SLOP_PX = 12;  // finger drift allowed while holding
// The textarea always starts with this invisible character, so pressing
// backspace has something to delete (an empty field fires no event).
const SENTINEL = '\\u200B';
const segmenter = window.Intl && Intl.Segmenter ? new Intl.Segmenter() : null;

let kbdPrev = SENTINEL;

function graphemes(s) {
  // Split into user-visible characters, so one emoji = one backspace.
  return segmenter ? Array.from(segmenter.segment(s), g => g.segment) : Array.from(s);
}

function resetKbdBuffer() {
  kbdInput.value = SENTINEL;
  kbdInput.setSelectionRange(SENTINEL.length, SENTINEL.length);
  kbdPrev = SENTINEL;
}

kbdInput.addEventListener('input', () => {
  const before = graphemes(kbdPrev);
  const after = graphemes(kbdInput.value);
  let i = 0;
  while (i < before.length && i < after.length && before[i] === after[i]) i++;

  const deleted = before.length - i;
  if (deleted > 0) send({ type: 'key', key: 'backspace', count: deleted });

  const lines = after.slice(i).join('').split(SENTINEL).join('').split('\\n');
  lines.forEach((line, n) => {
    if (n > 0) send({ type: 'key', key: 'return' });
    if (line) send({ type: 'text', text: line });
  });

  kbdPrev = kbdInput.value;
  // Start fresh after Return or once the backspace hit the sentinel; also
  // keep the buffer from growing forever in one long paragraph.
  if (lines.length > 1 || !kbdPrev.startsWith(SENTINEL) ||
      (kbdPrev.length > 300 && /\\s$/.test(kbdPrev))) {
    resetKbdBuffer();
  }
});

function openKeyboard() {
  // Must run synchronously inside a touch handler, or iOS won't show the keyboard.
  resetKbdBuffer();
  kbdInput.focus();
}

function closeKeyboard() {
  kbdInput.blur();
}

// The "typing" state follows real focus, so dismissing the keyboard any
// way at all (Done, the button, the keyboard's own hide key) closes it.
kbdInput.addEventListener('focus', () => document.body.classList.add('typing'));
kbdInput.addEventListener('blur', () => {
  document.body.classList.remove('typing');
  resetKbdBuffer();
});

let holdTimer = null;
let holdOrigin = null;
let holdReady = false;
let tipTimer = null;

function cancelHold() {
  clearTimeout(holdTimer);
  holdTimer = null;
  holdOrigin = null;
  holdReady = false;
  kbdBtn.classList.remove('holding', 'ready');
}

function showTip() {
  kbdTip.classList.add('show');
  clearTimeout(tipTimer);
  tipTimer = setTimeout(() => kbdTip.classList.remove('show'), 1500);
}

kbdBtn.addEventListener('touchstart', (e) => {
  e.preventDefault();
  if (document.body.classList.contains('typing')) return;  // tap to close, on touchend
  const t = e.changedTouches[0];
  holdOrigin = { x: t.clientX, y: t.clientY };
  holdReady = false;
  kbdBtn.classList.add('holding');
  holdTimer = setTimeout(() => {
    holdReady = true;
    kbdBtn.classList.add('ready');
    if (navigator.vibrate) navigator.vibrate(10);
  }, KBD_HOLD_MS);
}, { passive: false });

kbdBtn.addEventListener('touchmove', (e) => {
  e.preventDefault();
  if (!holdOrigin) return;
  const t = e.changedTouches[0];
  if (Math.hypot(t.clientX - holdOrigin.x, t.clientY - holdOrigin.y) > KBD_HOLD_SLOP_PX) {
    cancelHold();
  }
}, { passive: false });

kbdBtn.addEventListener('touchend', (e) => {
  e.preventDefault();
  if (document.body.classList.contains('typing')) {
    closeKeyboard();
    return;
  }
  const wasHolding = holdOrigin !== null;
  const ready = holdReady;
  cancelHold();
  // Opens on release after a full hold: the keyboard can only be summoned
  // from a direct touch event, not from the hold timer.
  if (ready) openKeyboard();
  else if (wasHolding) showTip();
}, { passive: false });

kbdBtn.addEventListener('touchcancel', cancelHold);

kbdDone.addEventListener('touchstart', (e) => e.preventDefault(), { passive: false });
kbdDone.addEventListener('touchend', (e) => {
  e.preventDefault();
  closeKeyboard();
}, { passive: false });

// Fit the layout to the part of the screen the keyboard isn't covering.
function fitToViewport() {
  const vv = window.visualViewport;
  if (!vv) return;
  app.style.top = vv.offsetTop + 'px';
  app.style.height = vv.height + 'px';
}
if (window.visualViewport) {
  visualViewport.addEventListener('resize', fitToViewport);
  visualViewport.addEventListener('scroll', fitToViewport);
}
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

    try:
        print_qr_ascii(url)
    except Exception:
        pass

    # Hand the main thread to a minimal Cocoa run loop via rumps. This is
    # what makes the app respond to Launch Services at startup — without
    # it, a double-clicked .app that never touches AppKit can trigger
    # "You can't open mousephone.app because it is not responding," even
    # though the server itself is running fine. It also adds a menu bar
    # icon whose dropdown shows the QR code directly, so there's no need
    # to open a separate image window to scan it.
    class MousephoneApp(rumps.App):
        def __init__(self):
            super().__init__(
                "mousephone", icon=MENU_BAR_ICON, template=True, quit_button="Quit"
            )
            items = [build_qr_menu_item(url), None, "Check Accessibility Permission"]

            # Updates only apply to the built .app — under dev.sh there's
            # no bundle to replace, so the menu item is left out entirely.
            self.app_path = updater.current_app_path()
            self.available_update = None
            self.updating = False
            if self.app_path:
                self.update_item = rumps.MenuItem("Check for Updates", callback=self.update_clicked)
                items.insert(2, self.update_item)
                self.update_timer = rumps.Timer(self.background_check, UPDATE_CHECK_INTERVAL)
                self.update_timer.start()
                self.background_check()

            self.menu = items

        # Network work runs on background threads; anything touching the
        # menu or showing an alert is handed back to the main thread.
        def background_check(self, _=None):
            threading.Thread(target=self._check_for_update, args=(False,), daemon=True).start()

        def _check_for_update(self, manual):
            try:
                update = updater.check_for_update(__version__)
            except Exception:
                if manual:
                    AppHelper.callAfter(
                        rumps.alert, title="mousephone",
                        message="Couldn't check for updates. Check your internet connection and try again.",
                    )
                return
            AppHelper.callAfter(self._on_check_result, update, manual)

        def _on_check_result(self, update, manual):
            if self.updating:
                return
            self.available_update = update
            self.update_item.title = (
                f"Update to v{update['version']}…" if update else "Check for Updates"
            )
            if manual:
                if update:
                    self._prompt_install()
                else:
                    rumps.alert(title="mousephone", message=f"You're up to date (v{__version__}).")

        def update_clicked(self, _):
            if self.updating:
                return
            if self.available_update:
                self._prompt_install()
            else:
                threading.Thread(target=self._check_for_update, args=(True,), daemon=True).start()

        def _prompt_install(self):
            update = self.available_update
            if not updater.can_install(self.app_path):
                rumps.alert(
                    title=f"mousephone {update['version']} is available",
                    message=(
                        "mousephone can't replace itself in its current folder. "
                        "Download the new version from the release page and drag "
                        "it into Applications."
                    ),
                )
                subprocess.run(["open", update["page_url"]], check=False)
                return
            if rumps.alert(
                title=f"Update to mousephone {update['version']}?",
                message="mousephone will download the update and restart. It only takes a few seconds.",
                ok="Update",
                cancel="Not Now",
            ) != 1:
                return

            self.updating = True
            self.update_item.title = "Downloading update…"

            def _download():
                try:
                    staging, new_app = updater.download_update(update, self.app_path)
                except Exception as e:
                    AppHelper.callAfter(self._on_install_failed, e)
                    return
                AppHelper.callAfter(self._finish_install, staging, new_app)

            threading.Thread(target=_download, daemon=True).start()

        def _finish_install(self, staging, new_app):
            updater.install_and_relaunch(self.app_path, staging, new_app)
            rumps.quit_application()

        def _on_install_failed(self, error):
            self.updating = False
            self.update_item.title = f"Update to v{self.available_update['version']}…"
            message = (
                str(error) if isinstance(error, updater.UpdateError)
                else "The download failed. Check your internet connection and try again."
            )
            rumps.alert(title="Update failed", message=message)

        @rumps.clicked("Check Accessibility Permission")
        def check_permission_clicked(self, _):
            if is_accessibility_trusted():
                rumps.alert(title="mousephone", message="Accessibility permission is granted. You're all set.")
            else:
                rumps.alert(
                    title="Accessibility Permission Needed",
                    message=(
                        "mousephone can't move the cursor without this.\n\n"
                        "In the Accessibility list, remove any existing "
                        "\u201cmousephone\u201d entry first (select it, click \u2212), "
                        "then add this app back and turn it on. Then quit and "
                        "reopen mousephone."
                    ),
                )
                open_accessibility_settings()

    if not trusted:
        rumps.alert(
            title="Accessibility Permission Needed",
            message=(
                "mousephone can't move the cursor without this.\n\n"
                "In the Accessibility list, remove any existing "
                "\u201cmousephone\u201d entry first (select it, click \u2212), "
                "then add this app back and turn it on. Then quit and "
                "reopen mousephone."
            ),
        )
        open_accessibility_settings()

    MousephoneApp().run()


if __name__ == "__main__":
    main()
