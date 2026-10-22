# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "Pillow>=10.0",
# ]
# ///
"""Remove the background from an icon image to produce a transparent PNG.

Samples the corner pixels of the image to detect the background color, then
creates an alpha mask based on color similarity. Pixels matching the background
color become transparent.

For best results, the input image should have a solid, uniform background
(generated with --background white or --background transparent-friendly).

Usage:
    uv run remove_bg.py icon.png
    uv run remove_bg.py icon.png --output icon_transparent.png
    uv run remove_bg.py icon.png --tolerance 35
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageFilter
except ImportError:
    print("ERROR: Pillow not found. Run with: uv run remove_bg.py ...", file=sys.stderr)
    sys.exit(1)


def sample_background_color(img: Image.Image) -> tuple[int, ...]:
    """Sample the background color from the four corners of the image."""
    img_rgb = img.convert("RGB")
    w, h = img_rgb.size
    corner_points = [
        (0, 0),
        (w - 1, 0),
        (0, h - 1),
        (w - 1, h - 1),
        (w // 2, 0),
        (w // 2, h - 1),
        (0, h // 2),
        (w - 1, h // 2),
    ]
    samples = [img_rgb.getpixel(pt) for pt in corner_points]

    r = sum(s[0] for s in samples) // len(samples)
    g = sum(s[1] for s in samples) // len(samples)
    b = sum(s[2] for s in samples) // len(samples)
    return (r, g, b)


def remove_background(
    img: Image.Image,
    bg_color: tuple[int, ...],
    tolerance: int = 30,
    feather: int = 1,
) -> Image.Image:
    """Remove the background color, making matching pixels transparent."""
    img_rgb = img.convert("RGB")
    w, h = img_rgb.size

    bg_r, bg_g, bg_b = bg_color

    mask = Image.new("L", (w, h), 0)
    mask_pixels = mask.load()
    img_pixels = img_rgb.load()

    tol_sq = tolerance * tolerance * 3

    for y in range(h):
        for x in range(w):
            r, g, b = img_pixels[x, y]
            dr = r - bg_r
            dg = g - bg_g
            db = b - bg_b
            dist_sq = dr * dr + dg * dg + db * db
            if dist_sq > tol_sq:
                mask_pixels[x, y] = 255

    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))

    result = img_rgb.copy()
    result.putalpha(mask)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove background from an icon image to create a transparent PNG.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", help="Path to the input image")
    parser.add_argument("--output", "-o", help="Output path (default: overwrite input or *_transparent.png)")
    parser.add_argument("--tolerance", "-t", type=int, default=30, help="Color distance tolerance (0-100), default 30. Higher = more pixels removed.")
    parser.add_argument("--feather", "-f", type=int, default=1, help="Edge feather radius in pixels, default 1")
    parser.add_argument("--bg-color", help="Force background color as R,G,B (e.g. '255,255,255'). Auto-detected if omitted.")

    args = parser.parse_args()

    img_path = Path(args.image)
    if not img_path.exists():
        print(f"ERROR: file not found: {img_path}", file=sys.stderr)
        sys.exit(1)

    img = Image.open(img_path)
    print(f"Input: {img_path} ({img.size[0]}x{img.size[1]}, mode={img.mode})")

    if args.bg_color:
        try:
            parts = [int(x.strip()) for x in args.bg_color.split(",")]
            bg_color = tuple(parts)
        except Exception:
            print("ERROR: --bg-color must be R,G,B format, e.g. '255,255,255'", file=sys.stderr)
            sys.exit(1)
    else:
        bg_color = sample_background_color(img)
    print(f"Background color: RGB{bg_color}")

    result = remove_background(img, bg_color, tolerance=args.tolerance, feather=args.feather)

    if args.output:
        out_path = Path(args.output)
    else:
        stem = img_path.stem
        out_path = img_path.with_name(f"{stem}_transparent.png")

    result.save(out_path, "PNG")
    print(f"Output: {out_path}")
    print(f"  Background removed, transparent PNG saved.")


if __name__ == "__main__":
    main()
