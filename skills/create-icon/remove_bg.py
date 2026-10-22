#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pillow>=10.0",
# ]
# ///
"""Remove a solid background from a generated icon to produce a transparent PNG.

Unlike a plain color key, this keeps *interior* whites (cloud fills, gear holes,
speech bubbles): only the background region connected to the image border is
cleared. Edges get a soft alpha ramp plus de-fringing, so there is no white halo.

Modes:
    auto    keep existing alpha if the image is already transparent, else flood
    flood   connected background flood-fill (default, safest)
    chroma  plain color key (for flat backgrounds with holes cut to the border)

Usage:
    uv run remove_bg.py icon.png
    uv run remove_bg.py icon.png -o icon_transparent.png --tolerance 18
    uv run remove_bg.py icon.png --mode chroma --bg-color "255,255,255"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

DEFAULT_TOLERANCE = 14


def sample_bg(im: Image.Image) -> tuple[int, int, int]:
    """Robust background sample from the eight border midpoints/corners."""
    rgb = im.convert("RGB")
    w, h = rgb.size
    pts = [
        (0, 0),
        (w - 1, 0),
        (0, h - 1),
        (w - 1, h - 1),
        (w // 2, 0),
        (w // 2, h - 1),
        (0, h // 2),
        (w - 1, h // 2),
    ]
    samples = sorted(rgb.getpixel(p) for p in pts)
    return tuple(int(v) for v in samples[len(samples) // 2])  # type: ignore[return-value]


def color_diff(im: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """Per-pixel Chebyshev distance to the background color (fast, C-level)."""
    r, g, b = im.convert("RGB").split()
    ref = Image.new("RGB", im.size, bg)
    rr, gg, bb = ref.split()
    return ImageChops.lighter(
        ImageChops.lighter(ImageChops.difference(r, rr), ImageChops.difference(g, gg)),
        ImageChops.difference(b, bb),
    )


def _flood_exterior(im: Image.Image, diff: Image.Image, tolerance: int) -> Image.Image:
    """Mask of background pixels connected to the border (255 = exterior)."""
    near = diff.point(lambda v: 255 if v <= tolerance else 0)
    region = ImageOps.invert(near)  # 0 = near background, 255 = artwork
    w, h = im.size
    marker = 128
    seeds = []
    for x in range(w):
        seeds.extend(((x, 0), (x, h - 1)))
    for y in range(h):
        seeds.extend(((0, y), (w - 1, y)))
    seeded = False
    for seed in seeds:
        if region.getpixel(seed) == 0:
            ImageDraw.floodfill(region, seed, marker, thresh=0)
            seeded = True
    if not seeded:
        return Image.new("L", (w, h), 0)
    return region.point(lambda v: 255 if v == marker else 0)


def _defringe(
    im: Image.Image, alpha: Image.Image, bg: tuple[int, int, int]
) -> Image.Image:
    """Remove background color bleeding from semi-transparent edge pixels."""
    out = im.convert("RGBA").copy()
    out.putalpha(alpha)
    partial = alpha.point(lambda v: 255 if 0 < v < 250 else 0)
    bbox = partial.getbbox()
    if not bbox:
        return out
    region = out.crop(bbox)
    px = region.load()
    for y in range(region.height):
        for x in range(region.width):
            r, g, b, a = px[x, y]
            if a == 0 or a >= 250:
                continue
            scale = a / 255.0
            nr = (r - (1 - scale) * bg[0]) / scale
            ng = (g - (1 - scale) * bg[1]) / scale
            nb = (b - (1 - scale) * bg[2]) / scale
            px[x, y] = (
                max(0, min(255, round(nr))),
                max(0, min(255, round(ng))),
                max(0, min(255, round(nb))),
                a,
            )
    out.paste(region, bbox[:2])
    return out


def remove_background(
    im: Image.Image,
    *,
    tolerance: int = DEFAULT_TOLERANCE,
    feather: float = 0.8,
    mode: str = "auto",
    bg_color: tuple[int, int, int] | None = None,
) -> tuple[Image.Image, dict]:
    """Return (RGBA image, info dict)."""
    im = im.convert("RGBA")
    bg = tuple(bg_color) if bg_color else sample_bg(im)
    w, h = im.size
    alpha = im.getchannel("A")
    already = sum(alpha.histogram()[:9]) / (w * h)

    info = {
        "mode": mode,
        "bg_color": list(bg),
        "tolerance": tolerance,
        "already_transparent": round(already, 4),
        "note": "",
    }

    if mode == "auto":
        mode = "keep" if already > 0.02 else "flood"
        info["mode"] = mode

    if mode == "keep":
        info["note"] = "image already has transparency; left as is"
        return im, info

    diff = color_diff(im, bg)
    if mode == "chroma":
        # Linear ramp: fully transparent at tolerance, opaque well past it.
        soft = max(tolerance, 1) * 4
        alpha_mask = diff.point(
            lambda v: 0
            if v <= tolerance
            else min(255, int((v - tolerance) * 255 / soft))
        )
        exterior = diff.point(lambda v: 255 if v <= tolerance else 0)
        if feather > 0:
            alpha_mask = alpha_mask.filter(ImageFilter.GaussianBlur(feather))
        info["note"] = (
            "chroma key: interior pixels matching the background are also removed"
        )
    else:
        exterior = _flood_exterior(im, diff, tolerance)
        alpha_mask = ImageOps.invert(exterior)
        if feather > 0:
            alpha_mask = alpha_mask.filter(ImageFilter.GaussianBlur(feather))
            # Never let the blurred edge spill outside the detected background.
            alpha_mask = ImageChops.multiply(alpha_mask, ImageOps.invert(exterior))
        info["exterior_ratio"] = round(sum(exterior.histogram()[200:]) / (w * h), 4)
        if info.get("exterior_ratio", 0) < 0.01:
            info["note"] = (
                "almost no background detected - the icon may touch the border; "
                "try --mode chroma or raise --tolerance"
            )

    # Keep any pre-existing transparency.
    alpha_mask = ImageChops.multiply(alpha_mask, alpha)
    out = _defringe(im, alpha_mask, bg)
    return out, info


def parse_bg(text: str) -> tuple[int, int, int]:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3:
        raise SystemExit("ERROR: --bg-color must be R,G,B, e.g. '255,255,255'")
    try:
        return tuple(int(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        raise SystemExit("ERROR: --bg-color must be R,G,B, e.g. '255,255,255'")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Remove a solid background from an icon (keeps interior whites).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("image", help="Input image path")
    ap.add_argument(
        "--output", "-o", help="Output path (default: <stem>_transparent.png)"
    )
    ap.add_argument(
        "--tolerance",
        "-t",
        type=int,
        default=DEFAULT_TOLERANCE,
        help=f"Background color distance threshold (default {DEFAULT_TOLERANCE}, 0-255)",
    )
    ap.add_argument(
        "--feather",
        "-f",
        type=float,
        default=0.8,
        help="Edge softening radius (default 0.8)",
    )
    ap.add_argument(
        "--mode", choices=["auto", "flood", "chroma", "keep"], default="auto"
    )
    ap.add_argument("--bg-color", help="Force background color as R,G,B")
    ap.add_argument("--json", action="store_true", help="Print the info dict as JSON")
    args = ap.parse_args()

    path = Path(args.image)
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    im = Image.open(path)
    print(f"Input: {path} ({im.size[0]}x{im.size[1]}, mode={im.mode})")
    result, info = remove_background(
        im,
        tolerance=args.tolerance,
        feather=args.feather,
        mode=args.mode,
        bg_color=parse_bg(args.bg_color) if args.bg_color else None,
    )
    out_path = (
        Path(args.output)
        if args.output
        else path.with_name(f"{path.stem}_transparent.png")
    )
    result.save(out_path, "PNG", optimize=True)
    print(f"Background: RGB{tuple(info['bg_color'])}  mode: {info['mode']}")
    if info.get("note"):
        print(f"Note: {info['note']}")
    print(f"Output: {out_path}")
    if args.json:
        print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
