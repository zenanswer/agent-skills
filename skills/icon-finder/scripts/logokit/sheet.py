"""Contact-sheet previews.

Text lists of candidate names are hard to judge. A single labelled PNG grid lets
the user (and the agent, via vision) pick the right logo at a glance.
"""

from __future__ import annotations

import io
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import render
from . import svg as svgmod

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)

PALETTES = {
    "light": {
        "bg": (245, 245, 247, 255),
        "card": (255, 255, 255, 255),
        "fg": (24, 24, 27, 255),
        "sub": (110, 113, 122, 255),
    },
    "dark": {
        "bg": (18, 18, 22, 255),
        "card": (30, 30, 36, 255),
        "fg": (244, 244, 245, 255),
        "sub": (160, 163, 172, 255),
    },
}


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ell = "..."
    while text and draw.textlength(text + ell, font=font) > max_width:
        text = text[:-1]
    return text + ell


def _to_image(value: Any) -> Image.Image | None:
    try:
        if isinstance(value, Image.Image):
            return value.convert("RGBA")
        if isinstance(value, (bytes, bytearray)):
            return Image.open(io.BytesIO(bytes(value))).convert("RGBA")
        if value is None:
            return None
        return Image.open(Path(value)).convert("RGBA")
    except Exception:  # noqa: BLE001 - a broken preview must not kill the sheet
        return None


def make_sheet(
    items: Iterable[dict[str, Any]],
    out_path: str | Path,
    *,
    cell: int = 220,
    cols: int | None = None,
    theme: str = "light",
    title: str | None = None,
) -> Path:
    """Compose a labelled grid. Each item: {image, label, sub?}."""
    items = list(items)
    if not items:
        raise ValueError("nothing to draw")
    palette = PALETTES.get(theme, PALETTES["light"])
    cols = cols or min(4, max(1, len(items)))
    rows = (len(items) + cols - 1) // cols
    pad, label_h = 24, 46
    title_h = 52 if title else 0
    width = pad + cols * (cell + pad)
    height = pad + title_h + rows * (cell + label_h + pad)

    sheet = Image.new("RGBA", (width, height), palette["bg"])
    draw = ImageDraw.Draw(sheet)
    if title:
        draw.text((pad, pad), title, font=_font(26), fill=palette["fg"])

    for idx, item in enumerate(items):
        r, c = divmod(idx, cols)
        x = pad + c * (cell + pad)
        y = pad + title_h + r * (cell + label_h + pad)
        draw.rounded_rectangle(
            [x, y, x + cell, y + cell], radius=14, fill=palette["card"]
        )
        img = _to_image(item.get("image"))
        if img is not None:
            inner = cell - 24
            if img.width > inner or img.height > inner:
                img.thumbnail((inner, inner), Image.LANCZOS)
            sheet.alpha_composite(
                img, (x + (cell - img.width) // 2, y + (cell - img.height) // 2)
            )
        else:
            draw.line(
                [x + 20, y + cell // 2, x + cell - 20, y + cell // 2],
                fill=palette["sub"],
                width=2,
            )
            draw.text(
                (x + cell // 2 - 18, y + cell // 2 - 24),
                "n/a",
                font=_font(16),
                fill=palette["sub"],
            )

        label = str(item.get("label") or "")
        sub = str(item.get("sub") or "")
        f_main, f_sub = _font(17), _font(13)
        label = _ellipsize(draw, label, f_main, cell - 8)
        lw = draw.textlength(label, font=f_main)
        draw.text(
            (x + (cell - lw) / 2, y + cell + 8), label, font=f_main, fill=palette["fg"]
        )
        if sub:
            sub = _ellipsize(draw, sub, f_sub, cell - 8)
            sw = draw.textlength(sub, font=f_sub)
            draw.text(
                (x + (cell - sw) / 2, y + cell + 29),
                sub,
                font=f_sub,
                fill=palette["sub"],
            )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out_path, "PNG", optimize=True)
    return out_path


def sheet_from_candidates(
    candidates: list[dict[str, Any]],
    out_path: str | Path,
    *,
    size: int = 200,
    theme: str = "light",
    title: str | None = None,
    variant: str = "auto",
) -> Path:
    """Fetch candidate previews concurrently and draw them on one sheet."""

    def load(cand: dict[str, Any]) -> Image.Image | None:
        try:
            fetched = svgmod.fetch_candidate(cand, variant=variant)
            return render.render_to_image(fetched["svg"], size)
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        images = list(pool.map(load, candidates))

    items = []
    for cand, img in zip(candidates, images):
        tags = cand["source"]
        if cand.get("brand_color"):
            tags += f" {cand['brand_color']}"
        items.append({"image": img, "label": cand["title"], "sub": tags})
    return make_sheet(items, out_path, cell=size, theme=theme, title=title)
