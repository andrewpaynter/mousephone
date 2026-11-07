# mousephone

Turn your phone into a wireless trackpad and keyboard for your Mac or
Windows PC. No app to install on the phone — just open a page in its
browser (or scan a QR code) over your home Wi-Fi.

Built with Claude Code

## How it works

`mouse_server.py` runs a small local web server on your computer. It
serves a touch-friendly trackpad page and opens a WebSocket connection back
to your phone. Touch gestures on the phone are sent over that connection and
translated into real cursor movement and typing — using Quartz Event
Services on macOS and `SendInput` on Windows, the same low-level APIs
remote-control and accessibility tools use.

Nothing leaves your local network — the phone only ever talks to your
computer's local IP address.

Everything OS-specific lives in `platforms/`: `platforms/base.py` defines
the interfaces (input, the tray/menu bar UI, and how updates are
installed), and `mac.py` / `windows.py` implement them. The server, phone
page and update flow are shared and only talk to those interfaces.

## Requirements

- A Mac, or a Windows 10/11 PC (see **Windows** below)
- Python 3 (macOS usually has this already; check with `python3 --version`)
- A phone and computer on the **same Wi-Fi network**

## Files

| File | Purpose |
|---|---|
| `mouse_server.py` | The shared server and phone page — run this to start mousephone |
| `platforms/` | OS-specific code behind shared interfaces (`base.py`, `mac.py`, `windows.py`) |
| `mousephone.command` | Double-click launcher (quick option, no build step) |
| `dev.sh` | Dev loop — runs the server directly and auto-restarts on save |
| `setup.py` | Build config for packaging into a real `.app` |
| `build.sh` | One-time script that builds `dist/mousephone.app` |
| `updater.py` | Checks GitHub Releases and installs updates from the menu bar |
| `tools/create_signing_cert.sh` | One-time setup of the certificate every build is signed with |
| `tools/release.sh` | Builds and publishes a GitHub Release that installed copies update to |
| `build_windows.ps1` | Builds the Windows installer (run on Windows; releases use GitHub Actions) |
| `installer/mousephone.iss` | Inno Setup config for the Windows installer |
| `.github/workflows/windows.yml` | Builds the Windows installer on PRs and attaches it to releases |
| `tools/create_windows_signing_cert.sh` | One-time setup of the certificate Windows builds are signed with |

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
tools/create_signing_cert.sh   # first time only
./build.sh
```

`create_signing_cert.sh` adds a "mousephone Code Signing" certificate to
your login keychain, and every build is signed with it. **Back it up**
(Keychain Access → My Certificates → right-click it → Export): it's what
lets updates keep their Accessibility permission, and installed copies
only accept updates signed with it.

This creates `dist/mousephone.app`. Drag it into `/Applications`.

**First launch only:** since the app isn't signed with a paid Apple
developer account, macOS will say it's from an "unidentified developer."
Right-click the app → **Open** → **Open** to allow it. After that it opens
normally.

## Windows

### Installing

Download `mousephone-<version>-windows-setup.exe` from the
[latest release](https://github.com/andrewpaynter/mousephone/releases/latest)
and run it. It installs just for your user (no admin needed) and adds
mousephone to the Start menu.

- **"Windows protected your PC"** — SmartScreen shows this for apps without
  a paid code-signing certificate. Click **More info → Run anyway**. Only
  the first install; updates don't show it.
- **Firewall prompt** — the first time mousephone runs, Windows asks
  whether to allow it on the network. Allow it on **private networks**. If
  your Wi-Fi is set to *Public*, the phone can't connect: Settings →
  Network & internet → Wi-Fi → your network → **Private network**.

mousephone lives in the system tray. Windows 11 tucks new tray icons into
the **^** overflow menu, so the QR code also opens automatically on launch;
click the tray icon to show it again.

### Running from source

```
pip install aiohttp "qrcode[pil]" pystray certifi
python mouse_server.py
```

Set `MOUSEPHONE_PORT=8766` and `MOUSEPHONE_DEV=1` (what `dev.sh` does on a
Mac) to run alongside the installed app, labeled DEV in the tray.

### Limitations

- **Admin windows** — Windows blocks simulated input to apps running as
  administrator (Task Manager, installers, elevated terminals), so the
  cursor and keyboard stop working over those windows.
- **Scrolling** — Windows' wheel scrolling is coarser than macOS's pixel
  scrolling. Apps with smooth scrolling (browsers, most modern apps) feel
  fine; older ones scroll in steps. Tune `WHEEL_UNITS_PER_PIXEL` in
  `platforms/windows.py` if it feels off.

### Building

Releases are built by GitHub Actions — `tools/release.sh` publishes the
release with the Mac app, which triggers `.github/workflows/windows.yml` to
build the Windows installer and attach it. Every pull request also builds
one, downloadable from the PR's checks, for testing before merging.

Like the Mac app, Windows builds are signed with the same certificate every
time, and the updater only installs updates signed with it. Create it once
(on a Mac) and store it as repo secrets:

```
tools/create_windows_signing_cert.sh --upload
```

**Back up** the folder it creates (`~/mousephone-windows-signing`).

To build locally on Windows: `powershell -ExecutionPolicy Bypass -File
build_windows.ps1` (needs Python 3.11+ and Inno Setup 6; pass `-Unsigned`
for a quick test build without the certificate).

## Development workflow

If you're editing `mouse_server.py`, don't use `build.sh` for every change —
a full build takes a few minutes, and you'd have to reinstall the `.app`
each time.

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
`.app` (e.g. to hand off or stop needing a Terminal window open).

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
4. To type, **press and hold** the keyboard button in the top-right corner
   until its ring fills, then let go. Your phone's own keyboard opens and
   everything you type (autocorrect, emoji, dictation included) is typed on
   the Mac. Tap **Done**, tap the keyboard button again, or hide the
   keyboard to close it. The trackpad keeps working while it's open.

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

Builds are all signed with the same certificate, so the permission
carries over across rebuilds and updates. You only need to re-grant it
when moving from an older ad-hoc-signed build (anything before the
updater was added), or if the signing certificate is ever replaced. In
that case, remove the old "mousephone" entry from the list first (select
it, click **−**) rather than just re-toggling it, then add the app back
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
  Accessibility permission. See the section above — if you've moved from
  an older ad-hoc-signed build, the old permission entry is stale and
  needs to be removed and re-added, not just re-toggled.
- **"Address already in use" on launch** — another copy of the server is
  already running; quit it first (menu bar icon → Quit), or run it on a
  different port with `MOUSEPHONE_PORT=9000 python3 mouse_server.py`.
  `dev.sh` uses port 8766 by default, so it can run alongside the
  installed app (8765).
- **Feels too fast / slow** — pick a different **Pointer Speed** or
  **Scroll Speed** from the menu bar / tray icon. It applies right away and
  is remembered. Turn on **Pointer Acceleration** to have quick flicks
  carry the cursor farther while slow movements stay precise. (To change
  what "Normal" means, or the acceleration curve, edit the constants at
  the top of `settings.py`.)

## Rebuilding after changes

If you edit `mouse_server.py` and you're using the `.app` version, rerun
`./build.sh` to pick up the changes — the app bundle is a snapshot taken at
build time, not a live link to the script. If you're actively iterating on
`mouse_server.py`, use `./dev.sh` instead (see **Development workflow**
above) so you're not rebuilding on every change.

## Updates

The installed app (the Mac `.app` or the Windows install) checks this
repo's GitHub Releases when it launches and every 6 hours. When a newer
version is out, the menu bar / tray icon shows **Update to vX…** — click
it, and mousephone downloads the update, checks it's signed with the same
certificate, installs it and relaunches. You can also check anytime from
**Check for Updates**. (Not shown when running from source, since there's
no installed app to update.)

To publish an update:

1. Bump `__version__` near the top of `mouse_server.py` in a PR and merge it.
2. From an up-to-date `main`, run `tools/release.sh`. It builds and signs
   the Mac app, tags the commit, and creates a GitHub Release with the
   zipped app attached. GitHub Actions then builds the Windows installer
   and attaches it to the same release a few minutes later. That release
   is what installed copies update to.

For a friend's first install, send them the latest release's `.zip` (Mac)
or `-windows-setup.exe` (Windows). They'll get the "unidentified
developer" (Mac, see Option B above) or SmartScreen (Windows, see
**Windows** above) prompt once; updates after that install without it.
