# Create Icon

Generate consistent, slide-ready icons with a configurable text-to-image model.

The pipeline is: **prompt compiler → provider → background removal → geometry
normalization → quality gate → manifest**. Every icon comes out on the same
square canvas with the same padding, at 1024 and 512 px.

## Features

- **Four-block prompt compiler** — subject, style, composition and negative
  prompt are separate; no duplicated clauses, no `a AI 算力`, no style keywords
  fighting each other.
- **16 style presets** with per-style negative prompts (flat, flat-2.0, line,
  duotone, 3D, clay, glass, isometric, gradient, hand-drawn, Notion, ...).
- **Consistent sets** — `--set` + a fixed palette + a seed family makes a deck's
  icons read as one family.
- **Honest transparency** — flood-fill from the border, so interior whites stay;
  soft alpha edges plus de-fringing remove the white halo.
- **Geometry normalization** — trim, 84% content box, centered, **1024 + 512**.
- **Quality gate** — `check.py` detects empty renders, edge contact, off-center
  artwork, bad padding and halo; `--ensure-quality` retries automatically.
- **Measured style transfer** — `analyze_style.py` combines a VLM description
  with a quantized palette, so hex values are sampled from the image.
- **Five providers** — MiniMax, Aliyun Qwen, Volcengine Ark (Seedream), OpenAI,
  and any OpenAI-compatible gateway.

## Quick start

```bash
# one icon
uv run generate_icon.py -p "growth arrow" -s flat-color -n 3

# an icon set for a deck
uv run generate_icon.py --set "growth,team,innovation,target" \
  -s flat-color --palette "#1E3A8A,#F59E0B,#FFFFFF" --seed 42 --transparent

# a transparent icon from a different provider
uv run generate_icon.py -p "shield" -s 3d-render --provider ark --transparent

# preview prompts without spending money
uv run generate_icon.py -p "rocket" -s gradient --dry-run
```

