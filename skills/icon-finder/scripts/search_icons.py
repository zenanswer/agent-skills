#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.28",
#   "pillow>=10.0",
#   "resvg-py>=0.2",
# ]
# ///
"""Search brand logos or UI icons across free, license-clear sources.

Modes
-----
logo  Brand/technology marks from Iconify `logos`, svgl, lobe-icons and
      Simple Icons (default).
ui    Concept icons from the curated Iconify UI sets (Material Symbols, MDI,
      Tabler, Lucide, Phosphor, Font Awesome). Adds concept expansion, license
      metadata and deterministic ranking.

Output is a deterministic JSON array on stdout. Human-facing hints go to stderr.

Usage:
  uv run scripts/search_icons.py "aws"
  uv run scripts/search_icons.py --mode ui "growth" --sheet /tmp/ui.png
  uv run scripts/search_icons.py --mode ui "cost saving,团队" --table
  uv run scripts/search_icons.py --mode ui "rocket" --license permissive
  uv run scripts/search_icons.py "k8s" --style mono
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logokit import cache, catalog, net, sources
from logokit.sheet import sheet_from_candidates

LOGO_SUGGESTIONS = """\
Try one of:
  - A common abbreviation: k8s -> kubernetes, tf -> terraform, gcp -> google cloud
  - A shorter/broader keyword: "elastic" instead of "elasticsearch-stack"
  - The full brand name: "amazon web services" instead of "aws"
If nothing matches, the brand may not be in any free icon collection yet."""

UI_SUGGESTIONS = """\
Try one of:
  - A concrete noun: rocket, users, shield, piggy-bank, chart-line
  - A supported concept: growth, team, cost saving, security, 风险, 预算
  - More collections: --collection all-open
