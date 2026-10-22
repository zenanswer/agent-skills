#!/usr/bin/env python3
"""Search brand/technology icons across multiple sources.

Sources (queried concurrently):
  - Iconify `logos` collection: colored official brand logos (CC0).
  - Simple Icons: ~3400 brand entries with official brand hex color (monochrome).

Proxy: set HTTPS_PROXY / HTTP_PROXY environment variables.

Output: JSON array of candidates to stdout. Each candidate:
  {
    "source": "iconify" | "simpleicons",
    "id": "<fetch slug, e.g. 'logos:aws' or 'amazonwebservices'>",
    "title": "Human readable name",
    "is_color": true|false,
    "brand_color": "#RRGGBB" | null,
    "preview_url": "..."
  }

Usage:
  python search_icons.py "<query>" [--style color|mono] [--limit 10]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

ICONIFY_SEARCH_URL = "https://api.iconify.design/search"
ICONIFY_SVG_URL = "https://api.iconify.design/{icon}.svg"
SIMPLEICONS_CDN_URL = "https://cdn.simpleicons.org/{slug}{color}"
SIMPLEICONS_JSON_URL = "https://cdn.jsdelivr.net/npm/simple-icons@latest/_data/simple-icons.json"

REQUEST_TIMEOUT = 30


def get_proxy() -> dict[str, str] | None:
    """Build a requests proxies dict from HTTPS_PROXY / HTTP_PROXY env vars."""
    proxies: dict[str, str] = {}
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = os.environ.get(var)
        if val:
            scheme = "https" if var.lower().startswith("https") else "http"
            proxies.setdefault(scheme, val)
    return proxies or None


PROXIES = get_proxy()

ABBREVIATIONS: dict[str, str] = {
    "k8s": "kubernetes",
    "tf": "terraform",
    "gcp": "google cloud",
    "eks": "amazon eks",
    "ecs": "amazon ecs",
    "rds": "amazon rds",
    "s3": "amazon s3",
    "elk": "elasticsearch",
    "pg": "postgresql",
    "mongo": "mongodb",
    "node": "node.js",
    "vue": "vue.js",
    "ts": "typescript",
    "js": "javascript",
    "gh": "github",
    "gl": "gitlab",
    "pwsh": "powershell",
}


def make_session() -> requests.Session:
    s = requests.Session()
    if PROXIES:
        s.proxies.update(PROXIES)
    return s


def normalize(query: str) -> str:
    return re.sub(r"\s+", "", query.strip().lower())


def compute_si_slug(title: str) -> str:
    """Compute the Simple Icons slug from a title.

    Simple Icons slugs are the title lowercased with all non-alphanumeric
    characters removed (e.g. "Node.js" -> "nodedotjs", "Google Cloud" ->
    "googlecloud", ".ENV" -> "env").
    """
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def slugify_query(query: str) -> str:
    return compute_si_slug(query)


def search_iconify(query: str, limit: int) -> list[dict[str, Any]]:
    """Search the Iconify `logos` collection (colored official brand logos)."""
    candidates: list[dict[str, Any]] = []
    session = make_session()
    try:
        resp = session.get(
            ICONIFY_SEARCH_URL,
            params={"query": query, "prefix": "logos", "limit": str(limit)},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        icons = data.get("icons", [])
        for icon_id in icons[:limit]:
            name = icon_id.split(":", 1)[-1]
            display = name.replace("-", " ").title()
            candidates.append({
                "source": "iconify",
                "id": icon_id,
                "title": display,
                "is_color": True,
                "brand_color": None,
                "preview_url": ICONIFY_SVG_URL.format(icon=icon_id),
            })
    except (requests.RequestException, ValueError) as exc:
        print(f"[warn] Iconify search failed: {exc}", file=sys.stderr)
    return candidates


def search_simpleicons(query: str, limit: int) -> list[dict[str, Any]]:
    """Search Simple Icons by matching computed slugs/titles against the query."""
    candidates: list[dict[str, Any]] = []
    session = make_session()
    try:
        resp = session.get(SIMPLEICONS_JSON_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        # The Simple Icons JSON is a flat list of entry dicts, NOT an object
        # with an "icons" key. Each entry has: title, hex, source, optional aliases.
        icons = data if isinstance(data, list) else data.get("icons", [])
        q_norm = normalize(query)
        q_slug = slugify_query(query)
        scored: list[tuple[int, dict[str, Any]]] = []
        for entry in icons:
            title = entry.get("title", "")
            slug = compute_si_slug(title)
            aliases = entry.get("aliases", {}) or {}
            aka_list = aliases.get("aka", []) or []
            dup_list = [d.get("title", "") for d in (aliases.get("dup", []) or [])]
            all_names = [title] + aka_list + dup_list
            score = 0
            if slug == q_slug:
                score = 100
            elif slug.startswith(q_slug):
                score = 80
            elif q_slug and q_slug in slug:
                score = 60
            else:
                for name in all_names:
                    if normalize(name) == q_norm:
                        score = 90
                        break
                    elif q_norm and q_norm in name.lower():
                        score = max(score, 40)
            if score > 0:
                hex_color = entry.get("hex", "")
                brand_color = f"#{hex_color}" if hex_color else None
                scored.append((score, {
                    "source": "simpleicons",
                    "id": slug,
                    "title": title,
                    "is_color": False,
                    "brand_color": brand_color,
                    "preview_url": SIMPLEICONS_CDN_URL.format(slug=slug, color=""),
                }))
        scored.sort(key=lambda x: (-x[0], x[1]["title"].lower()))
        candidates = [c for _, c in scored[:limit]]
    except (requests.RequestException, ValueError) as exc:
        print(f"[warn] Simple Icons search failed: {exc}", file=sys.stderr)
    return candidates


def dedupe(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove obvious duplicates preferring colored/iconify sources."""
    seen: dict[str, dict[str, Any]] = {}
    priority = {"iconify": 0, "simpleicons": 1}
    for c in candidates:
        key = c["title"].lower()
        existing = seen.get(key)
        if existing is None or priority.get(c["source"], 9) < priority.get(existing["source"], 9):
            seen[key] = c
    return list(seen.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Search brand/technology icons across sources.")
    parser.add_argument("query", help="Brand or technology name (e.g. 'aws', 'kubernetes').")
    parser.add_argument("--style", choices=["color", "mono"], default="color",
                        help="Preferred style (affects ordering; default color).")
    parser.add_argument("--limit", type=int, default=10, help="Max candidates per source.")
    args = parser.parse_args()

    if PROXIES:
        print(f"[info] Using proxy: {PROXIES.get('https') or PROXIES.get('http')}", file=sys.stderr)

    query = args.query
    expanded = ABBREVIATIONS.get(query.strip().lower())
    if expanded:
        print(f"[info] '{query}' expanded to '{expanded}'", file=sys.stderr)
        query = expanded

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(search_iconify, query, args.limit): "iconify",
            pool.submit(search_simpleicons, query, args.limit): "simpleicons",
        }
        all_candidates: list[dict[str, Any]] = []
        for fut in as_completed(futures):
            all_candidates.extend(fut.result())

    all_candidates = dedupe(all_candidates)
    all_candidates.sort(key=lambda c: (
        0 if c["is_color"] and args.style == "color" else 1,
        {"iconify": 0, "simpleicons": 1}.get(c["source"], 9),
        c["title"].lower(),
    ))

    print(json.dumps(all_candidates, indent=2, ensure_ascii=False))
    if not all_candidates:
        print(
            f"No icons found for '{args.query}'. Try:\n"
            "  - A common abbreviation (e.g. k8s -> kubernetes, tf -> terraform)\n"
            "  - A shorter/broader keyword (e.g. 'elastic' instead of 'elasticsearch-stack')\n"
            "  - The full brand name (e.g. 'amazon web services' instead of 'aws')\n"
            "If still nothing, the brand may not be in any free icon collection yet.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