Requires [uv](https://docs.astral.sh/uv/) and an API key. Nothing else to
install — scripts are PEP 723 and declare their own dependencies.

## Install

```bash
npx -y skills@latest add zenanswer/agent-skills -g -s create-icon \
  -a opencode claude-code -y
npx -y skills@latest update -g create-icon -y
```

Files land in `~/.agents/skills/create-icon`. Do not edit the installed copy —
`update` overwrites it.

## Configuration

Precedence: CLI flags > shell env > `.env` in the skill directory > defaults.

```bash
export ICON_PROVIDER="ark"                       # minimax | qwen | ark | openai | openai-compatible
export ICON_API_KEY="..."
# optional overrides
# export ICON_MODEL="doubao-seedream-5-0-pro-260628"
# export ICON_API_HOST="https://ark.cn-beijing.volces.com"
# export ICON_VLM_MODEL="..."
```

Convenience aliases are also read: `MINIMAX_API_KEY`, `MINIMAX_API_HOST`,
`DASHSCOPE_API_KEY`, `ARK_API_KEY`.

Or use a self-contained `.env`:

```bash
cd ~/.agents/skills/create-icon
cp .env.example .env   # then edit
```

## Providers

| Provider | Default image model | Default VLM | Default host |
|---|---|---|---|
| `minimax` | `image-01` | `MiniMax-M1` | `https://api.minimaxi.com` |
| `qwen` | `qwen-image-3.0-pro` | `qwen-vl-max` | `https://dashscope.aliyuncs.com` |
| `ark` | `doubao-seedream-5-0-pro-260628` | (set `ICON_VLM_MODEL`) | `https://ark.cn-beijing.volces.com` |
| `openai` | `gpt-image-1` | `gpt-4o` | `https://api.openai.com` |
| `openai-compatible` | (set) | (set) | (set) |

Notes:

- **MiniMax** has no negative-prompt field; the negative list is folded into the
  positive prompt as `avoid: ...`.
- **Qwen** supports `negative_prompt`, `seed`, and `n` up to 6. `qwen-image-max`
  / `plus` / base only accept a fixed set of sizes; the script handles that.
- **Ark / Seedream** returns one image per request, so `-n 3` issues three calls
  with seeds `seed, seed+1, seed+2`. `sequential_image_generation` is disabled
  explicitly so a "series" is never returned by accident.
- **OpenAI** `gpt-image-1` gets a real transparent background
  (`background=transparent`); `dall-e-3` is still supported and gets one call
  per image.

Adding a provider: append to `DEFAULT_HOSTS` / `DEFAULT_IMAGE_MODELS` /
`DEFAULT_VLM_MODELS`, implement `_gen_<name>()`, add it to
`SUPPORTED_PROVIDERS` and the dispatch in `generate_images()`.

## Styles

| Key | Name | Key | Name |
|---|---|---|---|
| `flat-color` | Flat Color | `3d-render` | 3D Render |
| `flat-2.0` | Flat 2.0 | `clay-3d` | Clay 3D |
| `line-monochrome` | Line Monochrome | `glass` | Glassmorphism |
| `line-color` | Line Color | `isometric` | Isometric |
| `duotone` | Duotone | `isometric-2.5d` | Isometric 2.5D |
| `duotone-line` | Duotone Line | `gradient` | Gradient |
| `filled-color` | Filled Color | `hand-drawn` | Hand Drawn |
| `minimal-solid` | Minimal Solid | `notion` | Notion Style |

Each preset defines `positive` and `negative` keyword lists in `styles.json`,
plus a `tags` field. Composition constraints (`single centered object`, `no
background scenery`, `generous even padding`, ...) live in `promptkit.py` and are
never repeated by a style.

## Normalization

`normalize.py` does one thing well:

```
raw image → trim to artwork (alpha or background color)
          → scale long edge to 84% of the canvas (8% padding per side)
          → center on a square canvas (transparent or background-filled)
          → export 1024 and 512
```

`--padding` changes the ratio (`0.12` = smaller artwork). `--no-trim` keeps the
generated margins. `--no-normalize` skips the whole step.

## Background removal

`remove_bg.py` keys the background region **connected to the image border**,
not every pixel that happens to match the background color. That preserves
interior whites. The alpha edge is softened and de-fringed against the sampled
background color.

Modes:

| Mode | Behavior |
|---|---|
| `auto` | Keep existing alpha if the image is already transparent, else flood |
| `flood` | Connected background removal (default) |
| `chroma` | Plain color key (for flat backgrounds with holes cut to the border) |
| `keep` | Do nothing |

## Quality gate

```bash
uv run check.py output/*.png --transparent
```

Checks: empty output, artwork touching the canvas edge, off-center content,
content box outside 84% ± 8%, coverage outside 5–95%, missing transparency and
halo ratio. Exit code is non-zero when something is wrong, so it can be used in
a loop.

## Style analysis

```bash
uv run analyze_style.py example.png
uv run analyze_style.py a.png b.png --json
uv run analyze_style.py example.png --output-style-only > style.txt
```

Outputs a style prompt plus the measured palette and background color. Passing
several examples asks the VLM for the common style.

## Tests

```bash
uv run tests/smoke.py
```

49 offline assertions: prompt compilation, style schema, normalization geometry,
background removal (including interior-white preservation), quality gate,
palette extraction, and a full end-to-end run against a local mock provider
(prompt → generate → remove bg → normalize → manifest).

## Layout

```
create-icon/
├── SKILL.md
├── README.md
├── CHANGELOG.md
├── generate_icon.py     CLI entry point
├── promptkit.py         prompt compiler + palette parsing
├── providers.py         provider adapters, retries, cost estimate
├── normalize.py         trim/pad/center/multi-size
├── remove_bg.py         flood-fill removal + de-fringe
├── check.py             quality gate
├── analyze_style.py     style + palette from examples
├── styles.json          16 presets
├── .env.example
└── tests/smoke.py
```

## Pricing

Approximate, per image: MiniMax ~0.025 CNY, Ark/Seedream ~0.2 CNY, Qwen
~0.35 CNY, OpenAI ~0.04 USD. Use `--estimate-cost` before a large run; vendor
prices change, so treat these as an order of magnitude.