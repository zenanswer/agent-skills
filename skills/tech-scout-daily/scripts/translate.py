#!/usr/bin/env python3
"""
Tech Scout Daily Translator
Adds Chinese translations to the scraped JSON data.
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

try:
    from deep_translator import GoogleTranslator
except ImportError:
    print(
        "ERROR: 'deep-translator' is required. Install with: pip install deep-translator",
        file=sys.stderr,
    )
    sys.exit(1)

from llm_common import LLM_MODEL, chat, extract_json_array, llm_available


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
                wait = 0.5 * (attempt + 1)
                if "too many requests" in str(e).lower():
                    wait = 2.0 * (attempt + 1)
                time.sleep(wait)
            else:
                print(f"  [WARN] Translation failed: {e}", file=sys.stderr)
                return ""


# ── 可选 LLM 翻译（配置与评分共用 llm_common；比 Google 快且质量更好） ──
TRANSLATE_MODEL = os.environ.get("TRANSLATE_LLM_MODEL") or LLM_MODEL
LLM_BATCH = int(os.environ.get("TECH_SCOUT_LLM_BATCH", "12"))


def _llm_translate_batch(batch: list[dict], fields: list[str]) -> list[dict]:
    payload_items = [
        {"i": row["i"], **{f: row["text"].get(f, "") for f in fields}} for row in batch
    ]
    prompt = (
        "Translate the following JSON items to Simplified Chinese. Keep product names, "
        "paper titles' technical terms and proper nouns accurate; do not summarize or add "
        "content. Return ONLY a JSON array with the same length and the same keys, e.g. "
        '[{"i":0,"title":"...","summary":"..."}].\n\n'
        + json.dumps(payload_items, ensure_ascii=False)
    )
    content = chat(prompt, TRANSLATE_MODEL, max_tokens=8192, timeout=120)
    return extract_json_array(content)


def _translate_with_llm(items: list[dict], fields: list[str]) -> int:
    """返回成功翻译的字段数；失败返回 0。"""
    rows = []
    for idx, item in enumerate(items):
        text = {f: item.get(f, "") for f in fields if item.get(f)}
        if text:
            rows.append({"i": idx, "text": text})
    if not rows:
        return 0

    print(f"  LLM 翻译（{TRANSLATE_MODEL}，batch={LLM_BATCH}）…", file=sys.stderr)
    done = 0
    for start in range(0, len(rows), LLM_BATCH):
        chunk = rows[start : start + LLM_BATCH]
        try:
            # 单批失败先重试一次：LLM 端点偶发 5xx 时，直接回退 Google 会撞 429 限流
            for attempt in range(2):
                try:
                    translated = _llm_translate_batch(chunk, fields)
                    break
                except Exception:
                    if attempt:
                        raise
                    time.sleep(2)
        except Exception as exc:
            print(f"  [WARN] LLM 翻译失败（{exc}），该批回退 Google", file=sys.stderr)
            for row in chunk:
                for field in fields:
                    zh = _translate(row["text"].get(field, ""))
                    if zh:
                        items[row["i"]][f"{field}_zh"] = zh
                        done += 1
            continue
        for row in translated:
            try:
                idx = int(row.get("i"))
            except (TypeError, ValueError):
                continue
            for field in fields:
                value = str(row.get(field, "") or "").strip()
                if value:
                    items[idx][f"{field}_zh"] = value
                    done += 1
        print(
            f"  [{min(start + LLM_BATCH, len(rows))}/{len(rows)}] LLM translated",
            file=sys.stderr,
        )
    return done


_MIN_INTERVAL = float(os.environ.get("TECH_SCOUT_TRANSLATE_INTERVAL", "1.0"))
_RATE_LOCK = threading.Lock()
_LAST_CALL = [0.0]


def _translate_limited(text: str) -> str:
    """Google 免费接口限速 5 req/s：串行化调用起点，避免 429。"""
    with _RATE_LOCK:
        wait = _MIN_INTERVAL - (time.time() - _LAST_CALL[0])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL[0] = time.time()
    return _translate(text)


def translate_json(
    input_path: str,
    output_path: str,
    fields: list[str] = None,
    max_items: int = None,
    jobs: int = 8,
    translator: str = "auto",
):
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

    use_llm = translator == "llm" or (translator == "auto" and llm_available())
    if use_llm:
        done = _translate_with_llm(items, fields)
        if done:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(
                f"Done. {total} items, {done} fields translated (LLM). Output: {output_path}",
                file=sys.stderr,
            )
            return
        print("  [WARN] LLM 翻译无结果，回退 Google", file=sys.stderr)

    # 去重后并行翻译：同一段文本只请求一次
    unique_texts = sorted({text for _, _, text in tasks})
    translated: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for i, (text, zh) in enumerate(
            zip(unique_texts, pool.map(_translate_limited, unique_texts)), 1
        ):
            if zh:
                translated[text] = zh
            if i % 20 == 0 or i == len(unique_texts):
                print(f"  [{i}/{len(unique_texts)}] translated", file=sys.stderr)

    for idx, field, en_text in tasks:
        zh_text = translated.get(en_text, "")
        if zh_text:
            items[idx][f"{field}_zh"] = zh_text

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Done. {total} items processed. Output: {output_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Tech Scout Daily Translator")
    parser.add_argument("--input", required=True, help="Input JSON file from scraper")
    parser.add_argument(
        "--output", required=True, help="Output JSON file with translations"
    )
    parser.add_argument(
        "--fields", default="title,summary", help="Comma-separated fields to translate"
    )
    parser.add_argument("--jobs", type=int, default=8, help="并发翻译数（默认 8）")
    parser.add_argument(
        "--translator",
        choices=["auto", "llm", "google"],
        default="auto",
        help="auto=有 LLM 配置用 LLM，否则 Google；llm；google",
    )
    args = parser.parse_args()

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    translate_json(
        args.input, args.output, fields, jobs=args.jobs, translator=args.translator
    )


if __name__ == "__main__":
    main()