Iconify search matches icon names, not meaning; concepts are expanded locally."""


def parse_sources(spec: str | None) -> list[str]:
    if not spec or spec == "all":
        return ["iconify", "svgl", "lobeicons", "simpleicons"]
    wanted = [s.strip().lower() for s in spec.split(",") if s.strip()]
    unknown = [s for s in wanted if s not in sources.SOURCE_PRIORITY]
    if unknown:
        raise SystemExit(
            f"ERROR: unknown source(s) {unknown}. Use: {', '.join(sources.SOURCE_PRIORITY)}"
        )
    return wanted


def print_table(cands: list[dict], mode: str) -> None:
    if mode == "ui":
        print(f"{'#':<3} {'TITLE':<26} {'SET':<18} {'LICENSE':<14} {'SCORE':<6} ID")
        print("-" * 100)
        for i, cand in enumerate(cands, 1):
            print(
                f"{i:<3} {cand['title'][:25]:<26} {cand.get('collection', ''):<18} "
                f"{cand.get('license') or '-':<14} {cand['score']:<6} {cand['id']}"
            )
            if cand.get("also_in"):
                print(f"{'':<3} also available in: {', '.join(cand['also_in'])}")
        return

    print(f"{'#':<3} {'TITLE':<30} {'SOURCE':<12} {'COLOR':<14} {'SCORE':<6} ID")
    print("-" * 96)
    for i, cand in enumerate(cands, 1):
        color = cand.get("brand_color") or ("multicolor" if cand["is_color"] else "-")
        variants = ",".join(cand.get("variants", []))
        print(
            f"{i:<3} {cand['title'][:29]:<30} {cand['source']:<12} {color:<14} "
            f"{cand['score']:<6} {cand['id']}"
        )
        if variants:
            print(f"{'':<3} {'':<30} variants: {variants}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Search brand logos (logo mode) or UI icons (ui mode) across free, license-clear sources.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("query", nargs="*", help="Brand name(s) or UI concept(s)")
    ap.add_argument(
        "--mode",
        choices=["logo", "ui"],
        default="logo",
        help="logo: brand marks; ui: concept icons from UI sets (default logo)",
    )
    ap.add_argument(
        "--style",
        choices=["color", "mono"],
        default=None,
        help="Preferred style (default: color in logo mode, mono in ui mode)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max candidates (logo: per source; ui: total). Default 10",
    )
    ap.add_argument(
        "--source",
        default="all",
        help="logo mode only: iconify,svgl,lobeicons,simpleicons (default all)",
    )
    ap.add_argument(
        "--collection",
        default=None,
        help="Iconify prefix(es), comma separated; 'all-open' or 'all'. "
        "Default: logos (logo) / curated UI six (ui)",
    )
    ap.add_argument(
        "--license",
        choices=["any", "permissive", "attribution", "no-sharealike"],
        default="any",
        help="Filter by license obligations (default any)",
    )
    ap.add_argument("--all", action="store_true", help="Keep per-collection duplicates")
    ap.add_argument(
        "--table", action="store_true", help="Print a human table instead of JSON"
    )
    ap.add_argument(
        "--sheet", help="Write a labelled contact sheet PNG of the candidates"
    )
    ap.add_argument(
        "--sheet-theme",
        choices=["light", "dark"],
        default="light",
        help="Contact sheet theme (use dark for white icons)",
    )
    ap.add_argument("--compact", action="store_true", help="Single-line JSON")
    ap.add_argument(
        "--cache-info", action="store_true", help="Show cache status and exit"
    )
    args = ap.parse_args()

    if args.cache_info:
        print(json.dumps(cache.cache_info(), indent=2))
        return 0
    if not args.query:
        ap.error("give at least one query, or use --cache-info")

    proxy = net.proxy_info()
    if proxy:
        print(f"[info] using proxy: {proxy}", file=sys.stderr)

    collections = catalog.resolve_collections(args.collection, args.mode)
    style = args.style or ("mono" if args.mode == "ui" else "color")
    wanted = parse_sources(args.source)
    if args.mode == "ui" and args.source != "all":
        print(
            "[info] ui mode always searches Iconify; --source is ignored",
            file=sys.stderr,
        )

    if args.mode == "ui":
        print(
            f"[info] ui mode: {len(collections)} collection(s) -> {', '.join(collections)}",
            file=sys.stderr,
        )

    merged: list[dict] = []
    seen: set[str] = set()
    for raw_query in args.query:
        if args.mode == "ui":
            queries = [raw_query]
        else:
            query, expansion = sources.expand_query(raw_query)
            if expansion:
                print(f"[info] {expansion}", file=sys.stderr)
            # Search the raw wording too: Iconify's index does not understand
            # long expanded phrases like "amazon web services" even when svgl does.
            queries = [query] if query == raw_query else [raw_query, query]

        pool: list[dict] = []
        for query in queries:
            pool.extend(
                sources.search_all(
                    query,
                    limit=max(1, args.limit),
                    collections=collections,
                    sources=wanted,
                    style=style,
                    show_all=args.all,
                    mode=args.mode,
                )
            )
        for cand in pool:
            cand["query"] = raw_query
        for cand in sources.dedupe_and_rank(
            pool, style=style, show_all=args.all, mode=args.mode
        ):
            key = sources.dedupe_key(cand)
            if key in seen:
                continue
            seen.add(key)
            merged.append(cand)

    if args.license != "any":
        merged = catalog.filter_by_license(merged, args.license)
        print(
            f"[info] license filter '{args.license}': {len(merged)} candidate(s) left",
            file=sys.stderr,
        )

    if merged:
        top = merged[0]
        print(
            f"[info] best match: {top['title']} ({top['id']}, score {top['score']}, "
            f"confidence {top['confidence']})",
            file=sys.stderr,
        )
        if (
            args.mode == "logo"
            and top["confidence"] >= 0.8
            and (len(merged) == 1 or merged[0]["score"] - merged[1]["score"] >= 8)
        ):
            print(
                "[info] high confidence - safe to fetch without asking", file=sys.stderr
            )

    if args.mode == "ui" and merged:
        licenses = sorted({c.get("license") or "unknown" for c in merged})
        print(f"[info] licenses in results: {', '.join(licenses)}", file=sys.stderr)
        if any(c.get("attribution_required") for c in merged):
            print(
                "[info] some sets are CC BY: run fetch_icon.py --credits CREDITS.md "
                "if you redistribute the deck",
                file=sys.stderr,
            )

    if args.sheet and merged:
        try:
            sheet_items = merged
            if len(args.query) > 1:
                grouped: dict[str, list[dict]] = {}
                for cand in merged:
                    grouped.setdefault(cand.get("query", ""), []).append(cand)
                sheet_items = [c for q in args.query for c in grouped.get(q, [])[:4]]
            title = (
                "Icon candidates: " if args.mode == "ui" else "Logo candidates: "
            ) + ", ".join(args.query)
            path = sheet_from_candidates(
                sheet_items[: min(len(sheet_items), 12)],
                args.sheet,
                size=200,
                theme=args.sheet_theme,
                title=title,
            )
            print(f"[info] contact sheet: {path.resolve()}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] could not draw contact sheet: {exc}", file=sys.stderr)

    if args.table:
        print_table(merged, args.mode)
    else:
        print(
            json.dumps(merged, indent=None if args.compact else 2, ensure_ascii=False)
        )

    if not merged:
        print(f"No icons found for '{', '.join(args.query)}'.", file=sys.stderr)
        print(
            UI_SUGGESTIONS if args.mode == "ui" else LOGO_SUGGESTIONS, file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
