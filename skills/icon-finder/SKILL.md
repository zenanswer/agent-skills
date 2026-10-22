---
name: icon-finder
description: "Find, download and normalize brand/technology logos for slides, documents and web pages. Searches Iconify, svgl, lobe-icons and Simple Icons, then renders SVG + square transparent PNGs with identical padding and preserved aspect ratio. Trigger on 'find logo', 'get icon', 'brand icon', 'AWS/Kubernetes/React/DeepSeek/Claude logo', 'logo for my deck/ppt', 'monochrome logos', or when a pptx task needs real logos instead of text."
---

# Icon Finder

Logo → slide-ready asset pipeline. Four free sources, zero API keys, no system
libraries (rendering goes through the pip-only `resvg-py`).

## What it guarantees (the part that used to be broken)

- **Aspect ratio is never distorted.** A 256×153 wordmark stays 256:153; it is
  fitted into the canvas, not squashed to a square.
- **One visual weight across a set.** Every asset is trimmed, scaled so its long
  edge is 86% of the canvas (8% padding per side), centered on a transparent
  square, then exported at **1024 + 512** px.
- **Deterministic results.** The same query returns the same order every run.
- **Real recoloring.** Monochrome/dark variants are produced with an injected
  stylesheet (`!important`), so inline `style`, `currentColor`, strokes and
  gradients are all handled.

## Quick reference

| Task | Command |
|---|---|
| Search + preview sheet | `uv run scripts/search_icons.py "aws" --sheet /tmp/candidates.png` |
| Fetch one logo (default 1024+512) | `uv run scripts/fetch_icon.py aws` |
| Fetch several at once | `uv run scripts/fetch_icon.py aws k8s react deepseek -o ./logos` |
| Monochrome for a dark slide | `uv run scripts/fetch_icon.py svgl:openai --variant dark` |
| Uniform single color | `uv run scripts/fetch_icon.py aws --variant mono --color "#FFFFFF"` |
| Native dark/light variant | `uv run scripts/fetch_icon.py svgl:amazon-web-services --variant dark` |
| Only vectors | `uv run scripts/fetch_icon.py aws --svg-only` |
| Manifest for downstream tools | `uv run scripts/fetch_icon.py aws k8s --manifest logos.json` |

Scripts are PEP 723: `uv run` installs `requests`, `pillow`, `resvg-py`
automatically. There is nothing to set up.

## Workflow

### 1. Search

```bash
uv run scripts/search_icons.py "aws"
uv run scripts/search_icons.py "openai" "k8s" "react" --sheet /tmp/candidates.png
```

Output is a JSON array on stdout (hints go to stderr). Each candidate:

```json
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
```

- `source`: `iconify` (official colored), `svgl` (curated, often light/dark +
  wordmark), `lobeicons` (AI brands), `simpleicons` (monochrome + brand hex).
- `id`: pass verbatim to `fetch_icon.py`.
- Abbreviations are expanded (`k8s` → kubernetes, `tf` → terraform, `gcp` →
  google cloud, `ds` → deepseek, ...).

### 2. Decide — do not over-ask

- `confidence >= 0.8` **and** a clear lead over the runner-up → fetch it
  directly, then show the result. No confirmation round-trip.
- Only ask when scores tie, the brand is ambiguous (Amazon the company vs AWS
  the service), or confidence is low.
- If a preview sheet was generated, show the image to the user; one look beats
  a list of slugs.

### 3. Fetch

```bash
uv run scripts/fetch_icon.py "iconify:logos:aws" -o ./logos
```

Bare names are auto-resolved through search, so `fetch_icon.py aws` works.
Accepted refs: `iconify:logos:aws`, `iconify:aws`, `logos/aws`,
`svgl:amazon-web-services`, `lobeicons:openai-color`, `simpleicons:github`,
a direct `https://...svg` URL, or a bare name.

Output per logo:

```
logos/aws.svg            original (or recolored) vector
logos/aws.png            1024×1024 transparent, 8% padding, aspect preserved
logos/aws@512.png        512×512 version
logos/logos.json         manifest (paths, source, brand color, stats)
```

Add `--sheet preview.png` to get a labelled contact sheet of what was fetched.

### 4. Hand off

Report absolute paths. For a deck, prefer the `.png` (transparent background,
consistent size); keep the `.svg` when the slide needs to scale beyond 1024 px.
If the user is in a pptx workflow, the manifest is the contract: every entry
has `png`, `svg`, `title`, `brand_color`.

## Variants

| `--variant` | Behavior |
|---|---|
| `auto` / `color` (default) | Official colors. Uses svgl `light` route when the file is split by theme. |
| `mono` | Single color: `--color`, else the brand hex. Multi-color logos are flattened (a warning is printed). |
| `dark` | For dark slides: native dark asset if the source has one, otherwise recolored to `#FFFFFF`. |
| `light` | For light slides; native light asset, otherwise `#111111`. |
| `wordmark` | Brand wordmark when the source provides one (svgl), else the icon mark. |

Variant suffixes keep files apart: `aws.png`, `aws_mono.png`, `aws_dark.png`.

## Useful flags

| Flag | Default | Why |
|---|---|---|
| `--sizes 1024,512` | `1024,512` | Largest keeps the plain filename, others get `@size` |
| `--size 512` | – | Single-size shorthand |
| `--padding 0.08` | `0.08` | Padding per side; same value = same visual weight |
| `--no-trim` | off | Keep the source whitespace instead of trimming to content |
| `--source iconify,svgl` | all four | Skip slow sources or enforce a house style |
| `--all` | off | Keep duplicate rows from different sources |
| `--style mono` | – | Legacy alias for `--variant mono` |
| `--cache-info` | – | Show cache dir, entry ages (search script) |

Indexes are cached in `~/.cache/icon-finder` (Simple Icons/lobe-icons 7 days,
svgl 1 day). Offline or rate-limited runs fall back to the stale copy.
`ICON_FINDER_NO_CACHE=1` bypasses it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `HTTP 404` for a logo | Wrong source for that brand — re-run search and pick another `id` (e.g. AWS is trademark-excluded from some CDNs). |
| `No SVG renderer available` | `uv run` should have installed `resvg-py`; check network, or install `librsvg` for `rsvg-convert`. |
| `mono rendering needs a color` | The brand has no hex in the index; pass `--color "#FFFFFF"`. |
| Network errors / timeouts | Set `HTTPS_PROXY` / `HTTP_PROXY`; the scripts print the proxy they use. |
| Logo looks empty | The source SVG uses `currentColor` with no color set; fetch with `--variant mono --color "#000000"`. |

## Sources

| Source | Content | License |
|---|---|---|
| Iconify `logos` | ~2000 colored official logos | CC0 |
| svgl | ~670 curated SVGs, light/dark + wordmarks | CC BY / brand guidelines |
| lobe-icons | ~976 AI/tech brand marks | MIT |
| Simple Icons | ~3300 monochrome marks + brand hex | CC0 |

Trademark note: logos remain the property of their owners. Use them for
identification/reference in decks; follow each brand's guidelines for
redistribution.