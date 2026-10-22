"""Fetch logo SVGs, inspect their colors, and recolor them safely.

Recoloring uses an injected stylesheet with ``!important`` so it also wins over
inline ``style="fill:#..."``, ``currentColor`` and gradient/stroke usage - the
old regex approach silently missed all of those.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from . import net, sources

_OPEN_TAG = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_COLOR_ATTR = re.compile(r'(?:fill|stop-color|color)\s*=\s*"([^"]+)"', re.IGNORECASE)
_STROKE_ATTR = re.compile(r'stroke\s*=\s*"([^"]+)"', re.IGNORECASE)
_HEX = re.compile(r"^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$", re.IGNORECASE)
_IGNORED_COLORS = {
    "none",
    "transparent",
    "currentcolor",
    "inherit",
    "context-fill",
    "context-stroke",
}


def _clean_color(value: str) -> str | None:
    v = value.strip().lower()
    if v in _IGNORED_COLORS or v.startswith("url("):
        return None
    if _HEX.match(v):
        if len(v) == 4:  # #abc -> #aabbcc
            return "#" + "".join(ch * 2 for ch in v[1:])
        return v[:7]
    m = re.match(r"rgba?\(([^)]+)\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).replace("/", " ").split(",")]
        try:
            r, g, b = (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
            return f"#{r:02x}{g:02x}{b:02x}"
        except (ValueError, IndexError):
            return None
    return None


def colors_in(svg: str) -> list[str]:
    """Distinct literal colors declared in the SVG (fills + gradient stops)."""
    found = []
    for raw in _COLOR_ATTR.findall(svg):
        c = _clean_color(raw)
        if c and c not in found:
            found.append(c)
    return found


def is_multicolor(svg: str) -> bool:
    return len(colors_in(svg)) > 1


def has_stroke(svg: str) -> bool:
    return any(_clean_color(v) for v in _STROKE_ATTR.findall(svg))


def recolor_svg(svg: str, color: str) -> str:
    """Force every painted element to a single color via an injected stylesheet."""
    target = color if color.startswith("#") else f"#{color.lstrip('#')}"
    shapes = "path,rect,circle,ellipse,polygon,polyline,line,text,tspan,use,g"
    rules = [
        f"{shapes}{{fill:{target} !important;}}",
        '[fill="none"]{fill:none !important;}',
        '[fill="transparent"]{fill:transparent !important;}',
    ]
    if has_stroke(svg):
        rules.append(f"{shapes}{{stroke:{target} !important;}}")
        rules.append('[stroke="none"]{stroke:none !important;}')
    style = "<style>" + "".join(rules) + "</style>"
    m = _OPEN_TAG.search(svg)
    if not m:
        raise ValueError("not an SVG document")
    return svg[: m.end()] + style + svg[m.end() :]


def is_svg(text: str) -> bool:
    head = text.lstrip()[:400].lower()
    return "<svg" in head or head.startswith("<?xml")


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #


def _url_for(candidate: dict[str, Any], variant: str) -> tuple[str, str]:
    """Return (url, native_variant) for a candidate + requested variant."""
    source = candidate["source"]
    meta = candidate.get("meta") or {}
    if source == "iconify":
        collection, name = meta.get("collection", "logos"), meta.get("name", "")
        return sources.ICONIFY_SVG_URL.format(collection=collection, name=name), "color"
    if source == "simpleicons":
        return sources.SIMPLEICONS_SVG_URL.format(slug=meta.get("slug", "")), "mono"
    if source == "svgl":
        route = meta.get("route") or candidate.get("preview_url") or {}
        wordmark = meta.get("wordmark")
        if variant == "wordmark" and wordmark:
            url = sources._url_of(wordmark, prefer="light")
            if url:
                return url, "wordmark"
        if isinstance(route, dict):
            if variant == "dark" and route.get("dark"):
                return route["dark"], "dark"
            if variant in {"light", "color", "auto"} and route.get("light"):
                return route["light"], variant if variant != "auto" else "color"
            if route.get("dark"):
                return route["dark"], "dark"
        url = sources._url_of(route)
        if not url:
            raise ValueError("svgl entry has no usable route")
        return url, "color"
    if source == "lobeicons":
        return sources.LOBE_SVG_URL.format(file=meta.get("file", "")), "color"
    if source == "url":
        return meta["url"], "color"
    raise ValueError(f"unsupported source '{source}'")


def fetch_candidate(
    candidate: dict[str, Any],
    *,
    variant: str = "auto",
    color: str | None = None,
    sess=None,
) -> dict[str, Any]:
    """Download an SVG and apply the requested variant.

    Returns {"svg", "variant", "recolored", "brand_color", "multicolor", "note"}.
    """
    s = sess or net.session()
    url, native = _url_for(candidate, variant)
    resp = net.get(url, sess=s)
    if resp.status_code == 404:
        raise RuntimeError(
            f"HTTP 404 for {url}. The brand may be missing from this source - "
            f'search again (search_icons.py "{candidate.get("title", "")}") and pick another source.'
        )
    resp.raise_for_status()
    svg = resp.text
    if not is_svg(svg):
        raise RuntimeError(
            f"{url} did not return SVG (content-type: {resp.headers.get('content-type', '?')})."
        )

    brand_color = candidate.get("brand_color")
    multicolor = is_multicolor(svg)
    recolor: str | None = None
    note = ""

    if variant == "mono":
        recolor = color or brand_color or candidate.get("default_color")
        if not recolor:
            raise ValueError(
                "mono rendering needs a color: pass --color '#FFFFFF' "
                "(this brand has no official hex in the index)."
            )
        if multicolor:
            note = "flattened a multi-color logo to one color (detail is lost)"
    elif variant == "dark" and native != "dark":
        recolor = color or "#FFFFFF"
        note = "no native dark variant for this source; recolored for dark backgrounds"
    elif variant == "light" and native == "dark":
        recolor = color or "#111111"
        note = "no native light variant; recolored for light backgrounds"
    elif variant == "wordmark" and native != "wordmark":
        note = "wordmark unavailable for this brand; using the icon mark"
    elif color:
        recolor = color

    if recolor:
        svg = recolor_svg(svg, recolor)

    return {
        "svg": svg,
        "url": url,
        "native_variant": native,
        "recolored": recolor,
        "brand_color": brand_color,
        "multicolor": multicolor,
        "note": note,
    }


def writes_svg(svg: str, path) -> None:
    path.write_text(svg, encoding="utf-8")


def warn(msg: str) -> None:
    print(f"[warn] {msg}", file=sys.stderr)
