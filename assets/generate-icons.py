#!/usr/bin/env python3
"""Generate Music Fix icon assets from source PNGs."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Pillow is required: python3 -m pip install pillow") from exc

ASSETS_DIR = Path(__file__).resolve().parent
SOURCE_ICON = ASSETS_DIR / "icon-source.png"
TEMPLATE_SOURCE = ASSETS_DIR / "menubar-template-source.png"
ICONSET_DIR = ASSETS_DIR / "icon.iconset"
ICNS_PATH = ASSETS_DIR / "MusicFix.icns"
MENUBAR_ICON = ASSETS_DIR / "menubar-template.png"
MENUBAR_ICON_2X = ASSETS_DIR / "menubar-template@2x.png"
APP_ICON_256 = ASSETS_DIR / "app-icon-256.png"
APP_ICON_512 = ASSETS_DIR / "app-icon-512.png"

ICONSET_SIZES = (
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
)


def ensure_sources() -> None:
    if not SOURCE_ICON.exists():
        raise SystemExit(f"Missing source icon: {SOURCE_ICON}")
    if not TEMPLATE_SOURCE.exists():
        raise SystemExit(f"Missing menu bar template source: {TEMPLATE_SOURCE}")


def resize_icon(source: Path, size: int, destination: Path) -> None:
    with Image.open(source) as image:
        resized = image.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        resized.save(destination, format="PNG")


def build_iconset() -> None:
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    ICONSET_DIR.mkdir(parents=True)

    for size, filename in ICONSET_SIZES:
        resize_icon(SOURCE_ICON, size, ICONSET_DIR / filename)

    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_PATH)],
        check=True,
    )


def build_app_pngs() -> None:
    resize_icon(SOURCE_ICON, 256, APP_ICON_256)
    resize_icon(SOURCE_ICON, 512, APP_ICON_512)


def _template_image(source: Path) -> Image.Image:
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
        gray = rgba.convert("L")
        mask = gray.point(lambda value: 255 if value < 245 else 0)
        bbox = mask.getbbox()
        if bbox:
            rgba = rgba.crop(bbox)

        width, height = rgba.size
        side = max(width, height)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(rgba, ((side - width) // 2, (side - height) // 2), rgba)

        pixels = square.load()
        for y in range(side):
            for x in range(side):
                red, green, blue, alpha = pixels[x, y]
                if alpha < 16:
                    pixels[x, y] = (0, 0, 0, 0)
                    continue
                luminance = 0.299 * red + 0.587 * green + 0.114 * blue
                if luminance > 210:
                    pixels[x, y] = (0, 0, 0, 0)
                else:
                    strength = min(255, alpha if luminance < 80 else int((255 - luminance) * 4))
                    pixels[x, y] = (0, 0, 0, strength)

        return square


def build_menubar_template() -> None:
    template = _template_image(TEMPLATE_SOURCE)
    template.resize((18, 18), Image.Resampling.LANCZOS).save(MENUBAR_ICON, format="PNG")
    template.resize((36, 36), Image.Resampling.LANCZOS).save(MENUBAR_ICON_2X, format="PNG")


def main() -> int:
    ensure_sources()
    build_iconset()
    build_app_pngs()
    build_menubar_template()
    print(f"Generated {ICNS_PATH.name}, menu bar icons, and app PNGs in {ASSETS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
