# /// script
# requires-python = ">=3.9"
# dependencies = [
#   "requests>=2.28",
# ]
# ///
"""Generate PPT icons using a configurable image-generation provider.

Supported providers (select via --provider or ICON_PROVIDER env):
  - minimax           MiniMax image-01 (default; backward compatible)
  - qwen              Aliyun DashScope qwen-image-2.0-pro
  - openai            OpenAI DALL-E 3
  - openai-compatible Any OpenAI-compatible gateway (SiliconFlow, Volcengine, ...)

Usage:
    uv run generate_icon.py --prompt "a growth arrow icon" --style flat-color
    uv run generate_icon.py --prompt "team collaboration" --style line-monochrome -n 3
    uv run generate_icon.py --prompt "innovation lightbulb" --custom-style "..." -n 2 --transparent
    uv run generate_icon.py --list-styles
    uv run generate_icon.py --list-subjects
    uv run generate_icon.py --prompt "growth" --style flat-color --provider qwen --model qwen-image-2.0-pro

Configuration (highest priority first):
    1. CLI flags: --provider / --model / --api-key / --host
    2. Generic env:  ICON_PROVIDER / ICON_MODEL / ICON_API_KEY / ICON_API_HOST
    3. Legacy env:   MINIMAX_API_KEY / MINIMAX_API_HOST (provider=minimax only)
    4. .env file in the skill directory
    5. Built-in defaults
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import providers

SCRIPT_DIR = Path(__file__).resolve().parent
STYLES_PATH = SCRIPT_DIR / "styles.json"
MAX_PROMPT_LEN = 1500


def load_styles() -> dict:
    with open(STYLES_PATH, encoding="utf-8") as f:
        return json.load(f)


def list_styles() -> None:
    data = load_styles()
    print("Available icon styles:\n")
    print(f"  {'Key':<20} {'Name':<18} {'Name (CN)':<12} Description")
    print(f"  {'---':<20} {'----':<18} {'---------':<12} -----------")
    for key, s in data["styles"].items():
        print(f"  {key:<20} {s['name']:<18} {s['name_cn']:<12} {s['description'][:60]}")
    print(f"\n  Available backgrounds: {', '.join(data['backgrounds'].keys())}")


def list_subjects() -> None:
    data = load_styles()
    print("Common icon subjects (use as --prompt):\n")
    for i, subj in enumerate(data["common_subjects"], 1):
        print(f"  {i:>2}. {subj}")


def build_prompt(
    user_prompt: str,
    style_key: str | None,
    custom_style: str | None,
    background: str,
) -> str:
    data = load_styles()
    parts: list[str] = []

    user_clean = user_prompt.strip()
    if not user_clean.startswith("a ") and not user_clean.startswith("an "):
        user_clean = f"a {user_clean}"
    parts.append(user_clean)

    if custom_style:
        parts.append(custom_style.strip())
    elif style_key:
        styles = data["styles"]
        if style_key not in styles:
            print(f"ERROR: style '{style_key}' not found. Use --list-styles.", file=sys.stderr)
            sys.exit(1)
        parts.append(styles[style_key]["prompt_suffix"])
    else:
        parts.append("icon design, clean, centered composition, simple, high quality")

    bg_desc = data["backgrounds"].get(background, data["backgrounds"]["white"])
    parts.append(bg_desc)

    parts.append("icon design, centered composition, no text, no watermark")
    full = ", ".join(parts)
    if len(full) > MAX_PROMPT_LEN:
        full = full[:MAX_PROMPT_LEN]
    return full


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:40] if slug else "icon"


def save_images(results: list[providers.ImageResult], output_dir: Path, name_base: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    multi = len(results) > 1
    for i, r in enumerate(results):
        suffix = f"-{i}" if multi else ""
        path = output_dir / f"{name_base}{suffix}.png"
        path.write_bytes(r.fetch())
        saved.append(path)
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate PPT icons using a configurable image-generation provider.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --list-styles
  %(prog)s --prompt "growth arrow" --style flat-color
  %(prog)s --prompt "team collaboration" --style line-monochrome -n 3
  %(prog)s --prompt "innovation" --custom-style "isometric, pastel" --transparent
  # Switch provider:
  %(prog)s --prompt "growth" --provider qwen --model qwen-image-2.0-pro
  %(prog)s --prompt "growth" --provider openai-compatible \\
      --host https://api.siliconflow.cn --model Kolors --api-key sk-xxx
""",
    )
    parser.add_argument("--prompt", "-p", help="Icon subject description, e.g. 'growth arrow'")
    parser.add_argument("--style", "-s", help="Preset style key (use --list-styles to see options)")
    parser.add_argument("--custom-style", help="Custom style description (overrides --style)")
    parser.add_argument("-n", type=int, default=1, help="Number of images to generate (1-9), default 1")
    parser.add_argument("--aspect-ratio", default="1:1", help="Aspect ratio, default 1:1")
    parser.add_argument("--background", default="white", help="Background preset key, default 'white'")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--transparent", action="store_true", help="Remove background (post-process to transparent PNG)")
    parser.add_argument("--output", "-o", default="./output", help="Output directory, default ./output")
    parser.add_argument("--name", help="Base filename for output (default: slugified prompt)")

    # Provider configuration
    parser.add_argument(
        "--provider",
        choices=providers.SUPPORTED_PROVIDERS,
        help=f"Image provider (or set ICON_PROVIDER env). Default: minimax",
    )
    parser.add_argument("--model", help="Image model name (or set ICON_MODEL env)")
    parser.add_argument("--api-key", help="API key (or set ICON_API_KEY env)")
    parser.add_argument("--host", help="API host/base URL (or set ICON_API_HOST env)")
    parser.add_argument("--negative-prompt", help="Negative prompt (qwen only; has sensible default)")

    parser.add_argument("--list-styles", action="store_true", help="List available preset styles and exit")
    parser.add_argument("--list-subjects", action="store_true", help="List common icon subjects and exit")
    parser.add_argument("--list-providers", action="store_true", help="List supported providers and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print the constructed prompt and exit without calling API")

    args = parser.parse_args()

    if args.list_styles:
        list_styles()
        return
    if args.list_subjects:
        list_subjects()
        return
    if args.list_providers:
        print("Supported providers:\n")
        print(f"  {'Key':<18} {'Default host':<40} {'Default image model'}")
        print(f"  {'---':<18} {'------------':<40} {'-------------------'}")
        for p in providers.SUPPORTED_PROVIDERS:
            print(f"  {p:<18} {providers.DEFAULT_HOSTS.get(p, '-'):<40} {providers.DEFAULT_IMAGE_MODELS.get(p, '-')}")
        print("\nConfigure via: --provider / --model / --api-key / --host")
        print("  or env vars: ICON_PROVIDER / ICON_MODEL / ICON_API_KEY / ICON_API_HOST")
        return
    if not args.prompt:
        parser.error("--prompt is required (unless using --list-styles / --list-subjects / --list-providers)")

    if not (1 <= args.n <= 9):
        parser.error("-n must be between 1 and 9")

    prompt = build_prompt(args.prompt, args.style, args.custom_style, args.background)

    if args.dry_run:
        print(f"Constructed prompt ({len(prompt)} chars):")
        print(f"  {prompt}")
        return

    cfg = providers.resolve_image_config(args.provider, args.api_key, args.host, args.model)
    print(f"Provider: {cfg['provider']}  Model: {cfg['model']}  Host: {cfg['host']}")
    print(f"Generating {args.n} icon(s)...")
    print(f"Prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")

    t0 = time.time()
    results = providers.generate_images(
        cfg,
        prompt=prompt,
        n=args.n,
        aspect_ratio=args.aspect_ratio,
        seed=args.seed,
        negative_prompt=args.negative_prompt,
    )
    elapsed = time.time() - t0
    print(f"API success: {len(results)} image(s), {elapsed:.1f}s")

    output_dir = Path(args.output)
    name_base = args.name or slugify(args.prompt)
    saved = save_images(results, output_dir, name_base)

    print(f"\nSaved {len(saved)} image(s):")
    for p in saved:
        print(f"  {p}")

    if args.transparent:
        print("\nRemoving backgrounds...")
        try:
            remove_bg_path = SCRIPT_DIR / "remove_bg.py"
            for p in saved:
                ret = os.system(f'uv run "{remove_bg_path}" "{p}" --output "{p}"')
                if ret == 0:
                    print(f"  Transparent: {p}")
                else:
                    print(f"  WARNING: bg removal failed for {p}", file=sys.stderr)
        except Exception as e:
            print(f"  WARNING: could not run remove_bg.py: {e}", file=sys.stderr)
            print(f"  Run manually: uv run remove_bg.py <image_path>", file=sys.stderr)

    print("\nDone.")


if __name__ == "__main__":
    main()
