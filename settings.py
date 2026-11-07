"""
Speed settings, chosen from the tray/menu bar and saved on the computer.

The phone sends raw finger movement; the server multiplies it by these
before moving the cursor or scrolling, so one setting applies to every
phone that connects.
"""

import json
import os

# (label, multiplier on the base speed) — shown as a submenu of choices.
SPEEDS = [
    ("Slowest", 0.5),
    ("Slow", 0.75),
    ("Normal", 1.0),
    ("Fast", 1.5),
    ("Fastest", 2.0),
]
DEFAULT_SPEED = "Normal"

# Finger pixels → cursor/scroll pixels at "Normal". These were the phone
# page's fixed SENSITIVITY / SCROLL_SENSITIVITY before speeds were adjustable.
BASE_POINTER = 1.6
BASE_SCROLL = 1.2


class Settings:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "settings.json")
        self.pointer_speed = DEFAULT_SPEED
        self.scroll_speed = DEFAULT_SPEED
        self._load()

    @property
    def pointer_scale(self):
        return BASE_POINTER * dict(SPEEDS)[self.pointer_speed]

    @property
    def scroll_scale(self):
        return BASE_SCROLL * dict(SPEEDS)[self.scroll_speed]

    def set_pointer_speed(self, label):
        self.pointer_speed = label
        self._save()

    def set_scroll_speed(self, label):
        self.scroll_speed = label
        self._save()

    def _load(self):
        try:
            with open(self.path) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return  # first run, or an unreadable file: keep the defaults
        labels = dict(SPEEDS)
        if saved.get("pointer_speed") in labels:
            self.pointer_speed = saved["pointer_speed"]
        if saved.get("scroll_speed") in labels:
            self.scroll_speed = saved["scroll_speed"]

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump({"pointer_speed": self.pointer_speed, "scroll_speed": self.scroll_speed}, f)
        except OSError:
            pass  # still applies for this session; just won't be remembered
