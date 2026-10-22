"""Geometry normalization for generated icons.

Generated icons arrive with wildly different margins and visual weights. This
module trims to the artwork, scales the long edge to 84% of the canvas, centers
it, and exports a fixed set of sizes - so a whole icon set looks consistent in
a deck.

Two background modes:
    bg=None          transparent canvas (after background removal)
    bg=(r, g, b)     opaque canvas painted with that color
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageChops

DEFAULT_SIZES = (1024, 512)
DEFAULT_PADDING = 0.08


def load(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def bg_from_corners(im: Image.Image) -> tuple[int, int, int]:
    """Median-ish background color from eight border samples."""
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
    mid = samples[len(samples) // 2]
    return tuple(int(v) for v in mid)  # type: ignore[return-value]


def _color_diff_mask(im: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    """Chebyshev distance between each pixel and the background color."""
    r, g, b = im.convert("RGB").split()
    ref = Image.new("RGB", im.size, bg)
    rr, gg, bb = ref.split()
    d = ImageChops.lighter(
        ImageChops.lighter(ImageChops.difference(r, rr), ImageChops.difference(g, gg)),
        ImageChops.difference(b, bb),
    )
    return d


def content_bbox(
    im: Image.Image,
    *,
    bg: tuple[int, int, int] | None = None,
    tolerance: int = 14,
    alpha_threshold: int = 8,
) -> tuple[int, int, int, int] | None:
    im = im.convert("RGBA")
    if bg is None:
        alpha = im.getchannel("A").point(lambda v: 255 if v > alpha_threshold else 0)
        return alpha.getbbox()
    diff = _color_diff_mask(im, bg).point(lambda v: 255 if v > tolerance else 0)
    # Ignore fully transparent areas even in color mode.
    diff = ImageChops.multiply(
        diff, im.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    )
    return diff.getbbox()


def normalize(
    im: Image.Image,
    *,
    padding: float = DEFAULT_PADDING,
    canvas: int | None = None,
    bg: tuple[int, int, int] | None = None,
    trimming: bool = True,
    tolerance: int = 14,
) -> Image.Image:
    """Return a square canvas with the artwork centered and evenly padded."""
    im = im.convert("RGBA")
    bbox = content_bbox(im, bg=bg, tolerance=tolerance) if trimming else None
    content = im.crop(bbox) if bbox else im
    w, h = content.size
    padding = min(max(padding, 0.0), 0.45)
    if canvas is None:
        canvas = max(1, round(max(w, h) / (1 - 2 * padding)))
    if w <= 0 or h <= 0:
        return Image.new("RGBA", (canvas, canvas), (*bg, 255) if bg else (0, 0, 0, 0))

    target = canvas * (1 - 2 * padding)
    scale = target / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    scaled = content.resize((nw, nh), Image.LANCZOS)
    fill = (*bg, 255) if bg else (0, 0, 0, 0)
    out = Image.new("RGBA", (canvas, canvas), fill)
    out.alpha_composite(scaled, ((canvas - nw) // 2, (canvas - nh) // 2))
    return out


def alpha_stats(im: Image.Image) -> dict:
    im = im.convert("RGBA")
    w, h = im.size
    alpha = im.getchannel("A")
    hist = alpha.histogram()
    bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bbox:
        return {
            "empty": True,
            "size": [w, h],
            "bbox": None,
            "coverage": 0.0,
            "center_offset_x": 0.0,
            "center_offset_y": 0.0,
            "touches_border": False,
            "partial_alpha_ratio": 0.0,
        }
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cx, cy = bbox[0] + bw / 2, bbox[1] + bh / 2
    return {
        "empty": False,
        "size": [w, h],
        "bbox": list(bbox),
        "coverage": round(sum(hist[9:]) / (w * h), 4),
        "center_offset_x": round(cx - w / 2, 1),
        "center_offset_y": round(cy - h / 2, 1),
        "touches_border": bbox[0] <= 2
        or bbox[1] <= 2
        or bbox[2] >= w - 2
        or bbox[3] >= h - 2,
        "partial_alpha_ratio": round(sum(hist[1:250]) / (w * h), 4),
    }


def content_stats(
    im: Image.Image, bg: tuple[int, int, int] | None = None, tolerance: int = 14
) -> dict:
    """Stats that work for both transparent and opaque (backgrounded) icons."""
    im = im.convert("RGBA")
    w, h = im.size
    bbox = content_bbox(im, bg=bg, tolerance=tolerance)
    alpha = im.getchannel("A")
    hist = alpha.histogram()
    partial = round(sum(hist[1:250]) / (w * h), 4)
    if not bbox:
        return {
            "empty": True,
            "size": [w, h],
            "bbox": None,
            "coverage": 0.0,
            "center_offset_x": 0.0,
            "center_offset_y": 0.0,
            "touches_border": False,
            "partial_alpha_ratio": partial,
            "long_edge_ratio": 0.0,
        }
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cx, cy = bbox[0] + bw / 2, bbox[1] + bh / 2
    return {
        "empty": False,
        "size": [w, h],
        "bbox": list(bbox),
        "coverage": round((bw * bh) / (w * h), 4),
        "center_offset_x": round(cx - w / 2, 1),
        "center_offset_y": round(cy - h / 2, 1),
        "touches_border": bbox[0] <= 2
        or bbox[1] <= 2
        or bbox[2] >= w - 2
        or bbox[3] >= h - 2,
        "partial_alpha_ratio": partial,
        "long_edge_ratio": round(max(bw, bh) / w, 4),
    }


def save_sizes(
    im: Image.Image,
    out_dir: str | Path,
    stem: str,
    sizes: tuple[int, ...] = DEFAULT_SIZES,
    suffix: str = "",
) -> list[Path]:
    """Write <stem><suffix>.png (largest) plus <stem><suffix>@<size>.png."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted({int(s) for s in sizes if int(s) > 0}, reverse=True) or [1024]
    written: list[Path] = []
    for i, size in enumerate(ordered):
        name = f"{stem}{suffix}.png" if i == 0 else f"{stem}{suffix}@{size}.png"
        path = out_dir / name
        scaled = (
            im if im.size == (size, size) else im.resize((size, size), Image.LANCZOS)
        )
        scaled.save(path, "PNG", optimize=True)
        written.append(path)
    return written


def parse_sizes(
    spec: str | None, fallback: tuple[int, ...] = DEFAULT_SIZES
) -> tuple[int, ...]:
    if not spec:
        return fallback
    out: list[int] = []
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        try:
            value = int(part.rstrip("px"))
        except ValueError:
            raise SystemExit(
                f"ERROR: bad size '{part}' in --sizes (expected e.g. 1024,512)"
            )
        if value > 0:
            out.append(value)
    return tuple(out) or fallback


def slugify(text: str, fallback: str = "icon") -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE)
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:48] or fallback
