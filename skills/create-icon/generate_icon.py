#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.28",
#   "pillow>=10.0",
# ]
# ///
"""Generate presentation icons with a configurable image model.

Pipeline: promptkit compiles subject + style + composition + negative, the
provider generates, then every image is background-stripped (optional), trimmed,
evenly padded, centered and exported at 1024 + 512 px, with a quality check and
an icons.json manifest.

Providers: minimax | qwen (DashScope) | ark (Seedream) | openai | openai-compatible

Examples:
    uv run generate_icon.py -p "growth arrow" -s flat-color -n 3
    uv run generate_icon.py -p "rocket" -s gradient --transparent
    uv run generate_icon.py --set "growth,team,innovation,target" -s flat-color \
        --palette "#1E3A8A,#F59E0B" --seed 42
    uv run generate_icon.py -p "shield" -s 3d-render --provider ark
    uv run generate_icon.py -p "growth" --dry-run
    uv run generate_icon.py --list-styles

Configuration precedence: CLI flags > ICON_* env > legacy minimax env > .env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import check
import normalize
import promptkit
import providers
import remove_bg
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
STYLES_PATH = SCRIPT_DIR / "styles.json"
DEFAULT_OUTPUT = "./output"

STRUCTURAL_ISSUES = (
    "empty",
    "touches_border",
    "off_center",
    "padding",
    "not_transparent",
)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Generate presentation icons (prompt -> provider -> normalized PNG set).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --list-styles
  %(prog)s -p "growth arrow" -s flat-color
  %(prog)s -p "team collaboration" -s line-monochrome -n 3
  %(prog)s -p "rocket" -s gradient --transparent --sizes 1024,512
  %(prog)s --set "growth,team,innovation" -s flat-color --palette "#1E3A8A,#F59E0B"
  %(prog)s -p "shield" -s 3d-render --provider ark
""",
    )
    ap.add_argument("--prompt", "-p", help="Icon subject, e.g. 'growth arrow'")
    ap.add_argument(
        "--set",
        dest="subject_set",
        help="Comma-separated subjects for a consistent icon set",
    )
    ap.add_argument("--subjects-file", help="File with one subject per line")
    ap.add_argument(
        "--style",
        "-s",
        default="flat-color",
        help="Preset style key (see --list-styles; default flat-color)",
    )
    ap.add_argument(
        "--custom-style", help="Custom style description (overrides --style)"
    )
    ap.add_argument(
        "--palette", help="Fixed color palette, e.g. '#1E3A8A,#F59E0B,#FFFFFF'"
    )
    ap.add_argument(
        "-n", type=int, default=1, help="Variants per subject (1-9, default 1)"
    )
    ap.add_argument("--aspect-ratio", default="1:1", help="Aspect ratio (default 1:1)")
    ap.add_argument(
        "--background",
        default="white",
        help="Background preset (see --list-backgrounds; default white)",
    )
    ap.add_argument("--seed", type=int, default=None, help="Base random seed")
    ap.add_argument("--negative-prompt", help="Override the style's negative prompt")

    ap.add_argument(
        "--transparent",
        action="store_true",
        help="Produce transparent PNGs (native for gpt-image-1, else flood-fill)",
    )
    ap.add_argument(
        "--tolerance",
        type=int,
        default=remove_bg.DEFAULT_TOLERANCE,
        help=f"Background removal tolerance (default {remove_bg.DEFAULT_TOLERANCE})",
    )
    ap.add_argument(
        "--bg-mode",
        choices=["auto", "flood", "chroma", "keep"],
        default="auto",
        help="Background removal mode (default auto)",
    )
    ap.add_argument(
        "--feather", type=float, default=0.8, help="Edge softening radius (default 0.8)"
    )

    ap.add_argument(
        "--output",
        "-o",
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default {DEFAULT_OUTPUT})",
    )
    ap.add_argument(
        "--name", help="Base filename (single icon only; default: slugified subject)"
    )
    ap.add_argument(
        "--sizes",
        default=None,
        help=f"Output sizes (default {','.join(map(str, normalize.DEFAULT_SIZES))})",
    )
    ap.add_argument(
        "--padding",
        type=float,
        default=normalize.DEFAULT_PADDING,
        help=f"Canvas padding ratio (default {normalize.DEFAULT_PADDING})",
    )
    ap.add_argument(
        "--no-normalize",
        action="store_true",
        help="Save the provider image as-is (skip trim/pad/resize)",
    )
    ap.add_argument(
        "--no-trim",
        action="store_true",
        help="Keep the generated margins when normalizing",
    )
    ap.add_argument(
        "--keep-raw",
        action="store_true",
        help="Also save the unprocessed provider image",
    )
    ap.add_argument(
        "--ensure-quality",
        action="store_true",
        help="Regenerate once with a new seed when the quality gate fails",
    )
    ap.add_argument("--manifest", help="Manifest path (default: <output>/icons.json)")

    ap.add_argument(
        "--provider",
        choices=providers.SUPPORTED_PROVIDERS,
        help="Image provider (or ICON_PROVIDER env). Default: minimax",
    )
    ap.add_argument("--model", help="Image model (or ICON_MODEL env)")
    ap.add_argument("--api-key", help="API key (or ICON_API_KEY env)")
    ap.add_argument("--host", help="API host/base URL (or ICON_API_HOST env)")
    ap.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Parallel requests for --set mode (default 3)",
    )

    ap.add_argument("--list-styles", action="store_true")
    ap.add_argument("--list-backgrounds", action="store_true")
    ap.add_argument("--list-subjects", action="store_true")
    ap.add_argument("--list-providers", action="store_true")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print compiled prompts without calling the API",
    )
    ap.add_argument(
        "--estimate-cost",
        action="store_true",
        help="Print an approximate cost before generating",
    )
    ap.add_argument("--json", action="store_true", help="Print the manifest as JSON")
    args = ap.parse_args()
    if not (1 <= args.n <= 9):
        ap.error("-n must be between 1 and 9")
    return args


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def load_styles() -> dict:
    return promptkit.load_styles(STYLES_PATH)


