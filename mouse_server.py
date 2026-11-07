#!/usr/bin/env python3
"""
mousephone server — turns your phone into a trackpad and keyboard for
your computer (macOS or Windows).

Run this on the computer, then open the printed URL in your phone's
browser (on the same Wi-Fi network).

Setup:
    macOS:   pip3 install aiohttp pyobjc-framework-Quartz "qrcode[pil]" rumps certifi
    Windows: pip install aiohttp "qrcode[pil]" pystray certifi

Run:
    python3 mouse_server.py

On macOS you'll need to grant Accessibility permission to Terminal (or
whatever app you run this from) in:
    System Settings > Privacy & Security > Accessibility

Everything OS-specific lives in platforms/ (see platforms/base.py); this
file is the shared part: the web server and the phone page.
"""

import json
import os
import socket
import sys
import threading

try:
    from aiohttp import web, WSMsgType
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install aiohttp")
    sys.exit(1)

try:
    import qrcode
except ImportError:
    print("Missing dependency. Install with:\n  pip3 install \"qrcode[pil]\"")
    sys.exit(1)

import platforms
import settings as speed_settings
import updater

# Bump this in a PR before running tools/release.sh. The Mac and Windows
# builds read it for their version metadata, and the updater compares it
# to the latest release.
__version__ = "1.3.0"

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


# ---------- Web server ----------

async def index(request):
    return web.Response(text=INDEX_HTML, content_type="text/html")


def make_websocket_handler(controller, settings):
    async def websocket_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        accelerator = speed_settings.PointerAccelerator(settings)

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue

                t = data.get("type")
                if t == "move":
                    dx, dy = data.get("dx", 0), data.get("dy", 0)
                    scale = settings.pointer_scale * accelerator.gain(dx, dy, data.get("dt"))
                    controller.move(dx * scale, dy * scale)
                elif t == "click":
                    controller.click(data.get("button", "left"))
                elif t == "down":
                    controller.mouse_down()
                elif t == "up":
                    controller.mouse_up()
                elif t == "scroll":
                    scale = settings.scroll_scale
                    controller.scroll(data.get("dx", 0) * scale, data.get("dy", 0) * scale)
                elif t == "text":
                    controller.type_text(str(data.get("text", "")))
                elif t == "key":
                    controller.press_key(data.get("key"), data.get("count", 1))
            elif msg.type == WSMsgType.ERROR:
                break

        return ws

    return websocket_handler


def print_qr_ascii(url):
    """Print a scannable QR code as text — visible when run from a terminal.
    (A windowed build has no stdout, which the caller tolerates.)"""
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make()
    qr.print_ascii(invert=True)


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
    <div id="kbd-bar">Typing on computer<div id="kbd-done">Done</div></div>
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

// Movement is sent as raw finger pixels; the computer applies the pointer
// and scroll speeds chosen in its tray/menu bar menu (see settings.py).

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
      dx: vx * dt,
      dy: vy * dt,
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
    touches[t.identifier] = { x: t.clientX, y: t.clientY, t: e.timeStamp };
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
    // dt (ms since the previous event) lets the computer apply pointer
    // acceleration from the finger's real speed; Wi-Fi delivers messages
    // too unevenly for it to time them itself.
    const dt = e.timeStamp - prev.t;
    send({ type: 'move', dx, dy, dt });
    touches[id] = { x: t.clientX, y: t.clientY, t: e.timeStamp };
  } else if (ids.length === 2) {
    let dxSum = 0, dySum = 0, n = 0;
    for (const t of e.touches) {
      const id = String(t.identifier);
      if (touches[id]) {
        dxSum += t.clientX - touches[id].x;
        dySum += t.clientY - touches[id].y;
        touches[id] = { x: t.clientX, y: t.clientY, t: e.timeStamp };
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
      send({ type: 'scroll', dx, dy });
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


def main():
    platform = platforms.current(ASSETS_DIR)
    controller = platform.create_input()
    settings = speed_settings.Settings(platform.data_dir())

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", make_websocket_handler(controller, settings))

    # dev.sh sets MOUSEPHONE_PORT so a dev server can run alongside the
    # installed app without fighting over the port.
    port = int(os.environ.get("MOUSEPHONE_PORT", 8765))
    # dev.sh also sets MOUSEPHONE_DEV, so its tray/menu bar icon can be told
    # apart from the installed app's when both are running.
    dev = os.environ.get("MOUSEPHONE_DEV") == "1"
    ip = get_local_ip()
    url = f"http://{ip}:{port}"

    print("=" * 50)
    print("mousephone server running")
    print(f"On your phone (same Wi-Fi), scan this QR code, or open:\n  {url}")
    print("=" * 50)

    # Run the web/WebSocket server on a background thread. handle_signals=False
    # is required here — aiohttp's signal handling only works on the main
    # thread, which we're reserving for the tray/menu bar UI below.
    def _run_server():
        web.run_app(app, host="0.0.0.0", port=port, print=None, handle_signals=False)

    threading.Thread(target=_run_server, daemon=True).start()

    try:
        print_qr_ascii(url)
    except Exception:
        pass

    tray = platform.create_tray(url, port, dev)
    for title, name in [
        ("Pointer Speed", "pointer_speed"),
        ("Pointer Acceleration", "acceleration"),
        ("Scroll Speed", "scroll_speed"),
    ]:
        tray.add_choice_menu(title, settings.choices(name), settings.values[name], settings.setter(name))

    # Updates only apply to an installed build — when running from source
    # there's nothing to replace, so the update menu item is left out.
    installer = platform.create_installer()
    if installer.current_install():
        updater.UpdateController(tray, installer, __version__)

    tray.run()


if __name__ == "__main__":
    main()
