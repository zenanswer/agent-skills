# Icon sources: license audit

Reference for why icon-finder only automates a subset of "free icon sites".
Written after auditing the 30-site list in
`cn.eagle.cool/blog/post/30-best-websites-for-free-icons-download-and-usage-guide-2021`
(checked 2026-10; that article dates from 2021 and several license descriptions
are wrong).

## Criteria for automation

A source is only usable in a batch pipeline when **all** of these hold:

1. A license that permits commercial use (and, ideally, redistribution in a deck).
2. A machine-readable index or stable URL scheme (API preferred).
3. Per-item license is not variable - otherwise no automated compliance.
4. No watermark, no account/login requirement, no per-download payment.

## Verdicts

### Open license / genuinely open source (5)

| Site | Actual license | Attribution | Already in icon-finder |
|---|---|---|---|
| Google Fonts Icons (Material Symbols) | Apache-2.0 | no | `material-symbols` (Iconify) |
| Font Awesome Free | icons CC BY 4.0, fonts OFL 1.1, code MIT | **yes** | `fa6-solid` / `fa6-regular` / `fa6-brands` |
| Boxicons | icons CC BY 4.0, fonts OFL 1.1, other files MIT | **yes** | `bx` / `bxs` / `bxl` |
| Feather | MIT | no | `feather` |
| Streamline (free subset only) | CC BY 4.0 | **yes** | `streamline` (3,000 icons) |

Notes:

- Boxicons' own README says "attribution is not required but is appreciated",
  which contradicts CC BY 4.0. Iconify labels the collection MIT. We treat it as
  **attribution required** - the conservative reading.
- Feather is MIT; the blog's "需要注明出处" is incorrect.
- Streamline's site is freemium; only the free subset (CC BY 4.0) is on Iconify.

### Free for commercial use, but not open source (3)

| Site | License shape | Why it is not automated |
|---|---|---|
| iconmonstr | custom: commercial OK, no attribution, **no redistribution** | no API, HTML scraping only; style overlaps Lucide/Tabler |
| UXWing | custom: commercial OK, no attribution, no resale of originals | no API; quality varies |
| IconStore | per-pack custom: commercial OK, **cannot redistribute packs** | pack-based, not per-icon searchable |

### Freemium / paid API / personal-only (11)

| Site | Reason |
|---|---|
| Iconfinder | free + paid mix; API is a paid subscription |
| Flaticon | attribution required on free, commercial needs a plan; API paid |
| Freepik | same as Flaticon |
| Icons8 | attribution on free, API paid, no resale |
| Noun Project | attribution on free; API pay-per-use, $25/month minimum |
| Squid Ink | 50 free icons, then paid |
| Iconshock | personal use only |
| Pngtree | watermarks / subscription / attribution |
| SoftIcons | personal free; per-icon commercial license |
| Iconfactory | personal projects only |
| VeryIcon | non-commercial only |

### Aggregators, communities, tools, dead (11)

| Site | Reason |
|---|---|
| FindIcons | aggregator, per-icon licenses |
| IconArchive | aggregator, mixed CC |
| 1001FreeDownloads | aggregator |
| GraphicBurger | freebie blog (unreachable at audit time) |
| Premium Pixels | freebie blog |
| Freebiesbug | freebie aggregator |
| Dribbble | community shots, per-author terms |
| DeviantArt | community, per-author terms, partly login-only |
| IcoMoon | builder tool; per-set licenses vary (some GPL) |
| Fontello | packaging tool for FA/Entypo, not a source |
| Oxygenna | site unreachable |

Eagle App (linked at the top of that article) is an asset manager, not an icon
source.

## What icon-finder does instead

`--mode ui` searches a curated set of Iconify collections in one API. As of the
audit that is ~29 license-clear sets and roughly 140,000 icons, including every
open set from the list above plus:

`lucide` (ISC), `tabler` (MIT), `ph` (MIT), `heroicons` (MIT), `solar`
(CC BY 4.0), `carbon` (Apache-2.0), `fluent` (MIT), `icon-park` (Apache-2.0),
`hugeicons` (MIT), `mingcute` (Apache-2.0), `gravity-ui` (MIT), `octicon` (MIT),
`codicon` (CC BY 4.0), `devicon` (MIT), `skill-icons` (MIT), `noto`
(Apache-2.0), `twemoji` (CC BY 4.0), `openmoji` (CC BY-SA 4.0), `arcticons`
(CC BY-SA 4.0).

License metadata lives in `scripts/logokit/collections.json`; `fetch_icon.py
--credits CREDITS.md` writes the attribution file required by the CC BY sets.

## Re-auditing

Licenses change. When adding a collection:

1. Read the upstream LICENSE/README, not a blog post.
2. Prefer the stricter interpretation when sources disagree.
3. Add it to `collections.json` with `license`, `license_url` and
   `attribution_required`.
4. Run `uv run tests/smoke.py` - it asserts that the attribution flag matches
   the SPDX id.