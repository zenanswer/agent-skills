"""HTTP session + proxy helpers shared by every logokit module."""

from __future__ import annotations

import os

import requests

USER_AGENT = "icon-finder/0.2 (+https://github.com/zenanswer/agent-skills)"


def proxy_info() -> str | None:
    """Human readable proxy description from the environment, if any."""
    for var in (
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        val = os.environ.get(var)
        if val:
            return val
    return None


def session() -> requests.Session:
    """A Session that sends a real UA and follows redirects (unpkg needs it)."""
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    return s


def get(
    url: str,
    *,
    timeout: float = 30,
    sess: requests.Session | None = None,
    retries: int = 2,
):
    """GET with a couple of retries on transient failures."""
    s = sess or session()
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return s.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last = exc
            if attempt == retries:
                break
    assert last is not None
    raise last
