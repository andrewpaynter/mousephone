"""
Pointer settings, chosen from the tray/menu bar and saved on the computer.

The phone sends raw finger movement; the server multiplies it by these
before moving the cursor or scrolling, so one setting applies to every
phone that connects.
"""

import json
import math
import os

# (label, multiplier on the base speed) — shown as a submenu of choices.
SPEEDS = [
    ("Slowest", 0.5),
    ("Slow", 0.75),
    ("Normal", 1.0),
    ("Fast", 1.5),
    ("Fastest", 2.0),
]

# (label, strength): extra cursor distance per unit of finger speed above
# ACCEL_THRESHOLD. "Off" keeps movement strictly proportional.
ACCELERATIONS = [
    ("Off", 0.0),
    ("Low", 0.6),
    ("Medium", 1.2),
    ("High", 2.0),
]

# Each saved setting: its menu choices and default.
FIELDS = {
    "pointer_speed": (SPEEDS, "Normal"),
    "scroll_speed": (SPEEDS, "Normal"),
    "acceleration": (ACCELERATIONS, "Off"),
}

# Finger pixels → cursor/scroll pixels at "Normal". These were the phone
# page's fixed SENSITIVITY / SCROLL_SENSITIVITY before speeds were adjustable.
BASE_POINTER = 1.6
BASE_SCROLL = 1.2

# Acceleration curve, in finger speed (px/ms). Below the threshold, movement
# is unaccelerated, so slow precise pointing feels the same with it on.
# Above it, gain grows linearly until the cap, so a fast flick carries the
# cursor much farther without flinging it uncontrollably (max gain is
# 1 + strength * (cap - threshold): 2.2x on Low, 5x on High).
ACCEL_THRESHOLD = 0.25
ACCEL_SPEED_CAP = 2.25
ACCEL_SMOOTHING = 0.5   # weight of the newest speed sample; damps jitter
ACCEL_STROKE_GAP_MS = 100  # a pause this long starts the speed afresh


class Settings:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "settings.json")
        self.values = {name: default for name, (_, default) in FIELDS.items()}
        self._load()

    @property
    def pointer_scale(self):
        return BASE_POINTER * dict(SPEEDS)[self.values["pointer_speed"]]

    @property
    def scroll_scale(self):
        return BASE_SCROLL * dict(SPEEDS)[self.values["scroll_speed"]]

    @property
    def acceleration_strength(self):
        return dict(ACCELERATIONS)[self.values["acceleration"]]

    def choices(self, name):
        return [label for label, _ in FIELDS[name][0]]

    def setter(self, name):
        """A callback that saves a new choice for `name` (for menu items)."""
        def set_value(label):
            self.values[name] = label
            self._save()
        return set_value

    def _load(self):
        try:
            with open(self.path) as f:
                saved = json.load(f)
        except (OSError, ValueError):
            return  # first run, or an unreadable file: keep the defaults
        for name, (options, _) in FIELDS.items():
            if saved.get(name) in dict(options):
                self.values[name] = saved[name]

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self.values, f)
        except OSError:
            pass  # still applies for this session; just won't be remembered


class PointerAccelerator:
    """Tracks one phone's finger speed and turns it into a distance
    multiplier. One per connection, since each has its own stroke."""

    def __init__(self, settings):
        self.settings = settings
        self.speed = None  # smoothed px/ms, None at the start of a stroke

    def gain(self, dx, dy, dt):
        strength = self.settings.acceleration_strength
        # dt comes from the phone; anything missing or odd means "no
        # acceleration for this event" rather than a wild jump.
        if not strength or not isinstance(dt, (int, float)) or not dt > 0:
            self.speed = None
            return 1.0
        sample = math.hypot(dx, dy) / dt
        if self.speed is None or dt >= ACCEL_STROKE_GAP_MS:
            self.speed = sample
        else:
            self.speed = ACCEL_SMOOTHING * sample + (1 - ACCEL_SMOOTHING) * self.speed
        excess = min(max(self.speed - ACCEL_THRESHOLD, 0.0), ACCEL_SPEED_CAP - ACCEL_THRESHOLD)
        return 1.0 + strength * excess
