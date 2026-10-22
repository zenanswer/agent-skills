#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "requests>=2.28",
#   "pillow>=10.0",
#   "resvg-py>=0.2",
# ]
# ///
"""Search brand/technology logos across four free sources and rank the results.

Sources: Iconify `logos` (colored official), svgl (curated, native light/dark +
wordmarks), lobe-icons (AI brands), Simple Icons (monochrome + brand hex).

Output is a deterministic JSON array on stdout. Human-facing hints go to stderr.

Usage:
  uv run scripts/search_icons.py "aws"
  uv run scripts/search_icons.py "k8s" --style mono
  uv run scripts/search_icons.py "deepseek" --sheet /tmp/candidates.png
  uv run scripts/search_icons.py "AWS, K8s, React" --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logokit import cache, net, sources
from logokit.sheet import sheet_from_candidates

SUGGESTIONS = """\
Try one of:
  - A common abbreviation: k8s -> kubernetes, tf -> terraform, gcp -> google cloud
  - A shorter/broader keyword: "elastic" instead of "elasticsearch-stack"
  - The full brand name: "amazon web services" instead of "aws"
If nothing matches, the brand may not be in any free icon collection yet."""


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


def print_table(cands: list[dict]) -> None:
    print(f"{'#':<3} {'TITLE':<30} {'SOURCE':<12} {'COLOR':<14} {'SCORE':<6} ID")
    print("-" * 96)
    for i, c in enumerate(cands, 1):
        color = c.get("brand_color") or ("multicolor" if c["is_color"] else "-")
        variants = ",".join(c.get("variants", []))
        print(
            f"{i:<3} {c['title'][:29]:<30} {c['source']:<12} {color:<14} {c['score']:<6} {c['id']}"
        )
        if variants:
            print(f"{'':<3} {'':<30} variants: {variants}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Search brand/technology logos across Iconify, svgl, lobe-icons and Simple Icons.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "query", nargs="*", help="Brand/technology name(s), e.g. aws kubernetes"
    )
    ap.add_argument(
        "--style",
        choices=["color", "mono"],
        default="color",
        help="Preferred style, affects ordering (default: color)",
    )
    ap.add_argument(
        "--limit", type=int, default=10, help="Max candidates per source (default 10)"
    )
    ap.add_argument(
        "--source",
        default="all",
        help="Comma list: iconify,svgl,lobeicons,simpleicons (default all)",
    )
    ap.add_argument(
        "--collection",
        default="logos",
        help="Iconify collection(s) to search, comma separated (default logos)",
    )
    ap.add_argument(
        "--all", action="store_true", help="Keep duplicates from different sources"
    )
    ap.add_argument(
        "--table", action="store_true", help="Print a human table instead of JSON"
    )
    ap.add_argument(
        "--sheet", help="Write a labelled contact sheet PNG of the candidates"
    )
    ap.add_argument("--sheet-theme", choices=["light", "dark"], default="light")
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

    collections = tuple(c.strip() for c in args.collection.split(",") if c.strip())
    wanted = parse_sources(args.source)

    merged: list[dict] = []
    seen: set[str] = set()
    for raw_query in args.query:
        query, expansion = sources.expand_query(raw_query)
        if expansion:
            print(f"[info] {expansion}", file=sys.stderr)
        # Search the raw wording too: Iconify's index does not understand
        # long expanded phrases like "amazon web services" even when svgl does.
        queries = [query] if query == raw_query else [raw_query, query]
        pool: list[dict] = []
        for q in queries:
            pool.extend(
                sources.search_all(
                    q,
                    limit=max(1, args.limit),
                    collections=collections,
                    sources=wanted,
                    style=args.style,
                    show_all=args.all,
                )
            )
        for cand in pool:
            cand["query"] = raw_query
        for cand in sources.dedupe_and_rank(pool, style=args.style, show_all=args.all):
            key = sources.dedupe_key(cand)
            if key in seen:
                continue
            seen.add(key)
            merged.append(cand)

    if merged:
        top = merged[0]
        print(
            f"[info] best match: {top['title']} ({top['id']}, score {top['score']}, "
            f"confidence {top['confidence']})",
            file=sys.stderr,
        )
        if top["confidence"] >= 0.8 and (
            len(merged) == 1 or merged[0]["score"] - merged[1]["score"] >= 8
        ):
            print(
                "[info] high confidence - safe to fetch without asking",
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
            path = sheet_from_candidates(
                sheet_items[: min(len(sheet_items), 12)],
                args.sheet,
                size=200,
                theme=args.sheet_theme,
                title=f"Logo candidates: {', '.join(args.query)}",
            )
            print(f"[info] contact sheet: {path.resolve()}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] could not draw contact sheet: {exc}", file=sys.stderr)

    if args.table:
        print_table(merged)
    else:
        print(
            json.dumps(merged, indent=None if args.compact else 2, ensure_ascii=False)
        )

    if not merged:
        print(f"No icons found for '{', '.join(args.query)}'.", file=sys.stderr)
        print(SUGGESTIONS, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
