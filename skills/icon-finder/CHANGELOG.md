# Changelog

## 0.3.0

### Added

- **`--mode ui` for concept icons.** Searches a curated set of Iconify UI
  collections (default: Material Symbols, MDI, Tabler, Lucide, Phosphor,
  Font Awesome) with one API call, then normalizes and licenses the results like
  any other asset.
- `scripts/logokit/collections.json`: 30+ curated sets with name, author,
  license, license URL and `attribution_required`. Brand collections are
  included for reference; UI mode searches the UI/emoji ones.
- `scripts/logokit/concepts.json`: ~100 English + Chinese deck concepts mapped to
  icon names, because Iconify search matches names, not meaning. `cost saving` →
  `piggy-bank`/`wallet`/`coins`; `风险` → `alert-triangle`/`shield-alert`.
- **License metadata on every candidate and manifest entry**:
  `collection`, `collection_name`, `license`, `license_url`,
  `attribution_required`.
- `fetch_icon.py --credits CREDITS.md`: grouped attribution table plus an
  "Attribution required" section for CC BY / BY-SA sets.
- `search_icons.py --license permissive|attribution|no-sharealike` filter.
- `--collection all-open` (29 license-clear sets, ~140k icons) and `all`.
- `also_in` on UI results: other sets that ship the same icon family.
- `references/icon-sources.md`: license audit of the popular "30 free icon sites"
  list, with per-site verdicts and the reason each is or is not automated.

### Changed

- Iconify search now sends `prefixes` (comma-separated) for multiple
  collections; the previous code only supported `prefix` (one collection).
- UI results deduplicate one row per concept family: `rocket`, `rocket-outline`,
  `rocket-rounded` collapse; `shield-alert` and `wallet-off` stay distinct.
- UI icons default to mono with `#111111` when no brand color exists.
- `fetch_icon.py --mode ui` accepts bare names (`--mode ui rocket`).
- Manifest includes `mode` and the resolved `collections` list.

### Fixed

- `datetime.UTC` (Python 3.11+) had been introduced by the formatter although the
  scripts declare `requires-python >= 3.10`; reverted to `timezone.utc`.

## 0.2.0

### Fixed

- **Iconify fetches always 404'd.** The URL builder used the
  `logos:aws.svg` form; the API serves `logos/aws.svg`. Every colored official
  logo failed.
- **PNGs were stretched to a square.** Rendering asked for
  `output_width=size, output_height=size`, which scales x and y independently:
  the 256×153 AWS wordmark came out 512×512 (1.67× vertical stretch).
- **`mono` recolor missed most SVGs.** Regex replacement of `fill="..."` ignored
  inline `style`, `currentColor`, `stroke` and gradients. Recolor is now an
  injected stylesheet with `!important`, keeping `fill="none"` intact.
- **Simple Icons CDN 404s** for trademark-excluded brands (AWS, Azure, ...) now
  fall back to jsDelivr source files.
- **Non-deterministic result order** from `as_completed`; ranking is explicitly
  sorted by (score, color-first, source priority, title).

### Added

- `svgl` (~670 curated SVGs, native light/dark + wordmarks) and `lobe-icons`
  (~976 AI/tech brands).
- Geometry normalization: trim → 8% padding → centered square → **1024 + 512**.
- `--variant dark|light|mono|wordmark`, preferring native variants.
- Contact sheets (`--sheet`), batch fetching, merged `logos.json`, `--json`.
- On-disk index cache with stale fallback for offline runs.
- Pure-pip rendering via `resvg-py`; `cairosvg` / `rsvg-convert` remain fallbacks.
- `tests/smoke.py`.

### Changed

- Scripts are PEP 723 (`uv run scripts/...`); no venv setup.
- Bare refs (`fetch_icon.py aws`) auto-resolve through search.
- `--size` is a single-size shorthand; `--sizes` lists multiple sizes.

## 0.1.0

- Initial release: Iconify + Simple Icons search, SVG + PNG rendering,
  color/mono styles, abbreviation expansion.