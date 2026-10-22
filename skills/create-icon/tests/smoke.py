#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.28",
#   "pillow>=10.0",
# ]
# ///
"""Offline smoke tests for create-icon (no external API calls).

A tiny local HTTP server impersonates an OpenAI-compatible endpoint, so the
whole pipeline (prompt -> provider -> background removal -> normalization ->
manifest) is exercised end to end.

Run: uv run tests/smoke.py
"""

from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analyze_style
import check
import generate_icon
import normalize
import promptkit
import remove_bg
from PIL import Image, ImageDraw

PASS: list[str] = []
FAIL: list[str] = []
STYLES = promptkit.load_styles(ROOT / "styles.json")


def check_(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(
        f"[{'ok  ' if cond else 'FAIL'}] {name}{'' if not detail else '  (' + detail + ')'}"
    )


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


def mock_icon(size: int = 1024) -> Image.Image:
    """White background, blue donut (interior white must survive) + amber bar."""
    im = Image.new("RGB", (size, size), (255, 255, 255))
    d = ImageDraw.Draw(im)
    s = size / 1024
    d.ellipse([200 * s, 200 * s, 824 * s, 824 * s], fill=(30, 90, 200))
    d.ellipse([340 * s, 340 * s, 684 * s, 684 * s], fill=(255, 255, 255))
    d.rounded_rectangle(
        [760 * s, 60 * s, 960 * s, 140 * s], radius=20 * s, fill=(240, 160, 20)
    )
    return im


def png_b64(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #


def test_promptkit() -> None:
    prompt = promptkit.build_prompt("growth arrow", STYLES, style_key="flat-color")
    positive = prompt["positive"].lower()
    check_(
        "all styles have positive+negative",
        all(s.get("positive") and s.get("negative") for s in STYLES["styles"].values()),
    )
    check_("style count >= 16", len(STYLES["styles"]) >= 16, str(len(STYLES["styles"])))
    check_(
        "no duplicated composition clause",
        positive.count("single centered object") == 1,
    )
    check_("negative not empty", bool(prompt["negative"]))
    check_("background described", "background:" in positive)

    cn = promptkit.build_prompt("AI 算力", STYLES, style_key="line-monochrome")
    check_(
        "no article before CJK subject",
        cn["positive"].startswith("AI 算力, "),
        cn["positive"][:20],
    )
    check_("no 'a AI' artifact", "a AI" not in cn["positive"])

    with_palette = promptkit.build_prompt(
        "target",
        STYLES,
        style_key="flat-color",
        palette=promptkit.parse_palette("#1E3A8A, #F59E0B"),
    )
    check_(
        "palette injected",
        "#1e3a8a" in with_palette["positive"] and "#f59e0b" in with_palette["positive"],
    )

    custom = promptkit.build_prompt(
        "rocket", STYLES, custom_style="glassmorphism, pastel, soft glow"
    )
    check_(
        "custom style used",
        "glassmorphism" in custom["positive"] and custom["style_key"] == "custom",
    )

    inline = promptkit.prompt_for_provider(prompt, supports_negative=False)
    check_("negative folded for providers without the field", "avoid:" in inline)
    check_(
        "negative kept separate when supported",
        promptkit.prompt_for_provider(prompt, supports_negative=True)
        == prompt["positive"],
    )


def test_normalize() -> None:
    im = mock_icon().convert("RGBA")
    transparent = normalize.normalize(im, padding=0.08, canvas=1024, bg=None)
    stats = normalize.content_stats(transparent)
    check_("square canvas", transparent.size == (1024, 1024))
    check_(
        "long edge 84%",
        abs(stats["long_edge_ratio"] - 0.84) < 0.02,
        str(stats["long_edge_ratio"]),
    )
    check_(
        "centered",
        abs(stats["center_offset_x"]) <= 1 and abs(stats["center_offset_y"]) <= 1,
    )
    check_("padding: no border touch", not stats["touches_border"])

    opaque = normalize.normalize(im, padding=0.08, canvas=1024, bg=(255, 255, 255))
    check_(
        "opaque canvas keeps background", opaque.getpixel((5, 5))[:3] == (255, 255, 255)
    )

    with tempfile.TemporaryDirectory() as tmp:
        files = normalize.save_sizes(transparent, tmp, "icon", (1024, 512))
        names = sorted(p.name for p in files)
        check_("two size outputs", names == ["icon.png", "icon@512.png"], str(names))
        check_(
            "sizes correct",
            Image.open(files[0]).size == (1024, 1024)
            and Image.open(files[1]).size == (512, 512),
        )

    check_("slugify ascii", normalize.slugify("Growth Arrow") == "growth-arrow")
    check_("slugify cjk not empty", normalize.slugify("AI 算力") != "icon")


def test_remove_bg() -> None:
    im = mock_icon()
    out, info = remove_bg.remove_background(im, tolerance=14)
    check_("background made transparent", out.getpixel((10, 10))[3] == 0)
    check_(
        "interior white preserved",
        out.getpixel((512, 512))[:3] == (255, 255, 255)
        and out.getpixel((512, 512))[3] == 255,
    )
    check_("artwork kept", out.getpixel((512, 300))[3] == 255)
    check_("flood mode used", info["mode"] == "flood", info["mode"])
    check_(
        "edge softened",
        0 < out.getpixel((512, 200))[3] < 255,
        str(out.getpixel((512, 200))),
    )

    noop, info2 = remove_bg.remove_background(out, mode="auto")
    check_("auto keeps existing alpha", info2["mode"] == "keep")
    check_("idempotent alpha", noop.getpixel((512, 512))[3] == 255)

    chroma, _ = remove_bg.remove_background(im, mode="chroma", tolerance=14)
    check_("chroma mode runs", chroma.getpixel((512, 512))[3] == 0)  # hole is keyed out


def test_check() -> None:
    good = normalize.normalize(
        mock_icon().convert("RGBA"), padding=0.08, canvas=1024, bg=None
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "good.png"
        good.save(path)
        report = check.inspect(path, expect_transparent=True)
        check_("good icon passes", report["ok"], str(report["issues"]))

        bad_path = Path(tmp) / "bad.png"
        edge = mock_icon(256).copy()
        ImageDraw.Draw(edge).rectangle([0, 100, 40, 160], fill=(30, 90, 200))
        edge.save(bad_path)
        bad = check.inspect(bad_path)
        check_(
            "border-touching icon flagged",
            not bad["ok"] and any("touches_border" in i for i in bad["issues"]),
        )

        empty = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        empty_path = Path(tmp) / "empty.png"
        empty.save(empty_path)
        check_(
            "empty icon flagged",
            not check.inspect(empty_path, expect_transparent=True)["ok"],
        )


def test_palette() -> None:
    im = Image.new("RGB", (100, 100), (10, 20, 200))
    ImageDraw.Draw(im).rectangle([0, 0, 49, 99], fill=(245, 240, 200))
    palette = analyze_style.extract_palette(im.convert("RGBA"), 4)
    hexes = [item["hex"] for item in palette]
    check_(
        "dominant colors extracted",
        "#0a14c8" in hexes and len(palette) >= 2,
        str(hexes),
    )
    check_("shares sum ~1", abs(sum(item["share"] for item in palette) - 1.0) < 0.05)
    check_(
        "background sampled",
        analyze_style.background_color(im.convert("RGBA")) == "#0a14c8",
    )

    parsed = analyze_style.parse_json_response('```json\n{"style_tags": ["flat"]}\n```')
    check_("json fence stripped", parsed == {"style_tags": ["flat"]})
    check_(
        "legacy STYLE_PROMPT parsed",
        analyze_style.extract_style_line("x\nSTYLE_PROMPT: flat, bold") == "flat, bold",
    )


class MockHandler(BaseHTTPRequestHandler):
    calls: ClassVar[list[dict]] = []

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        MockHandler.calls.append({"path": self.path, "payload": payload})
        if not self.path.endswith("/images/generations"):
            self.send_response(404)
            self.end_headers()
            return
        n = int(payload.get("n", 1))
        body = json.dumps(
            {"data": [{"b64_json": png_b64(mock_icon())} for _ in range(n)]}
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


def test_end_to_end() -> None:
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    with tempfile.TemporaryDirectory() as tmp:
        argv = [
            "generate_icon.py",
            "--set",
            "growth,team",
            "-s",
            "flat-color",
            "-n",
            "2",
            "--transparent",
            "--palette",
            "#1E3A8A,#F59E0B",
            "--provider",
            "openai-compatible",
            "--host",
            f"http://127.0.0.1:{port}",
            "--model",
            "mock-image",
            "--api-key",
            "test",
            "--output",
            tmp,
            "--sizes",
            "1024,512",
            "--concurrency",
            "2",
        ]
        sys.argv = argv
        rc = generate_icon.main()
        check_("e2e exit code", rc == 0, str(rc))

        out = Path(tmp)
        files = sorted(p.name for p in out.glob("*.png"))
        check_(
            "e2e produced 8 files (2 subjects x 2 variants x 2 sizes)",
            len(files) == 8,
            str(files),
        )
        manifest_path = out / "icons.json"
        check_("manifest written", manifest_path.exists())
        manifest = json.loads(manifest_path.read_text())
        check_("manifest has 2 icons", len(manifest["icons"]) == 2)
        check_(
            "manifest records palette", manifest["palette"] == ["#1e3a8a", "#f59e0b"]
        )
        check_("manifest records provider", manifest["provider"] == "openai-compatible")
        check_(
            "provider got n=1 per call for non-gpt-image",
            all(c["payload"].get("n", 1) == 1 for c in MockHandler.calls),
        )
        check_(
            "prompt includes palette",
            all("#1e3a8a" in c["payload"]["prompt"] for c in MockHandler.calls),
        )

        first = Image.open(manifest["icons"][0]["files"][0]).convert("RGBA")
        check_("output is square 1024", first.size == (1024, 1024))
        check_("output has transparency", first.getchannel("A").getextrema()[0] == 0)
        check_(
            "interior white kept after removal", first.getpixel((512, 512))[3] == 255
        )
        check_(
            "center is content not halo",
            first.getpixel((512, 512))[:3] == (255, 255, 255),
        )

        # dry-run must not require an API key or hit the network
        sys.argv = ["generate_icon.py", "-p", "growth", "--dry-run"]
        check_("dry-run works without key", generate_icon.main() == 0)

    server.shutdown()


def main() -> int:
    for fn in (
        test_promptkit,
        test_normalize,
        test_remove_bg,
        test_check,
        test_palette,
        test_end_to_end,
    ):
        print(f"\n== {fn.__name__}")
        fn()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
