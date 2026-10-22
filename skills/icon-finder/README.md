# Icon Finder

Find, download and normalize brand logos **or** concept icons, and turn them
into slide-ready assets: SVG plus transparent PNGs on a square canvas with
identical padding, plus license metadata.

## Two modes

| Mode | Purpose | Sources |
|---|---|---|
| `logo` (default) | Brand/technology marks (AWS, Kubernetes, DeepSeek, Claude) | Iconify `logos`, [svgl](https://svgl.app), [lobe-icons](https://github.com/lobehub/lobe-icons), [Simple Icons](https://simpleicons.org) |
| `ui` | Concept icons for slides (growth, team, risk, cost, 预算) | 6 curated Iconify UI sets; `--collection all-open` for 29 sets |

## Features

- **Four logo sources + 29 UI sets, no API keys**
- **Aspect ratio preserved** - wordmarks stay wide instead of being squashed
- **Consistent visual weight** - trim → 8% padding → centered square → 1024 + 512
- **Deterministic ranking** - same query, same order; no `as_completed` races
- **Real recoloring** - mono/dark/light via injected CSS, not regex `fill=` patching
- **Concept expansion** - `cost saving` → `piggy-bank`/`wallet`/`coins`; `团队` → `users`/`handshake`
- **Variant collapsing** - one row per concept, with `also_in` listing the other sets
- **License metadata + credits** - `license`, `license_url`, `attribution_required`, `--credits CREDITS.md`
- **Contact sheets** - one labelled PNG grid to eyeball candidates or results
- **Batch + manifest** - fetch many icons, emit `logos.json` for downstream tools
- **Zero install friction** - PEP 723; `uv run` provides `requests`, `pillow`, `resvg-py`

## Quick start

```bash
cd ~/.agents/skills/icon-finder

# brand logos
uv run scripts/search_icons.py "aws"
uv run scripts/fetch_icon.py aws kubernetes deepseek --out ./logos --sheet ./logos/preview.png

# concept icons
uv run scripts/search_icons.py --mode ui "growth" --sheet /tmp/ui.png
uv run scripts/fetch_icon.py --mode ui rocket users piggy-bank --out ./icons

# Chinese concepts, permissive licenses only
uv run scripts/search_icons.py --mode ui "团队" "风险" --license permissive --table

# dark-slide / monochrome variants
uv run scripts/fetch_icon.py svgl:openai --variant dark
uv run scripts/fetch_icon.py iconify:tabler:rocket --variant mono --color "#FFFFFF"

# attribution file when using CC BY sets
uv run scripts/fetch_icon.py --mode ui "cost saving" --credits CREDITS.md
```

Output:

```
logos/
├── aws.svg            # vector (original or recolored)
├── aws.png            # 1024×1024 transparent, 8% padding
├── aws@512.png        # 512×512
├── logos.json         # manifest: source, collection, license, alpha stats
└── preview.png        # optional contact sheet
```

## Search output

```json
[
  {
    "source": "iconify",
    "id": "iconify:material-symbols:trending-up",
    "title": "Trending Up",
    "is_color": false,
    "brand_color": null,
    "collection": "material-symbols",
    "collection_name": "Material Symbols",
    "license": "Apache-2.0",
    "license_url": "https://github.com/google/material-design-icons/blob/master/LICENSE",
    "attribution_required": false,
    "variants": ["mono"],
    "also_in": ["tabler", "lucide", "ph"],
    "preview_url": "https://api.iconify.design/material-symbols/trending-up.svg",
    "score": 100,
    "confidence": 1.0
  }
]
```

| Field | Meaning |
|---|---|
| `id` | Reference for `fetch_icon.py` |
| `collection` | Iconify prefix (UI mode) |
| `license` / `license_url` | Machine-readable license info |
| `attribution_required` | `true` for CC BY / CC BY-SA sets |
| `variants` | `color`, `mono`, `light`, `dark`, `wordmark` |
| `also_in` | Other UI sets with the same icon family |
| `score` | 0-100; `confidence` is `score/100` |

Ranking is `(score, color-first, name length, source priority, title)` - stable
across runs. UI mode deduplicates one row per concept family (style suffixes
such as `-outline`, `-rounded`, `-sharp` collapse; meaningful ones like
`-alert` and `-off` do not).

## UI mode

Default collections: `material-symbols`, `mdi`, `tabler`, `lucide`, `ph`,
`fa6-solid`.

```bash
uv run scripts/search_icons.py --mode ui "rocket"
uv run scripts/search_icons.py --mode ui "rocket" --collection tabler,lucide
uv run scripts/search_icons.py --mode ui "rocket" --collection all-open --limit 10
uv run scripts/search_icons.py --mode ui "rocket" --license attribution
```

**Concept expansion** is local, because the Iconify search matches names rather
than meaning. The map lives in `scripts/logokit/concepts.json` and covers ~100
English/Chinese deck concepts. Plain names bypass the map.

**Variant collapsing** keeps results readable: six sets all have a `rocket`, but
you get one row (`Rocket`, `also_in: tabler, lucide, ph, fa6-solid`) instead of
six near-duplicates.

## Licenses

License metadata is curated in `scripts/logokit/collections.json`; the 30-site
audit that drove it is in [`references/icon-sources.md`](references/icon-sources.md).

| Obligation | Sets |
|---|---|
| None | MIT / ISC / Apache-2.0 / CC0 / OFL: Material Symbols, MDI, Tabler, Lucide, Phosphor, Heroicons, Carbon, Fluent, Octicon, Feather, Noto, ... |
| Attribution | CC BY 4.0 / BY-SA 4.0: Font Awesome, Boxicons, Solar, Basil, Codicon, Streamline, Twemoji, OpenMoji, Arcticons |

Conservative choices:

- **Boxicons** is treated as CC BY 4.0 (Iconify metadata says MIT; its own README
  says icons are CC BY 4.0).
- **Streamline** only covers the free CC BY subset on Iconify.
- Brand logos are trademarks of their owners; use them for identification.

`fetch_icon.py --credits CREDITS.md` writes a grouped attribution table and a
"Attribution required" section with license URLs.

## Fetch options

| Flag | Default | Description |
|---|---|---|
| `--out, -o` | `./logos` | Output directory |
| `--mode` | `logo` | `logo` or `ui` (sets default collections) |
| `--collection` | mode default | Iconify prefixes, `all-open`, `all` |
| `--sizes` | `1024,512` | Square sizes; largest keeps the plain filename |
| `--size` | - | Single-size shorthand |
| `--variant` | `auto` | `auto`/`color`/`mono`/`light`/`dark`/`wordmark` |
| `--style` | - | Legacy alias for `--variant` |
| `--color` | brand / `#111111` | Target color for mono/dark/light |
| `--padding` | `0.08` | Padding per side |
| `--no-trim` | off | Keep source whitespace |
| `--svg-only` / `--png-only` | off | Emit one format |
| `--sheet` | - | Contact sheet path |
| `--credits` | - | Attribution Markdown path |
| `--manifest` | `<out>/logos.json` | Manifest path (merged across runs) |
| `--json` | off | Also print the manifest |

Ref formats:

```
iconify:logos:aws      iconify:material-symbols:rocket
iconify:aws            logos/aws
svgl:amazon-web-services
lobeicons:openai-color
simpleicons:github
aws                    # bare name → auto search
rocket                 # with --mode ui → UI concept
https://…/x.svg        # direct URL
```

## Architecture

```
icon-finder/
├── SKILL.md
├── README.md
├── references/
│   └── icon-sources.md      # license audit of the "30 free icon sites" list
├── scripts/
│   ├── search_icons.py      # CLI: logo/ui search + ranking + contact sheet
│   ├── fetch_icon.py        # CLI: fetch → normalize → multi-size + credits
│   └── logokit/
│       ├── net.py           # session, UA, proxy info, retries
│       ├── cache.py         # ~/.cache/icon-finder JSON cache with stale fallback
│       ├── sources.py       # source adapters, scoring, ranking, UI mode
│       ├── catalog.py       # collection catalog, concepts, licenses, credits
│       ├── collections.json # curated sets + license metadata
│       ├── concepts.json    # deck concept → icon names (EN/CN)
│       ├── svg.py           # fetch, color analysis, CSS-injection recolor
│       ├── render.py        # resvg-py → cairosvg → rsvg-convert (aspect preserved)
│       ├── normalize.py     # trim, 8% padding, square canvas, multi-size
│       └── sheet.py         # labelled contact sheets
└── tests/
    └── smoke.py             # 65 offline assertions
```

## Tests

```bash
uv run tests/smoke.py
```

65 offline assertions: slugs, scoring and fuzzy-match guards, ref parsing,
recolor correctness (`fill="none"`, inline styles, strokes), aspect-preserving
render, normalization geometry, multi-size output, contact sheets, catalog
integrity, concept expansion, license mapping, credits generation, UI-mode
dedupe and default colors.

## Install

```bash
npx -y skills@latest add zenanswer/agent-skills -g -s icon-finder -a opencode claude-code -y
npx -y skills@latest update -g icon-finder -y
```

The installed copy at `~/.agents/skills/icon-finder` is overwritten by
`update`; send changes to the source repo.

## Notes

- Rendering uses `resvg-py` (pure pip wheel), then `cairosvg`, then
  `rsvg-convert`.
- Brand indexes and the lobe-icons index are cached in `~/.cache/icon-finder`.
- Iconify's search API uses `prefix` for one collection and `prefixes` for many;
  the client handles both.
- Logos are trademarks; icons keep their upstream licenses. Follow each source's
  terms when redistributing.