# Create Icon Skill

Generate professional icons for PPT/presentation slides using a configurable text-to-image model.

Supports multiple providers out of the box:

| Provider | Image model | VLM (style analysis) | Vendor |
|----------|-------------|----------------------|--------|
| `minimax` (default) | `image-01` | `MiniMax-M1` | MiniMax |
| `qwen` | `qwen-image-2.0-pro` | `qwen-vl-max` | Aliyun DashScope |
| `openai` | `dall-e-3` | `gpt-4o` | OpenAI |
| `openai-compatible` | any (e.g. `Kolors`) | any (e.g. `Qwen2-VL-72B`) | SiliconFlow, Volcengine, Together, self-hosted gateway, ... |

## Quick Start

### Prerequisites

1. Install [uv](https://docs.astral.sh/uv/):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Set your API key (any one of the supported providers):
   ```bash
   # Generic (recommended - works for all providers)
   export ICON_PROVIDER="minimax"   # or qwen / openai / openai-compatible
   export ICON_API_KEY="your-api-key-here"

   # Legacy alias (still works when ICON_PROVIDER=minimax or unset)
   export MINIMAX_API_KEY="your-api-key-here"
   ```

### Generate Your First Icon

```bash
uv run generate_icon.py --prompt "growth arrow" --style flat-color
```

Output is saved to `./output/`.

### List supported providers

```bash
uv run generate_icon.py --list-providers
```

---

## Install

This skill ships in [`zenanswer/agent-skills`](https://github.com/zenanswer/agent-skills). Install it with the official skills CLI:

```bash
npx -y skills@latest add zenanswer/agent-skills -g -s create-icon \
  -a opencode claude-code -y
```

- Files land in `~/.agents/skills/create-icon`; other agent directories are symlinked automatically.
- Update: `npx -y skills@latest update -g create-icon -y`；remove: `npx -y skills@latest remove -g create-icon -y`.
- The directory name must equal the `name` field in `SKILL.md` (`create-icon`) — `npx skills` uses `name` verbatim as the install directory.

### Configure Environment

The skill supports **multiple providers**. Configuration precedence (highest first):

1. CLI flags: `--provider` / `--model` / `--api-key` / `--host`
2. Generic env vars: `ICON_PROVIDER` / `ICON_API_KEY` / `ICON_API_HOST` / `ICON_MODEL` / `ICON_VLM_MODEL`
3. Legacy env vars (minimax only): `MINIMAX_API_KEY` / `MINIMAX_API_HOST`
4. `.env` file in the skill directory
5. Built-in defaults

#### Method 1: Shell environment variables (recommended)

Add to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
# Pick a provider: minimax | qwen | openai | openai-compatible
export ICON_PROVIDER="minimax"
export ICON_API_KEY="sk-your-key-here"
# Optional overrides (provider-specific defaults apply if omitted):
# export ICON_API_HOST="https://api.minimaxi.com"
# export ICON_MODEL="image-01"
# export ICON_VLM_MODEL="MiniMax-M1"
```

Then reload: `source ~/.zshrc`

#### Method 2: `.env` file in the skill directory (self-contained)

The scripts auto-load a `.env` file from the skill directory as a fallback:

```bash
cd ~/.agents/skills/create-icon
cp .env.example .env
# Edit .env and fill in your real key + provider
```

```env
ICON_PROVIDER=minimax
ICON_API_KEY=sk-your-key-here
```

> **Security:** The `.gitignore` file already excludes `.env` from version control.

#### Method 3: CLI flags (per-run override)

```bash
uv run generate_icon.py --prompt "growth" --provider qwen \
  --api-key sk-xxxx --model qwen-image-2.0-pro
```

### Verify

Start opencode and ask it to generate an icon:

```
> Generate a flat-color "growth arrow" icon for my PPT, make 3 variants with transparent background
```

The agent should:
1. Load the `create-icon` skill automatically
2. Run `uv run generate_icon.py --prompt "growth arrow" --style flat-color -n 3 --transparent`
3. Save icons to `./output/` and report the file paths

### Other agents

`npx skills` installs to `~/.agents/skills` and links into every agent you selected with `-a`. To cover more agents, re-run the add command with additional agent names (`-a '*'` for all detected agents). Do not hand-copy the directory into `~/.claude/skills` — the link is maintained by the CLI.

---

## Scripts

All scripts use **PEP 723 inline metadata** — `uv run` handles dependencies automatically, no manual installation needed.

### `generate_icon.py` — Main Icon Generator

Calls the configured provider's image-generation API to generate icons from text prompts.

```bash
# List available preset styles
uv run generate_icon.py --list-styles

# Generate a single flat-color icon
uv run generate_icon.py --prompt "team collaboration" --style flat-color

# Generate 3 variants of a line icon
uv run generate_icon.py --prompt "innovation" --style line-monochrome -n 3

# Generate with transparent background (auto post-processing)
uv run generate_icon.py --prompt "rocket" --style gradient --transparent

# Generate with custom style description
uv run generate_icon.py --prompt "target" --custom-style "3D isometric, pastel colors, soft shadows"

# Preview the prompt without calling the API
uv run generate_icon.py --prompt "growth" --style flat-color --dry-run

# Use a seed for reproducibility
uv run generate_icon.py --prompt "shield" --style 3d-render --seed 42

# Switch provider on the fly
uv run generate_icon.py --prompt "growth" --style flat-color \
  --provider qwen --model qwen-image-2.0-pro --api-key sk-xxxxx
```

**Options:**

| Flag | Description |
|------|-------------|
| `--prompt, -p` | Icon subject description (required) |
| `--style, -s` | Preset style key (see `--list-styles`) |
| `--custom-style` | Custom style description (overrides `--style`) |
| `-n` | Number of images (1-9, default 1) |
| `--aspect-ratio` | Aspect ratio (default `1:1` = 1024×1024) |
| `--background` | Background preset: `white`, `light-gray`, `dark`, `transparent-friendly` |
| `--transparent` | Remove background to create transparent PNG |
| `--output, -o` | Output directory (default `./output`) |
| `--name` | Base filename (default: slugified prompt) |
| `--seed` | Random seed for reproducibility |
| `--provider` | Provider: `minimax` / `qwen` / `openai` / `openai-compatible` |
| `--model` | Image model name (provider-specific default) |
| `--api-key` | API key (or `ICON_API_KEY` env) |
| `--host` | API host/base URL (or `ICON_API_HOST` env) |
| `--negative-prompt` | Negative prompt (qwen only; has sensible default) |
| `--dry-run` | Print constructed prompt without calling API |
| `--list-styles` | List preset styles and exit |
| `--list-subjects` | List common icon subjects and exit |
| `--list-providers` | List supported providers and exit |

### `analyze_style.py` — Style Analysis from Example

Uses the configured provider's VLM (vision language model) to analyze an example icon and extract its style.

```bash
# Analyze a local image file (uses ICON_PROVIDER / ICON_VLM_MODEL env)
uv run analyze_style.py path/to/example_icon.png

# Analyze from URL
uv run analyze_style.py https://example.com/icon.png

# Output only the style prompt (for scripting)
uv run analyze_style.py example.png --output-style-only > style.txt

# Use the extracted style to generate matching icons
uv run generate_icon.py -p "growth" --custom-style "$(cat style.txt)"

# Use a specific provider/VLM for analysis
uv run analyze_style.py icon.png --provider qwen --vlm-model qwen-vl-max
```

### `remove_bg.py` — Background Removal

Removes a solid background from an icon to create a transparent PNG.

```bash
# Auto-detect background color
uv run remove_bg.py output/icon.png

# Specify output path
uv run remove_bg.py icon.png --output icon_transparent.png

# Adjust tolerance for better results
uv run remove_bg.py icon.png --tolerance 50

# Force specific background color
uv run remove_bg.py icon.png --bg-color "240,240,240"
```

**Options:**

| Flag | Description |
|------|-------------|
| `--output, -o` | Output path (default: `*_transparent.png`) |
| `--tolerance, -t` | Color distance tolerance 0-100 (default 30, higher = more pixels removed) |
| `--feather, -f` | Edge feather radius in pixels (default 1) |
| `--bg-color` | Force background as `R,G,B` (e.g. `255,255,255`) |

---

## Preset Styles

| Key | Name | Description |
|-----|------|-------------|
| `flat-color` | Flat Color | Solid vibrant colors, no gradients/shadows |
| `line-monochrome` | Line Monochrome | Single-color thin lines, minimalist |
| `line-color` | Line Color | Outlined with accent color fills |
| `3d-render` | 3D Render | Soft shadows, depth, glossy |
| `duotone` | Duotone | Two-tone color scheme |
| `filled-color` | Filled Color | Bold solid filled shapes |
| `isometric` | Isometric | 30-degree angle 3D projection |
| `hand-drawn` | Hand Drawn | Organic, sketch-like quality |
| `gradient` | Gradient | Smooth color gradients, vibrant |
| `minimal-solid` | Minimal Solid | High-contrast solid silhouette |

---

## Environment Variables

| Variable | Description | Default | Source |
|----------|-------------|---------|--------|
| `ICON_PROVIDER` | Provider: `minimax`/`qwen`/`openai`/`openai-compatible` | `minimax` | Shell env or `.env` |
| `ICON_API_KEY` | API key for the selected provider | - | Shell env or `.env` |
| `ICON_API_HOST` | API host / base URL | provider-specific | Shell env or `.env` |
| `ICON_MODEL` | Image generation model name | provider-specific | Shell env or `.env` |
| `ICON_VLM_MODEL` | VLM model name (for `analyze_style.py`) | provider-specific | Shell env or `.env` |
| `MINIMAX_API_KEY` | Legacy alias (used when `ICON_PROVIDER=minimax`) | - | Shell env or `.env` |
| `MINIMAX_API_HOST` | Legacy alias for minimax host | `https://api.minimaxi.com` | Shell env or `.env` |

**Precedence:** CLI flags > shell env > `.env` file > built-in defaults.

---

## Providers

The skill ships with a provider abstraction (`providers.py`) so you can switch
image-generation backends without touching the workflow code.

### Provider overview

| Provider | Default image model | Default VLM | Default host | Notes |
|----------|---------------------|-------------|--------------|-------|
| `minimax` | `image-01` | `MiniMax-M1` | `https://api.minimaxi.com` | Backward compatible with `MINIMAX_API_KEY`. |
| `qwen` | `qwen-image-2.0-pro` | `qwen-vl-max` | `https://dashscope.aliyuncs.com` | Aliyun DashScope. Also supports `qwen-image-plus`, `qwen-image-max`. |
| `openai` | `dall-e-3` | `gpt-4o` | `https://api.openai.com` | OpenAI official. |
| `openai-compatible` | (must set) | (must set) | (must set) | Any OpenAI-compatible gateway. |

### Switching providers

**Via environment variables (persistent):**

```bash
# Switch to Aliyun Qwen
export ICON_PROVIDER=qwen
export ICON_API_KEY=sk-xxxxx                 # from https://bailian.console.aliyun.com/?apiKey=1
# Optional overrides:
# export ICON_MODEL=qwen-image-2.0-pro
# export ICON_VLM_MODEL=qwen-vl-max
```

```bash
# Switch to an OpenAI-compatible gateway (e.g. SiliconFlow)
export ICON_PROVIDER=openai-compatible
export ICON_API_HOST=https://api.siliconflow.cn
export ICON_API_KEY=sk-xxxxx
export ICON_MODEL=Kolors                       # or flux.1-schnell, ...
export ICON_VLM_MODEL=Qwen/Qwen2-VL-72B-Instruct
```

**Via CLI flags (per-run):**

```bash
uv run generate_icon.py -p "growth" -s flat-color \
  --provider qwen --api-key sk-xxxxx --model qwen-image-2.0-pro

uv run generate_icon.py -p "growth" -s flat-color \
  --provider openai-compatible \
  --host https://api.siliconflow.cn \
  --api-key sk-xxxxx --model Kolors
```

### Where to get keys

| Provider | Key URL | Docs |
|----------|---------|------|
| MiniMax | https://platform.minimaxi.com/user-center/basic-information/interface-key | - |
| Qwen (Aliyun DashScope) | https://bailian.console.aliyun.com/?apiKey=1 | https://help.aliyun.com/zh/model-studio/qwen-image-api |
| OpenAI | https://platform.openai.com/api-keys | https://platform.openai.com/docs/api-reference/images |
| SiliconFlow | https://cloud.siliconflow.cn | https://docs.siliconflow.cn |

### Adding a new provider

The provider layer lives in `providers.py`. To add a new backend:

1. Add an entry to `DEFAULT_HOSTS`, `DEFAULT_IMAGE_MODELS`, `DEFAULT_VLM_MODELS`.
2. Implement a `_gen_<name>()` function following the existing pattern (returns `list[ImageResult]`).
3. (Optional) Implement a `_vlm_<name>()` function for `analyze_style.py`.
4. Add the name to `SUPPORTED_PROVIDERS` and the dispatch in `generate_images()` / `vlm_analyze()`.

The `openai-compatible` provider already covers any backend that speaks the
OpenAI Images API (`POST /v1/images/generations`) and Chat Completions API
(`POST /v1/chat/completions`), so most third-party gateways work without custom code.

---

## Pricing

- **0.025 CNY per image** (~0.0035 USD)
- Generating 9 icons costs ~0.225 CNY
- See https://platform.minimaxi.com/docs/guides/pricing-paygo for details

---

## How It Works

1. `generate_icon.py` constructs a prompt from the user's subject + style template
2. `providers.py` dispatches to the configured backend:
   - `minimax` → `POST {host}/v1/image_generation` with model `image-01`
   - `qwen` → `POST {host}/api/v1/services/aigc/multimodal-generation/generation`
   - `openai` / `openai-compatible` → `POST {host}/v1/images/generations`
3. Decodes the base64 / downloads the URL response and saves as PNG
4. (Optional) `remove_bg.py` post-processes to create transparent background
5. (Optional) `analyze_style.py` uses the configured VLM to learn style from example icons

---

## File Structure

```
create_icon/
├── SKILL.md           # Skill definition for agent integration
├── generate_icon.py   # Main icon generation script (PEP 723)
├── analyze_style.py   # Style analysis from example image (PEP 723)
├── providers.py       # Multi-provider abstraction (image gen + VLM)
├── remove_bg.py       # Background removal utility (PEP 723)
├── styles.json        # Preset style templates
├── README.md          # This file
├── .env.example       # Environment variable template
├── .gitignore         # Excludes .env and output/ from version control
└── output/            # Generated icons (auto-created, gitignored)
```
