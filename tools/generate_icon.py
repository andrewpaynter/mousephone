#!/usr/bin/env python3
"""
Generates mousephone's logo assets: the menu bar status icon and the
app bundle .icns. Not needed to run the app -- only re-run this if the
mark itself needs to change.

    python3 tools/generate_icon.py

Requires: Pillow (already a project dependency via "qrcode[pil]"), and
iconutil (ships with macOS) to assemble the .icns.
"""

import os
import shutil
import subprocess

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

SS = 8  # supersampling factor for smooth curves, downsampled at the end


def _pointer_polygon(box):
    """A mouse-cursor arrow silhouette, normalized to unit square, scaled
    into `box` = (x, y, w, h)."""
    pts = [
        (0.00, 0.00),
        (0.00, 0.78),
        (0.23, 0.60),
        (0.37, 1.00),
        (0.50, 0.95),
        (0.36, 0.55),
        (0.64, 0.55),
    ]
    x, y, w, h = box
    return [(x + px * w, y + py * h) for px, py in pts]


def draw_mark(draw, size, color, phone_only=False):
    """Draws the mousephone mark (phone outline + overlapping cursor arrow)
    centered in a `size` x `size` canvas."""
    s = size
    phone_w, phone_h = s * 0.40, s * 0.64
    phone_x = s * 0.28
    phone_y = s * 0.16
    stroke = max(2, int(s * 0.045))

    draw.rounded_rectangle(
        [phone_x, phone_y, phone_x + phone_w, phone_y + phone_h],
        radius=phone_w * 0.22,
        outline=color,
        width=stroke,
    )
    # speaker slit near the top of the phone
    slit_w = phone_w * 0.28
    slit_y = phone_y + phone_h * 0.10
    draw.rounded_rectangle(
        [s / 2 - slit_w / 2, slit_y, s / 2 + slit_w / 2, slit_y + stroke * 0.8],
        radius=stroke * 0.4,
        fill=color,
    )

    if phone_only:
        return

    cursor_size = s * 0.50
    cursor_box = (
        phone_x + phone_w * 0.48,
        phone_y + phone_h * 0.58,
        cursor_size,
        cursor_size,
    )
    draw.polygon(_pointer_polygon(cursor_box), fill=color)


def render(size, color, transparent=True, phone_only=False):
    big = size * SS
    bg = (0, 0, 0, 0) if transparent else color
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_mark(draw, big, color, phone_only=phone_only)
    return img.resize((size, size), Image.LANCZOS)


def render_app_icon(size):
    """Full-color rounded-square app icon: a dark gradient backing plate
    with the mark in white."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    top = (58, 66, 92, 255)
    bottom = (24, 27, 38, 255)
    plate = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    px = plate.load()
    for yy in range(big):
        t = yy / (big - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for xx in range(big):
            px[xx, yy] = (r, g, b, 255)

    mask = Image.new("L", (big, big), 0)
    mask_draw = ImageDraw.Draw(mask)
    margin = big * 0.04
    mask_draw.rounded_rectangle(
        [margin, margin, big - margin, big - margin],
        radius=big * 0.225,
        fill=255,
    )
    img.paste(plate, (0, 0), mask)

    draw = ImageDraw.Draw(img)
    draw_mark(draw, big, (255, 255, 255, 255))

    return img.resize((size, size), Image.LANCZOS)


def build_menu_bar_icon():
    # Template image for the status bar: a black silhouette with alpha;
    # macOS re-tints it automatically for light/dark menu bars.
    icon = render(128, (0, 0, 0, 255))
    path = os.path.join(ASSETS, "menu_bar_icon.png")
    icon.save(path)
    print(f"wrote {path}")


def build_icns():
    iconset = os.path.join(ASSETS, "mousephone.iconset")
    if os.path.isdir(iconset):
        shutil.rmtree(iconset)
    os.makedirs(iconset)

    sizes = [16, 32, 128, 256, 512]
    for sz in sizes:
        render_app_icon(sz).save(os.path.join(iconset, f"icon_{sz}x{sz}.png"))
        render_app_icon(sz * 2).save(os.path.join(iconset, f"icon_{sz}x{sz}@2x.png"))

    icns_path = os.path.join(ASSETS, "mousephone.icns")
    subprocess.run(
        ["iconutil", "-c", "icns", iconset, "-o", icns_path],
        check=True,
    )
    shutil.rmtree(iconset)
    print(f"wrote {icns_path}")


def build_preview():
    """A big flat PNG of both marks, side by side, purely for eyeballing
    the design -- not shipped with the app."""
    pad = 40
    cell = 512
    sheet = Image.new("RGBA", (cell * 2 + pad * 3, cell + pad * 2), (32, 32, 36, 255))
    sheet.paste(render_app_icon(cell), (pad, pad), render_app_icon(cell))
    mono = render(cell, (255, 255, 255, 255))
    sheet.paste(mono, (pad * 2 + cell, pad), mono)
    path = os.path.join(ASSETS, "_preview.png")
    sheet.save(path)
    print(f"wrote {path}")


if __name__ == "__main__":
    os.makedirs(ASSETS, exist_ok=True)
    build_menu_bar_icon()
    build_icns()
    build_preview()
