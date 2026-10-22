"""Render SVG to PNG while always preserving the source aspect ratio.

Renderer order:
  1. resvg-py   (pure pip wheel, no system libs - preferred)
  2. cairosvg   (needs libcairo)
  3. rsvg-convert binary

Every renderer is asked to *fit inside* a size x size box, never to stretch to
it. That was the bug that turned the 256x153 AWS logo into a 512x512 square.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

_VIEWBOX = re.compile(r'viewBox\s*=\s*"([^"]+)"', re.IGNORECASE)
_WIDTH = re.compile(r'\bwidth\s*=\s*"([0-9.]+)', re.IGNORECASE)
_HEIGHT = re.compile(r'\bheight\s*=\s*"([0-9.]+)', re.IGNORECASE)


def svg_size(svg: str) -> tuple[float, float] | None:
    """Read width/height from the viewBox, falling back to width/height attrs."""
    m = _VIEWBOX.search(svg)
    if m:
        parts = re.split(r"[\s,]+", m.group(1).strip())
        if len(parts) == 4:
            try:
                w, h = float(parts[2]), float(parts[3])
                if w > 0 and h > 0:
                    return w, h
            except ValueError:
                pass
    mw, mh = _WIDTH.search(svg), _HEIGHT.search(svg)
    if mw and mh:
        try:
            return float(mw.group(1)), float(mh.group(1))
        except ValueError:
            pass
    return None


def _render_resvg(svg: str, size: int, background: str | None) -> bytes | None:
    try:
        import resvg_py
    except ImportError:
        return None
    try:
        return bytes(
            resvg_py.svg_to_bytes(
                svg_string=svg,
                width=size,
                height=size,
                background=background,
            )
        )
    except Exception as exc:  # noqa: BLE001 - fall through to the next renderer
        print(f"[warn] resvg render failed ({exc}); trying cairosvg", file=sys.stderr)
        return None


def _render_cairosvg(svg: str, size: int, background: str | None) -> bytes | None:
    try:
        import cairosvg
    except ImportError:
        return None
    dims = svg_size(svg)
    kwargs = {"bytestring": svg.encode("utf-8"), "background_color": background}
    if dims:
        kwargs["scale"] = size / max(dims)
    else:
        kwargs["output_width"] = size
    try:
        return cairosvg.svg2png(**kwargs)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[warn] cairosvg render failed ({exc}); trying rsvg-convert",
            file=sys.stderr,
        )
        return None


def _render_rsvg(svg: str, size: int, background: str | None) -> bytes | None:
    binary = shutil.which("rsvg-convert")
    if not binary:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.svg"
        dst = Path(tmp) / "out.png"
        src.write_text(svg, encoding="utf-8")
        cmd = [binary, "-w", str(size), "-h", str(size), "-o", str(dst), str(src)]
        if background:
            cmd[1:1] = ["-b", background]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            print(
                f"[warn] rsvg-convert failed: {exc.stderr.decode(errors='ignore')[:200]}",
                file=sys.stderr,
            )
            return None
        return dst.read_bytes() if dst.exists() else None


def render_bytes(svg: str, size: int = 1024, background: str | None = None) -> bytes:
    """Render SVG into PNG bytes, fitted inside size x size, aspect preserved."""
    for fn in (_render_resvg, _render_cairosvg, _render_rsvg):
        data = fn(svg, size, background)
        if data:
            return data
    raise RuntimeError(
        "No SVG renderer available. Install one of:\n"
        "  uv run --with resvg-py ...   (recommended, pure pip)\n"
        "  pip install cairosvg          (also needs libcairo)\n"
        "  apt/brew install librsvg      (provides rsvg-convert)"
    )


def render_to_image(
    svg: str, size: int = 1024, background: str | None = None
) -> Image.Image:
    return Image.open(io.BytesIO(render_bytes(svg, size, background))).convert("RGBA")


def render_png(
    svg: str, out_path: Path, size: int = 1024, background: str | None = None
) -> tuple[int, int]:
    data = render_bytes(svg, size, background)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    with Image.open(out_path) as im:
        return im.size


def renderer_name() -> str:
    try:
        import resvg_py  # noqa: F401

        return "resvg-py"
    except ImportError:
        pass
    try:
        import cairosvg  # noqa: F401

        return "cairosvg"
    except ImportError:
        pass
    if shutil.which("rsvg-convert"):
        return "rsvg-convert"
    return "none"
