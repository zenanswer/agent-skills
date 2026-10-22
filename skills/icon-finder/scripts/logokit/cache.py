"""On-disk JSON cache for the icon-finder index files.

Brand indexes (Simple Icons ~370 KB, svgl ~130 KB, lobe-icons ~1 MB) are
fetched once and reused. Every entry is a plain JSON file keyed by a stable
name, so a failed/offline refresh can always fall back to the last good copy.

Environment:
    ICON_FINDER_CACHE_DIR   override cache location (default ~/.cache/icon-finder)
    ICON_FINDER_NO_CACHE=1  ignore reads and skip writes (still fetches)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError as exc:  # pragma: no cover - uv always provides it
    raise SystemExit(
        "ERROR: 'requests' is missing. Run scripts with: uv run <script>"
    ) from exc


DEFAULT_CACHE_DIR = Path.home() / ".cache" / "icon-finder"
CACHE_DIR = Path(os.environ.get("ICON_FINDER_CACHE_DIR") or DEFAULT_CACHE_DIR)
NO_CACHE = os.environ.get("ICON_FINDER_NO_CACHE", "").strip() in {"1", "true", "yes"}
USER_AGENT = "icon-finder/0.2 (+https://github.com/zenanswer/agent-skills)"


def _session(session: requests.Session | None) -> requests.Session:
    if session is not None:
        return session
    s = requests.Session()
    s.headers.setdefault("User-Agent", USER_AGENT)
    return s


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def read_json(key: str, max_age: float) -> Any | None:
    """Return cached JSON if it exists and is younger than max_age seconds."""
    if NO_CACHE:
        return None
    p = _path(key)
    try:
        if max_age >= 0 and (time.time() - p.stat().st_mtime) > max_age:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_stale(key: str) -> Any | None:
    """Return cached JSON regardless of age (offline fallback)."""
    try:
        return json.loads(_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(key: str, data: Any) -> None:
    if NO_CACHE:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _path(key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass  # caching is best-effort, never fatal


def get_json(
    key: str,
    url: str,
    ttl: float = 86400,
    session: requests.Session | None = None,
    timeout: int = 30,
) -> Any:
    """Fetch JSON with cache. Falls back to a stale copy when the network fails."""
    fresh = read_json(key, ttl)
    if fresh is not None:
        return fresh
    s = _session(session)
    try:
        resp = s.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        write_json(key, data)
        return data
    except (requests.RequestException, ValueError) as exc:
        stale = read_stale(key)
        if stale is not None:
            print(
                f"[warn] {url} unreachable ({exc}); using stale cache",
                file=__import__("sys").stderr,
            )
            return stale
        raise


def cache_info() -> dict[str, Any]:
    """Small diagnostic payload for --cache-info."""
    entries = []
    if CACHE_DIR.exists():
        for p in sorted(CACHE_DIR.glob("*.json")):
            st = p.stat()
            entries.append(
                {
                    "key": p.stem,
                    "size_kb": round(st.st_size / 1024, 1),
                    "age_hours": round((time.time() - st.st_mtime) / 3600, 1),
                }
            )
    return {"dir": str(CACHE_DIR), "no_cache": NO_CACHE, "entries": entries}
