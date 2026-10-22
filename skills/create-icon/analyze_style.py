#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.28",
#   "pillow>=10.0",
# ]
# ///
"""Learn an icon style from example images and emit a reusable style prompt.

Two signals are combined:
  1. A VLM describes the construction (flat/line/3D, stroke, corners, effects).
  2. Pillow quantizes the actual pixels, so the palette is *measured* rather
     than guessed - models are unreliable at naming hex codes.

Output is a style prompt ready for generate_icon.py --custom-style, plus the
measured palette.

Usage:
    uv run analyze_style.py example.png
    uv run analyze_style.py a.png b.png --json
    uv run analyze_style.py icon.png --output-style-only > style.txt
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import providers
from PIL import Image

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_K = 6

ANALYSIS_PROMPT = """\
You are an expert icon designer. Analyze the icon image(s) and describe their \
visual style so an image generator can reproduce it.

Return ONLY a JSON object, no prose, with these keys:
{
  "style_tags": ["flat", "line", "3d", "isometric", "gradient", ...],
  "line": "stroke width, caps, fill vs outline",
  "corners": "rounded vs sharp, radius feel",
  "shading": "flat / two-step / soft shadow / none, gradients",
  "composition": "centering, padding, simplicity level",
  "effects": ["drop shadow", "inner glow", "noise", ...],
  "style_prompt": "comma-separated English style description suitable for an image prompt; describe STYLE only, not the subject",
  "confidence": 0.0
}

