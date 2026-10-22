"""Multi-provider abstraction for image generation and VLM analysis.

Providers
---------
minimax            MiniMax native (image-01 / image-01-live)
qwen               Aliyun DashScope (qwen-image-3.0-pro and friends)
ark                Volcengine Ark / Seedream 5.0 (cheap, strong icon quality)
openai             OpenAI Images (gpt-image-1 or dall-e-3)
openai-compatible  any gateway speaking the OpenAI Images API (SiliconFlow,
                   DashScope compatible-mode, self-hosted, ...)

Config resolution (highest first):
  1. CLI args (--provider / --model / --api-key / --host)
  2. env vars: ICON_PROVIDER, ICON_API_KEY, ICON_API_HOST, ICON_MODEL,
     ICON_VLM_MODEL
  3. legacy minimax vars: MINIMAX_API_KEY, MINIMAX_API_HOST
  4. .env file next to this file
  5. built-in defaults

Imported by generate_icon.py, analyze_style.py and check.py. Not a CLI.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "ERROR: 'requests' not found. Run scripts with: uv run <script>.py ..."
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
MAX_RETRIES = 3

SUPPORTED_PROVIDERS = ("minimax", "qwen", "ark", "openai", "openai-compatible")

DEFAULT_HOSTS = {
    "minimax": "https://api.minimaxi.com",
    "qwen": "https://dashscope.aliyuncs.com",
    "ark": "https://ark.cn-beijing.volces.com",
    "openai": "https://api.openai.com",
    "openai-compatible": "",
}

DEFAULT_IMAGE_MODELS = {
    "minimax": "image-01",
    "qwen": "qwen-image-3.0-pro",
    "ark": "doubao-seedream-5-0-pro-260628",
    "openai": "gpt-image-1",
    "openai-compatible": "",
}

DEFAULT_VLM_MODELS = {
    "minimax": "MiniMax-M1",
    "qwen": "qwen-vl-max",
    "ark": "",  # set ICON_VLM_MODEL (e.g. a doubao vision model id)
    "openai": "gpt-4o",
    "openai-compatible": "",
}

# Providers that accept a separate negative prompt field.
NEGATIVE_SUPPORT = {
    "qwen": True,
    "minimax": False,
    "ark": False,
    "openai": False,
    "openai-compatible": False,
}

QWEN_SIZE_MAP = {
    "1:1": "2048*2048",
    "16:9": "2688*1536",
    "9:16": "1536*2688",
    "4:3": "2368*1728",
    "3:4": "1728*2368",
}
# qwen-image / plus / max only accept these fixed sizes.
QWEN_FIXED_SIZE_MAP = {
    "1:1": "1328*1328",
    "16:9": "1664*928",
    "4:3": "1472*1104",
    "3:4": "1104*1472",
    "9:16": "928*1664",
}
QWEN_FIXED_MODELS = ("qwen-image", "qwen-image-plus", "qwen-image-max")

ARK_SIZE_MAP = {
    "1:1": "2048x2048",
    "16:9": "2560x1440",
    "9:16": "1440x2560",
    "4:3": "2304x1728",
    "3:4": "1728x2304",
}

OPENAI_DALLE_SIZE_MAP = {
    "1:1": "1024x1024",
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "4:3": "1792x1024",
    "3:4": "1024x1792",
}
OPENAI_GPT_IMAGE_SIZE_MAP = {
    "1:1": "1024x1024",
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "4:3": "1536x1024",
    "3:4": "1024x1536",
}

DEFAULT_ICON_NEGATIVE_PROMPT = (
    "text, watermark, signature, low quality, blurry, distorted, cluttered"
)

# Rough per-image prices for --estimate-cost. Clearly approximate; vendors change
# pricing often. Values are in the provider's billing currency.
COST_TABLE = {
    "minimax": {"currency": "CNY", "per_image": 0.025},
    "qwen": {"currency": "CNY", "per_image": 0.35},
    "ark": {"currency": "CNY", "per_image": 0.20},
    "openai": {"currency": "USD", "per_image": 0.04},
    "openai-compatible": {"currency": "CNY", "per_image": 0.20},
}


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def load_env_file() -> None:
    """Load .env next to this module (only sets variables that are unset)."""
    env_path = SCRIPT_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_provider(provider: str | None) -> str:
    prov = (provider or os.environ.get("ICON_PROVIDER") or "minimax").strip().lower()
    if prov not in DEFAULT_HOSTS:
        raise SystemExit(
            f"ERROR: unknown provider '{prov}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    return prov


def _resolve_api_key(api_key: str | None, prov: str) -> str:
    key = api_key or os.environ.get("ICON_API_KEY")
    if not key and prov == "minimax":
        key = os.environ.get("MINIMAX_API_KEY")
    if not key and prov == "ark":
        key = os.environ.get("ARK_API_KEY")
    if not key and prov == "qwen":
        key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        hints = {
            "minimax": ", MINIMAX_API_KEY",
            "ark": ", ARK_API_KEY",
            "qwen": ", DASHSCOPE_API_KEY",
        }.get(prov, "")
        raise SystemExit(
            f"ERROR: API key not set for provider '{prov}'. "
            f"Use --api-key, ICON_API_KEY{hints}, or a .env file."
        )
    return key


def _resolve_host(host: str | None, prov: str) -> str:
    base = host or os.environ.get("ICON_API_HOST")
    if not base:
        if prov == "minimax":
            base = os.environ.get("MINIMAX_API_HOST", DEFAULT_HOSTS[prov])
        else:
            base = DEFAULT_HOSTS[prov]
    if not base:
        raise SystemExit(
            f"ERROR: API host required for provider '{prov}'. Use --host or set ICON_API_HOST."
        )
    return base.rstrip("/")


def resolve_image_config(
    provider: str | None,
    api_key: str | None,
    host: str | None,
    model: str | None,
) -> dict:
    load_env_file()
    prov = _resolve_provider(provider)
    cfg = {
        "provider": prov,
        "api_key": _resolve_api_key(api_key, prov),
        "host": _resolve_host(host, prov),
        "model": model or os.environ.get("ICON_MODEL") or DEFAULT_IMAGE_MODELS[prov],
    }
    if not cfg["model"]:
        raise SystemExit(
            f"ERROR: image model required for provider '{prov}'. Use --model or set ICON_MODEL."
        )
    return cfg


def resolve_vlm_config(
    provider: str | None,
    api_key: str | None,
    host: str | None,
    model: str | None,
) -> dict:
    load_env_file()
    prov = _resolve_provider(provider)
    cfg = {
        "provider": prov,
        "api_key": _resolve_api_key(api_key, prov),
        "host": _resolve_host(host, prov),
        "model": model
        or os.environ.get("ICON_VLM_MODEL")
        or DEFAULT_VLM_MODELS.get(prov, ""),
    }
    if not cfg["model"]:
        raise SystemExit(
            f"ERROR: VLM model required for provider '{prov}'. "
            "Use --vlm-model or set ICON_VLM_MODEL."
        )
    return cfg


def supports_negative(provider: str) -> bool:
    return NEGATIVE_SUPPORT.get(provider, False)


def supports_native_transparency(provider: str, model: str) -> bool:
    return provider == "openai" and model.startswith("gpt-image")


def estimate_cost(cfg: dict, n: int) -> dict:
    entry = COST_TABLE.get(cfg["provider"], {"currency": "?", "per_image": 0.0})
    return {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "images": n,
        "currency": entry["currency"],
        "unit": entry["per_image"],
        "total": round(entry["per_image"] * n, 3),
        "note": "approximate - verify against the vendor's current pricing",
    }


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


def _post_json(url: str, headers: dict, payload: dict, timeout: int = 180) -> dict:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                wait = float(resp.headers.get("Retry-After") or (2**attempt))
                print(
                    f"[warn] {resp.status_code} from provider; retrying in {wait:.0f}s "
                    f"({attempt + 1}/{MAX_RETRIES})",
                    file=sys.stderr,
                )
                time.sleep(min(wait, 30))
                continue
            if resp.status_code >= 400:
                body = resp.text[:400].replace("\n", " ")
                raise SystemExit(f"API ERROR [{resp.status_code}] {url}: {body}")
            return resp.json()
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(min(2**attempt, 8))
                continue
        except ValueError as exc:
            raise SystemExit(f"ERROR: provider returned non-JSON: {exc}") from exc
    raise SystemExit(
        f"ERROR: network failure after {MAX_RETRIES + 1} attempts: {last_error}"
    )


def _get_bytes(url: str, timeout: int = 60) -> bytes:
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.content
        except (requests.RequestException, OSError):
            if attempt == MAX_RETRIES:
                raise
            time.sleep(min(2**attempt, 8))
    raise RuntimeError("unreachable")


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #


class ImageResult:
    """A generated image as raw bytes and/or a downloadable URL."""

    def __init__(self, data: bytes | None = None, url: str | None = None):
        self.data = data
        self.url = url

    def fetch(self) -> bytes:
        if self.data is not None:
            return self.data
        if self.url:
            return _get_bytes(self.url)
        raise RuntimeError("ImageResult has neither data nor url")


def _openai_url(host: str, path_after_v1: str) -> str:
    h = host.rstrip("/")
    if h.endswith("/v1"):
        return h + path_after_v1
    return h + "/v1" + path_after_v1


# --------------------------------------------------------------------------- #
# image generation
# --------------------------------------------------------------------------- #


def generate_images(
    cfg: dict,
    prompt: str,
    n: int = 1,
    aspect_ratio: str = "1:1",
    seed: int | None = None,
    negative_prompt: str | None = None,
    transparent: bool = False,
) -> list[ImageResult]:
    prov = cfg["provider"]
    if prov == "minimax":
        return _gen_minimax(cfg, prompt, n, aspect_ratio, seed)
    if prov == "qwen":
        return _gen_qwen(cfg, prompt, n, aspect_ratio, seed, negative_prompt)
    if prov == "ark":
        return _gen_ark(cfg, prompt, n, aspect_ratio, seed)
    if prov in ("openai", "openai-compatible"):
        return _gen_openai(cfg, prompt, n, aspect_ratio, seed, transparent)
    raise SystemExit(f"ERROR: unsupported image provider '{prov}'")


def _gen_minimax(cfg, prompt, n, aspect_ratio, seed) -> list[ImageResult]:
    url = f"{cfg['host']}/v1/image_generation"
    payload: dict = {
        "model": cfg["model"],
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "n": n,
        "response_format": "base64",
        "prompt_optimizer": True,
        "aigc_watermark": False,
    }
    if seed is not None:
        payload["seed"] = seed
    result = _post_json(
        url,
        {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        payload,
        timeout=120,
    )
    base_resp = result.get("base_resp", {})
    if base_resp.get("status_code", -1) != 0:
        raise SystemExit(
            f"API ERROR [{base_resp.get('status_code')}]: {base_resp.get('status_msg', 'unknown')}"
        )
    data = result.get("data", {})
    results = [
        ImageResult(data=base64.b64decode(b64)) for b64 in data.get("image_base64", [])
    ]
    results += [ImageResult(url=u) for u in data.get("image_urls", [])]
    if not results:
        raise SystemExit("ERROR: no images in API response.")
    return results


def _gen_qwen(cfg, prompt, n, aspect_ratio, seed, negative_prompt) -> list[ImageResult]:
    url = f"{cfg['host']}/api/v1/services/aigc/multimodal-generation/generation"
    model = cfg["model"]
    size_map = QWEN_FIXED_SIZE_MAP if model in QWEN_FIXED_MODELS else QWEN_SIZE_MAP
    params: dict = {
        "prompt_extend": True,
        "watermark": False,
        "size": size_map.get(aspect_ratio, size_map["1:1"]),
    }
    # Fixed-size legacy models only return one image per call.
    if model not in QWEN_FIXED_MODELS:
        if n > 1:
            params["n"] = n
        if seed is not None:
            params["seed"] = seed
    neg = (
        negative_prompt if negative_prompt is not None else DEFAULT_ICON_NEGATIVE_PROMPT
    )
    if neg:
        params["negative_prompt"] = neg
    payload = {
        "model": model,
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": params,
    }
    result = _post_json(
        url,
        {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        payload,
        timeout=180,
    )
    if result.get("code"):
        raise SystemExit(
            f"API ERROR [{result.get('code')}]: {result.get('message', 'unknown')}"
        )
    results: list[ImageResult] = []
    for choice in result.get("output", {}).get("choices", []):
        for item in choice.get("message", {}).get("content", []):
            if item.get("image"):
                results.append(ImageResult(url=item["image"]))
    if not results:
        raise SystemExit("ERROR: no images in API response.")
    if len(results) < n and model in QWEN_FIXED_MODELS:
        for i in range(1, n):
            results.extend(
                _gen_qwen(
                    cfg,
                    prompt,
                    1,
                    aspect_ratio,
                    None if seed is None else seed + i,
                    negative_prompt,
                )
            )
    return results


def _gen_ark(cfg, prompt, n, aspect_ratio, seed) -> list[ImageResult]:
    url = f"{cfg['host']}/api/v3/images/generations"
    results: list[ImageResult] = []
    for i in range(n):
        payload: dict = {
            "model": cfg["model"],
            "prompt": prompt,
            "size": ARK_SIZE_MAP.get(aspect_ratio, ARK_SIZE_MAP["1:1"]),
            "response_format": "url",
            "watermark": False,
        }
        if "seedream-4" in cfg["model"] or "seedream-5" in cfg["model"]:
            # Guarantees exactly one image instead of a generated series.
            payload["sequential_image_generation"] = "disabled"
        if seed is not None:
            payload["seed"] = seed + i
        data = _post_json(
            url,
            {
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            payload,
            timeout=180,
        )
        if data.get("error"):
            err = data["error"]
            raise SystemExit(
                f"API ERROR [{err.get('code')}]: {err.get('message', 'unknown')}"
            )
        for item in data.get("data", []):
            if item.get("b64_json"):
                results.append(ImageResult(data=base64.b64decode(item["b64_json"])))
            elif item.get("url"):
                results.append(ImageResult(url=item["url"]))
    if not results:
        raise SystemExit("ERROR: no images in API response.")
    return results


def _gen_openai(cfg, prompt, n, aspect_ratio, seed, transparent) -> list[ImageResult]:
    url = _openai_url(cfg["host"], "/images/generations")
    model = cfg["model"]
    headers = {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": "application/json",
    }
    is_gpt_image = model.startswith("gpt-image")
    results: list[ImageResult] = []

    calls = 1 if is_gpt_image else n  # dall-e-3 only accepts n=1
    per_call = n if is_gpt_image else 1
    for i in range(calls):
        if is_gpt_image:
            payload: dict = {
                "model": model,
                "prompt": prompt,
                "n": per_call,
                "size": OPENAI_GPT_IMAGE_SIZE_MAP.get(aspect_ratio, "1024x1024"),
            }
            if transparent:
                payload["background"] = "transparent"
                payload["output_format"] = "png"
        else:
            payload = {
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": OPENAI_DALLE_SIZE_MAP.get(aspect_ratio, "1024x1024"),
                "response_format": "b64_json",
            }
            if seed is not None:
                payload["seed"] = seed + i
        data = _post_json(url, headers, payload, timeout=180)
        for item in data.get("data", []):
            if item.get("b64_json"):
                results.append(ImageResult(data=base64.b64decode(item["b64_json"])))
            elif item.get("url"):
                results.append(ImageResult(url=item["url"]))
    if not results:
        raise SystemExit("ERROR: no images in API response.")
    return results


# --------------------------------------------------------------------------- #
# VLM
# --------------------------------------------------------------------------- #


def vlm_analyze(
    cfg: dict, image_input: str | list[str], text_prompt: str, max_tokens: int = 1200
) -> str:
    prov = cfg["provider"]
    if prov == "minimax":
        url = f"{cfg['host']}/v1/chat/completions"
    elif prov == "qwen":
        url = f"{cfg['host']}/compatible-mode/v1/chat/completions"
    elif prov == "ark":
        url = f"{cfg['host']}/api/v3/chat/completions"
    else:
        url = _openai_url(cfg["host"], "/chat/completions")

    images = [image_input] if isinstance(image_input, str) else list(image_input)
    content: list[dict] = [{"type": "text", "text": text_prompt}]
    content.extend(
        {"type": "image_url", "image_url": {"url": url_or_data}}
        for url_or_data in images
    )
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    result = _post_json(
        url,
        {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        payload,
        timeout=120,
    )
    base_resp = result.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise SystemExit(f"API ERROR: {base_resp.get('status_msg', 'unknown')}")
    if result.get("code"):
        raise SystemExit(
            f"API ERROR [{result.get('code')}]: {result.get('message', 'unknown')}"
        )
    choices = result.get("choices", [])
    if not choices:
        raise SystemExit("ERROR: no response from VLM.")
    return choices[0].get("message", {}).get("content", "")
