#!/usr/bin/env python3
"""
Tech Scout Daily Scraper
Scrapes AI news from 7 sources and outputs a unified JSON file.

Supports two fetch modes:
  - requests (default, fast, no JS)
  - playwright (slower, but bypasses anti-bot, can use proxy)
"""

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: 'beautifulsoup4' is required. Install with: pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)

# ──────────────────────────────────────────────
#  Configuration
# ──────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
}

REQUEST_TIMEOUT = 30

# ── 可选：crawl4ai 服务（JS 渲染 / 反爬 / 干净出口） ──
def _load_env_file() -> None:
    for candidate in (
        Path.home() / ".config" / "tech-scout-daily" / "env",
        Path.cwd() / ".env",
    ):
        if not candidate.is_file():
            continue
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        except OSError:
            pass


_load_env_file()

CRAWL4AI_URL = os.environ.get("CRAWL4AI_URL", "").rstrip("/")
CRAWL4AI_TOKEN = os.environ.get("CRAWL4AI_TOKEN", "")
_FETCHER = "auto"            # auto | requests | crawl4ai
_STRICT = False
_C4A_CACHE: dict[str, str] = {}
_C4A_DISK_CACHE = Path.home() / ".cache" / "tech-scout-daily" / datetime.now().strftime("%Y-%m-%d")

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# Runtime options (set by main() from CLI args)
_PROXY: Optional[str] = None
_USE_PLAYWRIGHT: bool = False
_INSECURE_SSL: bool = os.environ.get("TECH_SCOUT_INSECURE_SSL", "0") == "1"
if _INSECURE_SSL:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────────────────────────
#  Fetchers
# ──────────────────────────────────────────────

_PLAYWRIGHT_BROWSER = None
_PLAYWRIGHT_CONTEXT = None


def _get_playwright():
    """Lazy-init Playwright browser with proxy."""
    global _PLAYWRIGHT_BROWSER, _PLAYWRIGHT_CONTEXT
    if _PLAYWRIGHT_BROWSER is not None:
        return _PLAYWRIGHT_BROWSER

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [WARN] playwright 未安装，跳过浏览器兜底（pip install playwright && playwright install chromium）", file=sys.stderr)
        return None

    pw = sync_playwright().start()
    launch_kwargs = {"headless": True}
    if _PROXY:
        launch_kwargs["proxy"] = {"server": _PROXY}
    _PLAYWRIGHT_BROWSER = pw.chromium.launch(**launch_kwargs)
    _PLAYWRIGHT_CONTEXT = _PLAYWRIGHT_BROWSER.new_context(
        user_agent=HEADERS["User-Agent"],
        ignore_https_errors=_INSECURE_SSL,
    )
    return _PLAYWRIGHT_BROWSER


def _safe_get(url: str, **kwargs) -> Optional[requests.Response]:
    """Safe GET via requests with timeout, retry, and proxy support."""
    if _INSECURE_SSL:
        kwargs.setdefault("verify", False)
    if _PROXY:
        kwargs.setdefault("proxies", {"http": _PROXY, "https": _PROXY})

    last_err = None
    for attempt in range(3):
        try:
            resp = SESSION.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    print(f"  [WARN] requests failed for {url}: {last_err}", file=sys.stderr)
    return None


def _playwright_get(url: str, wait_selector: Optional[str] = None, wait_ms: int = 2000) -> Optional[str]:
    """Fetch URL via Playwright (with proxy if configured). Returns HTML or None."""
    try:
        browser = _get_playwright()
        if browser is None:
            return None
        page = browser.new_page()
        page.set_default_timeout(REQUEST_TIMEOUT * 1000)
        page.goto(url, wait_until="domcontentloaded")
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=REQUEST_TIMEOUT * 1000)
            except Exception:
                pass
        page.wait_for_timeout(wait_ms)
        html = page.content()
        page.close()
        return html
    except Exception as e:
        print(f"  [WARN] playwright failed for {url}: {e}", file=sys.stderr)
        return None


def _c4a_disk_path(url: str) -> Path:
    return _C4A_DISK_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")


def _c4a_disk_get(url: str) -> Optional[str]:
    if os.environ.get("TECH_SCOUT_REFRESH") == "1":
        return None
    path = _c4a_disk_path(url)
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else None
    except OSError:
        return None


def _c4a_disk_put(url: str, html: str) -> None:
    path = _c4a_disk_path(url)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        (path.parent / "index.tsv").open("a", encoding="utf-8").write(f"{path.name}\t{url}\n")
    except OSError:
        pass


