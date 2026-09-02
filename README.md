# Phone Mouse

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
| `Phone Mouse.command` | Double-click launcher (quick option, no build step) |
| `setup.py` | Build config for packaging into a real `.app` |
| `build.sh` | One-time script that builds `dist/Phone Mouse.app` |

## Setup

Install the dependencies once:

```
pip3 install aiohttp pyobjc-framework-Quartz "qrcode[pil]"
```

Then pick one of two ways to run it:

### Option A — Quick (no build step)

Double-click **`Phone Mouse.command`**. A Terminal window opens and runs the
server.

If double-clicking does nothing, the executable flag was probably lost when
the file was downloaded — fix it once with:

```
chmod +x "Phone Mouse.command"
```

### Option B — Build a real app

Turns this into `Phone Mouse.app`, which you can put in `/Applications` and
launch like any other Mac app (no Terminal window).

```
chmod +x build.sh
./build.sh
```

This creates `dist/Phone Mouse.app`. Drag it into `/Applications`.

**First launch only:** since the app isn't signed with a paid Apple
developer account, macOS will say it's from an "unidentified developer."
Right-click the app → **Open** → **Open** to allow it. After that it opens
normally.

## Using it

1. Launch the server (either option above). A window pops up with a QR
   code — and if you're running it from Terminal, an ASCII version prints
   there too.
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
`Phone Mouse.command`, or **Phone Mouse** if you built and ran the `.app`.
You may need to quit and relaunch the server after granting permission.

## Troubleshooting

- **QR code / URL doesn't load on the phone** — double-check both devices
  are on the same Wi-Fi network (not one on Wi-Fi and one on cellular data),
  and that no VPN is active on either device.
- **Cursor doesn't move** — see Accessibility permission above.
- **"Address already in use" on launch** — another copy of the server is
  already running; quit it first, or edit the `port = 8765` line in
  `mouse_server.py` to use a different port.
- **Feels too fast / slow** — open `mouse_server.py` and adjust
  `SENSITIVITY` and `SCROLL_SENSITIVITY` near the top of the `INDEX_HTML`
  section, then relaunch (and rebuild the `.app` if you're using one).

## Rebuilding after changes

If you edit `mouse_server.py` and you're using the `.app` version, rerun
`./build.sh` to pick up the changes — the app bundle is a snapshot taken at
build time, not a live link to the script.
