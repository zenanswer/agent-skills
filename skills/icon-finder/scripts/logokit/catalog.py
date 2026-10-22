"""Curated icon collections, concept aliases and license bookkeeping.

`collections.json` is the source of truth for what UI mode searches and under
which license. It is deliberately conservative where upstream sources disagree
(e.g. Boxicons is labeled MIT by Iconify, but its own README says icons are
CC BY 4.0 - we treat it as attribution-required).

`concepts.json` exists because the Iconify search API matches icon *names*, not
meaning: "cost saving" returns nothing, while "piggy-bank" returns the right
icons. The map translates deck concepts (English and Chinese) into names.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent
COLLECTIONS_PATH = DATA_DIR / "collections.json"
CONCEPTS_PATH = DATA_DIR / "concepts.json"

# SPDX ids that require attribution.
ATTRIBUTION_LICENSES = {"CC-BY-3.0", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0"}


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - packaging error
        raise SystemExit(f"ERROR: cannot read {path}: {exc}") from exc


_CATALOG: dict | None = None
_CONCEPTS: dict | None = None


def catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = _load(COLLECTIONS_PATH)
    return _CATALOG


def concepts() -> dict[str, list[str]]:
    global _CONCEPTS
    if _CONCEPTS is None:
        _CONCEPTS = _load(CONCEPTS_PATH).get("concepts", {})
    return _CONCEPTS


def collection(prefix: str) -> dict[str, Any] | None:
    return catalog()["collections"].get(prefix)


def all_prefixes() -> list[str]:
    return list(catalog()["collections"].keys())


def ui_defaults() -> list[str]:
    return list(catalog().get("defaults", {}).get("ui", []))


def is_ui_collection(prefix: str) -> bool:
    entry = collection(prefix)
    return bool(entry and entry.get("category") in {"ui", "emoji"})


def resolve_collections(spec: str | None, mode: str = "logo") -> list[str]:
    """Turn a CLI/spec string into a validated list of Iconify prefixes."""
    if not spec:
        return ui_defaults() if mode == "ui" else ["logos"]
    spec = spec.strip()
    if spec == "all":
        return all_prefixes()
    if spec in {"all-open", "open"}:
        return [p for p in all_prefixes() if is_ui_collection(p)]
    wanted = [part.strip() for part in spec.split(",") if part.strip()]
    known = set(all_prefixes())
    valid: list[str] = []
    for prefix in wanted:
        if prefix in known:
            valid.append(prefix)
        else:
            # Allow any Iconify collection, even if not in the curated catalog.
            print(
                f"[warn] '{prefix}' is not in the curated catalog; "
                f"license info will come from Iconify",
                file=sys.stderr,
            )
            valid.append(prefix)
    return valid


def attribution_required(spdx: str | None) -> bool:
    if not spdx:
        return False
    lic = spdx.strip().upper()
    return lic in ATTRIBUTION_LICENSES or lic.startswith("CC-BY")


def license_for(prefix: str, api_info: dict | None = None) -> dict[str, Any]:
    """License metadata for one collection.

    The curated catalog wins over Iconify metadata (it carries conservative
    corrections); Iconify's response is the fallback for unknown prefixes.
    """
    entry = collection(prefix)
    if entry:
        return {
            "collection": prefix,
            "collection_name": entry.get("name", prefix),
            "author": entry.get("author"),
            "license": entry.get("license"),
            "license_url": entry.get("license_url"),
            "attribution_required": bool(entry.get("attribution_required")),
            "license_source": "catalog",
        }
    info = api_info or {}
    lic = info.get("license") or {}
    spdx = lic.get("spdx") or lic.get("title")
    return {
        "collection": prefix,
        "collection_name": info.get("name", prefix),
        "author": (info.get("author") or {}).get("name")
        if isinstance(info.get("author"), dict)
        else None,
        "license": spdx,
        "license_url": lic.get("url"),
        "attribution_required": attribution_required(spdx),
        "license_source": "iconify",
    }


STYLE_SUFFIXES = {
    "outline", "outlined", "rounded", "round", "sharp", "bold", "fill", "filled",
    "duotone", "twotone", "two", "tone", "thin", "light", "regular", "solid",
    "broken", "alt", "alternative", "minimal", "minimalistic", "line", "linear", "stroke",
}


def family_name(name: str) -> str:
    """'rocket-outline-rounded' -> 'rocket'; keeps meaningful suffixes (alert, off)."""
    parts = [p for p in name.split("-") if p]
    while len(parts) > 1 and (parts[-1] in STYLE_SUFFIXES or parts[-1].isdigit()):
        parts.pop()
    return "-".join(parts) or name


def concept_terms(query: str) -> list[str]:
    """Expand a concept like 'cost saving' or '省钱' into searchable icon names."""
    from .sources import normalize  # local import avoids a cycle at import time

    q = normalize(query)
    if not q:
        return []
    terms: list[str] = []
    for key, names in concepts().items():
        nk = normalize(key)
        if not nk:
            continue
        if q == nk or (len(nk) >= 3 and nk in q) or (len(q) >= 3 and q in nk):
            terms.extend(names)
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            out.append(term)
    return out


def filter_by_license(candidates: Iterable[dict], mode: str) -> list[dict]:
    """mode: any | permissive | attribution | no-sharealike."""
    if mode == "any":
        return list(candidates)
    out = []
    for cand in candidates:
        lic = (cand.get("license") or "").upper()
        req = bool(cand.get("attribution_required"))
        if mode == "permissive" and req:
            continue
        if mode == "attribution" and not req:
            continue
        if mode == "no-sharealike" and "SA" in lic:
            continue
        out.append(cand)
    return out


def credits_markdown(entries: Iterable[dict], title: str = "Icon credits") -> str:
    """Build an attribution file from manifest entries."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        prefix = entry.get("collection") or entry.get("source") or "unknown"
        name = entry.get("collection_name") or prefix
        license_name = entry.get("license") or "unknown"
        key = (prefix, license_name)
        group = groups.setdefault(
            key,
            {
                "name": name,
                "license": license_name,
                "license_url": entry.get("license_url") or "",
                "attribution_required": bool(entry.get("attribution_required")),
                "icons": [],
            },
        )
        label = entry.get("title") or entry.get("ref") or ""
        if label and label not in group["icons"]:
            group["icons"].append(label)

    ordered = sorted(
        groups.values(),
        key=lambda g: (not g["attribution_required"], g["name"].lower()),
    )
    lines = [
        f"# {title}",
        "",
        f"Generated by icon-finder on {datetime.now(timezone.utc).date().isoformat()}.",  # noqa: UP017
        "",
        "| Collection | License | Attribution | Icons |",
        "|---|---|---|---|",
    ]
    for group in ordered:
        need = "required" if group["attribution_required"] else "not required"
        lines.append(
            f"| {group['name']} | {group['license']} | {need} | {len(group['icons'])} |"
        )
    lines.append("")
    if any(g["attribution_required"] for g in ordered):
        lines += [
            "## Attribution required",
            "",
            "These sets are licensed CC BY / CC BY-SA. Keep this section with the deck",
            "when you share it, or replace the icons with permissive sets.",
            "",
        ]
        for group in ordered:
            if not group["attribution_required"]:
                continue
            icons = ", ".join(group["icons"][:12])
            more = (
                ""
                if len(group["icons"]) <= 12
                else f" (+{len(group['icons']) - 12} more)"
            )
            lines.append(
                f"- **{group['name']}** — {group['license']} — {group['license_url']}"
            )
            if icons:
                lines.append(f"  - {icons}{more}")
        lines.append("")
    lines += [
        "## Notes",
        "",
        "- MIT / ISC / Apache-2.0 / CC0 / OFL sets do not require attribution.",
        "- Brand logos remain trademarks of their owners; use them for identification only.",
        "- License metadata is curated in `scripts/logokit/collections.json`; verify with",
        "  the upstream project before redistribution.",
        "",
    ]
    return "\n".join(lines)
