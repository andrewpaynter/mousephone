# mousephone

Turn your phone into a wireless trackpad for your Mac. No app to install on
the phone — just open a page in its browser (or scan a QR code) over your
home Wi-Fi.

Built with Claude Code

## How it works

`mouse_server.py` runs a small local web server on your Mac. It serves a
touch-friendly trackpad page and opens a WebSocket connection back to your
phone. Touch gestures on the phone are sent over that connection and
translated into real cursor movement using macOS's Quartz Event Services —
the same low-level APIs remote-control and accessibility tools use.

Nothing leaves your local network — the phone only ever talks to your Mac's
local IP address.

## Requirements

- A Mac
- Python 3 (macOS usually has this already; check with `python3 --version`)
- A phone and Mac on the **same Wi-Fi network**

## Files

| File | Purpose |
|---|---|
| `mouse_server.py` | The server itself — this is all you actually need to run |
| `mousephone.command` | Double-click launcher (quick option, no build step) |
| `dev.sh` | Dev loop — runs the server directly and auto-restarts on save |
| `setup.py` | Build config for packaging into a real `.app` |
| `build.sh` | One-time script that builds `dist/mousephone.app` |

## Setup

Install the dependencies once:

```
pip3 install aiohttp pyobjc-framework-Quartz "qrcode[pil]" rumps
```

Then pick one of two ways to run it:

### Option A — Quick (no build step)

Double-click **`mousephone.command`**. A Terminal window opens and runs the
server.

If double-clicking does nothing, the executable flag was probably lost when
the file was downloaded — fix it once with:

```
chmod +x "mousephone.command"
```

### Option B — Build a real app

Turns this into `mousephone.app`, which you can put in `/Applications` and
launch like any other Mac app (no Terminal window).

```
chmod +x build.sh
./build.sh
```

This creates `dist/mousephone.app`. Drag it into `/Applications`.

**First launch only:** since the app isn't signed with a paid Apple
developer account, macOS will say it's from an "unidentified developer."
Right-click the app → **Open** → **Open** to allow it. After that it opens
normally.

## Development workflow

If you're editing `mouse_server.py`, don't use `build.sh` for every change —
building produces a freshly ad-hoc-signed `.app` each time, and macOS treats
each signature as a different app, so you'd have to re-grant Accessibility
permission after every single edit.

Instead:

```
./dev.sh
```

This runs the server directly (like `mousephone.command`) and auto-restarts
it whenever it detects a change to `mouse_server.py`. Grant Accessibility
permission **once**, to your terminal app (Terminal/iTerm — whichever you
run `dev.sh` from), not to `mousephone`. Because that's your terminal app's
own permission grant and its signature never changes, it stays valid across
every future edit, restart, and even new Terminal windows — no rebuild, no
reinstall into `/Applications`, no re-granting.

Reserve `build.sh` for when you actually want the packaged, double-click
`.app` (e.g. to hand off or stop needing a Terminal window open) — and
expect to re-grant permission once after that build, as noted below.

## Using it

1. Launch the server (either option above). A mousephone icon appears in
   your menu bar — click it to see the QR code right there in the
   dropdown (no separate window to open). If you're running it from
   Terminal, an ASCII version also prints there.
2. On your phone, scan the QR code (or type the printed URL into your
   browser manually).
3. Use the page as a trackpad:
   - **One finger, drag** — move the cursor
   - **One finger, tap** — left click
   - **Two fingers, drag** — scroll
   - **Two fingers, tap** — right click
   - **Hold "Left Click," then drag** — click-and-drag

## Accessibility permission

macOS blocks apps from generating synthetic mouse input by default. The
first time the cursor doesn't move, go to:

**System Settings → Privacy & Security → Accessibility**

and enable the app that's running the server — **Terminal** if you used
`mousephone.command`, or **mousephone** if you built and ran the `.app`.
You may need to quit and relaunch the server after granting permission.

The app checks this on launch — if it's not granted, you'll get an alert
and Settings will open automatically. You can also re-check anytime from
the mousephone menu bar icon → **Check Accessibility Permission**.

**After every rebuild of the `.app`,** re-grant this permission — each
build produces a new signed binary, and macOS treats it as a different
app. Remove the old "mousephone" entry from the list first (select it,
click **−**) rather than just re-toggling it, then add the new build back
with **+**.

## Troubleshooting

- **"You can't open mousephone.app because it is not responding"** — this
  happens with older builds that never engaged a Cocoa run loop, so macOS's
  Launch Services thought the app had hung at startup (even though the
  server itself was running fine). Fixed by moving the server onto a
  background thread and giving the app a real run loop + menu bar icon.
  If you're seeing this, rebuild: `pip3 install rumps`, then rerun
  `./build.sh` and replace the app in `/Applications` with the new one.
- **QR code / URL doesn't load on the phone** — double-check both devices
  are on the same Wi-Fi network (not one on Wi-Fi and one on cellular data),
  and that no VPN is active on either device.
- **Cursor doesn't move (page loads and connects fine)** — almost always
  Accessibility permission. See the section above — after any rebuild, the
  old permission entry goes stale and needs to be removed and re-added,
  not just re-toggled.
- **"Address already in use" on launch** — another copy of the server is
  already running; quit it first (menu bar icon → Quit), or edit the
  `port = 8765` line in `mouse_server.py` to use a different port.
- **Feels too fast / slow** — open `mouse_server.py` and adjust
  `SENSITIVITY` and `SCROLL_SENSITIVITY` near the top of the `INDEX_HTML`
  section, then relaunch (and rebuild the `.app` if you're using one).

## Rebuilding after changes

If you edit `mouse_server.py` and you're using the `.app` version, rerun
`./build.sh` to pick up the changes — the app bundle is a snapshot taken at
build time, not a live link to the script. If you're actively iterating on
`mouse_server.py`, use `./dev.sh` instead (see **Development workflow**
above) so you're not rebuilding and re-granting permission on every change.