def list_styles(styles: dict) -> None:
    print("Available icon styles:\n")
    print(f"  {'KEY':<18} {'NAME':<16} {'中文':<10} DESCRIPTION")
    print(f"  {'---':<18} {'----':<16} {'----':<10} -----------")
    for key, style in styles["styles"].items():
        tags = f"  [{', '.join(style.get('tags', []))}]" if style.get("tags") else ""
        print(
            f"  {key:<18} {style['name']:<16} {style.get('name_cn', ''):<10} "
            f"{style['description'][:58]}{tags}"
        )
    print(f"\n  Backgrounds: {', '.join(styles['backgrounds'])}")


def list_subjects(styles: dict) -> None:
    print("Common icon subjects (use as --prompt / --set items):\n")
    for i, subject in enumerate(styles["common_subjects"], 1):
        print(f"  {i:>2}. {subject}")


def list_providers() -> None:
    print("Supported providers:\n")
    print(f"  {'KEY':<18} {'DEFAULT HOST':<38} {'IMAGE MODEL'}")
    print(f"  {'---':<18} {'------------':<38} {'-----------'}")
    for prov in providers.SUPPORTED_PROVIDERS:
        host = providers.DEFAULT_HOSTS.get(prov) or "(set --host)"
        model = providers.DEFAULT_IMAGE_MODELS.get(prov) or "(set --model)"
        cost = providers.COST_TABLE.get(prov, {})
        note = f"  ~{cost['per_image']} {cost['currency']}/img" if cost else ""
        print(f"  {prov:<18} {host:<38} {model}{note}")
    print("\nConfigure via --provider/--model/--api-key/--host or ICON_* env vars.")


def parse_subjects(args) -> list[str]:
    subjects: list[str] = []
    if args.subject_set:
        subjects.extend(
            s.strip() for s in args.subject_set.replace(";", ",").split(",")
        )
    if args.subjects_file:
        text = Path(args.subjects_file).read_text(encoding="utf-8")
        subjects.extend(line.strip() for line in text.splitlines())
    if args.prompt:
        subjects.append(args.prompt.strip())
    subjects = [s for s in subjects if s]
    if not subjects:
        raise SystemExit(
            "ERROR: give --prompt, --set or --subjects-file (see --list-subjects)"
        )
    seen: set[str] = set()
    unique = []
    for subject in subjects:
        if subject.lower() not in seen:
            seen.add(subject.lower())
            unique.append(subject)
    return unique


