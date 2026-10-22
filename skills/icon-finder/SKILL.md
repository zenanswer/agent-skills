---
name: icon-finder
description: "Search and fetch brand/technology logos and icons (open-source software, cloud services, tech companies) for use in presentations, documents, and web pages. Use this skill whenever the user needs to find, download, or render logos/icons/brand marks for things like AWS, Kubernetes, React, Azure, Docker, Google Cloud, GitHub, etc. Trigger on phrases like 'find logo', 'get icon', 'search brand icon', 'need the AWS logo', 'download Kubernetes logo', 'logo for my slides/ppt/deck', or any request involving brand/technology logos and icons. Also trigger when a user mentions preparing logos for a pptx/presentation alongside the pptx skill."
---

# Icon Finder

Search and fetch brand/technology logos across multiple icon sources, rendering both SVG (vector) and PNG (raster, transparent background) so they can be dropped directly into presentations.

## When to use

- User asks for a logo/icon for a brand, open-source project, or cloud service.
- User is building a slide deck (often alongside the `pptx` skill) and needs tech/cloud logos.
- User wants to render an icon in a specific color or size.

## Quick Reference

| Task | Command |
|------|---------|
| Search icons by keyword | `python scripts/search_icons.py "<query>" [--style color\|mono]` |
| Fetch one icon (SVG+PNG) | `python scripts/fetch_icon.py <source:slug> [--out DIR] [--size 512] [--style color\|mono] [--color HEX]` |

Run scripts with the project venv Python if dependencies are installed there (e.g. `./../../.venv/bin/python`). Install deps first if missing: see `scripts/requirements.txt`.

## Default behavior (when user gives no specifics)

- **Style**: color-first. Fetch the official colored logo (Iconify `logos` collection). Fall back to Simple Icons brand-color rendering if no colored version exists.
  - Switch to monochrome when the user says "单色", "monochrome", "mono", "统一颜色", or requests a single specific color.
- **Output format**: BOTH `.svg` and `.png` (transparent background) for every icon.
- **Output directory**: `./logos/` (created if missing). The user may override with `--out`.
- **PNG size**: 512px on the long edge. Override with `--size`.
- **Naming**: lowercase, hyphenated slug (e.g. `amazon-web-services.png`).

## Workflow

### 1. Understand the request

Parse from the user's message:
- The brand(s)/technology name(s) wanted (may be multiple: "AWS, K8s, and React").
- Style preference (default: color). Watch for "单色/mono/uniform color".
- Output directory (default: `./logos/`).
- Size if specified.

### 2. Search

Run the search script for each requested brand. Show the user the candidates so they can pick the right one (brand names can be ambiguous, e.g. "Amazon" the company vs "Amazon Web Services").

```bash
python scripts/search_icons.py "aws"
```

Output is JSON: a list of candidates with `source`, `id` (the slug used for fetching), `title`, `is_color`, `brand_color`, and `preview_url`. Candidates from Iconify `logos` (colored, official) are listed first; Simple Icons (monochrome+brand color) next.

The search script auto-expands common abbreviations (k8s -> kubernetes, tf -> terraform, gcp -> google cloud, etc.) and prints the expansion to stderr.

### If search returns no results

When `search_icons.py` outputs an empty array `[]` and exits with code 1, it also prints suggestions to stderr. Relay these to the user and try alternatives:

1. **Try a different name or spelling** -- e.g. "elastic stack" -> "elasticsearch", "MS SQL" -> "microsoft sql server".
2. **Try a shorter keyword** -- partial matches work, so "elastic" finds Elasticsearch-related logos.
3. **Try the full brand name** -- "amazon web services" instead of "aws".

If repeated attempts still return nothing, the brand is likely not in any free icon collection. Tell the user honestly -- they may need to provide an official SVG file manually.

### 3. Confirm with the user

Present candidates concisely, e.g.:
```
Found 4 candidates for "aws":
1. [color]    AWS          (iconify:logos:aws)        ← official colored logo
2. [color]    AWS Lambda   (iconify:logos:aws-lambda)
3. [mono]     Amazon Web Services (simpleicons:amazonwebservices)  brand color #FF9900
4. [color]    Amazon       (iconify:logos:amazon)
```
Default-recommend the colored exact match (candidate 1). Ask the user to confirm or pick alternatives.

### 4. Fetch and render

```bash
python scripts/fetch_icon.py "iconify:logos:aws" --out ./logos --size 512 --style color
```

This writes both `aws.svg` and `aws.png` (transparent background) to the output directory. For monochrome style, the PNG is rendered with the brand color (or a user-specified `--color`).

### 5. Hand off

Report the absolute paths of the generated files. If the user is working with the `pptx` skill, point out that the PNG paths can be inserted as images in slides.

## Style details

- **color** (default): Use Iconify `logos` collection (already multi-color official logos). If only a Simple Icons (monochrome) result exists, render the PNG filled with the brand's official hex color so it still looks branded, not black.
- **mono**: Render everything as a single color. Default to the brand color; let the user override with `--color`. Useful when the user wants a uniform look across many logos (e.g. all white on a dark slide). For colored source SVGs, convert to a single fill.

## Output format details

- **SVG**: the original vector file (recolor as needed). Good for scalable embedding.
- **PNG**: transparent background, rendered at the requested size via `cairosvg`. Best for direct PPT image insertion.
Both are always produced unless the user asks for only one.

## Proxy

If the user is behind a proxy (common in corporate networks), set the `HTTPS_PROXY` / `HTTP_PROXY` environment variables before running the scripts:
```bash
export HTTPS_PROXY=http://your-proxy-host:port
```
When a proxy is active, scripts print `[info] Using proxy: ...` to stderr. If the user reports network errors (timeouts, connection refused), check whether they need a proxy.

## Dependencies

The scripts need Python packages from `scripts/requirements.txt`:
```
requests
cairosvg
Pillow
```
`cairosvg` requires the system `cairo` library (`brew install cairo` on macOS). The skill's fetch script auto-detects available renderers (cairosvg -> rsvg-convert -> error with install instructions) so it degrades gracefully.

Use a virtualenv if the system Python is externally-managed (PEP 668). The project venv at `.venv/` is used if present.

## Icon sources

| Source | Type | Auth | Notes |
|--------|------|------|-------|
| Iconify (`logos` collection) | Colored official logos | none | ~1900 brand logos, CC0 |
| Simple Icons | Monochrome + brand hex | none | ~3400 brands, single-color SVG with official color |
