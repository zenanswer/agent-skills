"""Multi-provider abstraction for image generation and VLM analysis.

Supported providers:
  - minimax           MiniMax native (image-01 + MiniMax-M1 VLM)
  - qwen              Aliyun DashScope (qwen-image-2.0-pro + qwen-vl-max)
  - openai            OpenAI official (DALL-E 3 + GPT-4o vision)
  - openai-compatible Any OpenAI-compatible gateway (SiliconFlow, Volcengine, ...)

Config resolution (highest first):
  1. CLI args (--provider / --model / --api-key / --host)
  2. Generic env vars: ICON_PROVIDER, ICON_API_KEY, ICON_API_HOST, ICON_MODEL,
                       ICON_VLM_MODEL
  3. Legacy env vars (minimax only): MINIMAX_API_KEY, MINIMAX_API_HOST
  4. .env file in the script directory
  5. Built-in defaults

This module is imported by generate_icon.py and analyze_style.py. It is NOT
meant to be run directly.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

try:
    import requests
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "ERROR: 'requests' not found. Run scripts with: uv run <script>.py ..."
    ) from e


SCRIPT_DIR = Path(__file__).resolve().parent

# ---- Defaults -------------------------------------------------------------

SUPPORTED_PROVIDERS = ("minimax", "qwen", "openai", "openai-compatible")

DEFAULT_HOSTS = {
    "minimax": "https://api.minimaxi.com",
    "qwen": "https://dashscope.aliyuncs.com",
    "openai": "https://api.openai.com",
    "openai-compatible": "",  # must be provided
}

DEFAULT_IMAGE_MODELS = {
    "minimax": "image-01",
    "qwen": "qwen-image-2.0-pro",
    "openai": "dall-e-3",
    "openai-compatible": "",  # must be provided
}

DEFAULT_VLM_MODELS = {
    "minimax": "MiniMax-M1",
    "qwen": "qwen-vl-max",
    "openai": "gpt-4o",
    "openai-compatible": "",  # must be provided
}

# Aspect ratio -> Qwen size string
QWEN_SIZE_MAP = {
    "1:1": "2048*2048",
    "16:9": "2688*1536",
    "9:16": "1536*2688",
    "4:3": "2368*1728",
    "3:4": "1728*2368",
}

# Aspect ratio -> OpenAI Images API size
OPENAI_SIZE_MAP = {
    "1:1": "1024x1024",
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "4:3": "1792x1024",
    "3:4": "1024x1792",
}

DEFAULT_ICON_NEGATIVE_PROMPT = (
    "text, watermark, signature, low quality, blurry, distorted, cluttered"
)


# ---- .env loading ---------------------------------------------------------

def load_env_file() -> None:
    """Load .env file from the script directory (only sets unset vars)."""
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


# ---- Config resolution ----------------------------------------------------

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
    if not key:
        hint = ", or MINIMAX_API_KEY" if prov == "minimax" else ""
        raise SystemExit(
            f"ERROR: API key not set for provider '{prov}'. "
            f"Use --api-key, ICON_API_KEY env{hint}, or a .env file."
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
            f"ERROR: API host required for provider '{prov}'. "
            "Use --host or set ICON_API_HOST."
        )
    return base.rstrip("/")


def resolve_image_config(
    provider: str | None,
    api_key: str | None,
    host: str | None,
    model: str | None,
) -> dict:
    """Resolve config for image generation."""
    load_env_file()
    prov = _resolve_provider(provider)
    key = _resolve_api_key(api_key, prov)
    base = _resolve_host(host, prov)
    mdl = model or os.environ.get("ICON_MODEL") or DEFAULT_IMAGE_MODELS[prov]
    if not mdl:
        raise SystemExit(
            f"ERROR: image model required for provider '{prov}'. "
            "Use --model or set ICON_MODEL."
        )
    return {"provider": prov, "api_key": key, "host": base, "model": mdl}


def resolve_vlm_config(
    provider: str | None,
    api_key: str | None,
    host: str | None,
    model: str | None,
) -> dict:
    """Resolve config for VLM (vision language model) analysis."""
    load_env_file()
    prov = _resolve_provider(provider)
    key = _resolve_api_key(api_key, prov)
    base = _resolve_host(host, prov)
    mdl = model or os.environ.get("ICON_VLM_MODEL") or DEFAULT_VLM_MODELS.get(prov, "")
    if not mdl:
        raise SystemExit(
            f"ERROR: VLM model required for provider '{prov}'. "
            "Use --vlm-model or set ICON_VLM_MODEL."
        )
    return {"provider": prov, "api_key": key, "host": base, "model": mdl}


# ---- URL helpers ----------------------------------------------------------

def _openai_url(host: str, path_after_v1: str) -> str:
    """Join host with an OpenAI-style path (path after /v1).

    Handles hosts that already include /v1 (e.g. SiliconFlow) and those that
    do not (e.g. https://api.openai.com).
    """
    h = host.rstrip("/")
    if h.endswith("/v1"):
        return h + path_after_v1
    return h + "/v1" + path_after_v1


# ---- Image result --------------------------------------------------------

class ImageResult:
    """A generated image, as raw bytes and/or a downloadable URL."""

    def __init__(self, data: bytes | None = None, url: str | None = None):
        self.data = data
        self.url = url

    def fetch(self) -> bytes:
        if self.data is not None:
            return self.data
        if self.url:
            resp = requests.get(self.url, timeout=60)
            resp.raise_for_status()
            return resp.content
        raise RuntimeError("ImageResult has neither data nor url")


# ---- Image generation -----------------------------------------------------

def generate_images(
    cfg: dict,
    prompt: str,
    n: int = 1,
    aspect_ratio: str = "1:1",
    seed: int | None = None,
    negative_prompt: str | None = None,
) -> list[ImageResult]:
    """Dispatch to the configured provider and return a list of ImageResult."""
    prov = cfg["provider"]
    if prov == "minimax":
        return _gen_minimax(cfg, prompt, n, aspect_ratio, seed)
    if prov == "qwen":
        return _gen_qwen(cfg, prompt, n, aspect_ratio, seed, negative_prompt)
    if prov in ("openai", "openai-compatible"):
        return _gen_openai(cfg, prompt, n, aspect_ratio, seed)
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
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    result = resp.json()
    base_resp = result.get("base_resp", {})
    if base_resp.get("status_code", -1) != 0:
        raise SystemExit(
            f"API ERROR [{base_resp.get('status_code')}]: "
            f"{base_resp.get('status_msg', 'unknown')}"
        )
    data = result.get("data", {})
    results: list[ImageResult] = []
    for b64 in data.get("image_base64", []):
        results.append(ImageResult(data=base64.b64decode(b64)))
    for img_url in data.get("image_urls", []):
        results.append(ImageResult(url=img_url))
    if not results:
        raise SystemExit("ERROR: no images in API response.")
    return results


def _gen_qwen(cfg, prompt, n, aspect_ratio, seed, negative_prompt) -> list[ImageResult]:
    url = f"{cfg['host']}/api/v1/services/aigc/multimodal-generation/generation"
    size = QWEN_SIZE_MAP.get(aspect_ratio, "2048*2048")
    params: dict = {"prompt_extend": True, "watermark": False, "size": size}
    if n > 1:
        params["n"] = n
    if seed is not None:
        params["seed"] = seed
    neg = negative_prompt if negative_prompt is not None else DEFAULT_ICON_NEGATIVE_PROMPT
    if neg:
        params["negative_prompt"] = neg
    payload = {
        "model": cfg["model"],
        "input": {
            "messages": [
                {"role": "user", "content": [{"text": prompt}]}
            ]
        },
        "parameters": params,
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    result = resp.json()
    if "code" in result:
        raise SystemExit(
            f"API ERROR [{result.get('code')}]: {result.get('message', 'unknown')}"
        )
    choices = result.get("output", {}).get("choices", [])
    results: list[ImageResult] = []
    for ch in choices:
        for c in ch.get("message", {}).get("content", []):
            if c.get("image"):
                results.append(ImageResult(url=c["image"]))
    if not results:
        raise SystemExit("ERROR: no images in API response.")
    return results


def _gen_openai(cfg, prompt, n, aspect_ratio, seed) -> list[ImageResult]:
    url = _openai_url(cfg["host"], "/images/generations")
    size = OPENAI_SIZE_MAP.get(aspect_ratio, "1024x1024")
    payload: dict = {
        "model": cfg["model"],
        "prompt": prompt,
        "n": n,
        "size": size,
        "response_format": "b64_json",
    }
    if seed is not None:
        payload["seed"] = seed
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    result = resp.json()
    results: list[ImageResult] = []
    for item in result.get("data", []):
        if item.get("b64_json"):
            results.append(ImageResult(data=base64.b64decode(item["b64_json"])))
        elif item.get("url"):
            results.append(ImageResult(url=item["url"]))
    if not results:
        raise SystemExit("ERROR: no images in API response.")
    return results


# ---- VLM (vision language model) -----------------------------------------

def vlm_analyze(cfg: dict, image_input: str, text_prompt: str, max_tokens: int = 600) -> str:
    """Call the VLM with an image (data URL or http URL) and a text prompt.

    Returns the model's text response.
    """
    prov = cfg["provider"]
    if prov == "minimax":
        return _vlm_minimax(cfg, image_input, text_prompt, max_tokens)
    if prov == "qwen":
        return _vlm_qwen(cfg, image_input, text_prompt, max_tokens)
    if prov in ("openai", "openai-compatible"):
        return _vlm_openai(cfg, image_input, text_prompt, max_tokens)
    raise SystemExit(f"ERROR: unsupported VLM provider '{prov}'")


def _vlm_payload(model, text_prompt, image_input, max_tokens):
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {"type": "image_url", "image_url": {"url": image_input}},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }


def _vlm_minimax(cfg, image_input, text_prompt, max_tokens) -> str:
    url = f"{cfg['host']}/v1/chat/completions"
    payload = _vlm_payload(cfg["model"], text_prompt, image_input, max_tokens)
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    base_resp = result.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        raise SystemExit(f"API ERROR: {base_resp.get('status_msg', 'unknown')}")
    choices = result.get("choices", [])
    if not choices:
        raise SystemExit("ERROR: no response from VLM.")
    return choices[0].get("message", {}).get("content", "")


def _vlm_qwen(cfg, image_input, text_prompt, max_tokens) -> str:
    # Qwen VL via DashScope OpenAI-compatible mode
    url = f"{cfg['host']}/compatible-mode/v1/chat/completions"
    payload = _vlm_payload(cfg["model"], text_prompt, image_input, max_tokens)
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    if "code" in result:
        raise SystemExit(
            f"API ERROR [{result.get('code')}]: {result.get('message', 'unknown')}"
        )
    choices = result.get("choices", [])
    if not choices:
        raise SystemExit("ERROR: no response from VLM.")
    return choices[0].get("message", {}).get("content", "")


def _vlm_openai(cfg, image_input, text_prompt, max_tokens) -> str:
    url = _openai_url(cfg["host"], "/chat/completions")
    payload = _vlm_payload(cfg["model"], text_prompt, image_input, max_tokens)
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    choices = result.get("choices", [])
    if not choices:
        raise SystemExit("ERROR: no response from VLM.")
    return choices[0].get("message", {}).get("content", "")
