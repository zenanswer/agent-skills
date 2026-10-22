"""Multi-source logo search with deterministic ranking.

Sources
-------
iconify       Colored official brand logos (collection `logos`, CC0). Also
              supports any other Iconify collection (skill-icons, devicon, ...).
simpleicons   ~3300 monochrome brand marks with official hex colors.
svgl          ~670 curated SVGs, many with native light/dark and wordmark variants.
lobe-icons    ~976 AI/tech brand marks (OpenAI, Claude, DeepSeek, Qwen, ...).

Every candidate is a plain dict so it can be printed as JSON:

    {
      "source": "iconify",
      "id": "iconify:logos:aws",
      "title": "AWS",
      "is_color": true,
      "brand_color": null,
      "variants": [],
      "preview_url": "https://api.iconify.design/logos/aws.svg",
      "score": 100,
      "confidence": 1.0,
      "meta": {"collection": "logos", "name": "aws"}
    }

Results are sorted by (score desc, source priority, title) so repeated runs are
byte-identical.
"""

from __future__ import annotations

import difflib
import re
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import cache, catalog, net

ICONIFY_SEARCH_URL = "https://api.iconify.design/search"
ICONIFY_SVG_URL = "https://api.iconify.design/{collection}/{name}.svg"
SIMPLEICONS_JSON_URL = (
    "https://cdn.jsdelivr.net/npm/simple-icons@latest/_data/simple-icons.json"
)
SIMPLEICONS_SVG_URL = (
    "https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/{slug}.svg"
)
SVGL_JSON_URL = "https://api.svgl.app/"
LOBE_INDEX_URL = "https://unpkg.com/@lobehub/icons-static-svg@latest/icons/?meta"
LOBE_SVG_URL = "https://unpkg.com/@lobehub/icons-static-svg@latest{file}"

DEFAULT_COLLECTIONS = ("logos",)
SOURCE_PRIORITY = {"iconify": 0, "svgl": 1, "lobeicons": 2, "simpleicons": 3}

# Common query -> canonical name used by every source.
ABBREVIATIONS: dict[str, str] = {
    # cloud / infra
    "k8s": "kubernetes",
    "k8s2": "kubernetes",
    "eks": "aws eks",
    "ecs": "aws ecs",
    "rds": "aws rds",
    "s3": "aws s3",
    "ec2": "aws ec2",
    "iam": "aws iam",
    "vpc": "aws vpc",
    "sqs": "aws sqs",
    "sns": "aws sns",
    "eksctl": "eks",
    "gcp": "google cloud",
    "gke": "google kubernetes engine",
    "aks": "azure kubernetes",
    "az": "azure",
    "cdn": "cloudflare",
    "lb": "load balancer",
    # tooling
    "tf": "terraform",
    "gh": "github",
    "gl": "gitlab",
    "pg": "postgresql",
    "psql": "postgresql",
    "mongo": "mongodb",
    "es": "elasticsearch",
    "elk": "elasticsearch",
    "redis": "redis",
    "kafka": "apache kafka",
    "rabbit": "rabbitmq",
    "nginx": "nginx",
    "pwsh": "powershell",
    "gha": "github actions",
    "ci": "github actions",
    # languages / frameworks
    "js": "javascript",
    "ts": "typescript",
    "node": "node.js",
    "nodejs": "node.js",
    "vue": "vue.js",
    "nuxt": "nuxt",
    "next": "next.js",
    "reactjs": "react",
    "py": "python",
    "golang": "go",
    "rs": "rust",
    "kt": "kotlin",
    "dotnet": ".net",
    "c#": "c sharp",
    "cpp": "c++",
    # AI brands
    "llm": "openai",
    "gpt": "openai",
    "chatgpt": "openai",
    "oai": "openai",
    "claude": "claude",
    "anthropic": "anthropic",
    "ds": "deepseek",
    "deepseek": "deepseek",
    "qwen": "qwen",
    "tongyi": "qwen",
    "通义": "qwen",
    "gemini": "gemini",
    "bard": "gemini",
    "llama": "meta",
    "mistral": "mistral ai",
    "hf": "hugging face",
    "huggingface": "hugging face",
    "sd": "stability ai",
    "mj": "midjourney",
    "ollama": "ollama",
    "langchain": "langchain",
    # business
    "aws": "amazon web services",
    "ms": "microsoft",
    "msft": "microsoft",
    "ali": "alibaba",
    "aliyun": "alibaba cloud",
    "tx": "tencent",
    "tencentcloud": "tencent cloud",
    "bytedance": "bytedance",
    "volc": "volcengine",
    "feishu": "lark",
    "lark": "lark",
    "dingtalk": "dingtalk",
    "wechat": "wechat",
    "wx": "wechat",
}