def light_config(args) -> dict:
    """Provider/model without requiring an API key (dry-run, cost estimate)."""
    prov = (
        (args.provider or os.environ.get("ICON_PROVIDER") or "minimax").strip().lower()
    )
    model = (
        args.model
        or os.environ.get("ICON_MODEL")
        or providers.DEFAULT_IMAGE_MODELS.get(prov, "")
    )
    return {"provider": prov, "model": model, "host": "", "api_key": ""}


def unique_base(subject: str, used: set[str]) -> str:
    base = normalize.slugify(subject)
    candidate, index = base, 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def postprocess(
    raw: bytes,
    *,
    base: str,
    args,
    sizes: tuple[int, ...],
    transparent_done: bool,
) -> tuple[list[Path], dict, list[str], Path | None]:
    """Save one generated image (optional bg removal + normalization + sizes)."""
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_transparent" if args.transparent else ""
    raw_path = None
    if args.keep_raw:
        raw_path = out_dir / f"{base}{suffix}_raw.png"
        raw_path.write_bytes(raw)

    im = Image.open(BytesIO(raw)).convert("RGBA")
    bg = None
    if args.transparent and not transparent_done:
        im, _info = remove_bg.remove_background(
            im, tolerance=args.tolerance, feather=args.feather, mode=args.bg_mode
        )
    elif not args.transparent:
        bg = normalize.bg_from_corners(im)

    if args.no_normalize:
        files = [out_dir / f"{base}{suffix}.png"]
        im.save(files[0], "PNG", optimize=True)
        stats = normalize.content_stats(im, bg=bg)
        return files, stats, [], raw_path

    canvas = max(sizes)
    normalized = normalize.normalize(
        im, padding=args.padding, canvas=canvas, bg=bg, trimming=not args.no_trim
    )
    files = normalize.save_sizes(normalized, out_dir, base, sizes, suffix=suffix)
    stats = normalize.content_stats(normalized, bg=bg)
    report = check.inspect(
        files[0], expect_transparent=args.transparent, padding=args.padding
    )
    return files, stats, report["issues"], raw_path


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")).get("icons", [])
        except (OSError, ValueError):
            existing = []
    incoming = {entry["base"] for entry in manifest["icons"]}
    manifest["icons"] = [
        e for e in existing if e.get("base") not in incoming
    ] + manifest["icons"]
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    args = build_parser()
    styles = load_styles()

    if args.list_styles:
        list_styles(styles)
        return 0
    if args.list_backgrounds:
        for key, desc in styles["backgrounds"].items():
            print(f"  {key:<22} {desc}")
        return 0
    if args.list_subjects:
        list_subjects(styles)
        return 0
    if args.list_providers:
        list_providers()
        return 0

    subjects = parse_subjects(args)
    palette = promptkit.parse_palette(args.palette)
    sizes = normalize.parse_sizes(args.sizes)

    prompts = []
    for subject in subjects:
        try:
            compiled = promptkit.build_prompt(
                subject,
                styles,
                style_key=args.style,
                custom_style=args.custom_style,
                background=args.background,
                palette=palette,
            )
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if args.negative_prompt:
            compiled["negative"] = args.negative_prompt
        prompts.append(compiled)

    cfg = light_config(args)
    total_images = len(prompts) * args.n

    print(f"Provider: {cfg['provider']}  Model: {cfg['model']}")
    print(
        f"Style: {prompts[0]['style_key']}  Subjects: {len(prompts)}  Variants: {args.n}  "
        f"Images: {total_images}"
    )
    if palette:
        print(f"Palette: {', '.join(palette)}")

    if args.estimate_cost:
        estimate = providers.estimate_cost(cfg, total_images)
        print(
            f"Estimated cost: ~{estimate['total']} {estimate['currency']} "
            f"({estimate['images']} images, {estimate['note']})"
        )

    if args.dry_run:
        for compiled in prompts:
            print(f"\n[{compiled['subject']}]")
            print(f"  positive: {compiled['positive']}")
            print(f"  negative: {compiled['negative']}")
        return 0

    try:
        cfg = providers.resolve_image_config(
            args.provider, args.api_key, args.host, args.model
        )
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1

    native_transparency = providers.supports_native_transparency(
        cfg["provider"], cfg["model"]
    )
    negative_supported = providers.supports_negative(cfg["provider"])

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
        "provider": cfg["provider"],
        "model": cfg["model"],
        "style": prompts[0]["style_key"],
        "style_name": prompts[0]["style_name"],
        "palette": palette,
        "background": args.background,
        "transparent": args.transparent,
        "sizes": list(sizes),
        "padding": args.padding,
        "icons": [],
    }

    used_names: set[str] = set()
    bases: list[str] = []
    for compiled in prompts:
        if args.name and len(prompts) == 1:
            base = args.name
            used_names.add(base)
        else:
            base = unique_base(compiled["subject"], used_names)
        bases.append(base)

    def run_one(index: int, compiled: dict) -> dict:
        subject = compiled["subject"]
        base = bases[index]
        provider_prompt = promptkit.prompt_for_provider(compiled, negative_supported)
        seed = None if args.seed is None else args.seed + index

        attempts = 2 if args.ensure_quality else 1
        entry: dict = {"base": base, "subject": subject, "files": [], "issues": []}
        last_attempt = 0
        for attempt in range(attempts):
            last_attempt = attempt
            this_seed = None if seed is None else seed + attempt * 1000
            t0 = time.time()
            results = providers.generate_images(
                cfg,
                prompt=provider_prompt,
                n=args.n,
                aspect_ratio=args.aspect_ratio,
                seed=this_seed,
                negative_prompt=compiled["negative"] if negative_supported else None,
                transparent=args.transparent and native_transparency,
            )
            elapsed = time.time() - t0
            print(f"[{subject}] {len(results)} image(s) in {elapsed:.1f}s")

            files_all: list[Path] = []
            issues_all: list[str] = []
            stats_all: list[dict] = []
            for i, result in enumerate(results):
                raw = result.fetch()
                suffix_base = base if len(results) == 1 else f"{base}-{i}"
                files, stats, issues, raw_path = postprocess(
                    raw,
                    base=suffix_base,
                    args=args,
                    sizes=sizes,
                    transparent_done=args.transparent and native_transparency,
                )
                files_all.extend(files)
                stats_all.append(stats)
                issues_all.extend(f"[{suffix_base}] {issue}" for issue in issues)
                if raw_path:
                    print(f"  raw: {raw_path}")

            entry.update(
                {
                    "prompt": compiled["positive"],
                    "negative_prompt": compiled["negative"],
                    "seed": this_seed,
                    "files": [str(p.resolve()) for p in files_all],
                    "stats": stats_all,
                    "issues": issues_all,
                    "ok": not issues_all,
                }
            )
            if not issues_all or attempt == attempts - 1:
                break
            print(
                f"[{subject}] quality gate failed ({'; '.join(issues_all)}); retrying with a new seed"
            )

        entry["attempts"] = last_attempt + 1
        return entry

    if len(prompts) == 1 or args.concurrency <= 1:
        entries = [run_one(i, compiled) for i, compiled in enumerate(prompts)]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            entries = list(pool.map(lambda pair: run_one(*pair), enumerate(prompts)))

    manifest["icons"] = entries
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "icons.json"
    write_manifest(manifest_path, manifest)
    manifest["manifest"] = str(manifest_path.resolve())

    print("\nSaved:")
    for entry in entries:
        for path in entry["files"]:
            print(f"  {path}")
    print(f"\nManifest: {manifest_path.resolve()}")

    bad = [e for e in entries if e["issues"]]
    if bad:
        print(f"\nQuality warnings ({len(bad)}):", file=sys.stderr)
        for entry in bad:
            for issue in entry["issues"]:
                print(f"  - {issue}", file=sys.stderr)

    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
