#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pillow>=10.0",
# ]
# ///
"""Quality gate for generated icons.

Catches the failure modes that make an icon look wrong in a deck:
empty renders, artwork touching the canvas edge, off-center content, a subject
that is too small/large, and white halos left by background removal.

Usage:
    uv run check.py icon.png
    uv run check.py icon.png --transparent --json
    uv run check.py ./output/*.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import normalize

DEFAULT_CENTER_TOLERANCE = 0.03  # 3% of canvas edge
DEFAULT_COVERAGE_RANGE = (0.05, 0.95)
DEFAULT_HALO_LIMIT = 0.25  # share of semi-transparent pixels


def inspect(
    path: str | Path,
    *,
    expect_transparent: bool | None = None,
    padding: float = normalize.DEFAULT_PADDING,
    coverage_range: tuple[float, float] = DEFAULT_COVERAGE_RANGE,
) -> dict:
    im = normalize.load(path)
    bg = None if expect_transparent else normalize.bg_from_corners(im)
    stats = normalize.content_stats(im, bg=bg)
    issues: list[str] = []

    if stats["empty"]:
        issues.append("empty: no visible artwork")
    else:
        if stats["touches_border"]:
            issues.append(
                "touches_border: artwork reaches the canvas edge (not normalized?)"
            )
        tolerance = max(4, round(im.size[0] * DEFAULT_CENTER_TOLERANCE))
        if (
            abs(stats["center_offset_x"]) > tolerance
            or abs(stats["center_offset_y"]) > tolerance
        ):
            issues.append(
                f"off_center: offset ({stats['center_offset_x']}, {stats['center_offset_y']}) "
                f"exceeds {tolerance}px"
            )
        expected = round(1 - 2 * padding, 2)
        if stats["long_edge_ratio"] and abs(stats["long_edge_ratio"] - expected) > 0.08:
            issues.append(
                f"padding: content long edge is {stats['long_edge_ratio']:.0%} of the canvas, "
                f"expected ~{expected:.0%}"
            )
        if not (coverage_range[0] <= stats["coverage"] <= coverage_range[1]):
            issues.append(
                f"coverage: {stats['coverage']:.0%} outside "
                f"{coverage_range[0]:.0%}-{coverage_range[1]:.0%}"
            )

    if expect_transparent:
        alpha = im.getchannel("A")
        if alpha.histogram()[0] == 0:
            issues.append("not_transparent: no transparent pixels found")
        elif stats["partial_alpha_ratio"] > DEFAULT_HALO_LIMIT:
            issues.append(
                f"halo: {stats['partial_alpha_ratio']:.0%} semi-transparent pixels "
                f"(possible background fringe)"
            )

    return {
        "path": str(Path(path).resolve()),
        "ok": not issues,
        "issues": issues,
        "stats": stats,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check generated icons for common defects."
    )
    ap.add_argument("images", nargs="+", help="Icon PNGs to inspect")
    ap.add_argument(
        "--transparent",
        action="store_true",
        help="Require transparency and check for halo",
    )
    ap.add_argument("--padding", type=float, default=normalize.DEFAULT_PADDING)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    reports = []
    for path in args.images:
        try:
            reports.append(
                inspect(
                    path,
                    expect_transparent=True if args.transparent else None,
                    padding=args.padding,
                )
            )
        except Exception as exc:  # noqa: BLE001
            reports.append(
                {
                    "path": str(path),
                    "ok": False,
                    "issues": [f"error: {exc}"],
                    "stats": {},
                }
            )

    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        for rep in reports:
            mark = "OK  " if rep["ok"] else "WARN"
            print(f"[{mark}] {rep['path']}")
            for issue in rep["issues"]:
                print(f"       - {issue}")

    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