ACRONYMS = {
    "aws": "AWS",
    "gcp": "GCP",
    "api": "API",
    "sdk": "SDK",
    "cli": "CLI",
    "ui": "UI",
    "ux": "UX",
    "ai": "AI",
    "ml": "ML",
    "llm": "LLM",
    "db": "DB",
    "sql": "SQL",
    "http": "HTTP",
    "https": "HTTPS",
    "css": "CSS",
    "html": "HTML",
    "js": "JS",
    "ts": "TS",
    "id": "ID",
    "jwt": "JWT",
    "sso": "SSO",
    "cdn": "CDN",
    "gpu": "GPU",
    "cpu": "CPU",
    "ram": "RAM",
    "ssh": "SSH",
    "dns": "DNS",
    "vm": "VM",
    "os": "OS",
    "iot": "IoT",
    "s3": "S3",
    "ec2": "EC2",
    "iam": "IAM",
    "rds": "RDS",
    "eks": "EKS",
    "ecs": "ECS",
    "sqs": "SQS",
    "sns": "SNS",
    "vpc": "VPC",
    "kms": "KMS",
    "waf": "WAF",
    "mq": "MQ",
    "ses": "SES",
    "elb": "ELB",
    "xray": "X-Ray",
}

# Brands whose canonical spelling is not title-case.
BRAND_TITLES = {
    "aws": "AWS",
    "github": "GitHub",
    "gitlab": "GitLab",
    "npm": "npm",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "nuxt": "Nuxt",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "react": "React",
    "reactjs": "React",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "openshift": "OpenShift",
    "openai": "OpenAI",
    "chatgpt": "ChatGPT",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "claude": "Claude",
    "anthropic": "Anthropic",
    "gemini": "Gemini",
    "kubernetes": "Kubernetes",
    "docker": "Docker",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "kafka": "Apache Kafka",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "jenkins": "Jenkins",
    "grafana": "Grafana",
    "prometheus": "Prometheus",
    "linux": "Linux",
    "ubuntu": "Ubuntu",
    "debian": "Debian",
    "windows": "Windows",
    "microsoft": "Microsoft",
    "azure": "Azure",
    "google": "Google",
    "googlecloud": "Google Cloud",
    "alibabacloud": "Alibaba Cloud",
    "tencentcloud": "Tencent Cloud",
    "volcengine": "Volcengine",
    "lark": "Lark",
    "feishu": "Feishu",
    "wechat": "WeChat",
    "dingtalk": "DingTalk",
    "huggingface": "Hugging Face",
    "ollama": "Ollama",
    "langchain": "LangChain",
    "dify": "Dify",
    "cohere": "Cohere",
    "midjourney": "Midjourney",
    "stabilityai": "Stability AI",
    "bytedance": "ByteDance",
    "alibaba": "Alibaba",
    "tencent": "Tencent",
    "baidu": "Baidu",
    "juejin": "Juejin",
    "bilibili": "Bilibili",
    "zhihu": "Zhihu",
    "taobao": "Taobao",
    "figma": "Figma",
    "notion": "Notion",
    "slack": "Slack",
    "discord": "Discord",
    "vercel": "Vercel",
    "netlify": "Netlify",
    "supabase": "Supabase",
    "firebase": "Firebase",
    "cloudflare": "Cloudflare",
    "datadog": "Datadog",
    "sentry": "Sentry",
    "postman": "Postman",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def normalize(text: str) -> str:
    """Lowercase and strip everything that is not a letter or digit."""
    return re.sub(r"[\W_]+", "", text.lower())


def compute_si_slug(title: str) -> str:
    """Simple Icons slugs are the title with all non-alphanumerics removed."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def safe_name(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "logo"


def prettify(name: str) -> str:
    """Turn a slug like 'aws-lambda' or 'microsoftazure' into a readable name."""
    raw = name.replace("_", "-").strip("-")
    words = [w for w in re.split(r"-+", raw) if w]
    if not words:
        return name
    joined = normalize(raw)
    if joined in BRAND_TITLES:
        return BRAND_TITLES[joined]
    # split camelCase / glued words we know about
    if len(words) == 1 and joined in BRAND_TITLES:
        return BRAND_TITLES[joined]
    out = []
    for w in words:
        low = w.lower()
        out.append(
            BRAND_TITLES.get(low) or ACRONYMS.get(low) or (w[:1].upper() + w[1:])
        )
    text = " ".join(out)
    # collapse "Aws Lambda" -> "AWS Lambda" style fixes
    text = re.sub(r"\bAws\b", "AWS", text)
    text = re.sub(r"\bGcp\b", "GCP", text)
    return text


def expand_query(query: str) -> tuple[str, str | None]:
    """Return (expanded_query, expansion_note)."""
    q = query.strip()
    key = normalize(q)
    target = ABBREVIATIONS.get(key) or ABBREVIATIONS.get(q.lower())
    if target and normalize(target) != key:
        return target, f"'{q}' expanded to '{target}'"
    return q, None


def name_score(query: str, name: str, allow_fuzzy: bool = True) -> int:
    q, n = normalize(query), normalize(name)
    if not q or not n:
        return 0
    if q == n:
        return 100
    if n.startswith(q):
        return 88
    if q in n:
        return 76
    if not allow_fuzzy:
        return 0
    ratio = difflib.SequenceMatcher(None, q, n).ratio()
    # Typos only: require the same opening characters, otherwise curated
    # indexes full of near-identical names ("react" / "relace") get noisy.
    if ratio >= 0.82 and q[:2] == n[:2]:
        return round(50 + ratio * 25)
    return 0


def _candidate(
    source: str,
    ident: str,
    title: str,
    *,
    is_color: bool,
    brand_color: str | None = None,
    variants: Iterable[str] = (),
    preview_url: str | None = None,
    score: int = 0,
    meta: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cand = {
        "source": source,
        "id": ident,
        "title": title,
        "is_color": is_color,
        "brand_color": brand_color,
        "variants": sorted(set(variants)),
        "preview_url": preview_url,
        "score": score,
        "confidence": round(min(1.0, score / 100), 2),
        "meta": meta or {},
    }
    if extra:
        cand.update(extra)
    return cand


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #


def _iconify_params(query: str, collections: Iterable[str], limit: int) -> dict[str, str]:
    """Build the /search query. Iconify uses `prefix` (one) or `prefixes` (many)."""
    prefixes = [c for c in collections if c]
    params = {"query": query, "limit": str(max(limit, 32))}
    if len(prefixes) == 1:
        params["prefix"] = prefixes[0]
    else:
        params["prefixes"] = ",".join(prefixes)
    return params


def search_iconify(
    query: str,
    limit: int = 10,
    collections: Iterable[str] = DEFAULT_COLLECTIONS,
    sess=None,
) -> list[dict[str, Any]]:
    """Search one or more Iconify collections in a single request.

    Works for brand logos (`logos`) and for UI sets (`mdi`, `tabler`, ...).
    License metadata is attached per collection.
    """
    prefixes = [c for c in collections if c]
    if not prefixes:
        return []
    s = sess or net.session()
    try:
        resp = s.get(ICONIFY_SEARCH_URL, params=_iconify_params(query, prefixes, limit), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        icons = payload.get("icons", []) or []
        api_collections = payload.get("collections") or {}
    except Exception as exc:  # noqa: BLE001 - a failed search should not kill the CLI
        print(f"[warn] Iconify search failed: {exc}", file=sys.stderr)
        return []

    out: list[dict[str, Any]] = []
    for rank, icon_id in enumerate(icons[:limit]):
        if ":" in icon_id:
            coll, name = icon_id.split(":", 1)
        else:
            coll, name = prefixes[0], icon_id
        score = max(name_score(query, name), name_score(query, f"{coll} {name}"))
        score = max(score, max(0, 60 - rank))
        meta = catalog.collection(coll)
        ui_like = bool(meta and meta.get("category") in {"ui", "emoji"})
        lic = catalog.license_for(coll, api_collections.get(coll))
        out.append(
            _candidate(
                "iconify",
                f"iconify:{coll}:{name}",
                prettify(name),
                is_color=not ui_like,
                variants=["mono"] if ui_like else ["color"],
                preview_url=ICONIFY_SVG_URL.format(collection=coll, name=name),
                score=score,
                meta={"collection": coll, "name": name},
                extra={
                    **{k: lic[k] for k in ("license", "license_url", "attribution_required")},
                    "collection": coll,
                    "collection_name": lic["collection_name"],
                    "author": lic.get("author"),
                    "default_color": "#111111" if ui_like else None,
                },
            )
        )
    return out


def search_ui(
    query: str,
    *,
    collections: Iterable[str] | None = None,
    limit: int = 12,
    sess=None,
) -> list[dict[str, Any]]:
    """Concept-aware search across UI icon sets.

    Iconify matches names, so a deck concept ("cost saving", "省钱") is first
    expanded into names that exist ("piggy-bank", "wallet", ...).
    """
    prefixes = list(collections) if collections else catalog.ui_defaults()
    terms = catalog.concept_terms(query)
    if not terms:
        terms = [query]

    pool: list[dict[str, Any]] = []
    wants_off = "off" in normalize(query) or "关闭" in query
    for term_index, term in enumerate(terms):
        for cand in search_iconify(term, limit=32, collections=prefixes, sess=sess):
            # "-off" icons are negation states ("wallet off"), rarely what a deck wants.
            if not wants_off and (cand["meta"].get("name") or "").endswith("-off"):
                continue
            # Earlier synonym entries are more relevant; every entry is at least
            # a legitimate name match, so keep a decent floor.
            cand["score"] = max(cand["score"] - term_index * 2, 60)
            cand["matched_term"] = term
            cand["ui_family"] = catalog.family_name(cand["meta"]["name"])
            pool.append(cand)
    ranked = dedupe_and_rank(pool, style="mono", mode="ui")
    families: dict[str, set[str]] = {}
    for cand in pool:
        families.setdefault(cand.get("ui_family", ""), set()).add(cand.get("collection", ""))
    for cand in ranked:
        others = sorted(families.get(cand.get("ui_family", ""), set()) - {cand.get("collection", "")})
        cand["also_in"] = others
    return ranked[:limit]


def _simpleicons_index(sess=None) -> list[dict[str, Any]]:
    data = cache.get_json(
        "simpleicons.json", SIMPLEICONS_JSON_URL, ttl=7 * 86400, session=sess
    )
    if isinstance(data, dict):
        data = data.get("icons", [])
    return data if isinstance(data, list) else []


def search_simpleicons(query: str, limit: int = 10, sess=None) -> list[dict[str, Any]]:
    q_norm = normalize(query)
    q_slug = compute_si_slug(query)
    out: list[dict[str, Any]] = []
    try:
        icons = _simpleicons_index(sess)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Simple Icons index failed: {exc}", file=sys.stderr)
        return out
    for entry in icons:
        title = entry.get("title", "")
        slug = entry.get("slug") or compute_si_slug(title)
        aliases = entry.get("aliases") or {}
        aka = aliases.get("aka") or []
        dup = [d.get("title", "") for d in (aliases.get("dup") or [])]
        score = 0
        if slug == q_slug:
            score = 100
        elif q_slug and slug.startswith(q_slug):
            score = 86
        elif q_slug and q_slug in slug:
            score = 74
        for alias in [title, *aka, *dup]:
            if not alias:
                continue
            an = normalize(alias)
            if an == q_norm:
                score = max(score, 96)
            elif q_norm and an.startswith(q_norm):
                score = max(score, 84)
            elif q_norm and q_norm in an:
                score = max(score, 70)
        if score == 0:
            score = name_score(query, title)
        if score < 40:
            continue
        hex_color = (entry.get("hex") or "").strip()
        out.append(
            _candidate(
                "simpleicons",
                f"simpleicons:{slug}",
                title,
                is_color=False,
                brand_color=f"#{hex_color}" if hex_color else None,
                variants=["mono"],
                preview_url=SIMPLEICONS_SVG_URL.format(slug=slug),
                score=score,
                meta={"slug": slug},
            )
        )
    out.sort(key=lambda c: (-c["score"], c["title"].lower()))
    return out[:limit]


def _svgl_index(sess=None) -> list[dict[str, Any]]:
    data = cache.get_json("svgl.json", SVGL_JSON_URL, ttl=86400, session=sess)
    return data if isinstance(data, list) else []


def _url_of(value: Any, prefer: str = "light") -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get(prefer) or value.get("light") or value.get("dark")
    return None


def search_svgl(query: str, limit: int = 10, sess=None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        index = _svgl_index(sess)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] svgl index failed: {exc}", file=sys.stderr)
        return out
    for entry in index:
        title = entry.get("title", "")
        score = name_score(query, title, allow_fuzzy=False)
        if score < 40:
            continue
        route = entry.get("route")
        wordmark = entry.get("wordmark")
        variants = ["color"]
        if isinstance(route, dict):
            if route.get("dark"):
                variants.append("dark")
            if route.get("light"):
                variants.append("light")
        out.append(
            _candidate(
                "svgl",
                f"svgl:{safe_name(title)}",
                title,
                is_color=True,
                variants=variants,
                preview_url=_url_of(route),
                score=score,
                meta={
                    "slug": safe_name(title),
                    "route": route,
                    "wordmark": wordmark,
                    "category": entry.get("category"),
                    "url": entry.get("url"),
                    "brand_url": entry.get("brandUrl"),
                },
            )
        )
    out.sort(key=lambda c: (-c["score"], c["title"].lower()))
    return out[:limit]


def _lobe_index(sess=None) -> list[str]:
    data = cache.get_json("lobeicons.json", LOBE_INDEX_URL, ttl=7 * 86400, session=sess)
    files = data.get("files", []) if isinstance(data, dict) else []
    return [f.get("path", "") for f in files if f.get("path", "").endswith(".svg")]


def search_lobeicons(query: str, limit: int = 10, sess=None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        paths = _lobe_index(sess)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] lobe-icons index failed: {exc}", file=sys.stderr)
        return out
    by_stem = {p.rsplit("/", 1)[-1][:-4]: p for p in paths}
    seen: set[str] = set()
    for stem, path in sorted(by_stem.items()):
        if stem.endswith(
            "-text"
        ):  # wordmarks are handled by svgl; keep results icon-only
            continue
        base = stem.removesuffix("-color")
        if base in seen:
            continue
        title = prettify(base)
        score = max(
            name_score(query, base, allow_fuzzy=False),
            name_score(query, title, allow_fuzzy=False),
        )
        if score < 40:
            continue
        seen.add(base)
        file_path = by_stem.get(f"{base}-color") or path
        out.append(
            _candidate(
                "lobeicons",
                f"lobeicons:{file_path.rsplit('/', 1)[-1][:-4]}",
                title,
                is_color=True,
                variants=["color"],
                preview_url=LOBE_SVG_URL.format(file=file_path),
                score=score,
                meta={"file": file_path, "stem": file_path.rsplit("/", 1)[-1][:-4]},
            )
        )
    out.sort(key=lambda c: (-c["score"], c["title"].lower()))
    return out[:limit]


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #


def dedupe_key(cand: dict[str, Any]) -> str:
    """One row per (brand, color-vs-mono) so mono options stay visible."""
    mono = (not cand["is_color"]) or ("mono" in cand.get("variants", ()))
    return normalize(cand["title"]) + ("|mono" if mono else "|color")


def _dedupe(
    candidates: list[dict[str, Any]], show_all: bool, mode: str = "logo"
) -> list[dict[str, Any]]:
    if show_all:
        return candidates
    best: dict[str, dict[str, Any]] = {}
    for cand in candidates:
        if mode == "ui":
            key = (cand.get("ui_family") or cand["meta"].get("name") or cand["title"]) + "|mono"
        else:
            key = dedupe_key(cand)
        current = best.get(key)
        if current is None:
            best[key] = cand
            continue
        def name_len(c: dict[str, Any]) -> int:
            return len((c.get("meta") or {}).get("name", ""))

        better = (
            cand["score"],
            -SOURCE_PRIORITY.get(cand["source"], 9),
            -name_len(cand),
            -len(cand["title"]),
        ) > (
            current["score"],
            -SOURCE_PRIORITY.get(current["source"], 9),
            -name_len(current),
            -len(current["title"]),
        )
        if better:
            best[key] = cand
    return list(best.values())


def search_all(
    query: str,
    *,
    limit: int = 10,
    collections: Iterable[str] = DEFAULT_COLLECTIONS,
    sources: Iterable[str] = ("iconify", "svgl", "lobeicons", "simpleicons"),
    style: str = "color",
    show_all: bool = False,
    mode: str = "logo",
    sess=None,
) -> list[dict[str, Any]]:
    """Run every requested source concurrently and return a stable ranking."""
    if mode == "ui":
        # UI mode is Iconify-only: one API, license metadata, deterministic.
        return search_ui(query, collections=collections, limit=limit or 12, sess=sess)

    wanted = [s for s in sources if s]
    jobs = {
        "iconify": lambda: search_iconify(query, limit, collections, sess),
        "simpleicons": lambda: search_simpleicons(query, limit, sess),
        "svgl": lambda: search_svgl(query, limit, sess),
        "lobeicons": lambda: search_lobeicons(query, limit, sess),
    }
    results: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(wanted))) as pool:
        futures = {name: pool.submit(jobs[name]) for name in wanted if name in jobs}
        for name, fut in futures.items():
            try:
                results[name] = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] source '{name}' failed: {exc}", file=sys.stderr)
                results[name] = []

    merged: list[dict[str, Any]] = []
    for name in wanted:
        merged.extend(results.get(name, []))
    return dedupe_and_rank(merged, style=style, show_all=show_all)


def _sort_key(style: str, mode: str = "logo"):
    def key(c: dict[str, Any]):
        if style == "color":
            color_first = 0 if c["is_color"] else 1
        else:
            color_first = 0 if (not c["is_color"] or "mono" in c["variants"]) else 1
        # In UI mode prefer canonical short names over variant suffixes:
        # "rocket" beats "rocket-launch-outline-rounded".
        name_len = len((c.get("meta") or {}).get("name", "")) if mode == "ui" else 0
        return (
            -c["score"],
            color_first,
            name_len,
            SOURCE_PRIORITY.get(c["source"], 9),
            c["title"].lower(),
        )

    return key


def dedupe_and_rank(
    candidates: list[dict[str, Any]],
    *,
    style: str = "color",
    show_all: bool = False,
    mode: str = "logo",
) -> list[dict[str, Any]]:
    merged = _dedupe(candidates, show_all, mode=mode)
    merged.sort(key=_sort_key(style, mode))
    return merged


def resolve_ref(
    ref: str,
    sess=None,
    prefer_variant: str | None = None,
    mode: str = "logo",
    collections: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Turn a fetch reference into a candidate dict (no search needed).

    Accepted forms:
        iconify:logos:aws          iconify:aws          logos/aws
        simpleicons:amazonwebservices                    amazonwebservices
        svgl:amazon-web-services
        lobeicons:openai-color
    """
    ref = ref.strip()
    if not ref:
        raise ValueError("empty ref")

    if ref.startswith(("http://", "https://")):
        title = safe_name(ref.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        return _candidate(
            "url",
            f"url:{ref}",
            prettify(title),
            is_color=True,
            preview_url=ref,
            meta={"url": ref},
        )

    source = None
    rest = ref
    if ":" in ref:
        head, tail = ref.split(":", 1)
        if head in {"iconify", "simpleicons", "svgl", "lobeicons"}:
            source, rest = head, tail
        elif head in {
            "logos",
            "simple-icons",
            "skill-icons",
            "devicon",
            "mdi",
            "tabler",
        }:
            source, rest = "iconify", f"{head}:{tail}"

    if source == "iconify":
        if ":" in rest:
            collection, name = rest.split(":", 1)
        elif "/" in rest:
            collection, name = rest.split("/", 1)
        else:
            collection, name = "logos", rest
        meta = catalog.collection(collection)
        ui_like = bool(meta and meta.get("category") in {"ui", "emoji"})
        lic = catalog.license_for(collection)
        return _candidate(
            "iconify",
            f"iconify:{collection}:{name}",
            prettify(name),
            is_color=not ui_like,
            variants=["mono"] if ui_like else ["color"],
            preview_url=ICONIFY_SVG_URL.format(collection=collection, name=name),
            meta={"collection": collection, "name": name},
            extra={
                **{k: lic[k] for k in ("license", "license_url", "attribution_required")},
                "collection": collection,
                "collection_name": lic["collection_name"],
                "author": lic.get("author"),
                "default_color": "#111111" if ui_like else None,
            },
        )

    if source == "simpleicons":
        slug = rest
        entry = None
        try:
            for item in _simpleicons_index(sess):
                if (item.get("slug") or compute_si_slug(item.get("title", ""))) == slug:
                    entry = item
                    break
        except Exception:  # noqa: BLE001
            entry = None
        hex_color = (entry or {}).get("hex")
        return _candidate(
            "simpleicons",
            f"simpleicons:{slug}",
            (entry or {}).get("title") or prettify(slug),
            is_color=False,
            brand_color=f"#{hex_color}" if hex_color else None,
            variants=["mono"],
            preview_url=SIMPLEICONS_SVG_URL.format(slug=slug),
            meta={"slug": slug},
        )

    if source == "svgl":
        slug = rest
        try:
            for entry in _svgl_index(sess):
                if safe_name(entry.get("title", "")) == slug:
                    route = entry.get("route")
                    variants = ["color"]
                    if isinstance(route, dict) and route.get("dark"):
                        variants.append("dark")
                    return _candidate(
                        "svgl",
                        f"svgl:{slug}",
                        entry.get("title", prettify(slug)),
                        is_color=True,
                        variants=variants,
                        preview_url=_url_of(route),
                        meta={
                            "slug": slug,
                            "route": route,
                            "wordmark": entry.get("wordmark"),
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] svgl lookup failed: {exc}", file=sys.stderr)
        raise ValueError(
            f"svgl slug '{slug}' not found. Run search_icons.py \"{slug}\" to list svgl candidates."
        )

    if source == "lobeicons":
        stem = rest
        path = f"/icons/{stem}.svg"
        return _candidate(
            "lobeicons",
            f"lobeicons:{stem}",
            prettify(stem.replace("-color", "")),
            is_color=True,
            preview_url=LOBE_SVG_URL.format(file=path),
            meta={"file": path, "stem": stem},
        )

    # bare slug: a plain SVG URL is fetched directly; anything else is
    # auto-resolved through search so `fetch_icon.py aws` just works.
    if ref.lower().endswith(".svg"):
        return resolve_ref(f"url:{ref}", sess)
    expanded, _note = expand_query(ref)
    queries = [ref] if mode == "ui" or normalize(expanded) == normalize(ref) else [ref, expanded]
    found: list[dict[str, Any]] = []
    try:
        for query in queries:
            found.extend(
                search_all(
                    query,
                    limit=8,
                    style="mono" if mode == "ui" else "color",
                    mode=mode,
                    collections=collections if collections is not None else ("logos" if mode == "logo" else catalog.ui_defaults()),
                    sess=sess,
                )
            )
        found = dedupe_and_rank(found, style="mono" if mode == "ui" else "color", mode=mode)
    except Exception:  # noqa: BLE001 - offline fallback below
        found = []
    if prefer_variant in {"dark", "light", "wordmark", "mono"}:
        # Prefer a source that ships the requested variant (e.g. svgl's native
        # dark AWS logo) over recoloring a color logo by hand.
        found = sorted(
            found,
            key=lambda c: (0 if prefer_variant in c.get("variants", ()) else 1, -c["score"]),
        )
    if found:
        best = dict(found[0])
        best["auto_resolved"] = True
        return best
    slug = ref.split(":", 1)[-1]
    return _candidate(
        "simpleicons",
        f"simpleicons:{slug}",
        prettify(slug),
        is_color=False,
        variants=["mono"],
        preview_url=SIMPLEICONS_SVG_URL.format(slug=slug),
        meta={"slug": slug},
    )
