# Icon Finder

Search and fetch brand/technology logos (open-source software, cloud services, tech companies) and render them as SVG + PNG for use in presentations, documents, and web pages.

## Features

- **Two free icon sources, no API keys required:**
  - [Iconify](https://iconify.design) `logos` collection — ~1900 colored official brand logos (CC0)
  - [Simple Icons](https://simpleicons.org) — ~3400 monochrome brand icons with official brand colors
- **Dual format output:** every icon is rendered as both SVG (vector) and PNG (transparent background, configurable size)
- **Color-first by default:** fetches the official colored logo; falls back to brand-color rendering for monochrome-only brands
- **Monochrome mode:** render all logos in a single uniform color (e.g. all white for dark slides)
- **Abbreviation expansion:** `k8s` → kubernetes, `tf` → terraform, `gcp` → google cloud, and more
- **Smart no-results guidance:** when a brand isn't found, prints actionable suggestions
- **Trademark-aware:** some brands (AWS, Azure, Vue.js, Java) are excluded from Simple Icons CDN for legal reasons — the fetch script detects this and suggests the Iconify alternative

## Project Structure

```
icon-finder/
├── SKILL.md                  # Skill metadata + workflow (read by opencode agent)
└── scripts/
    ├── search_icons.py       # Multi-source keyword search → JSON candidates
    ├── fetch_icon.py         # Download SVG + render PNG (transparent background)
    └── requirements.txt      # Python dependencies
```

## Prerequisites

### System dependencies

```bash
# macOS — cairo is needed by cairosvg for PNG rendering
brew install cairo

# Alternative renderer (optional, used as fallback if cairosvg is unavailable)
brew install librsvg
```

### Python dependencies

```bash
# Create a virtualenv (recommended, avoids PEP 668 issues)
python3 -m venv .venv

# Install dependencies
.venv/bin/pip install -r icon-finder/scripts/requirements.txt
```

Dependencies: `requests`, `cairosvg`, `Pillow`

## Usage

### Search for icons

```bash
python scripts/search_icons.py "aws"
python scripts/search_icons.py "k8s"          # auto-expanded to "kubernetes"
python scripts/search_icons.py "deepseek" --limit 5
```

Output is a JSON array of candidates:

```json
[
  {
    "source": "iconify",
    "id": "logos:aws",
    "title": "Aws",
    "is_color": true,
    "brand_color": null,
    "preview_url": "https://api.iconify.design/logos:aws.svg"
  }
]
```

### Fetch and render

```bash
# Colored logo (default), 512px PNG, output to ./logos/
python scripts/fetch_icon.py "iconify:logos:aws" --out ./logos --size 512 --style color

# Monochrome, rendered in white (for dark slides)
python scripts/fetch_icon.py "iconify:logos:aws" --out ./logos --style mono --color "#FFFFFF"

# SVG only (skip PNG rendering)
python scripts/fetch_icon.py "iconify:logos:aws" --out ./logos --svg-only
```

Each fetch produces two files:
- `<name>.svg` — original vector file
- `<name>.png` — transparent-background raster at the requested size

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--out` | `./logos` | Output directory (created if missing) |
| `--size` | `512` | PNG long-edge size in pixels |
| `--style` | `color` | `color` (official colors) or `mono` (single color) |
| `--color` | brand color | Hex color for mono mode (e.g. `#FFFFFF`) |
| `--svg-only` | off | Skip PNG rendering, output SVG only |

### Proxy

If you're behind a proxy, set the standard environment variables:

```bash
export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897
```

The scripts will route all requests through the proxy and print `[info] Using proxy: ...` to stderr.

## Install

This skill ships in [`zenanswer/agent-skills`](https://github.com/zenanswer/agent-skills). Install it with the official skills CLI:

```bash
npx -y skills@latest add zenanswer/agent-skills -g -s icon-finder \
  -a opencode claude-code -y
```

- Files land in `~/.agents/skills/icon-finder`; other agent directories are symlinked automatically.
- Update with `npx -y skills@latest update -g icon-finder -y`, remove with `npx -y skills@latest remove -g icon-finder -y`.
- Do not edit the installed copy — `update` overwrites it; send changes to the source repo instead.

### Verify installation

After installing, restart opencode. The skill should appear in the available skills list. You can test it by asking:

> "帮我找一下 AWS 和 Kubernetes 的 logo"

The agent will search, present candidates, fetch the selected icons, and output SVG + PNG files ready for your slides.

### Dependencies note for deployment

The scripts need Python packages (`requests`, `cairosvg`, `Pillow`) and the system `cairo` library. If opencode runs with a specific Python, make sure these are installed in that environment. The SKILL.md instructs the agent to use the project `.venv/` if present, or install deps otherwise.

```bash
python3 -m pip install -r ~/.agents/skills/icon-finder/scripts/requirements.txt
# Debian/Ubuntu: sudo apt install libcairo2
# macOS: brew install cairo
```
