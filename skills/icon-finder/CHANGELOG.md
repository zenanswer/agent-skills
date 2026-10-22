# Changelog

## 0.2.0

### Fixed

- **Iconify fetches always 404'd.** The URL builder used the
  `logos:aws.svg` form; the API serves `logos/aws.svg`. Every colored official
  logo failed. Previews and fetches now use the slash form (old `:` refs in
  `fetch_icon.py` are still accepted).
- **PNGs were stretched to a square.** Rendering asked for
  `output_width=size, output_height=size`, which scales x and y independently:
  the 256×153 AWS wordmark came out 512×512 (1.67× vertical stretch). Rendering
  now fits inside the box and the aspect ratio is preserved.
- **`mono` recolor missed most SVGs.** Regex replacement of `fill="..."` ignored
  inline `style`, `currentColor`, `stroke` and gradients. Recolor is now an
  injected stylesheet with `!important`, keeping `fill="none"` intact.
- **Simple Icons CDN 404s** for trademark-excluded brands (AWS, Azure, ...) now
  fall back to the jsDelivr source files, which do serve them.
- **Non-deterministic result order** from `as_completed` collection; ranking is
  now explicitly sorted by (score, color-first, source priority, title).

### Added

- `svgl` source (~670 curated SVGs with native light/dark and wordmark
  variants) and `lobe-icons` (~976 AI/tech brands).
- Geometry normalization: trim → 8% padding → centered square canvas →
  **1024 + 512** output. A set of logos now shares one visual weight.
- `--variant dark|light|mono|wordmark`, with native variants preferred over
  recoloring, and variant suffixes (`_dark`, `_mono`).
- Contact sheets (`--sheet`) for candidates and for fetched results.
- Batch fetching, merged `logos.json` manifests, `--json` output.
- On-disk index cache (`~/.cache/icon-finder`) with stale fallback for offline
  runs.
- Pure-pip rendering via `resvg-py`; `cairosvg` / `rsvg-convert` remain as
  fallbacks. No more mandatory `brew install cairo`.
- `tests/smoke.py` (32 offline assertions).

### Changed

- Scripts are PEP 723 (`uv run scripts/...`), matching `create-icon`. Manual
  venv setup is no longer required.
- Bare refs (`fetch_icon.py aws`) auto-resolve through search instead of
  assuming Simple Icons.
- `--size` is now a single-size shorthand; `--sizes` lists multiple sizes
  (default `1024,512`).
- SKILL.md rewritten around a no-question default path and a confidence rule.

## 0.1.0

- Initial release: Iconify + Simple Icons search, SVG + PNG rendering,
  color/mono styles, abbreviation expansion.