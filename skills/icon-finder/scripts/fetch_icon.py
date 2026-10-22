#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.28",
#   "pillow>=10.0",
#   "resvg-py>=0.2",
# ]
# ///
"""Fetch logos as SVG + normalized PNG sets (aspect preserved, equal padding).

Each ref produces:
  <slug>.svg            original or recolored vector
  <slug>.png            normalized square PNG at the largest requested size
  <slug>@512.png        the same asset at smaller sizes

Usage:
  uv run scripts/fetch_icon.py "iconify:logos:aws"
  uv run scripts/fetch_icon.py aws kubernetes react --out ./logos --sizes 1024,512
  uv run scripts/fetch_icon.py "svgl:openai" --variant dark
  uv run scripts/fetch_icon.py "iconify:logos:aws" --style mono --color "#FFFFFF"
  uv run scripts/fetch_icon.py aws k8s --manifest logos.json --sheet preview.png
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logokit import net, normalize, render, sources
from logokit import svg as svgmod
from logokit.sheet import make_sheet

SUFFIX = {
    "color": "",
    "auto": "",
    "mono": "_mono",
    "dark": "_dark",
    "light": "_light",
    "wordmark": "_wordmark",
}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Fetch logos as SVG + normalized transparent PNGs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "refs",
        nargs="+",
        help="Refs from search output, e.g. 'iconify:logos:aws' 'simpleicons:github' 'svgl:openai'",
    )
    ap.add_argument(
        "--out", "-o", default="./logos", help="Output directory (default ./logos)"
    )
    ap.add_argument(
        "--sizes",
        default=None,
        help="Comma list of square sizes (default 1024,512). Largest keeps the plain name.",
    )
    ap.add_argument(
        "--size",
        type=int,
        default=None,
        help="Single size shorthand (overrides --sizes)",
    )
    ap.add_argument(
        "--variant",
        choices=["auto", "color", "mono", "light", "dark", "wordmark"],
        default="auto",
        help="auto/color: official colors; mono: one color; dark/light: slide-background aware",
    )
    ap.add_argument(
        "--style",
        choices=["color", "mono"],
        default=None,
        help="Backward-compatible alias for --variant",
    )
    ap.add_argument("--color", help="Hex color for mono/dark/light recoloring")
    ap.add_argument(
        "--padding",
        type=float,
        default=normalize.DEFAULT_PADDING,
        help=f"Canvas padding ratio (default {normalize.DEFAULT_PADDING})",
    )
    ap.add_argument(
        "--no-trim",
        action="store_true",
        help="Keep the source whitespace instead of trimming",
    )
    ap.add_argument("--svg-only", action="store_true", help="Only write SVG")
    ap.add_argument("--png-only", action="store_true", help="Only write PNG")
    ap.add_argument("--sheet", help="Write a contact sheet of the fetched logos")
    ap.add_argument("--sheet-theme", choices=["light", "dark"], default="light")
    ap.add_argument(
        "--manifest", help="Write a manifest JSON (default: <out>/logos.json)"
    )
    ap.add_argument("--json", action="store_true", help="Print the manifest to stdout")
    args = ap.parse_args()
    if args.svg_only and args.png_only:
        ap.error("--svg-only and --png-only are mutually exclusive")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.size:
        sizes = (args.size,)
    else:
        sizes = normalize.parse_sizes(args.sizes)
    variant = args.variant
    if args.style:  # legacy flag wins only when --variant was left at auto
        variant = args.style if variant == "auto" else variant

    proxy = net.proxy_info()
    if proxy:
        print(f"[info] using proxy: {proxy}", file=sys.stderr)
    print(
        f"[info] renderer: {render.renderer_name()}  sizes: {sizes}  variant: {variant}",
        file=sys.stderr,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = net.session()

    entries: list[dict] = []
    failures: list[dict] = []
    used_names: set[str] = set()

    for ref in args.refs:
        try:
            candidate = sources.resolve_ref(ref, session, prefer_variant=variant)
            fetched = svgmod.fetch_candidate(
                candidate, variant=variant, color=args.color, sess=session
            )
            if fetched["note"]:
                print(f"[info] {ref}: {fetched['note']}", file=sys.stderr)

            if candidate.get("auto_resolved"):
                # `fetch_icon.py aws` should produce aws.png, not the source's
                # long official title.
                base = sources.safe_name(ref)
            else:
                base = sources.safe_name(
                    candidate["title"] or candidate["meta"].get("name", "logo")
                )
            stem, n = base, 2
            while stem in used_names:
                stem, n = f"{base}-{n}", n + 1
            used_names.add(stem)
            suffix = SUFFIX.get(variant, "")

            svg_path = None
            if not args.png_only:
                svg_path = out_dir / f"{stem}{suffix}.svg"
                svgmod.writes_svg(fetched["svg"], svg_path)

            png_paths: list[Path] = []
            stats = None
            if not args.svg_only:
                raw_png = render.render_bytes(fetched["svg"], max(sizes))
                from io import BytesIO

                from PIL import Image

                img = Image.open(BytesIO(raw_png)).convert("RGBA")
                normalized = normalize.normalize(
                    img,
                    padding=args.padding,
                    canvas=max(sizes),
                    trimming=not args.no_trim,
                )
                png_paths = normalize.save_sizes(
                    normalized, out_dir, stem, sizes, suffix=suffix
                )
                stats = normalize.alpha_stats(normalized)

            entry = {
                "ref": ref,
                "title": candidate["title"],
                "source": candidate["source"],
                "variant": variant,
                "native_variant": fetched["native_variant"],
                "recolored": fetched["recolored"],
                "brand_color": fetched["brand_color"],
                "svg": str(svg_path.resolve()) if svg_path else None,
                "png": [str(p.resolve()) for p in png_paths],
                "note": fetched["note"],
                "stats": stats,
            }
            entries.append(entry)
            for p in png_paths:
                print(f"PNG: {p.resolve()}")
            if svg_path:
                print(f"SVG: {svg_path.resolve()}")
            if fetched["brand_color"]:
                print(f"    brand color: {fetched['brand_color']}")
        except Exception as exc:  # noqa: BLE001 - keep going in batch mode
            failures.append({"ref": ref, "error": str(exc)})
            print(f"[error] {ref}: {exc}", file=sys.stderr)

    if entries and args.sheet:
        try:
            items = [
                {
                    "image": Path(e["png"][0]) if e["png"] else None,
                    "label": e["title"],
                    "sub": e["source"]
                    + (f" {e['variant']}" if e["variant"] != "color" else ""),
                }
                for e in entries
            ]
            sheet_path = make_sheet(
                items,
                args.sheet,
                cell=220,
                theme=args.sheet_theme,
                title="Fetched logos",
            )
            print(f"[info] contact sheet: {sheet_path.resolve()}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] could not draw contact sheet: {exc}", file=sys.stderr)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "output_dir": str(out_dir.resolve()),
        "sizes": list(sizes),
        "padding": args.padding,
        "variant": variant,
        "renderer": render.renderer_name(),
        "logos": entries,
        "failures": failures,
    }
    manifest_path = Path(args.manifest) if args.manifest else out_dir / "logos.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        # Merge with what is already there so repeated batch runs accumulate.
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            old_logos = previous.get("logos") or []
        except (OSError, ValueError):
            old_logos = []
        incoming = {(e["ref"], e["variant"]) for e in entries}
        manifest["logos"] = [
            e for e in old_logos if (e.get("ref"), e.get("variant")) not in incoming
        ] + entries
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[info] manifest: {manifest_path.resolve()}", file=sys.stderr)

    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))

    if failures:
        print(
            f"[error] {len(failures)} of {len(args.refs)} refs failed", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