def _crawl4ai_batch(urls: list[str]) -> dict[str, str]:
    """一次 POST /crawl 抓多个 URL，返回 {url: html}。

    - 当天缓存命中则直接复用（TECH_SCOUT_REFRESH=1 可强制刷新）
    - 网络抖动重试 1 次；401/403 明确提示 token 失效
    """
    urls = [u for u in urls if u]
    out: dict[str, str] = {}
    pending: list[str] = []
    for url in urls:
        cached = _C4A_CACHE.get(url) or _c4a_disk_get(url)
        if cached:
            out[url] = cached
        else:
            pending.append(url)
    if not pending:
        return out
    if not (CRAWL4AI_URL and CRAWL4AI_TOKEN):
        print("  [WARN] 未配置 CRAWL4AI_URL / CRAWL4AI_TOKEN，跳过 crawl4ai", file=sys.stderr)
        return out

    payload = {"urls": pending, "crawler_config": {"cache_mode": "BYPASS"}}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CRAWL4AI_TOKEN}",
    }
    data = None
    for attempt in range(2):
        try:
            resp = requests.post(
                f"{CRAWL4AI_URL}/crawl", json=payload, headers=headers,
                timeout=max(120, REQUEST_TIMEOUT * len(pending)),
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status in (401, 403):
                print(f"  [ERROR] crawl4ai 鉴权失败（HTTP {status}）：CRAWL4AI_TOKEN 可能已失效",
                      file=sys.stderr)
                return out
            print(f"  [WARN] crawl4ai 请求失败（尝试 {attempt + 1}/2）: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  [WARN] crawl4ai 请求失败（尝试 {attempt + 1}/2）: {e}", file=sys.stderr)
        if attempt == 0:
            time.sleep(2)
    if data is None:
        return out

    for result in data.get("results") or []:
        if result.get("success") and result.get("html"):
            url = result["url"]
            out[url] = result["html"]
            _c4a_disk_put(url, result["html"])
    _C4A_CACHE.update(out)
    return out


def _crawl4ai_html(url: str) -> Optional[str]:
    if url in _C4A_CACHE:
        return _C4A_CACHE[url]
    if not (CRAWL4AI_URL and CRAWL4AI_TOKEN):
        print("  [WARN] 未配置 CRAWL4AI_URL / CRAWL4AI_TOKEN，跳过 crawl4ai 兜底", file=sys.stderr)
        return None
    return _crawl4ai_batch([url]).get(url)


def _unwrap_pre(text: str) -> str:
    """crawl4ai 会把非 HTML 内容（JSON/XML）包在 <pre> 里。"""
    m = re.search(r"<pre[^>]*>(.*?)</pre>", text, re.S | re.I)
    return html_lib.unescape(m.group(1)) if m else text


def _fetch_html(url: str, wait_selector: Optional[str] = None, wait_ms: int = 2000) -> Optional[str]:
    """统一抓取：requests → crawl4ai → Playwright（可选）。"""
    if _USE_PLAYWRIGHT:
        return _playwright_get(url, wait_selector, wait_ms)

    # 同一天的 crawl4ai 缓存优先（requests 模式除外）
    if _FETCHER in ("auto", "crawl4ai"):
        cached = _C4A_CACHE.get(url) or _c4a_disk_get(url)
        if cached:
            _C4A_CACHE[url] = cached
            return cached

    if _FETCHER == "crawl4ai":
        cached = _crawl4ai_html(url)
        if cached:
            return cached
        if _STRICT:
            return None
        print(f"  [fallback] crawl4ai 未取到，改用 requests: {url}", file=sys.stderr)
        resp = _safe_get(url)
        return resp.text if resp is not None else None

    resp = _safe_get(url)
    if resp is not None:
        return resp.text

    if _FETCHER in ("auto", "crawl4ai"):
        cached = _crawl4ai_html(url)
        if cached:
            print(f"  [crawl4ai] {url}", file=sys.stderr)
            return cached

    try:
        return _playwright_get(url, wait_selector, wait_ms)
    except Exception:
        return None


def _fetch_json(url: str) -> Optional[dict]:
    """Fetch JSON：缓存优先 → requests → crawl4ai 的 <pre> 内容。"""
    if _FETCHER in ("auto", "crawl4ai"):
        cached = _C4A_CACHE.get(url) or _c4a_disk_get(url)
        if cached:
            _C4A_CACHE[url] = cached
            try:
                return json.loads(_unwrap_pre(cached))
            except Exception as e:
                print(f"  [WARN] 缓存 JSON 解析失败 {url}: {e}", file=sys.stderr)
        if _FETCHER == "crawl4ai":
            fetched = _crawl4ai_html(url)
            if fetched:
                try:
                    return json.loads(_unwrap_pre(fetched))
                except Exception as e:
                    print(f"  [WARN] crawl4ai JSON parse failed for {url}: {e}", file=sys.stderr)
            if _STRICT:
                return None

    resp = _safe_get(url)
    if resp is not None:
        try:
            return resp.json()
        except Exception as e:
            print(f"  [WARN] JSON parse failed for {url}: {e}", file=sys.stderr)

    if _FETCHER in ("auto", "crawl4ai"):
        cached = _crawl4ai_html(url)
        if cached:
            try:
                return json.loads(_unwrap_pre(cached))
            except Exception as e:
                print(f"  [WARN] crawl4ai JSON parse failed for {url}: {e}", file=sys.stderr)
    return None


def _parse_date(text: str) -> Optional[str]:
    """Try to extract an ISO date from a text snippet."""
    patterns = [
        r"(\d{4}-\d{2}-\d{2})",
        r"(\w+ \d{1,2},?\s*\d{4})",
        r"(\d{1,2} \w+ \d{4})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                try:
                    return datetime.strptime(m.group(1), "%b %d, %Y").strftime("%Y-%m-%d")
                except ValueError:
                    try:
                        return datetime.strptime(m.group(1), "%d %B %Y").strftime("%Y-%m-%d")
                    except ValueError:
                        pass
    return None


def _clean_text(text: str) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


# ──────────────────────────────────────────────
#  Source 1: HuggingFace Daily Papers (API)
# ──────────────────────────────────────────────

def scrape_hf_daily_papers() -> list[dict]:
    """Fetch via HuggingFace daily papers API."""
    print("[1/7] HuggingFace Daily Papers ...", file=sys.stderr)
    url = "https://huggingface.co/api/daily_papers"
    papers = _fetch_json(url)
    if not papers:
        return []

    results = []
    for p in papers[:50]:
        results.append({
            "source": "HuggingFace Daily Papers",
            "source_type": "paper",
            "title": p.get("title", ""),
            "url": f"https://huggingface.co/papers/{p.get('paper', {}).get('id', '')}",
            "summary": p.get("paper", {}).get("summary", ""),
            "authors": p.get("paper", {}).get("authors", []),
            "date": p.get("publishedAt", "")[:10] if p.get("publishedAt") else "",
            "upvotes": p.get("upvotes", 0),
            "tags": [],
        })
    print(f"  -> {len(results)} papers", file=sys.stderr)
    return results


# ──────────────────────────────────────────────
#  Source 2: HuggingFace Trending Papers (HTML)
# ──────────────────────────────────────────────

def scrape_hf_trending_papers() -> list[dict]:
    """Scrape HuggingFace trending papers page."""
    print("[2/7] HuggingFace Trending Papers ...", file=sys.stderr)
    url = "https://huggingface.co/papers/trending"
    html = _fetch_html(url, wait_selector="article", wait_ms=3000)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []
    articles = soup.find_all("article")
    for article in articles[:30]:
        title_el = article.find(["h3", "h4"])
        link_el = article.find("a", href=True)
        title = title_el.get_text(strip=True) if title_el else ""
        href = link_el["href"] if link_el else ""
        if href and not href.startswith("http"):
            href = urljoin("https://huggingface.co", href)

        if title:
            results.append({
                "source": "HuggingFace Trending Papers",
                "source_type": "paper",
                "title": _clean_text(title),
                "url": href,
                "summary": "",
                "authors": [],
                "date": "",
                "upvotes": 0,
                "tags": [],
            })

    print(f"  -> {len(results)} papers", file=sys.stderr)
    return results


# ──────────────────────────────────────────────
#  Source 3: LLM Stats News
# ──────────────────────────────────────────────

def scrape_llm_stats_news() -> list[dict]:
    """Scrape LLM Stats AI news page."""
    print("[3/7] LLM Stats News ...", file=sys.stderr)
    url = "https://llm-stats.com/ai-news"
    html = _fetch_html(url, wait_ms=2000)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Blacklist URL patterns that are NOT news
    NON_NEWS_PATTERNS = [
        "/benchmarks/", "/models/", "/leaderboards/", "/playground",
        "/arenas/", "/compare", "/category/", "model/view", "modelsView",
        "ModelView", "Subscribe", "subscribe",
    ]

    def _is_non_news(href: str, title: str) -> bool:
        for pat in NON_NEWS_PATTERNS:
            if pat.lower() in href.lower():
                return True
        # Skip benchmark/model descriptions that got scraped as text
        if any(kw in title.lower() for kw in ["benchmark", "modelsview", "modelview", "announce type:"]):
            return True
        return False

    # Try to find news article cards/links
    for tag in soup.find_all(["article", "div"], class_=re.compile(r"article|news|post|card", re.I)):
        title_el = tag.find(["h2", "h3", "h4"])
        link_el = tag.find("a", href=True)
        summary_el = tag.find("p")

        title = _clean_text(title_el.get_text()) if title_el else ""
        if not title or len(title) < 10:
            continue

        href = link_el["href"] if link_el else ""
        if href and not href.startswith("http"):
            href = urljoin(url, href)

        if _is_non_news(href, title):
            continue

        date_str = ""
        date_el = tag.find("time") or tag.find(class_=re.compile(r"date|time", re.I))
        if date_el:
            date_str = _parse_date(date_el.get_text()) or ""

        results.append({
            "source": "LLM Stats News",
            "source_type": "news",
            "title": title,
            "url": href,
            "summary": _clean_text(summary_el.get_text()) if summary_el else "",
            "authors": [],
            "date": date_str,
            "upvotes": 0,
            "tags": [],
        })

    # Fallback: if no structured articles found, grab links that look like news
    if not results:
        for a in soup.find_all("a", href=True):
            txt = _clean_text(a.get_text())
            href = a["href"]
            if len(txt) > 20 and not any(skip in txt.lower() for skip in ["subscribe", "privacy", "terms", "cookie", "login", "sign up"]):
                if not href.startswith("http"):
                    href = urljoin(url, href)
                if _is_non_news(href, txt):
                    continue
                results.append({
                    "source": "LLM Stats News",
                    "source_type": "news",
                    "title": txt,
                    "url": href,
                    "summary": "",
                    "authors": [],
                    "date": "",
                    "upvotes": 0,
                    "tags": [],
                })

    print(f"  -> {len(results)} articles", file=sys.stderr)
    return results[:30]


# ──────────────────────────────────────────────
#  Source 4: AI News (artificialintelligence-news.com)
# ──────────────────────────────────────────────

def scrape_ai_news() -> list[dict]:
    """Source 4: The Decoder RSS（原 AI News 站点被 SG captcha 永久拦截）。"""
    print("[4/7] The Decoder (RSS) ...", file=sys.stderr)
    xml = _fetch_html(THE_DECODER_RSS, wait_ms=1000)
    items = _parse_rss(xml, "The Decoder", "news") if xml else []
    print(f"  -> {len(items)} articles", file=sys.stderr)
    return items[:30]


# ──────────────────────────────────────────────
#  Source 5: MIT AI News
# ──────────────────────────────────────────────

def scrape_mit_ai_news() -> list[dict]:
    """Scrape MIT AI news topic page."""
    print("[5/7] MIT AI News ...", file=sys.stderr)
    url = "https://news.mit.edu/topic/artificial-intelligence2"
    html = _fetch_html(url, wait_ms=2000)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # MIT news uses a specific structure with article cards
    for article in soup.find_all(["article", "div"], class_=re.compile(r"article|news-item|post-item|term-page--item", re.I)):
        title_el = article.find(["h2", "h3", "h4"])
        link_el = article.find("a", href=True)
        summary_el = article.find("p")
        date_el = article.find("time") or article.find(class_=re.compile(r"date|time", re.I))

        title = _clean_text(title_el.get_text()) if title_el else ""
        if not title or len(title) < 10:
            continue

        href = link_el["href"] if link_el else ""
        if href and not href.startswith("http"):
            href = urljoin("https://news.mit.edu", href)

        date_str = _parse_date(date_el.get_text()) if date_el else ""

        results.append({
            "source": "MIT News",
            "source_type": "academic",
            "title": title,
            "url": href,
            "summary": _clean_text(summary_el.get_text()) if summary_el else "",
            "authors": [],
            "date": date_str,
            "upvotes": 0,
            "tags": [],
        })

    print(f"  -> {len(results)} articles", file=sys.stderr)
    return results[:20]


# ──────────────────────────────────────────────
#  Source 6: Google AI Blog
# ──────────────────────────────────────────────

GOOGLE_RSS = "https://blog.google/innovation-and-ai/technology/ai/rss/"
THE_DECODER_RSS = "https://the-decoder.com/feed/"


def _parse_rss(xml_text: str, source: str, source_type: str) -> list[dict]:
    """解析 RSS 2.0/Atom（crawl4ai 返回的内容可能是 <pre> 包裹的 XML）。"""
    try:
        root = ET.fromstring(_unwrap_pre(xml_text))
    except ET.ParseError:
        return []
    items: list[dict] = []
    for node in root.iter("item"):
        title = _clean_text(node.findtext("title") or "")
        link = _clean_text(node.findtext("link") or "")
        desc = _clean_text(re.sub(r"<[^>]+>", " ", node.findtext("description") or ""))
        if not title:
            continue
        items.append({
            "source": source,
            "source_type": source_type,
            "title": title,
            "url": link,
            "summary": desc[:400],
            "authors": [],
            "date": _parse_date(node.findtext("pubDate") or "") or "",
            "upvotes": 0,
            "tags": [],
        })
    return items


def scrape_google_ai_blog() -> list[dict]:
    """Scrape Google AI Blog（优先 RSS，失败回退页面解析）。"""
    print("[6/7] Google AI Blog ...", file=sys.stderr)
    rss = _fetch_html(GOOGLE_RSS, wait_ms=1000)
    rss_items = _parse_rss(rss, "Google AI Blog", "corporate") if rss else []
    if rss_items:
        print(f"  -> {len(rss_items)} articles (RSS)", file=sys.stderr)
        return rss_items[:20]
    url = "https://blog.google/technology/ai/"
    html = _fetch_html(url, wait_ms=2000)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    for article in soup.find_all("article"):
        title_el = article.find(["h2", "h3", "h4"])
        link_el = article.find("a", href=True)
        summary_el = article.find("p")
        date_el = article.find("time") or article.find(class_=re.compile(r"date|time", re.I))

        title = _clean_text(title_el.get_text()) if title_el else ""
        if not title or len(title) < 10:
            continue

        href = link_el["href"] if link_el else ""
        if href and not href.startswith("http"):
            href = urljoin("https://blog.google", href)

        date_str = _parse_date(date_el.get_text()) if date_el else ""

        results.append({
            "source": "Google AI Blog",
            "source_type": "corporate",
            "title": title,
            "url": href,
            "summary": _clean_text(summary_el.get_text()) if summary_el else "",
            "authors": [],
            "date": date_str,
            "upvotes": 0,
            "tags": [],
        })

    print(f"  -> {len(results)} articles", file=sys.stderr)
    return results[:20]


# ──────────────────────────────────────────────
#  Source 7: GitHub Trending
# ──────────────────────────────────────────────

def scrape_github_trending() -> list[dict]:
    """Scrape GitHub Trending page."""
    print("[7/7] GitHub Trending ...", file=sys.stderr)
    url = "https://github.com/trending"
    html = _fetch_html(url, wait_ms=2000)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    for article in soup.find_all("article", class_="Box-row"):
        h2 = article.find("h2")
        if not h2:
            continue

        link_el = h2.find("a", href=True)
        if not link_el:
            continue

        href = link_el["href"]
        full_url = urljoin("https://github.com", href)
        repo_name = href.strip("/")

        # Description
        desc_el = article.find("p")
        description = _clean_text(desc_el.get_text()) if desc_el else ""

        # Language — try both itemprop and span
        lang_el = article.find(itemprop="programmingLanguage")
        if not lang_el:
            # Try by class containing "repo-language-color" sibling
            color_el = article.find(class_=re.compile(r"repo-language-color", re.I))
            if color_el:
                lang_el = color_el.find_next_sibling("span")
        language = _clean_text(lang_el.get_text()) if lang_el else ""

        # Stars — try multiple strategies
        stars = 0
        # Strategy 1: Look for the star count in the float-right area
        star_area = article.find(class_=re.compile(r"float-sm-right|d-inline-block", re.I))
        if star_area:
            star_text = star_area.get_text(strip=True)
            # Parse "1,234" or "12.3k" format
            star_text = star_text.replace(",", "").strip()
            if star_text.lower().endswith("k"):
                try:
                    stars = int(float(star_text[:-1]) * 1000)
                except ValueError:
                    pass
            else:
                try:
                    stars = int(re.sub(r"[^\d]", "", star_text))
                except ValueError:
                    pass

        # Strategy 2: Look for "stars today" text nearby
        if stars == 0:
            for text_el in article.find_all(string=re.compile(r"stars?\s*(today|this week)", re.I)):
                parent = text_el.parent
                if parent:
                    num_text = parent.get_text(strip=True)
                    nums = re.findall(r"[\d,]+", num_text)
                    if nums:
                        try:
                            stars = int(nums[0].replace(",", ""))
                        except ValueError:
                            pass

        # Strategy 3: Look for any number near a star icon (svg with octicon-star)
        if stars == 0:
            star_icon = article.find("svg", class_=re.compile(r"octicon-star", re.I))
            if star_icon:
                parent = star_icon.parent
                if parent:
                    parent_text = parent.get_text(strip=True)
                    nums = re.findall(r"[\d,]+", parent_text)
                    for n in nums:
                        try:
                            stars = int(n.replace(",", ""))
                            break
                        except ValueError:
                            pass

        # Forks
        forks = 0
        fork_icon = article.find("svg", class_=re.compile(r"octicon-repo-forked", re.I))
        if fork_icon:
            fork_parent = fork_icon.parent
            if fork_parent:
                fork_text = fork_parent.get_text(strip=True)
                fork_nums = re.findall(r"[\d,]+", fork_text)
                for n in fork_nums:
                    try:
                        forks = int(n.replace(",", ""))
                        break
                    except ValueError:
                        pass

        results.append({
            "source": "GitHub Trending",
            "source_type": "repo",
            "title": repo_name,
            "url": full_url,
            "summary": description,
            "authors": [],
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "upvotes": stars,
            "tags": [language] if language else [],
            "forks": forks,
        })

    print(f"  -> {len(results)} repos", file=sys.stderr)
    return results[:25]


# ──────────────────────────────────────────────
#  Entity extraction
# ──────────────────────────────────────────────

KNOWN_ENTITIES = {
    # Companies
    "OpenAI": ["openai", "gpt-", "chatgpt", "sora"],
    "Google": ["google", "gemini", "deepmind", "veo", "alphafold", "tensorflow"],
    "Meta": ["meta", "llama", "facebook"],
    "Anthropic": ["anthropic", "claude"],
    "Microsoft": ["microsoft", "azure", "msft"],
    "Nvidia": ["nvidia", "cuda"],
    "Apple": ["apple"],
    "Amazon": ["amazon", "aws", "nova"],
    "xAI": ["xai", "grok"],
    "DeepSeek": ["deepseek"],
    "Mistral": ["mistral"],
    "HuggingFace": ["hugging face", "huggingface"],
    "IBM": ["ibm"],
    "Intel": ["intel"],
    "AMD": ["amd"],
    "Samsung": ["samsung"],
    "Baidu": ["baidu"],
    "Alibaba": ["alibaba", "qwen"],
    "ByteDance": ["bytedance", "tiktok"],
    "SenseTime": ["sensetime", "sense time"],
    # Institutions
    "MIT": ["mit", "massachusetts institute"],
    "Stanford": ["stanford"],
    "Berkeley": ["berkeley", "uc berkeley"],
    "CMU": ["cmu", "carnegie mellon"],
    "Tsinghua": ["tsinghua"],
    "PKU": ["pku", "peking university"],
    "ETH Zurich": ["eth zurich", "eth zürich"],
    "Oxford": ["oxford"],
    "Cambridge": ["cambridge"],
    "NYU": ["nyu", "new york university"],
}

# Known key people (name -> affiliation)
KNOWN_PEOPLE = {
    "Sam Altman": "OpenAI",
    "Greg Brockman": "OpenAI",
    "Ilya Sutskever": "SSI",
    "Dario Amodei": "Anthropic",
    "Daniela Amodei": "Anthropic",
    "Demis Hassabis": "Google DeepMind",
    "Yann LeCun": "Meta",
    "Andrej Karpathy": "Eureka Labs",
    "Fei-Fei Li": "Stanford",
    "Andrew Ng": "DeepLearning.AI",
    "Geoffrey Hinton": "University of Toronto",
    "Yoshua Bengio": "Mila",
    "Jensen Huang": "Nvidia",
    "Satya Nadella": "Microsoft",
    "Sundar Pichai": "Google",
    "Mark Zuckerberg": "Meta",
    "Elon Musk": "xAI",
    "Liang Wenfeng": "DeepSeek",
    "Kai-Fu Lee": "01.AI",
    "Jim Fan": "Nvidia",
    "Noam Shazeer": "Google DeepMind",
    "Aidan Gomez": "Cohere",
    "Clement Delangue": "HuggingFace",
    "Thomas Wolf": "HuggingFace",
}


def extract_entities(items: list[dict]) -> list[dict]:
    """Annotate each item with detected companies/institutions and people."""
    for item in items:
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()

        companies = []
        for name, keywords in KNOWN_ENTITIES.items():
            for kw in keywords:
                if kw in text:
                    companies.append(name)
                    break

        people = []
        for name, affiliation in KNOWN_PEOPLE.items():
            if name.lower() in text:
                people.append({"name": name, "affiliation": affiliation})

        item["companies"] = companies
        item["people"] = people

    return items


# ──────────────────────────────────────────────
#  Scorer
# ──────────────────────────────────────────────

TECH_KEYWORDS = {
    "transformer": 3, "diffusion": 3, "reinforcement learning": 3,
    "rlhf": 3, "agent": 2, "multimodal": 2, "llm": 1,
    "reasoning": 2, "chain-of-thought": 3, "mixture of experts": 3,
    "moe": 3, "quantization": 2, "distillation": 2, "fine-tuning": 1,
    "retrieval-augmented": 3, "rag": 3, "graph neural": 3, "gnn": 3,
    "foundation model": 2, "zero-shot": 2, "few-shot": 1,
    "self-supervised": 2, "contrastive": 1, "adversarial": 2,
    "vision transformer": 2, "vit": 2, "swin": 2,
    "neural radiance": 3, "nerf": 3, "gaussian splatting": 3,
    "robot": 2, "embodied": 3, "autonomous": 2,
    "safety": 2, "alignment": 3, "interpretability": 3,
    "benchmark": 1, "sota": 2, "state-of-the-art": 2,
    "new architecture": 3, "novel": 1, "breakthrough": 2,
    "efficient": 1, "scaling": 2, "pretraining": 1,
    "tokenizer": 1, "attention": 1, "latent": 1,
    "code generation": 2, "swe-bench": 2, "humaneval": 1,
    "protein": 3, "drug discovery": 3, "genomics": 3,
    "quantum": 3, "neuromorphic": 3, "analog": 2,
}

BUSINESS_KEYWORDS = {
    "enterprise": 2, "production": 2, "deployment": 1,
    "saas": 2, "api": 1, "cloud": 1,
    "billion": 3, "million": 1, "funding": 2, "series": 2,
    "revenue": 2, "commercial": 2, "pricing": 1,
    "startup": 1, "unicorn": 2, "ipo": 3,
    "partnership": 1, "acquisition": 2, "merger": 2,
    "healthcare": 2, "finance": 2, "education": 1,
    "manufacturing": 2, "retail": 1, "autonomous driving": 3,
    "chip": 2, "hardware": 1, "infrastructure": 2,
    "regulation": 2, "compliance": 1, "governance": 1,
    "open source": 1, "open weight": 1, "open-weight": 1,
    "patent": 1, "intellectual property": 1,
}


def score_item(item: dict) -> dict:
    """Assign tech_value and business_value scores."""
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()

    tech_score = 3.0  # baseline
    tech_hits = 0
    for kw, weight in TECH_KEYWORDS.items():
        if kw in text:
            tech_score += weight
            tech_hits += 1
    tech_score = min(10, round(tech_score + tech_hits * 0.5, 1))

    biz_score = 3.0
    biz_hits = 0
    for kw, weight in BUSINESS_KEYWORDS.items():
        if kw in text:
            biz_score += weight
            biz_hits += 1
    biz_score = min(10, round(biz_score + biz_hits * 0.5, 1))

    # Boost for corporate/academic types
    if item.get("source_type") == "corporate":
        biz_score = min(10, biz_score + 1)
    if item.get("source_type") == "repo":
        tech_score = min(10, tech_score + 1)

    item["tech_value"] = tech_score
    item["business_value"] = biz_score
    return item


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

SOURCES = {
    "1": ("hf_daily", scrape_hf_daily_papers),
    "2": ("hf_trending", scrape_hf_trending_papers),
    "3": ("llm_stats", scrape_llm_stats_news),
    "4": ("the_decoder", scrape_ai_news),
    "5": ("mit", scrape_mit_ai_news),
    "6": ("google_blog", scrape_google_ai_blog),
    "7": ("github", scrape_github_trending),
}


def main():
    global _PROXY, _USE_PLAYWRIGHT, _INSECURE_SSL, _FETCHER, _STRICT

    parser = argparse.ArgumentParser(description="Tech Scout Daily Scraper")
    parser.add_argument("--output", default="/tmp/tech_scout_raw.json", help="Output JSON file")
    parser.add_argument("--days", type=int, default=1, help="Days back to filter (unused for now)")
    parser.add_argument("--sources", default="", help="Comma-separated source numbers (default: all)")
    parser.add_argument("--proxy", default="", help="HTTP proxy URL (e.g. http://<host>:<port>)")
    parser.add_argument("--fetcher", choices=["auto", "requests", "crawl4ai"], default="auto",
                        help="抓取后端：auto=requests 失败后走 crawl4ai；requests；crawl4ai=全部走 crawl4ai")
    parser.add_argument("--strict", action="store_true",
                        help="crawl4ai 模式失败时不回退 requests（默认会部分降级）")
    parser.add_argument("--health", action="store_true",
                        help="只做各源可达性检查，不写 JSON、不出报纸")
    parser.add_argument("--use-playwright", action="store_true", help="Use Playwright for all sources (bypasses anti-bot, uses proxy)")
    parser.add_argument("--insecure-ssl", action="store_true", help="Skip SSL verification")
    args = parser.parse_args()

    # Apply runtime options
    if args.proxy:
        _PROXY = args.proxy
    _FETCHER = args.fetcher
    _STRICT = args.strict
    if args.use_playwright:
        _USE_PLAYWRIGHT = True
    if args.insecure_ssl:
        _INSECURE_SSL = True
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if _PROXY:
        print(f"[Proxy] Using proxy: {_PROXY}", file=sys.stderr)
    if _USE_PLAYWRIGHT:
        print("[Mode] Playwright (browser-based, JS rendering)", file=sys.stderr)
    if _INSECURE_SSL:
        print("[SSL] Verification disabled", file=sys.stderr)

    selected = set(args.sources.split(",")) if args.sources else set(SOURCES.keys())
    valid = [s for s in selected if s in SOURCES]

    if not valid:
        print("ERROR: No valid sources selected.", file=sys.stderr)
        sys.exit(1)

    # crawl4ai 模式：一次批量抓取所有选中源，后续解析直接用缓存
    if _FETCHER == "crawl4ai":
        urls = [
            {"1": "https://huggingface.co/api/daily_papers",
             "2": "https://huggingface.co/papers/trending",
             "3": "https://llm-stats.com/ai-news",
             "4": "https://the-decoder.com/feed/",
             "5": "https://news.mit.edu/topic/artificial-intelligence2",
             "6": "https://blog.google/innovation-and-ai/technology/ai/rss/",
             "7": "https://github.com/trending"}[k]
            for k in valid
        ]
        fetched = _crawl4ai_batch(urls)
        print(f"[crawl4ai] prefetched {len(fetched)}/{len(urls)} sources", file=sys.stderr)

    all_items = []
    failures = []
    per_source: dict[str, int] = {}

    for key in valid:
        name, fn = SOURCES[key]
        try:
            items = fn()
            if items is None or len(items) == 0:
                # Treat empty results as a failure (network blocked, etc.)
                failures.append(name)
                per_source[name] = 0
                print(f"  [WARN] Source {key} ({name}) returned no items", file=sys.stderr)
            else:
                all_items.extend(items)
                per_source[name] = len(items)
        except Exception as e:
            print(f"  [ERROR] Source {key} ({name}) failed: {e}", file=sys.stderr)
            failures.append(name)
            per_source[name] = 0

    if args.health:
        print("\n源健康检查（0 表示该源无内容）:", file=sys.stderr)
        for key in valid:
            name = SOURCES[key][0]
            count = per_source.get(name, 0)
            flag = "OK  " if count else "FAIL"
            print(f"  {flag} [{key}] {name:16s} {count:3d} items", file=sys.stderr)
        print(f"\n结果: {len(valid) - len(failures)}/{len(valid)} 源可用", file=sys.stderr)
        sys.exit(0 if not failures else 1)

    # Cleanup Playwright browser if used
    if _PLAYWRIGHT_BROWSER is not None:
        try:
            _PLAYWRIGHT_BROWSER.close()
        except Exception:
            pass

    print(f"\nTotal raw items: {len(all_items)}", file=sys.stderr)

    # Deduplicate by URL
    seen_urls = set()
    deduped = []
    for item in all_items:
        url = item.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        deduped.append(item)
    print(f"After dedup: {len(deduped)}", file=sys.stderr)

    # Extract entities
    deduped = extract_entities(deduped)

    # Score
    deduped = [score_item(item) for item in deduped]

    # Sort by tech_value descending
    deduped.sort(key=lambda x: x.get("tech_value", 0), reverse=True)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_items": len(deduped),
        "sources_used": [SOURCES[k][0] for k in valid],
        "sources_failed": failures,
        "items": deduped,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Output: {args.output} ({len(deduped)} items)", file=sys.stderr)


if __name__ == "__main__":
    main()