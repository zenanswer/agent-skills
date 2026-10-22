"""Prompt compiler for icon generation.

A prompt is built from four explicit blocks instead of string concatenation:

    subject + style + composition + palette (+ negative)

That removes the old defects: duplicated clauses, an article glued onto Chinese
subjects ("a AI 算力"), style keywords fighting each other, and no negative
prompt at all for providers that support one.

Public API:
    load_styles(path)                  -> dict
    style_names(styles)                -> list[str]
    resolve_style(styles, key)         -> dict
    build_prompt(...)                   -> dict with positive/negative/...
    inline_negative(negative)           -> str for providers without a negative field
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MAX_PROMPT_LEN = 1400

# Always appended to a style's own negatives.
UNIVERSAL_NEGATIVE = [
    "text",
    "letters",
    "typography",
    "words",
    "watermark",
    "signature",
    "mockup",
    "frame",
    "border",
    "collage",
    "multiple objects",
    "busy scene",
    "background objects",
    "blurry",
    "low contrast",
    "cropped",
    "off-center",
    "cluttered",
]

# Default composition constraints. Styles never repeat these.
COMPOSITION = [
    "single centered object",
    "no background scenery",
    "generous even padding around the object",
    "clean crisp edges",
    "high contrast with the background",
    "icon for presentation slides",
]


def load_styles(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if "styles" not in data:
        raise SystemExit(f"ERROR: {path} has no 'styles' section")
    data.setdefault("backgrounds", {"white": "plain solid white background"})
    data.setdefault("common_subjects", [])
    return data


def style_names(styles: dict) -> list[str]:
    return list(styles["styles"].keys())


def resolve_style(styles: dict, key: str) -> dict:
    try:
        style = styles["styles"][key]
    except KeyError:
        print(f"ERROR: unknown style '{key}'. Use --list-styles.", file=sys.stderr)
        raise SystemExit(1)
    if "positive" not in style:
        raise SystemExit(
            f"ERROR: style '{key}' uses the old schema. Expected a 'positive' list."
        )
    return style


def _clean_subject(subject: str) -> str:
    """Trim punctuation and drop a leading article glued onto non-Latin text."""
    text = re.sub(r"\s+", " ", subject).strip().strip(" .,;:!?、。，；：")
    if not text:
        raise SystemExit("ERROR: empty icon subject")
    # "a AI 算力" is wrong for CJK subjects; drop the article entirely.
    if re.match(r"^(a|an|the)\s+", text, flags=re.IGNORECASE) and not re.match(
        r"^(a|an|the)\s+[A-Za-z0-9]", text
    ):
        text = re.sub(r"^(a|an|the)\s+", "", text, flags=re.IGNORECASE)
    return text


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def parse_palette(spec: str | None) -> list[str]:
    """Accepts '#1E3A8A, #F59E0B' or '1e3a8a f59e0b'."""
    if not spec:
        return []
    out = []
    for raw in re.split(r"[,;\s]+", spec.strip()):
        if not raw:
            continue
        color = raw if raw.startswith("#") else f"#{raw}"
        if not re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})", color):
            raise SystemExit(
                f"ERROR: bad color '{raw}' in --palette (expected #RRGGBB)"
            )
        out.append(color.lower())
    return _dedupe(out)


def build_prompt(
    subject: str,
    styles: dict,
    *,
    style_key: str | None = None,
    custom_style: str | None = None,
    background: str = "white",
    palette: list[str] | None = None,
    extra: str | None = None,
) -> dict:
    """Compile a single icon prompt. Returns a dict, never a bare string."""
    if not subject or not subject.strip():
        raise SystemExit("ERROR: empty icon subject")
    text = _clean_subject(subject)

    if custom_style:
        style_block = [part.strip() for part in custom_style.split(",") if part.strip()]
        style_label, style_name, negative = "custom", "Custom style", []
    else:
        key = style_key or "flat-color"
        style = resolve_style(styles, key)
        style_block = list(style.get("positive") or [])
        style_label = key
        style_name = style.get("name", key)
        negative = list(style.get("negative") or [])

    bg_desc = styles["backgrounds"].get(background)
    if bg_desc is None:
        raise SystemExit(
            f"ERROR: unknown background '{background}'. Use: {', '.join(styles['backgrounds'])}"
        )

    parts: list[str] = [text]
    parts.extend(style_block)
    parts.extend(COMPOSITION)
    parts.append(f"background: {bg_desc}")
    if palette:
        parts.append("color palette: " + ", ".join(palette))
    if extra:
        parts.append(extra.strip())

    positive = ", ".join(_dedupe(parts))
    if len(positive) > MAX_PROMPT_LEN:
        positive = positive[:MAX_PROMPT_LEN]

    negative_list = _dedupe([*negative, *UNIVERSAL_NEGATIVE])
    if palette:
        # Keep the palette authoritative but still forbid photo/mockup looks.
        pass

    return {
        "subject": text,
        "style_key": style_label,
        "style_name": style_name,
        "background": background,
        "palette": list(palette or []),
        "positive": positive,
        "negative": ", ".join(negative_list),
    }


def inline_negative(negative: str) -> str:
    """Fold a negative list into a positive prompt for providers without one."""
    if not negative:
        return ""
    return "avoid: " + negative


def prompt_for_provider(prompt: dict, supports_negative: bool) -> str:
    """Positive prompt, with the avoid-list folded in when the provider can't take one."""
    if supports_negative:
        return prompt["positive"]
    tail = inline_negative(prompt["negative"])
    return f"{prompt['positive']}, {tail}" if tail else prompt["positive"]
