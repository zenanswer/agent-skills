# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "requests>=2.28",
# ]
# ///
"""Analyze an example icon image to extract its style description.

Uses the configured provider's VLM (vision language model) to understand the
visual style of a user-provided icon, then outputs a style prompt that can be
fed into generate_icon.py via --custom-style.

Supported providers (select via --provider or ICON_PROVIDER env):
  - minimax           MiniMax-M1 (default; backward compatible)
  - qwen              qwen-vl-max (Aliyun DashScope)
  - openai            gpt-4o
  - openai-compatible Any OpenAI-compatible gateway

Usage:
    uv run analyze_style.py path/to/example_icon.png
    uv run analyze_style.py https://example.com/icon.png
    uv run analyze_style.py path/to/icon.png --output-style-only
    uv run analyze_style.py icon.png --provider qwen --vlm-model qwen-vl-max

Environment:
    ICON_PROVIDER / ICON_API_KEY / ICON_API_HOST / ICON_VLM_MODEL
    Legacy (minimax only): MINIMAX_API_KEY / MINIMAX_API_HOST
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import providers

SCRIPT_DIR = Path(__file__).resolve().parent

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB (API limit)

ANALYSIS_PROMPT = """\
You are an expert icon designer. Analyze this icon image and describe its visual \
style in detail for the purpose of reproducing the same style in an AI image generator.

Describe the following aspects concisely:
1. Overall style (flat, line, 3D, isometric, hand-drawn, gradient, etc.)
2. Color palette (specific colors or color scheme - be precise, e.g. "navy blue (#1A237E) and amber (#FFC107)")
3. Line/shape characteristics (stroke width, rounded vs sharp corners, filled vs outline)
4. Shadows, gradients, or texture effects
5. Composition (centered, padding, simplicity level)
6. Background (color, texture, transparent)

Then, output a FINAL LINE starting with "STYLE_PROMPT:" containing a comma-separated \
English style description suitable for an image generation prompt. This line should \
capture ALL the visual characteristics so that an icon generated with this description \
would match the original style. Do NOT include the icon's subject (what it depicts), \
only describe the STYLE.

Example output format:
Overall style: flat design with subtle 3D depth
Color palette: navy blue (#1A237E), white, light gray
Line/shape: bold rounded shapes, no outlines, filled
Shadows/texture: soft drop shadow, subtle gradient on main shape
Composition: centered with generous padding, very simple
Background: solid white

STYLE_PROMPT: flat design with subtle 3D depth, navy blue (#1A237E) and white color scheme, bold rounded filled shapes, soft drop shadow, subtle gradient, centered with generous padding, solid white background, simple and clean, vector-like icon style
"""


def load_image_as_data_url(image_path: str) -> str:
    p = Path(image_path)
    if not p.exists():
        print(f"ERROR: file not found: {image_path}", file=sys.stderr)
        sys.exit(1)

    ext = p.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        print(f"ERROR: unsupported format '{ext}'. Supported: {', '.join(SUPPORTED_FORMATS)}", file=sys.stderr)
        sys.exit(1)

    size = p.stat().st_size
    if size > MAX_FILE_SIZE:
        print(f"ERROR: file too large ({size/1024/1024:.1f}MB). Max: 10MB.", file=sys.stderr)
        sys.exit(1)

    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
    mime = mime_map[ext]

    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    return f"data:{mime};base64,{b64}"


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def extract_style_prompt(text: str) -> str | None:
    for line in text.split("\n"):
        line = line.strip()
        if line.upper().startswith("STYLE_PROMPT:"):
            return line.split(":", 1)[1].strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze an example icon image to extract its visual style description.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
The output STYLE_PROMPT can be passed to generate_icon.py:
  %(prog)s example.png --output-style-only > style.txt
  uv run generate_icon.py --prompt "growth" --custom-style "$(cat style.txt)"

Examples:
  %(prog)s path/to/icon.png
  %(prog)s https://example.com/icon.png
  %(prog)s icon.png --output-style-only
  %(prog)s icon.png --provider qwen --vlm-model qwen-vl-max
""",
    )
    parser.add_argument("image", help="Path or URL to the example icon image")

    # Provider configuration (shared with generate_icon.py)
    parser.add_argument(
        "--provider",
        choices=providers.SUPPORTED_PROVIDERS,
        help="VLM provider (or set ICON_PROVIDER env). Default: minimax",
    )
    parser.add_argument("--vlm-model", help="VLM model name (or set ICON_VLM_MODEL env)")
    parser.add_argument("--api-key", help="API key (or set ICON_API_KEY env)")
    parser.add_argument("--host", help="API host/base URL (or set ICON_API_HOST env)")
    parser.add_argument("--output-style-only", action="store_true", help="Only output the extracted STYLE_PROMPT line (for scripting)")

    args = parser.parse_args()

    cfg = providers.resolve_vlm_config(args.provider, args.api_key, args.host, args.vlm_model)

    if is_url(args.image):
        image_input: str = args.image
        print(f"Analyzing image from URL: {args.image}")
    else:
        image_input = load_image_as_data_url(args.image)
        print(f"Analyzing image: {args.image}")

    print(f"Provider: {cfg['provider']}  VLM: {cfg['model']}  Host: {cfg['host']}")

    response_text = providers.vlm_analyze(cfg, image_input, ANALYSIS_PROMPT, max_tokens=600)

    style_prompt = extract_style_prompt(response_text)

    if args.output_style_only:
        if style_prompt:
            print(style_prompt)
        else:
            print(response_text.strip())
        return

    print("\n" + "=" * 60)
    print("STYLE ANALYSIS")
    print("=" * 60)
    print(response_text)

    if style_prompt:
        print("\n" + "=" * 60)
        print("EXTRACTED STYLE PROMPT (for generate_icon.py --custom-style):")
        print("=" * 60)
        print(style_prompt)
        print()
        print("Usage:")
        print(f'  uv run generate_icon.py --prompt "your subject" --custom-style "{style_prompt}"')


if __name__ == "__main__":
    main()
