---
name: icon-finder
description: "Find, download and normalize brand logos or concept icons for slides, documents and web pages. Logo mode searches Iconify, svgl, lobe-icons and Simple Icons; UI mode searches six license-clear Iconify sets (Material Symbols, MDI, Tabler, Lucide, Phosphor, Font Awesome) with concept expansion for queries like 'cost saving' or '团队'. Outputs SVG + square transparent PNGs at 1024/512 with identical padding, preserved aspect ratio, license metadata and an optional credits file. Trigger on 'find logo', 'get icon', 'brand icon', 'AWS/DeepSeek/Claude logo', 'slide icon', 'icon set', 'monochrome icons', or when a pptx task needs real icons instead of text."
---

# Icon Finder

Logo → slide-ready asset pipeline, plus a license-clear UI icon mode.

## Two modes

| Mode | Use for | Sources |
|---|---|---|
| `logo` (default) | Brand marks: AWS, Kubernetes, DeepSeek, Claude | Iconify `logos`, svgl, lobe-icons, Simple Icons |
| `ui` | Concept icons for slides: growth, team, risk, 预算 | Six curated Iconify UI sets, all license-clear |

**Rule of thumb:** if a stock icon exists, use `--mode ui`; use `create-icon`
only when you need something custom, illustrated or 3D.

## What it guarantees

- **Aspect ratio is never distorted.** A 256×153 wordmark stays 256:153; it is
  fitted into the canvas, not squashed to a square.
- **One visual weight across a set.** Trimmed, scaled so the long edge is 84% of
  the canvas (8% padding per side), centered on a transparent square, exported
  at **1024 + 512** px.
- **Deterministic results.** Same query, same order.
- **Real recoloring.** Mono/dark/light variants via an injected stylesheet, so
  inline `style`, `currentColor`, strokes and gradients are all handled.
- **License metadata.** Every result carries `license`, `license_url` and
  `attribution_required`; `--credits` writes the attribution file.

## Quick reference

| Task | Command |
|---|---|
| Search a brand | `uv run scripts/search_icons.py "aws"` |
| Search UI icons | `uv run scripts/search_icons.py --mode ui "growth" --sheet /tmp/ui.png` |
| Search with Chinese concept | `uv run scripts/search_icons.py --mode ui "团队" "风险"` |
| Only permissive licenses | `uv run scripts/search_icons.py --mode ui "rocket" --license permissive` |
| Fetch a logo | `uv run scripts/fetch_icon.py aws` |
| Fetch UI icons | `uv run scripts/fetch_icon.py --mode ui rocket users piggy-bank` |
| Credits file (CC BY) | `uv run scripts/fetch_icon.py --mode ui growth --credits CREDITS.md` |
| Monochrome / dark slide | `uv run scripts/fetch_icon.py svgl:openai --variant dark` |
| Uniform color | `uv run scripts/fetch_icon.py iconify:tabler:rocket --variant mono --color "#FFFFFF"` |
| Batch + manifest | `uv run scripts/fetch_icon.py aws k8s react -o ./logos` |

Scripts are PEP 723: `uv run` installs `requests`, `pillow`, `resvg-py`.
Nothing to set up, no system cairo needed.

## Workflow

### 1. Search

```bash
uv run scripts/search_icons.py "aws"
uv run scripts/search_icons.py --mode ui "cost saving"
```

Output is a JSON array on stdout (hints on stderr). Each candidate:

```json
{
  "source": "iconify",
  "id": "iconify:material-symbols:trending-up",
  "title": "Trending Up",
  "is_color": false,
  "collection": "material-symbols",
  "license": "Apache-2.0",
  "license_url": "https://github.com/google/material-design-icons/blob/master/LICENSE",
  "attribution_required": false,
  "variants": ["mono"],
  "also_in": ["tabler", "lucide", "ph"],
  "score": 100,
  "confidence": 1.0
}
```

- `id`: pass verbatim to `fetch_icon.py`.
- `also_in`: other UI sets that ship the same family (useful when the deck's
  style needs Tabler instead of Material).
- Abbreviations are expanded in logo mode (`k8s` → kubernetes, `ds` → deepseek).

### 2. Decide - do not over-ask

- Logo mode: `confidence >= 0.8` and a clear lead → fetch directly.
- UI mode: results are already deduplicated one-per-concept; pick the top match
  unless the style is clearly wrong (then `--collection tabler,lucide`).
- Show the contact sheet when one was generated; one look beats a slug list.

### 3. Fetch

```bash
uv run scripts/fetch_icon.py "iconify:logos:aws" -o ./logos
uv run scripts/fetch_icon.py --mode ui "rocket" -o ./icons
```

Bare names are auto-resolved through search, so `fetch_icon.py aws` works, and
`fetch_icon.py --mode ui rocket` resolves to a UI icon.

Output per icon:

```
icons/rocket.svg             vector
icons/rocket.png             1024×1024 transparent, 8% padding
icons/rocket@512.png         512×512
icons/logos.json             manifest: source, collection, license, stats
icons/CREDITS.md             only with --credits
```

Add `--sheet preview.png` for a labelled contact sheet.

### 4. Hand off

