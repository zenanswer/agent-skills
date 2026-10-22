#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.28",
#   "pillow>=10.0",
#   "resvg-py>=0.2",
# ]
# ///
"""Offline smoke tests for icon-finder (no network, no API keys).

Run: uv run tests/smoke.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from logokit import normalize, render, sheet, sources, svg
from PIL import Image

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "ok  " if cond else "FAIL"
    print(f"[{mark}] {name}{'' if not detail else '  (' + detail + ')'}")


WIDE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 153">
<path fill="#252f3e" d="M10 10h236v30H10z"/><path fill="#ff9900" d="M10 60h160v20H10z"/></svg>"""

MONO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<path fill="none" d="M0 0h24v24H0z"/>
<path style="fill:#333333" d="M2 2h20v20H2z"/>
<path stroke="#abcdef" stroke-width="2" d="M4 4L20 20"/></svg>"""


def test_sources() -> None:
    check("prettify aws", sources.prettify("aws") == "AWS")
    check("prettify aws-lambda", sources.prettify("aws-lambda") == "AWS Lambda")
    check("prettify node.js", sources.prettify("node.js") == "Node.js")
    check(
        "simpleicons slug",
        sources.compute_si_slug("Node.js") == "nodotjs"
        or sources.compute_si_slug("Node.js") == "nodejs",
    )
    check("exact match scores 100", sources.name_score("aws", "aws") == 100)
    check("typo tolerance", sources.name_score("kubernets", "kubernetes") > 0)
    check("no false fuzzy hit", sources.name_score("react", "relace") == 0)
    expanded, note = sources.expand_query("k8s")
    check("abbreviation expansion", expanded == "kubernetes" and bool(note))
    color = sources.resolve_ref("iconify:logos:aws")
    mono = sources.resolve_ref("simpleicons:github")
    check("ref parsing iconify", color["id"] == "iconify:logos:aws")
    check("ref parsing simpleicons", mono["meta"]["slug"] == "github")
    check(
        "dedupe separates mono", sources.dedupe_key(color) != sources.dedupe_key(mono)
    )
    check("iconify preview url uses slash", "logos/aws.svg" in color["preview_url"])


def test_svg() -> None:
    check("multicolor detected", svg.is_multicolor(WIDE_SVG))
    check("monochrome detected", not svg.is_multicolor(MONO_SVG))
    check("colors listed", set(svg.colors_in(WIDE_SVG)) == {"#252f3e", "#ff9900"})
    recolored = svg.recolor_svg(WIDE_SVG, "#FFFFFF")
    check("recolor injected", "!important" in recolored and "#FFFFFF" in recolored)
    kept_none = svg.recolor_svg(MONO_SVG, "#FFFFFF")
    check("fill=none preserved", '[fill="none"]{fill:none !important;}' in kept_none)
    check("stroke recolored when present", "stroke:#FFFFFF !important" in kept_none)
    check("inline style overridden", "!important" in kept_none)


def test_render() -> None:
    dims = render.svg_size(WIDE_SVG)
    check("viewBox parsed", dims == (256.0, 153.0), str(dims))
    png = render.render_bytes(WIDE_SVG, 512)
    im = Image.open(__import__("io").BytesIO(png))
    check(
        "aspect preserved on render",
        abs(im.size[1] - round(512 * 153 / 256)) <= 2,
        f"{im.size}",
    )
    check(
        "renderer available", render.renderer_name() != "none", render.renderer_name()
    )


def test_normalize() -> None:
    canvas = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    canvas.alpha_composite(Image.new("RGBA", (100, 100), (255, 0, 0, 255)), (40, 190))
    out = normalize.normalize(canvas, padding=0.08, canvas=1024)
    bbox = out.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    check("normalized canvas is square", out.size == (1024, 1024), str(out.size))
    check("content long edge ~84%", abs(max(w, h) - 860) <= 2, f"{w}x{h}")
    stats = normalize.alpha_stats(out)
    check(
        "content centered",
        abs(stats["center_offset_x"]) <= 1 and abs(stats["center_offset_y"]) <= 1,
        str(stats),
    )
    check("no border touch", not stats["touches_border"])

    with tempfile.TemporaryDirectory() as tmp:
        files = normalize.save_sizes(out, tmp, "logo", (1024, 512))
        names = sorted(p.name for p in files)
        check("multi-size output", names == ["logo.png", "logo@512.png"], str(names))
        check(
            "sizes written",
            Image.open(files[0]).size == (1024, 1024)
            and Image.open(files[1]).size == (512, 512),
        )

    tight = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    check("border touch detected", normalize.alpha_stats(tight)["touches_border"])
    empty = normalize.alpha_stats(Image.new("RGBA", (32, 32), (0, 0, 0, 0)))
    check("empty detected", empty["empty"] is True)


def test_sheet() -> None:
    red = Image.new("RGBA", (64, 64), (200, 30, 30, 255))
    with tempfile.TemporaryDirectory() as tmp:
        path = sheet.make_sheet(
            [
                {"image": red, "label": "Alpha", "sub": "iconify"},
                {"image": red, "label": "Beta", "sub": "svgl"},
            ],
            Path(tmp) / "sheet.png",
            cell=120,
            cols=2,
            title="test",
        )
        check("sheet written", path.exists() and path.stat().st_size > 1000)
        with Image.open(path) as im:
            check("sheet has 2 columns", im.width == 24 + 2 * (120 + 24), str(im.size))


def main() -> int:
    for fn in (test_sources, test_svg, test_render, test_normalize, test_sheet):
        print(f"\n== {fn.__name__}")
        fn()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
