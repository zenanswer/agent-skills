#!/usr/bin/env python3
"""
Tech Scout Daily — One-command runner.

Scrapes all sources, translates to Chinese, generates the daily newspaper,
and prints a summary.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SCRAPER = SCRIPT_DIR / "scraper.py"
TRANSLATOR = SCRIPT_DIR / "translate.py"
GENERATOR = SCRIPT_DIR / "generate_daily.py"


def main():
    parser = argparse.ArgumentParser(description="Tech Scout Daily — one-command runner")
    parser.add_argument("--output-dir", default="/tmp", help="Output directory")
    parser.add_argument("--format", choices=["md", "html", "both"], default="md", help="Output format: md / html / both")
    parser.add_argument("--insecure-ssl", action="store_true", help="Skip SSL verification")
    parser.add_argument("--sources", default="", help="Comma-separated source numbers (default: all)")
    parser.add_argument("--no-translate", action="store_true", help="Skip translation step (English only)")
    parser.add_argument("--proxy", default="", help="HTTP proxy URL (e.g. http://<host>:<port>)")
    parser.add_argument("--fetcher", choices=["auto", "requests", "crawl4ai"], default="auto",
                        help="抓取后端：auto=requests 失败后走 crawl4ai；requests；crawl4ai=全部走 crawl4ai")
    parser.add_argument("--strict", action="store_true",
                        help="crawl4ai 模式失败时不回退 requests")
    parser.add_argument("--health", action="store_true",
                        help="只检查各源可达性，不生成日报")
    parser.add_argument("--use-playwright", action="store_true", help="Use Playwright (browser-based, bypasses anti-bot)")
    parser.add_argument("--playwright-only-failures", action="store_true", help="Use Playwright only for failed sources (fallback)")
    parser.add_argument("--ask-on-failure", action="store_true", help="After initial fetch, if any source still failed, interactively ask to skip, supply a proxy, or abort")
    parser.add_argument("--no-print", action="store_true", help="Don't print the newspaper content to stdout")
    args = parser.parse_args()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_file = os.path.join(args.output_dir, f"tech_scout_raw_{today}.json")
    translated_file = os.path.join(args.output_dir, f"tech_scout_translated_{today}.json")
    # When --format=both, generator writes both .md and .html with the same base
    if args.format == "both":
        out_file = os.path.join(args.output_dir, f"tech_scout_daily_{today}.md")
    else:
        out_file = os.path.join(args.output_dir, f"tech_scout_daily_{today}.{args.format}")

    env = os.environ.copy()
    if args.insecure_ssl:
        env["TECH_SCOUT_INSECURE_SSL"] = "1"

    os.makedirs(args.output_dir, exist_ok=True)

    # Step 1: Scrape
    print("=" * 60, flush=True)
    print("Step 1/3: Scraping sources...", flush=True)
    print("=" * 60, flush=True)
    scraper_cmd = [
        sys.executable, str(SCRAPER),
        "--output", raw_file,
    ]
    if args.sources:
        scraper_cmd += ["--sources", args.sources]
    if args.insecure_ssl:
        scraper_cmd += ["--insecure-ssl"]
    if args.proxy:
        scraper_cmd += ["--proxy", args.proxy]
    if args.use_playwright:
        scraper_cmd += ["--use-playwright"]
    if args.fetcher and args.fetcher != "auto":
        scraper_cmd += ["--fetcher", args.fetcher]
    if args.strict:
        scraper_cmd += ["--strict"]
    if args.health:
        scraper_cmd += ["--health"]

    ret = subprocess.run(scraper_cmd, env=env)
    if ret.returncode != 0:
        print("ERROR: Scraper failed.", file=sys.stderr)
        sys.exit(1)

    if args.health:
        sys.exit(ret.returncode)

    if not os.path.exists(raw_file):
        print(f"ERROR: Scraper output not found: {raw_file}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(raw_file, "r", encoding="utf-8") as f:
            _raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 读取抓取结果失败: {e}", file=sys.stderr)
        sys.exit(1)

    if not _raw.get("items"):
        failed = _raw.get("sources_failed") or []
        print("ERROR: 所有源都没有抓到内容。", file=sys.stderr)
        print(f"  失败源: {', '.join(failed) if failed else '未知'}", file=sys.stderr)
        print("  排查建议:", file=sys.stderr)
        print("    1) crawl4ai 是否可达、CRAWL4AI_TOKEN 是否失效（401/403）", file=sys.stderr)
        print("    2) 改用 --fetcher auto 观察哪些源本地可直连", file=sys.stderr)
        print("    3) 网络受限时可加 --proxy <url> 或用 --health 只做连通性检查", file=sys.stderr)
        sys.exit(2)

    # If --playwright-only-failures, check which sources failed and re-run with playwright for those
    if args.playwright_only_failures:
        try:
            with open(raw_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            failed = data.get("sources_failed", [])
            if failed:
                print()
                print(
                    f"  [Fallback] Re-running {len(failed)} failed sources with Playwright: {failed}",
                    flush=True,
                )
                # Map source names back to source numbers
                name_to_id = {v[0]: k for k, v in {
                    "1": ("hf_daily", None),
                    "2": ("hf_trending", None),
                    "3": ("llm_stats", None),
                    "4": ("the_decoder", None),
                    "5": ("mit", None),
                    "6": ("google_blog", None),
                    "7": ("github", None),
                }.items()}
                retry_ids = [name_to_id[n] for n in failed if n in name_to_id]
                if retry_ids:
                    retry_cmd = [
                        sys.executable, str(SCRAPER),
                        "--output", raw_file + ".retry",
                        "--sources", ",".join(retry_ids),
                        "--use-playwright",
                    ]
                    if args.insecure_ssl:
                        retry_cmd += ["--insecure-ssl"]
                    if args.proxy:
                        retry_cmd += ["--proxy", args.proxy]
                    if args.fetcher and args.fetcher != "auto":
                        retry_cmd += ["--fetcher", args.fetcher]
                    subprocess.run(retry_cmd, env=env)
                    # Merge results
                    retry_path = raw_file + ".retry"
                    if os.path.exists(retry_path):
                        with open(retry_path, "r", encoding="utf-8") as f:
                            retry_data = json.load(f)
                        data["items"].extend(retry_data.get("items", []))
                        data["sources_failed"] = [
                            f for f in data.get("sources_failed", [])
                            if f not in retry_data.get("sources_used", [])
                        ]
                        with open(raw_file, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        os.remove(retry_path)
        except Exception as e:
            print(f"  [WARN] Playwright fallback failed: {e}", file=sys.stderr)

    # Step 1.5: If sources still failed and --ask-on-failure is set, ask the user
    if args.ask_on_failure and not args.proxy:
        try:
            with open(raw_file, "r", encoding="utf-8") as f:
                _data = json.load(f)
            _failed = _data.get("sources_failed", [])
        except Exception:
            _failed = []

        if _failed:
            print()
            print("=" * 60, flush=True)
            print(f"⚠️  以下源未获取: {', '.join(_failed)}", flush=True)
            print("=" * 60, flush=True)

            # If running interactively, ask the user
            if sys.stdin.isatty() and sys.stdout.isatty():
                print("   1) 跳过失败的源，继续生成报纸")
                print("   2) 提供 HTTP 代理 URL 重试（如 http://<host>:<port>）")
                print("   3) 退出")
                try:
                    choice = input("   请选择 [1/2/3]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    choice = "1"

                if choice == "2":
                    try:
                        proxy_url = input("   代理 URL: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        proxy_url = ""
                    if proxy_url:
                        print(f"  [Retry] Re-running failed sources with proxy: {proxy_url}", flush=True)
                        name_to_id = {
                            "hf_daily": "1", "hf_trending": "2", "llm_stats": "3",
                            "the_decoder": "4", "mit": "5", "google_blog": "6", "github": "7",
                        }
                        retry_ids = [name_to_id[n] for n in _failed if n in name_to_id]
                        if retry_ids:
                            retry_cmd = [
                                sys.executable, str(SCRAPER),
                                "--output", raw_file + ".retry2",
                                "--sources", ",".join(retry_ids),
                                "--proxy", proxy_url,
                            ]
                            if args.insecure_ssl:
                                retry_cmd += ["--insecure-ssl"]
                            if args.fetcher and args.fetcher != "auto":
                                retry_cmd += ["--fetcher", args.fetcher]
                            subprocess.run(retry_cmd, env=env)
                            retry_path = raw_file + ".retry2"
                            if os.path.exists(retry_path):
                                with open(retry_path, "r", encoding="utf-8") as f:
                                    retry_data = json.load(f)
                                with open(raw_file, "r", encoding="utf-8") as f:
                                    data = json.load(f)
                                data["items"].extend(retry_data.get("items", []))
                                data["sources_failed"] = [
                                    f for f in data.get("sources_failed", [])
                                    if f not in retry_data.get("sources_used", [])
                                ]
                                with open(raw_file, "w", encoding="utf-8") as f:
                                    json.dump(data, f, ensure_ascii=False, indent=2)
                                os.remove(retry_path)
                elif choice == "3":
                    print("Aborted.", file=sys.stderr)
                    sys.exit(1)
            else:
                # Non-interactive (e.g. opencode skill running piped): just skip
                print("  [Note] Non-interactive mode: continuing with successful sources only.", flush=True)

    # Step 2: Translate to Chinese (bilingual)
    final_input = raw_file
    if not args.no_translate:
        print()
        print("=" * 60, flush=True)
        print("Step 2/3: Translating to Chinese (bilingual mode)...", flush=True)
        print("=" * 60, flush=True)
        translator_cmd = [
            sys.executable, str(TRANSLATOR),
            "--input", raw_file,
            "--output", translated_file,
            "--fields", "title,summary",
        ]
        ret = subprocess.run(translator_cmd)
        if ret.returncode != 0:
            print("WARNING: Translation failed, continuing with English only.", file=sys.stderr)
        elif os.path.exists(translated_file):
            final_input = translated_file

    # Step 3: Generate newspaper
    print()
    print("=" * 60, flush=True)
    print("Step 3/3: Generating daily newspaper...", flush=True)
    print("=" * 60, flush=True)
    generator_cmd = [
        sys.executable, str(GENERATOR),
        "--input", final_input,
        "--output", out_file,
        "--format", args.format,
    ]
    ret = subprocess.run(generator_cmd)
    if ret.returncode != 0:
        print("ERROR: Generator failed.", file=sys.stderr)
        sys.exit(1)

    # Summary
    print()
    print("=" * 60, flush=True)
    print("✅ Daily newspaper generated!", flush=True)
    print("=" * 60, flush=True)
    print(f"  Raw JSON: {raw_file}")
    if not args.no_translate and os.path.exists(translated_file):
        print(f"  Translated JSON: {translated_file}")
    base = out_file.rsplit(".", 1)[0]
    if args.format in ("md", "both"):
        print(f"  📄 Markdown: {base}.md")
    if args.format in ("html", "both"):
        print(f"  🌐 HTML:     {base}.html")
    print()

    # Print the markdown content (skip for HTML-only or both)
    if not args.no_print and args.format == "md":
        print()
        print("=" * 60, flush=True)
        print("📰 NEWSPAPER CONTENT (Markdown)", flush=True)
        print("=" * 60, flush=True)
        with open(out_file, "r", encoding="utf-8") as f:
            print(f.read())


if __name__ == "__main__":
    main()