Report absolute paths. For a deck, use the `.png` (consistent size, transparent
background); keep `.svg` when the slide needs to scale beyond 1024 px. In a pptx
workflow, `logos.json` is the contract.

## UI mode details

- **Default collections (6):** `material-symbols`, `mdi`, `tabler`, `lucide`,
  `ph`, `fa6-solid`. Override with `--collection tabler,lucide` or
  `--collection all-open` (29 license-clear sets, ~140k icons).
- **Concept expansion:** Iconify matches icon *names*, not meaning. A local map
  translates deck concepts (English + Chinese) into names: `cost saving` →
  `piggy-bank`, `wallet`, `coins`; `风险` → `alert-triangle`, `shield-alert`;
  `团队` → `users`, `user-group`, `handshake`. Plain names like `rocket` are used
  as-is.
- **Variant collapsing:** style suffixes are stripped for grouping, so one row
  represents `rocket`, `rocket-outline`, `rocket-rounded`, `rocket-sharp`.
  `also_in` lists the other sets. Meaningful suffixes are kept (`shield-alert`,
  `wallet-off`).
- **Default style:** mono. UI icons are single-color; recolor with `--color`.
- **License filter:** `--license permissive` (MIT/ISC/Apache/CC0/OFL),
  `--license attribution` (CC BY), `--license no-sharealike` (excludes BY-SA).

## Variants

| `--variant` | Behavior |
|---|---|
| `auto` / `color` | Official colors; svgl `light` route when the file is split by theme |
| `mono` | One color: `--color`, else brand hex, else `#111111` for UI sets |
| `dark` | Native dark asset if available, otherwise recolored to `#FFFFFF` |
| `light` | Native light asset, otherwise `#111111` |
| `wordmark` | Brand wordmark when the source provides one |

Suffixes keep files apart: `aws.png`, `aws_mono.png`, `aws_dark.png`.

## Flags

| Flag | Default | Notes |
|---|---|---|
| `--mode` | `logo` | `logo` or `ui` |
| `--collection` | mode default | Iconify prefixes, `all-open`, or `all` |
| `--license` | `any` | `permissive` / `attribution` / `no-sharealike` |
| `--sizes` | `1024,512` | Largest keeps the plain filename |
| `--size` | – | Single-size shorthand |
| `--padding` | `0.08` | Padding per side |
| `--variant` / `--style` | `auto` / mode | `--style mono` is the legacy alias |
| `--color` | brand/default | Target color for mono/dark/light |
| `--no-trim` | off | Keep source whitespace |
| `--svg-only` / `--png-only` | off | One format only |
| `--sheet` | – | Contact sheet path |
| `--credits` | – | Attribution Markdown path |
| `--manifest` | `<out>/logos.json` | Merged across runs |
| `--all` | off | Keep per-collection duplicates |
| `--json` | off | Manifest on stdout |

Indexes are cached in `~/.cache/icon-finder`; offline runs use the stale copy.
`ICON_FINDER_NO_CACHE=1` bypasses the cache.

## Licenses

License metadata is curated in `scripts/logokit/collections.json`, with a full
audit in `references/icon-sources.md`.

| Group | Sets | Obligation |
|---|---|---|
| No attribution | MIT / ISC / Apache-2.0 / CC0 / OFL sets: Tabler, Lucide, Phosphor, Heroicons, MDI, Carbon, Fluent, Octicon, Feather, Noto, ... | none |
| Attribution required | CC BY 4.0 / BY-SA 4.0: Font Awesome, Boxicons, Solar, Basil, Codicon, Streamline, Twemoji, OpenMoji, Arcticons | keep `CREDITS.md` with the deck |

Conservative calls: **Boxicons** is treated as CC BY 4.0 (Iconify says MIT, its
README says CC BY), and **Streamline** only covers the free CC BY subset.
Brand logos remain trademarks of their owners - use them for identification.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `HTTP 404` for a logo | Wrong source for that brand - re-run search and pick another `id` |
| UI search returns little | Use a concrete noun (`rocket`, `users`) or `--collection all-open` |
| `No SVG renderer available` | `uv run` should install `resvg-py`; check network |
| `mono rendering needs a color` | Pass `--color "#FFFFFF"` (UI sets default to `#111111`) |
| Network errors | Set `HTTPS_PROXY` / `HTTP_PROXY` |
| Logo looks empty | `currentColor` with no color - fetch with `--variant mono --color "#000000"` |

## Tests

```bash
uv run tests/smoke.py   # 65 offline assertions, no network
```

Covers slugs, scoring, ref parsing, recolor correctness, aspect-preserving
render, normalization, contact sheets, the collection catalog, concept
expansion, license mapping, credits generation and UI-mode dedupe.

## Sources

| Source | Content | License |
|---|---|---|
| Iconify `logos` | ~2000 colored official logos | CC0 |
| svgl | ~670 curated SVGs, light/dark + wordmarks | per-brand |
| lobe-icons | ~976 AI/tech brand marks | MIT |
| Simple Icons | ~3300 monochrome marks | CC0 |
| Iconify UI sets (29 curated) | ~140,000 concept icons | MIT / ISC / Apache-2.0 / CC BY 4.0 (see catalog) |