Do not describe what the icon depicts. If several images are provided, capture
what they have in common."""


def load_image_input(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"ERROR: file not found: {path}")
    ext = p.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise SystemExit(
            f"ERROR: unsupported format '{ext}'. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )
    if p.stat().st_size > MAX_FILE_SIZE:
        raise SystemExit(f"ERROR: {path} is larger than 10MB")
    mime = "image/jpeg" if ext in {".jpg", ".jpeg"} else f"image/{ext.lstrip('.')}"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


# --------------------------------------------------------------------------- #
# palette
# --------------------------------------------------------------------------- #


def extract_palette(im: Image.Image, k: int = DEFAULT_K) -> list[dict]:
    """Quantize to k dominant colors, merging near-duplicates."""
    rgba = im.convert("RGBA")
    flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    flat.alpha_composite(rgba)
    quantized = flat.convert("RGB").quantize(colors=max(2, k), method=Image.MEDIANCUT)
    palette = quantized.getpalette() or []
    entries = []
    total = sum(count for count, _ in quantized.getcolors() or [])
    for count, index in quantized.getcolors() or []:
        r, g, b = palette[index * 3 : index * 3 + 3]
        entries.append((count, (r, g, b)))
    entries.sort(key=lambda item: -item[0])

    merged: list[dict] = []
    for count, rgb in entries:
        if count == 0:
            continue
        duplicate = None
        for existing in merged:
            er, eg, eb = existing["_rgb"]
            if max(abs(rgb[0] - er), abs(rgb[1] - eg), abs(rgb[2] - eb)) <= 24:
                duplicate = existing
                break
        if duplicate:
            duplicate["count"] += count
            continue
        merged.append(
            {"hex": "#{:02x}{:02x}{:02x}".format(*rgb), "count": count, "_rgb": rgb}
        )

    for item in merged:
        item["share"] = round(item["count"] / total, 3) if total else 0.0
        del item["count"]
        item.pop("_rgb", None)
    return merged[:k]


def background_color(im: Image.Image) -> str:
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
    r, g, b = samples[len(samples) // 2]
    return f"#{r:02x}{g:02x}{b:02x}"


# --------------------------------------------------------------------------- #
# VLM output parsing
# --------------------------------------------------------------------------- #


def parse_json_response(text: str) -> dict | None:
    cleaned = re.sub(
        r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE
    ).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return None


def extract_style_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip().upper().startswith("STYLE_PROMPT:"):
            return line.split(":", 1)[1].strip()
    return None


def build_style_prompt(
    analysis: dict, palette: list[dict], bg: str, extra_line: str | None
) -> str:
    base = (analysis.get("style_prompt") or extra_line or "").strip().rstrip(",")
    parts = [base] if base else []
    tags = analysis.get("style_tags") or []
    if tags and not base:
        parts.append(", ".join(tags))
    for key in ("line", "corners", "shading", "composition"):
        value = analysis.get(key)
        if (
            isinstance(value, str)
            and value.strip()
            and value.strip().lower() not in {"none", "n/a"}
        ):
            parts.append(f"{key.replace('_', ' ')}: {value.strip()}")
    effects = analysis.get("effects")
    if isinstance(effects, list) and effects:
        parts.append("effects: " + ", ".join(str(e) for e in effects))
    hexes = [item["hex"] for item in palette if item["share"] >= 0.03][:5]
    if hexes:
        parts.append("color palette: " + ", ".join(hexes))
    if bg:
        parts.append(f"background: {bg}")
    parts.append("single centered object, generous even padding")
    return ", ".join(part for part in parts if part)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Analyze example icon(s) and emit a reusable style prompt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("images", nargs="+", help="Example icon files or URLs")
    ap.add_argument(
        "--provider",
        choices=providers.SUPPORTED_PROVIDERS,
        help="VLM provider (or ICON_PROVIDER env)",
    )
    ap.add_argument("--vlm-model", help="VLM model (or ICON_VLM_MODEL env)")
    ap.add_argument("--api-key", help="API key (or ICON_API_KEY env)")
    ap.add_argument("--host", help="API host/base URL (or ICON_API_HOST env)")
    ap.add_argument(
        "--palette-size",
        type=int,
        default=DEFAULT_K,
        help="Dominant colors to extract (default 6)",
    )
    ap.add_argument("--json", action="store_true", help="Structured JSON output")
    ap.add_argument(
        "--output-style-only",
        action="store_true",
        help="Print only the style prompt (for scripting)",
    )
    args = ap.parse_args()

    local_images: list[tuple[str, Image.Image]] = []
    inputs: list[str] = []
    for path in args.images:
        if is_url(path):
            inputs.append(path)
            print(f"Using image URL: {path}", file=sys.stderr)
        else:
            inputs.append(load_image_input(path))
            local_images.append((path, Image.open(path).convert("RGBA")))
            print(f"Analyzing image: {path}", file=sys.stderr)

    palette: list[dict] = []
    for _path, im in local_images:
        palette.extend(extract_palette(im, args.palette_size))
    if palette:
        # Merge palettes across images, keeping the strongest entries.
        bucket: dict[str, dict] = {}
        for item in palette:
            bucket[item["hex"]] = bucket.get(
                item["hex"], {"hex": item["hex"], "share": 0.0}
            )
            bucket[item["hex"]]["share"] = round(
                bucket[item["hex"]]["share"] + item["share"], 3
            )
        palette = sorted(bucket.values(), key=lambda x: -x["share"])[
            : args.palette_size
        ]
    bg = background_color(local_images[0][1]) if local_images else ""

    cfg = providers.resolve_vlm_config(
        args.provider, args.api_key, args.host, args.vlm_model
    )
    print(f"Provider: {cfg['provider']}  VLM: {cfg['model']}", file=sys.stderr)

    text = providers.vlm_analyze(cfg, inputs, ANALYSIS_PROMPT, max_tokens=1200)
    analysis = parse_json_response(text) or {}
    style_line = extract_style_line(text)
    style_prompt = build_style_prompt(analysis, palette, bg, style_line)

    if args.output_style_only:
        print(style_prompt)
        return 0

    payload = {
        "images": args.images,
        "provider": cfg["provider"],
        "vlm_model": cfg["model"],
        "style_prompt": style_prompt,
        "palette": palette,
        "background": bg,
        "analysis": analysis,
        "raw": None if analysis else text,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print("\n" + "=" * 66)
    print("STYLE ANALYSIS")
    print("=" * 66)
    if analysis:
        for key in (
            "style_tags",
            "line",
            "corners",
            "shading",
            "composition",
            "effects",
        ):
            if key in analysis:
                print(f"{key.replace('_', ' ').title():<12} {analysis[key]}")
    else:
        print(text.strip())
    if palette:
        print("\nMeasured palette:")
        for item in palette:
            print(f"  {item['hex']}  {item['share'] * 100:5.1f}%")
    print(f"Background: {bg}")
    print("\n" + "=" * 66)
    print("STYLE PROMPT (generate_icon.py --custom-style):")
    print("=" * 66)
    print(style_prompt)
    print()
    print(
        f'  uv run generate_icon.py -p "your subject" --custom-style "{style_prompt}"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
