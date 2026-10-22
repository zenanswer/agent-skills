# Changelog

## 0.2.0

### Fixed

- **Prompts were a concatenation, not a design.** Clauses repeated
  (`centered composition` twice), Chinese subjects got an English article
  (`a AI 算力`), and providers that support a negative prompt never received
  one. Prompts are now compiled from four explicit blocks with per-style
  negatives.
- **Icons were never normalized.** Different margins and visual weights meant a
  set looked inconsistent in a deck. Every icon is now trimmed, scaled to an 84%
  content box with 8% padding per side, centered and exported at 1024 + 512.
- **Background removal punched holes in the artwork.** A global color key also
  erased interior whites (gear holes, cloud fills). Removal now flood-fills from
  the border, keeps interior whites, softens the alpha edge and de-fringes
  against the sampled background color.
- **`--transparent` re-entered `uv run` once per image** through `os.system`,
  adding seconds and swallowing failures. Background removal is now an
  in-process call.
- **`dall-e-3` with `-n > 1`** failed because the model only accepts one image
  per request; the provider now loops. `gpt-image-1` no longer receives
  `response_format` (which it rejects) and does receive
  `background=transparent`.
- **Non-ASCII subjects could collide on output names.** Slugging is
  Unicode-aware with a fallback, and duplicate bases get `-2` suffixes.

### Added

- `ark` provider (Volcengine Seedream 5.0), `qwen-image-3.0-pro` as the new
  Qwen default, and `gpt-image-1` support with native transparency.
- Retries with exponential backoff for 429/5xx, plus timeouts handled
  consistently; `--concurrency` for multi-subject runs.
- `--set` consistency mode: shared style, palette and seed family, plus an
  `icons.json` manifest.
- `--palette` fixed colors and `--estimate-cost` before spending.
- `check.py` quality gate and `--ensure-quality` auto-retry.
- `remove_bg.py` modes (`auto` / `flood` / `chroma` / `keep`) and JSON info.
- `analyze_style.py`: multi-image input, JSON output, and a **measured** palette
  via Pillow quantization instead of VLM-guessed hex codes.
- Six new style presets (flat-2.0, duotone-line, clay-3d, glass,
  isometric-2.5d, notion) and per-style negatives; old keys unchanged.
- `tests/smoke.py`: 49 offline assertions including a mock-provider e2e run.

### Changed

- Scripts declare `pillow` and `requests` via PEP 723; still `uv run`.
- `--sizes` defaults to `1024,512`; `--padding` defaults to `0.08`.
- Output filenames are `<subject>.png` / `<subject>@512.png`.
- SKILL.md rewritten around a default path that generates first and only asks
  when the style genuinely matters.

## 0.1.0

- Initial release: MiniMax / Qwen / OpenAI / compatible providers, preset
  styles, style analysis, background removal.