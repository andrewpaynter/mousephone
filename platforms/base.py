"""
The interfaces each OS implements. The shared app (server, phone page,
update flow) only ever talks to these — never to an OS API directly — so
anything that works differently on macOS and Windows belongs behind one
of them rather than in an `if sys.platform == ...` branch elsewhere.
"""

from abc import ABC, abstractmethod


class UpdateError(Exception):
    """An update failure whose message is safe and useful to show the user."""


class InputController(ABC):
    """Synthesizes mouse and keyboard input on the computer."""

    @abstractmethod
    def move(self, dx, dy):
        """Move the cursor by (dx, dy) screen pixels, clamped to the desktop
        across all displays. If the left button is held (mouse_down), this
        drags."""

    @abstractmethod
    def click(self, button):
        """Click "left" or "right" at the cursor."""

    @abstractmethod
    def mouse_down(self):
        """Press and hold the left button."""

    @abstractmethod
    def mouse_up(self):
        """Release the left button."""

    @abstractmethod
    def scroll(self, dx, dy):
        """Scroll by the phone's finger movement in pixels. Content follows
        the fingers: positive dy moves content down, positive dx right."""

    @abstractmethod
    def type_text(self, text):
        """Type arbitrary text — accents, emoji, any language — independent
        of the computer's keyboard layout."""

    @abstractmethod
    def press_key(self, key, count=1):
        """Press a non-character key `count` times: "backspace" or "return"."""


class Tray(ABC):
    """The always-running UI: the menu bar icon on macOS, the system tray
    icon on Windows. Create it and call run() on the main thread."""

    @abstractmethod
    def add_choice_menu(self, title, choices, selected, on_select):
        """Add a submenu `title` listing `choices` (labels), with a check mark
        on `selected`. Picking one moves the check mark to it and calls
        on_select(label)."""

    @abstractmethod
    def set_update_item(self, title, callback):
        """Add the update menu item, or change its title if it's already
        there. callback() is called with no arguments when it's clicked."""

    @abstractmethod
    def alert(self, title, message):
        """Show a message with a single OK button."""

    @abstractmethod
    def confirm(self, title, message, ok, cancel):
        """Ask a yes/no question; True if the user chose `ok`. The labels are
        used where the OS lets dialogs have custom buttons."""

    @abstractmethod
    def call_on_main(self, fn, *args):
        """Run fn(*args) on the UI thread. Background threads must use this
        for anything that touches the menu or shows a dialog."""

    @abstractmethod
    def every(self, seconds, fn):
        """Call fn() every `seconds` seconds."""

    @abstractmethod
    def open_url(self, url):
        """Open a web page in the default browser."""

    @abstractmethod
    def quit(self):
        """Exit the app."""

    @abstractmethod
    def run(self):
        """Run the UI until quit(). Blocks."""


class Installer(ABC):
    """How this OS's packaged app is found, verified and replaced during an
    in-app update. The shared update flow (updater.UpdateController) calls
    these in order: can_install, make_staging_dir, (download), prepare,
    install_and_relaunch."""

    @abstractmethod
    def asset_name(self, version):
        """File name of this OS's download in the GitHub release for `version`."""

    @abstractmethod
    def current_install(self):
        """Path of the installed app that's running, or None when running
        from source (dev.sh, Terminal) — in which case there's nothing to
        update and the update menu is left out."""

    @abstractmethod
    def can_install(self):
        """Whether the app has permission to replace itself where it is."""

    @abstractmethod
    def make_staging_dir(self):
        """A fresh temporary directory for the download. The installer owns
        it and cleans it up."""

    @abstractmethod
    def prepare(self, download_path, staging_dir):
        """Unpack and verify the download. Must reject (raise UpdateError)
        anything not signed by the same certificate as
        the running app. Returns whatever install_and_relaunch needs."""

    @abstractmethod
    def install_and_relaunch(self, prepared):
        """Start a detached helper that waits for this process to exit,
        installs the update and relaunches the app. The caller quits right
        after this returns."""


class Platform(ABC):
    """Builds this OS's implementations of the interfaces above."""

    def __init__(self, assets_dir):
        self.assets_dir = assets_dir

    @abstractmethod
    def data_dir(self):
        """Folder for the app's saved settings, in the OS's usual place for
        per-user app data. Shared by the installed app and dev runs."""

    @abstractmethod
    def create_input(self):
        """Returns an InputController."""

    @abstractmethod
    def create_tray(self, url, port, dev):
        """Returns a Tray for the server at `url`. `dev` is True under dev.sh,
        and should make the icon distinguishable from the installed app's."""

    @abstractmethod
    def create_installer(self):
        """Returns an Installer."""
