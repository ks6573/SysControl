#!/usr/bin/env python3
"""Generate a macOS .icns app icon for SysControl.

Creates a simple icon (dark circle with "SC" text) at all required sizes,
then calls ``iconutil`` to produce ``build_resources/SysControl.icns``.

Requirements: Pillow (``pip install Pillow``)
"""

import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "build_resources"
ICONSET = OUT_DIR / "SysControl.iconset"
ICNS = OUT_DIR / "SysControl.icns"

# macOS iconset required sizes: (filename_label, pixel_size)
SIZES = [
    ("icon_16x16",      16),
    ("icon_16x16@2x",   32),
    ("icon_32x32",      32),
    ("icon_32x32@2x",   64),
    ("icon_128x128",   128),
    ("icon_128x128@2x", 256),
    ("icon_256x256",   256),
    ("icon_256x256@2x", 512),
    ("icon_512x512",   512),
    ("icon_512x512@2x", 1024),
]

# Colours — matches the SysControl GUI accent palette
BG_COLOR = (43, 43, 43)       # #2b2b2b  (dark background)
ACCENT   = (196, 113, 91)     # #c4715b  (warm orange accent)
TEXT_COLOR = (245, 245, 240)   # #f5f5f0  (light text)


def _render(size: int) -> Image.Image:
    """Render the icon at the given pixel size."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-rect background (circle at small sizes)
    margin = max(1, size // 16)
    radius = size // 4
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=radius,
        fill=BG_COLOR,
    )

    # Accent stripe along the bottom
    stripe_h = max(2, size // 10)
    draw.rounded_rectangle(
        [margin, size - margin - stripe_h, size - margin, size - margin],
        radius=min(radius, stripe_h // 2),
        fill=ACCENT,
    )

    # "SC" text — skip for very small sizes where text is unreadable
    if size >= 32:
        font_size = max(10, int(size * 0.38))
        font = None
        for path in (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFCompact-Bold.otf",
        ):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except (OSError, IOError):
                continue
        if font is None:
            font = ImageFont.load_default(size=font_size)

        text = "SC"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (size - tw) // 2
        ty = (size - th) // 2 - (stripe_h // 2)
        draw.text((tx, ty), text, fill=TEXT_COLOR, font=font)

    return img


def main() -> None:
    # Clean and recreate iconset directory
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir(parents=True)

    for label, px in SIZES:
        icon = _render(px)
        icon.save(ICONSET / f"{label}.png")
        print(f"  {label}.png ({px}x{px})")

    # Convert to .icns
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(ICNS)],
        check=True,
    )
    print(f"\nIcon created: {ICNS}")

    # Clean up the intermediate iconset
    shutil.rmtree(ICONSET)


if __name__ == "__main__":
    main()
