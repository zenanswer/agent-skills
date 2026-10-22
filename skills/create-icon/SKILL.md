---
name: create-icon
description: "Generate consistent, slide-ready icons with a text-to-image model (MiniMax, Aliyun Qwen, Volcengine Seedream, OpenAI, or any OpenAI-compatible gateway). Compiles a real prompt (subject + style + composition + negative), strips backgrounds without punching holes in the artwork, then trims, pads, centers and exports 1024 + 512 px PNGs plus an icons.json manifest. Use for 'icon for my PPT', 'slide icons', 'icon set', 'transparent PNG icon', 'match this icon style', '生成图标'."
---

# Create Icon

Icons that survive being placed next to each other on a slide: same canvas,
same padding, same visual weight, no white halo, no stretched artwork.

## What it guarantees

- **Prompt is compiled, not concatenated** — four explicit blocks (subject,
  style, composition, negative), so clauses never fight or repeat and Chinese
  subjects never get a stray English article.
- **Every image is normalized** — trimmed to artwork, long edge at 84% of a
  square canvas (8% padding per side), centered, exported at **1024 + 512**.
- **Transparent means transparent** — only the background region connected to
  the border is removed; interior whites (gear holes, cloud fills, bubbles)
  stay. Edges are de-fringed, so no white halo.
- **Quality gate** — each icon is checked for empty output, edge contact,
  off-centering and halo; `--ensure-quality` retries once with a new seed.

## Providers

| Provider | Default model | Notes |
|---|---|---|
| `minimax` (default) | `image-01` | Cheapest; no negative-prompt field (folded into the prompt) |
| `qwen` | `qwen-image-3.0-pro` | Negative prompt + `n` up to 6 |
| `ark` | `doubao-seedream-5-0-pro-260628` | Seedream 5.0, strong icon quality, single image per call |
| `openai` | `gpt-image-1` | Native transparent background |
| `openai-compatible` | (set `--model`) | SiliconFlow, DashScope compatible-mode, Ark v3, self-hosted |

Config precedence: CLI flags > `ICON_*` env > `MINIMAX_*` / `DASHSCOPE_*` /
`ARK_*` aliases > `.env` in the skill directory > defaults.

```bash
echo "provider=${ICON_PROVIDER:-minimax} key=${ICON_API_KEY:+set}"
```

If the key is missing, check `.env` in the skill directory, or ask the user.
Never print the key.

## Default workflow (do not over-ask)

1. **Pick a style.** Default to `flat-color` unless the deck's look suggests
   otherwise. Only ask when the user clearly cares about visual style.
2. **Generate straight away.** One subject → `-p`; several → `--set` with a
   shared style/palette/seed.
3. **Look at the result.** Read the PNG with your vision capability, or run
   `check.py`. Fix concrete defects, not vibes.
4. **Iterate once, then deliver** paths + the manifest.

### Single icon

```bash
uv run generate_icon.py -p "growth arrow" -s flat-color -n 3
uv run generate_icon.py -p "rocket" -s gradient --transparent
uv run generate_icon.py -p "AI 算力" -s line-monochrome -n 2
```

### A consistent set (the common case for decks)

```bash
uv run generate_icon.py \
  --set "growth,team,innovation,target" \
  -s flat-color \
  --palette "#1E3A8A,#F59E0B,#FFFFFF" \
  --seed 42 \
  --transparent
```

All icons share the style block, palette and seed family (`seed+i`), so they
read as one set. Output includes `icons.json`.

### Learn a style from an example

```bash
STYLE=$(uv run analyze_style.py example.png --output-style-only)
uv run generate_icon.py -p "target" --custom-style "$STYLE"
```

`analyze_style.py` combines a VLM description with **measured** dominant colors
(Pillow quantization), so hex codes are real rather than guessed. Multiple
examples are supported: `analyze_style.py a.png b.png`.

### Check and iterate

```bash
uv run check.py output/*.png --transparent
```

| Symptom | Fix |
|---|---|
| Style is wrong | Different `-s`, or `--custom-style` |
| Too detailed / busy | Add "minimal, few shapes" to the prompt |
| Wrong colors | `--palette "#1E3A8A,#F59E0B"` |
| Icon too small/large in frame | `--padding 0.12` (bigger padding = smaller art) |
| White halo | `--tolerance 20`, or `--bg-mode chroma` |
| Interior holes removed | Raise `--tolerance`? No — lower it, or keep `--bg-mode flood` |
| Faces/text sneaking in | Extend `--negative-prompt` |

