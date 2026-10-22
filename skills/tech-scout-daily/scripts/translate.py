#!/usr/bin/env python3
"""
Tech Scout Daily Translator
Adds Chinese translations to the scraped JSON data.
"""

import argparse
import json
import sys
import time

try:
    from deep_translator import GoogleTranslator
except ImportError:
    print("ERROR: 'deep-translator' is required. Install with: pip install deep-translator", file=sys.stderr)
    sys.exit(1)


def _translate(text: str, max_retries: int = 3) -> str:
    """Translate English text to Simplified Chinese with retry."""
    if not text or not text.strip():
        return ""

    text = text.strip()
    # Google Translate has a 5000 character limit per request
    if len(text) > 4800:
        text = text[:4800]

    for attempt in range(max_retries):
        try:
            result = GoogleTranslator(source="en", target="zh-CN").translate(text)
            return result or ""
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                print(f"  [WARN] Translation failed: {e}", file=sys.stderr)
                return ""


def translate_json(input_path: str, output_path: str, fields: list[str] = None, max_items: int = None):
    """Add Chinese translations to the JSON file."""
    if fields is None:
        fields = ["title", "summary"]

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    if max_items:
        items = items[:max_items]
    total = len(items)

    print(f"Translating {total} items to Chinese...", file=sys.stderr)

    # Collect all (idx, field, text) to translate
    tasks = []
    for idx, item in enumerate(items):
        for field in fields:
            en_text = item.get(field, "")
            if not en_text:
                continue
            zh_field = f"{field}_zh"
            if item.get(zh_field):
                continue
            tasks.append((idx, field, en_text))

    print(f"  {len(tasks)} fields to translate", file=sys.stderr)

    for i, (idx, field, en_text) in enumerate(tasks):
        zh_text = _translate(en_text)
        if zh_text:
            items[idx][f"{field}_zh"] = zh_text

        if (i + 1) % 20 == 0 or i == len(tasks) - 1:
            print(f"  [{i+1}/{len(tasks)}] translated", file=sys.stderr)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Done. {total} items processed. Output: {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Tech Scout Daily Translator")
    parser.add_argument("--input", required=True, help="Input JSON file from scraper")
    parser.add_argument("--output", required=True, help="Output JSON file with translations")
    parser.add_argument("--fields", default="title,summary", help="Comma-separated fields to translate")
    args = parser.parse_args()

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    translate_json(args.input, args.output, fields)


if __name__ == "__main__":
    main()