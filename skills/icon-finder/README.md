# Icon Finder

Search and fetch brand/technology logos and turn them into slide-ready assets:
SVG plus transparent PNGs normalized to a square canvas with identical padding.

## Features

- **Four free sources, no API keys:**
  - [Iconify](https://iconify.design) `logos` — ~2000 colored official brand logos (CC0)
  - [svgl](https://svgl.app) — ~670 curated SVGs, many with native light/dark and wordmark variants
  - [lobe-icons](https://github.com/lobehub/lobe-icons) — ~976 AI/tech brand marks (OpenAI, Claude, DeepSeek, Qwen, ...)
  - [Simple Icons](https://simpleicons.org) — ~3300 monochrome marks with official brand hex colors
- **Aspect ratio preserved** — wordmarks stay wide instead of being squashed into a square
- **Consistent visual weight** — trim → 8% padding → centered square → export at 1024 + 512 px
- **Deterministic ranking** — same query, same order; no `as_completed` races
- **Real recoloring** — mono/dark/light variants via injected CSS, not regex `fill=` patching
- **Contact sheets** — one labelled PNG grid to eyeball candidates or results
- **Batch + manifest** — fetch many logos in one call, emit `logos.json` for downstream tools
- **Zero install friction** — PEP 723 scripts; `uv run` provides `requests`, `pillow`, `resvg-py`

## Quick start

```bash
cd ~/.agents/skills/icon-finder

# search (JSON on stdout, hints on stderr)
uv run scripts/search_icons.py "aws"

# search with a visual preview
uv run scripts/search_icons.py "openai" "k8s" "react" --sheet /tmp/candidates.png

# fetch: bare names are auto-resolved
uv run scripts/fetch_icon.py aws kubernetes deepseek claude --out ./logos --sheet ./logos/preview.png

# monochrome / dark-slide variants
uv run scripts/fetch_icon.py svgl:openai --variant dark
uv run scripts/fetch_icon.py iconify:logos:aws --variant mono --color "#FFFFFF"

# vectors only, or one specific size
uv run scripts/fetch_icon.py aws --svg-only
uv run scripts/fetch_icon.py aws --size 512
```

Output:

```
logos/
├── aws.svg            # vector (original or recolored)
├── aws.png            # 1024×1024 transparent, 8% padding
├── aws@512.png        # 512×512
├── kubernetes.png
├── logos.json         # manifest: paths, source, brand color, alpha stats
└── preview.png        # optional contact sheet
```

## Search output

```json
[
  {
    "source": "iconify",
    "id": "iconify:logos:aws",
    "title": "AWS",
    "is_color": true,
    "brand_color": null,
    "variants": [],
    "preview_url": "https://api.iconify.design/logos/aws.svg",
    "score": 100,
    "confidence": 1.0
  }
]
```

Fields:

| Field | Meaning |
|---|---|
| `source` | `iconify` / `svgl` / `lobeicons` / `simpleicons` |
| `id` | Reference to pass to `fetch_icon.py` |
| `is_color` | Multi-color official logo vs monochrome mark |
| `brand_color` | Official hex (Simple Icons only) |
| `variants` | `color`, `mono`, `light`, `dark`, `wordmark` available for this entry |
| `score` | 0–100 match score; `confidence` is `score/100` |

Ranking is `(score, color-first, source priority, title)` — stable across runs.
Duplicates from different sources are collapsed per `(brand, color|mono)` so the
monochrome option stays visible.

## Fetch options

| Flag | Default | Description |
|---|---|---|
| `--out, -o` | `./logos` | Output directory |
| `--sizes` | `1024,512` | Square sizes; largest keeps the plain filename |
| `--size` | – | Single-size shorthand |
| `--variant` | `auto` | `auto`/`color`/`mono`/`light`/`dark`/`wordmark` |
| `--style` | – | Legacy alias for `--variant` (`color`/`mono`) |
| `--color` | brand hex | Target color for mono/dark/light |
| `--padding` | `0.08` | Padding per side (canvas ratio) |
| `--no-trim` | off | Keep source whitespace |
| `--svg-only` / `--png-only` | off | Emit only one format |
| `--sheet` | – | Contact sheet path |
| `--manifest` | `<out>/logos.json` | Manifest path (merged across runs) |
| `--json` | off | Also print the manifest to stdout |

Ref formats accepted by `fetch_icon.py`:

```
iconify:logos:aws   iconify:aws   logos/aws
svgl:amazon-web-services
lobeicons:openai-color
simpleicons:github
aws                       # bare name → auto search, best match
https://example.com/x.svg  # direct URL
```

## Architecture

```
icon-finder/
├── SKILL.md
├── README.md
├── scripts/
│   ├── search_icons.py     # CLI: multi-source search + ranking (+ contact sheet)
│   ├── fetch_icon.py       # CLI: fetch → normalize → multi-size output + manifest
│   └── logokit/
│       ├── net.py          # session, UA, proxy info, retries
│       ├── cache.py        # ~/.cache/icon-finder JSON cache with stale fallback
│       ├── sources.py      # 4 source adapters, scoring, deterministic ranking
│       ├── svg.py          # fetch, color analysis, CSS-injection recolor
│       ├── render.py       # resvg-py → cairosvg → rsvg-convert (aspect preserved)
│       ├── normalize.py    # trim, 8% padding, square canvas, multi-size export
│       └── sheet.py        # labelled contact sheets
└── tests/
    └── smoke.py            # 32 offline assertions, no network needed
```

## Tests

```bash
uv run tests/smoke.py
```

Covers slug/title handling, scoring and fuzzy-match guards, ref parsing, recolor
correctness (`fill="none"`, inline styles, strokes), aspect-preserving render,
normalization geometry, multi-size output and contact-sheet layout.

## Install

```bash
npx -y skills@latest add zenanswer/agent-skills -g -s icon-finder -a opencode claude-code -y
npx -y skills@latest update -g icon-finder -y
```

The installed copy at `~/.agents/skills/icon-finder` is overwritten by
`update`; send changes to the source repo instead.

## Notes

- Rendering uses `resvg-py` (pure pip wheel). If it is unavailable, the scripts
  fall back to `cairosvg` (needs `libcairo`) and then `rsvg-convert`.
- Brand indexes are cached in `~/.cache/icon-finder`; set
  `ICON_FINDER_NO_CACHE=1` to bypass or `ICON_FINDER_CACHE_DIR` to relocate.
- Logos are trademarks of their owners; use them for identification and follow
  each brand's guidelines when redistributing.