#!/usr/bin/env python3
"""Fetch and render a single icon as both SVG and PNG (transparent background).

Proxy: set HTTPS_PROXY / HTTP_PROXY environment variables.

Usage:
  python fetch_icon.py <source:slug> [--out DIR] [--size 512] [--style color|mono] [--color HEX]

The <source:slug> identifier comes from search_icons.py output `id` field:
  - iconify:    "logos:aws"
  - simpleicons: "amazonwebservices"

Outputs <name>.svg and <name>.png into --out (default ./logos).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

ICONIFY_SVG_URL = "https://api.iconify.design/{icon}.svg"
SIMPLEICONS_CDN_URL = "https://cdn.simpleicons.org/{slug}{color}"
SIMPLEICONS_JSON_URL = "https://cdn.jsdelivr.net/npm/simple-icons@latest/_data/simple-icons.json"

REQUEST_TIMEOUT = 30


def get_proxy() -> dict[str, str] | None:
    """Build a requests proxies dict from HTTPS_PROXY / HTTP_PROXY env vars."""
    proxies: dict[str, str] = {}
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = os.environ.get(var)
        if val:
            scheme = "https" if var.lower().startswith("https") else "http"
            proxies.setdefault(scheme, val)
    return proxies or None


PROXIES = get_proxy()


def make_session() -> requests.Session:
    s = requests.Session()
    if PROXIES:
        s.proxies.update(PROXIES)
    return s


def compute_si_slug(title: str) -> str:
    """Compute the Simple Icons slug from a title (lowercase, alnum only)."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def parse_ref(ref: str) -> tuple[str, str]:
    """Parse a source:slug reference like 'iconify:logos:aws' or 'amazonwebservices'."""
    if ":" in ref:
        parts = ref.split(":", 1)
        source = parts[0]
        slug = parts[1]
        if source == "iconify" and slug.startswith("logos:"):
            slug = slug.split(":", 1)[1]
        return source, slug
    if ref.startswith("logos/"):
        return "iconify", ref.split("/", 1)[1]
    return "simpleicons", ref


def safe_name(slug: str) -> str:
    s = slug.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "icon"


def _get_simpleicons_entry(slug: str) -> dict[str, Any] | None:
    """Look up a Simple Icons entry by computed slug. Returns the entry dict or None."""
    session = make_session()
    try:
        resp = session.get(SIMPLEICONS_JSON_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        icons = data if isinstance(data, list) else data.get("icons", [])
        for entry in icons:
            if compute_si_slug(entry.get("title", "")) == slug:
                return entry
    except (requests.RequestException, ValueError):
        pass
    return None


def _get_simpleicons_color(slug: str) -> str | None:
    entry = _get_simpleicons_entry(slug)
    if entry:
        hex_val = entry.get("hex")
        return f"#{hex_val}" if hex_val else None
    return None


def fetch_svg(source: str, slug: str, style: str, color: str | None) -> tuple[str, str | None]:
    """Fetch the raw SVG string. Returns (svg_text, brand_color)."""
    session = make_session()

    if source == "iconify":
        url = ICONIFY_SVG_URL.format(icon=f"logos:{slug}")
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        svg = resp.text
        if style == "mono" and color:
            svg = _recolor_svg(svg, color)
        return svg, None

    if source == "simpleicons":
        brand_color = _get_simpleicons_color(slug)
        color_param = ""
        if style == "mono":
            target = color or brand_color
            if target:
                normalized = target.lstrip("#")
                color_param = f"/{normalized}"
        url = SIMPLEICONS_CDN_URL.format(slug=slug, color=color_param)
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            raise RuntimeError(
                f"Simple Icons CDN does not serve '{slug}' (HTTP 404). "
                f"Some brands (AWS, Azure, Vue.js, Java, etc.) are excluded from the CDN "
                f"for trademark/legal reasons even though they appear in the data. "
                f"Search again and pick an 'iconify' source candidate instead - e.g. "
                f"run: python scripts/search_icons.py \"{slug}\""
            )
        resp.raise_for_status()
        svg = resp.text
        if style == "mono" and color:
            svg = _recolor_svg(svg, color)
        return svg, brand_color

    raise ValueError(f"Unknown source: {source}")


def _recolor_svg(svg: str, color: str) -> str:
    """Replace the fill color in an SVG with the given hex color."""
    normalized = color if color.startswith("#") else f"#{color}"
    svg = re.sub(r'fill="[^"]*"', f'fill="{normalized}"', svg)
    if 'fill="' not in svg:
        svg = svg.replace("<path ", f'<path fill="{normalized}" ', 1)
    return svg


def render_png(svg_text: str, out_path: Path, size: int) -> None:
    """Render SVG to PNG (transparent background). Tries cairosvg then rsvg-convert."""
    try:
        import cairosvg
        cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            write_to=str(out_path),
            output_width=size,
            output_height=size,
        )
        return
    except ImportError:
        pass
    except Exception as exc:
        print(f"[warn] cairosvg render failed ({exc}); trying rsvg-convert.", file=sys.stderr)

    if shutil.which("rsvg-convert"):
        tmp_svg = out_path.with_suffix(".tmp.svg")
        tmp_svg.write_text(svg_text)
        try:
            subprocess.run(
                ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(out_path), str(tmp_svg)],
                check=True,
            )
            return
        finally:
            tmp_svg.unlink(missing_ok=True)

    print(
        "[error] No SVG renderer available. Install with:\n"
        "  pip install cairosvg   (and `brew install cairo` on macOS)\n"
        "  OR  brew install librsvg",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and render an icon as SVG + PNG.")
    parser.add_argument("ref", help="source:slug id from search_icons.py (e.g. 'iconify:logos:aws').")
    parser.add_argument("--out", default="./logos", help="Output directory (default ./logos).")
    parser.add_argument("--size", type=int, default=512, help="PNG long-edge size in px (default 512).")
    parser.add_argument("--style", choices=["color", "mono"], default="color",
                        help="Render style (default color).")
    parser.add_argument("--color", help="Hex color for mono style (e.g. '#FF9900'). Defaults to brand color.")
    parser.add_argument("--svg-only", action="store_true", help="Only output SVG, skip PNG.")
    args = parser.parse_args()

    if PROXIES:
        print(f"[info] Using proxy: {PROXIES.get('https') or PROXIES.get('http')}", file=sys.stderr)

    source, slug = parse_ref(args.ref)
    name = safe_name(slug)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    svg_text, brand_color = fetch_svg(source, slug, args.style, args.color)

    svg_path = out_dir / f"{name}.svg"
    svg_path.write_text(svg_text, encoding="utf-8")
    print(f"SVG: {svg_path.resolve()}")

    if not args.svg_only:
        png_path = out_dir / f"{name}.png"
        render_png(svg_text, png_path, args.size)
        print(f"PNG: {png_path.resolve()}")

    if brand_color:
        print(f"Brand color: {brand_color}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