## Output

```
output/
├── growth.png                1024×1024, normalized
├── growth@512.png            512×512
├── growth_transparent.png    when --transparent
├── growth_transparent@512.png
└── icons.json                prompt, seed, palette, sizes, stats, issues
```

`icons.json` is the hand-off contract for a pptx workflow: every entry has
`files`, `prompt`, `seed`, `stats` and `ok`.

## Presets

| Key | Name | Best for |
|---|---|---|
| `flat-color` | Flat Color | Default business decks |
| `flat-2.0` | Flat 2.0 | Modern layered look |
| `line-monochrome` | Line Monochrome | Easy to recolor, minimal |
| `line-color` | Line Color | Professional outlines + accents |
| `duotone` / `duotone-line` | Duotone | Stylish two-tone |
| `filled-color` | Filled Color | Bold, high contrast |
| `minimal-solid` | Minimal Solid | Maximum clarity |
| `3d-render` | 3D Render | Premium, Apple-like |
| `clay-3d` | Clay 3D | Friendly, playful |
| `glass` | Glassmorphism | SaaS landing-page look |
| `isometric` / `isometric-2.5d` | Isometric | Technical / diagram |
| `gradient` | Gradient | Vibrant SaaS |
| `hand-drawn` | Hand Drawn | Warm, human |
| `notion` | Notion Style | Editorial, calm |

`--list-styles`, `--list-subjects`, `--list-providers`, `--list-backgrounds`.

## Important flags

| Flag | Default | Notes |
|---|---|---|
| `-p, --prompt` | – | One subject |
| `--set` | – | Comma-separated subjects; produces a consistent set |
| `-n` | 1 | Variants per subject (1–9) |
| `-s, --style` | `flat-color` | Preset key |
| `--custom-style` | – | Overrides `-s` |
| `--palette` | – | Fixed hex colors, strongly recommended for sets |
| `--seed` | random | Same seed + model = reproducible |
| `--transparent` | off | Native for `gpt-image-1`, flood-fill otherwise |
| `--bg-mode` | `auto` | `flood` / `chroma` / `keep` |
| `--tolerance` | 14 | Background color distance |
| `--sizes` | `1024,512` | Largest keeps the plain filename |
| `--padding` | `0.08` | Padding per side |
| `--no-normalize` | off | Keep the provider image untouched |
| `--ensure-quality` | off | Retry once on structural defects |
| `--dry-run` | off | Print compiled prompts, no API call |
| `--estimate-cost` | off | Approximate cost before spending |
| `--json` | off | Manifest on stdout |
| `--concurrency` | 3 | Parallel subjects in `--set` mode |
| `--provider`, `--model`, `--api-key`, `--host` | – | Per-run overrides |

## Cost

`--estimate-cost` prints an approximate figure. Rough per-image prices:
MiniMax ~0.025 CNY, Ark/Seedream ~0.2 CNY, Qwen ~0.35 CNY, OpenAI ~0.04 USD.
Generating 9 variants is cheap; always estimate before a large `--set`.

## Troubleshooting

| Problem | Cause / fix |
|---|---|
| `API key not set` | Export `ICON_API_KEY`, use `--api-key`, or create `.env` |
| `404` / wrong host | Provider host must be the bare base URL; `openai-compatible` needs an explicit `--host` |
| MiniMax ignores negative prompts | It has no such field; the negative is folded in as `avoid: ...` |
| `n>1` fails on dall-e-3 | The script loops one call per image automatically |
| Transparent output has grey fringe | Raise `--tolerance` slightly, or switch `--bg-mode chroma` |
| Everything looks like a photo | Your provider's prompt optimizer can override the style; try `--provider ark` or a more specific `--custom-style` |

## Files

```
create-icon/
├── SKILL.md            this file
├── generate_icon.py    CLI: prompt -> provider -> normalize -> manifest
├── promptkit.py        four-block prompt compiler + palette parsing
├── providers.py        minimax / qwen / ark / openai / compatible + VLM
├── normalize.py        trim, pad, center, multi-size export
├── remove_bg.py        flood-fill background removal + de-fringe
├── check.py            quality gate
├── analyze_style.py    style + measured palette from example images
├── styles.json         16 style presets with negatives
└── tests/smoke.py      49 offline assertions incl. a mock-provider e2e
```

Run tests with `uv run tests/smoke.py`.