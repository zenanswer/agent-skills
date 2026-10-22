"""Geometry normalization: trim -> scale -> consistent padding -> fixed sizes.

Why this exists: image models and logo packs both scatter their artwork inside
arbitrary amounts of whitespace. Dropping those files straight into slides gives
a set where one icon looks huge and the next looks tiny, and where brand logos
sit off-center. Normalizing every asset to the same square canvas with the same
padding ratio fixes the "doesn't look like a set" problem.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

DEFAULT_SIZES = (1024, 512)
DEFAULT_PADDING = 0.08


def load_rgba(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def trim(im: Image.Image, threshold: int = 8) -> Image.Image:
    """Crop to the visible (non-transparent) bounding box."""
    im = im.convert("RGBA")
    alpha = im.getchannel("A").point(lambda v: 255 if v > threshold else 0)
    bbox = alpha.getbbox()
    if not bbox:
        return im
    return im.crop(bbox)


def normalize(
    im: Image.Image,
    padding: float = DEFAULT_PADDING,
    canvas: int | None = None,
    trimming: bool = True,
) -> Image.Image:
    """Return a square RGBA canvas with the artwork centered and evenly padded."""
    im = im.convert("RGBA")
    content = trim(im) if trimming else im
    w, h = content.size
    if w <= 0 or h <= 0:
        size = canvas or DEFAULT_SIZES[0]
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))

    padding = min(max(padding, 0.0), 0.45)
    if canvas is None:
        canvas = max(1, round(max(w, h) / (1 - 2 * padding)))
    target = canvas * (1 - 2 * padding)
    scale = target / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    scaled = content.resize((nw, nh), Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.alpha_composite(scaled, ((canvas - nw) // 2, (canvas - nh) // 2))
    return out


def alpha_stats(im: Image.Image) -> dict:
    """Content coverage, centering and edge-touch diagnostics."""
    im = im.convert("RGBA")
    w, h = im.size
    alpha = im.getchannel("A")
    bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bbox:
        return {
            "empty": True,
            "size": [w, h],
            "bbox": None,
            "coverage": 0.0,
            "center_offset_x": 0,
            "center_offset_y": 0,
            "touches_border": False,
            "partial_alpha_ratio": 0.0,
        }
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    cx, cy = bbox[0] + bw / 2, bbox[1] + bh / 2
    opaque = sum(alpha.histogram()[9:]) / (w * h)  # alpha >= 9
    partial = sum(alpha.histogram()[1:250]) / (w * h)
    return {
        "empty": False,
        "size": [w, h],
        "bbox": list(bbox),
        "coverage": round(opaque, 4),
        "center_offset_x": round(cx - w / 2, 1),
        "center_offset_y": round(cy - h / 2, 1),
        "touches_border": bbox[0] <= 2
        or bbox[1] <= 2
        or bbox[2] >= w - 2
        or bbox[3] >= h - 2,
        "partial_alpha_ratio": round(partial, 4),
    }


def save_sizes(
    im: Image.Image,
    out_dir: str | Path,
    stem: str,
    sizes: tuple[int, ...] = DEFAULT_SIZES,
    suffix: str = "",
) -> list[Path]:
    """Write one PNG per size. Largest is <stem><suffix>.png, others @<size>."""
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
    out = []
    for part in spec.replace(" ", ",").split(","):
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
