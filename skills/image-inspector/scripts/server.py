#!/usr/bin/env python3
"""
MCP server: understand_image via any OpenAI-compatible multimodal LLM.

同一个技能的 CLI 入口是 scripts/vision.py（ask/ocr/extract/batch/tile/
ground2d/ground3d）；`vision.py serve` 会直接拉起本文件。两者共用同一套
LLM_API_URL / LLM_MODEL_NAME / LLM_API_KEY 配置。

Configure via environment variables:
    LLM_API_URL      Base URL of an OpenAI-compatible Chat Completions endpoint.
                     Examples:
                       https://api.openai.com/v1
                       https://dashscope.aliyuncs.com/compatible-mode/v1
                       http://localhost:11434/v1   (Ollama)
    LLM_MODEL_NAME   Model name with vision support (e.g. gpt-4o,
                     qwen-vl-max, llama3.2-vision).
    LLM_API_KEY      API key (Bearer token). Use any non-empty placeholder
                     for local servers that do not require auth (e.g. "ollama").
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    """读取技能目录的 .env（shell env 优先）。"""
    candidates = (
        Path(__file__).resolve().parent.parent / ".env",
        Path.home() / ".config" / "image-inspector" / ".env",
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        except OSError:
            pass


_load_dotenv()

API_BASE_URL = os.environ.get("LLM_API_URL", "").rstrip("/")
MODEL_NAME = os.environ.get("LLM_MODEL_NAME", "")
API_KEY = os.environ.get("LLM_API_KEY", "")

# When True (default), remote image URLs are fetched server-side and sent as
# base64 data URIs. This is REQUIRED for providers that cannot fetch remote
# URLs themselves (e.g. Aliyun Token Plan, which returns HTTP 400 "The
# provided URL does not appear to be valid" for a raw http(s) image_url).
# Set LLM_FETCH_REMOTE=false to pass URLs through unchanged for providers
# (e.g. OpenAI) that fetch images themselves.
FETCH_REMOTE = os.environ.get("LLM_FETCH_REMOTE", "true").strip().lower() in (
    "1", "true", "yes", "on",
)
MAX_IMAGE_BYTES = int(os.environ.get("LLM_IMAGE_MAX_BYTES", str(25 * 1024 * 1024)))

# Reasoning models (Qwen3 thinking variants) emit long reasoning chains before
# the answer, which can blow past the MCP client timeout (JSON-RPC -32001).
# Disable thinking by default; set LLM_ENABLE_THINKING=true to opt back in.
ENABLE_THINKING = os.environ.get("LLM_ENABLE_THINKING", "false").strip().lower() in (
    "1", "true", "yes", "on",
)
_THINKING_EXPLICIT = "LLM_ENABLE_THINKING" in os.environ

# Upstream vision API timeout (seconds).
REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("understand_image_mcp")


class UnderstandImageInput(BaseModel):
    """Input model for the understand_image tool."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",
    )

    image_source: str = Field(
        ...,
        description=(
            "Location of the image to analyze. Accepts an HTTP/HTTPS URL "
            "(passed directly to the model) OR a local file path "
            "(read and sent as base64). Examples: "
            "'https://example.com/photo.jpg', '/Users/me/pic.png', "
            "'./images/frame.webp'."
        ),
        min_length=1,
    )
    prompt: str = Field(
        ...,
        description=(
            "Question or instruction about the image. The agent can ask "
            "anything, e.g. 'Describe this screenshot', 'What error is "
            "shown?', 'Extract all text as JSON'."
        ),
        min_length=1,
    )
    max_tokens: Optional[int] = Field(
        default=1024,
        description="Maximum number of tokens to generate in the response.",
        ge=1,
        le=8192,
    )
    temperature: Optional[float] = Field(
        default=0.2,
        description="Sampling temperature (0.0 = deterministic, 1.0 = creative).",
        ge=0.0,
        le=2.0,
    )

    @field_validator("image_source", "prompt")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Parameter cannot be empty or whitespace only")
        return v.strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IMAGE_MIME_FALLBACK = "image/jpeg"


def _config_error() -> str:
    """Build an actionable error string when config is missing."""
    missing = []
    if not API_BASE_URL:
        missing.append("LLM_API_URL")
    if not MODEL_NAME:
        missing.append("LLM_MODEL_NAME")
    if not API_KEY:
        missing.append("LLM_API_KEY")
    return (
        "Error: understand_image_mcp is not configured. "
        f"Missing environment variable(s): {', '.join(missing)}. "
        "Set LLM_API_URL (OpenAI-compatible base URL), LLM_MODEL_NAME, and "
        "LLM_API_KEY before starting the server."
    )


def _is_remote(source: str) -> bool:
    return source.lower().startswith(("http://", "https://"))


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime and mime.startswith("image/"):
        return mime
    return _IMAGE_MIME_FALLBACK


async def _encode_local_image(path: str) -> Tuple[str, bytes]:
    """Read a local image file and return (mime_type, raw_bytes)."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    if not p.is_file():
        raise ValueError(f"Path is not a regular file: {path}")
    mime = _guess_mime(str(p))
    data = p.read_bytes()
    return mime, data


def _build_data_uri(mime: str, raw: bytes) -> str:
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def _fetch_remote_image(url: str) -> Tuple[str, bytes]:
    """Download a remote image and return (mime_type, raw_bytes)."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        mime = ctype if ctype.startswith("image/") else _guess_mime(url)
        raw = resp.content
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image too large: {len(raw)} bytes exceeds the "
            f"{MAX_IMAGE_BYTES}-byte limit (set LLM_IMAGE_MAX_BYTES to raise)."
        )
    return mime, raw


async def _to_image_url(source: str) -> str:
    """Resolve an image source into the image_url string the model expects.

    Local file -> base64 data URI. Remote URL -> base64 data URI when
    FETCH_REMOTE is true (default, universal), otherwise the raw URL is
    passed through for providers that fetch images themselves.
    """
    if _is_remote(source):
        if FETCH_REMOTE:
            mime, raw = await _fetch_remote_image(source)
            return _build_data_uri(mime, raw)
        return source
    mime, raw = await _encode_local_image(source)
    return _build_data_uri(mime, raw)


def _build_messages(image_url: str, prompt: str) -> List[Dict[str, Any]]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }
    ]


def _resolve_endpoint() -> str:
    """Join the configured base URL with the chat completions path."""
    base = API_BASE_URL.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _handle_api_error(e: Exception) -> str:
    """Consistent, actionable error formatting."""
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        body = ""
        try:
            body = e.response.text[:500]
        except Exception:
            pass
        hints = {
            401: "Authentication failed. Check that LLM_API_KEY is valid.",
            403: "Permission denied. The API key may lack access to this model.",
            404: "Endpoint or model not found. Check LLM_API_URL and LLM_MODEL_NAME.",
            429: "Rate limit exceeded. Wait and retry.",
        }
        hint = hints.get(status, "")
        suffix = f" | Response: {body}" if body else ""
        return f"Error: API request failed (HTTP {status}). {hint}{suffix}".strip()
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Try again or reduce max_tokens."
    if isinstance(e, httpx.ConnectError):
        return (
            "Error: Could not connect to the API. "
            "Check LLM_API_URL and network connectivity."
        )
    return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@mcp.tool(
    name="understand_image",
    annotations={
        "title": "Understand Image Content",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def understand_image(params: UnderstandImageInput) -> str:
    """Analyze an image with a multimodal LLM and answer a question about it.

    You MUST use this tool whenever you need to analyze, describe, or extract
    information from an image, including when you get an image from user input
    or any task-related image.

    The tool calls the configured OpenAI-compatible vision model and returns
    the model's text answer. Both remote URLs and local file paths are
    supported as image sources.

    Args:
        params (UnderstandImageInput): Validated input parameters containing:
            - image_source (str): HTTP(S) URL or local file path of the image.
              Supported formats (JPEG, PNG, WebP, GIF, etc.) depend on the
              configured model.
            - prompt (str): The question or instruction about the image.
            - max_tokens (Optional[int]): Max tokens to generate (default 1024).
            - temperature (Optional[float]): Sampling temperature (default 0.2).

    Returns:
        str: The model's textual answer to the prompt about the image.
             On configuration or API errors, returns an actionable
             "Error: ..." string describing the problem and how to fix it.

    Examples:
        - Describe a screenshot:
            image_source="/tmp/error.png", prompt="What error is shown?"
        - Analyze a remote photo:
            image_source="https://x.com/cat.jpg", prompt="Count the cats."
        - Extract structured data:
            image_source="./chart.png", prompt="Return the data as JSON."
    """
    if not (API_BASE_URL and MODEL_NAME and API_KEY):
        return _config_error()

    source = params.image_source
    prompt = params.prompt

    try:
        image_url = await _to_image_url(source)
    except httpx.HTTPStatusError as e:
        return f"Error: Could not fetch image '{source}' (HTTP {e.response.status_code})."
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        return (
            f"Error: Could not fetch image '{source}' ({type(e).__name__}). "
            "Check the URL/network or pass a local file path instead."
        )
    except (FileNotFoundError, ValueError) as e:
        return f"Error: Could not read image from '{source}'. {e}"

    endpoint = _resolve_endpoint()
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": MODEL_NAME,
        "messages": _build_messages(image_url, prompt),
        "max_tokens": params.max_tokens,
        "temperature": params.temperature,
    }
    # Only send enable_thinking to Qwen3 models or when explicitly configured;
    # other OpenAI-compatible endpoints may reject unknown fields.
    if "qwen3" in MODEL_NAME.lower() or _THINKING_EXPLICIT:
        payload["enable_thinking"] = ENABLE_THINKING

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001 - convert to actionable text
        return _handle_api_error(e)

    # Extract answer text. OpenAI-compatible responses nest content in
    # choices[0].message.content (string or list of content parts).
    choices = data.get("choices") or []
    if not choices:
        return json.dumps(data, indent=2, ensure_ascii=False)
    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p) or json.dumps(data, indent=2, ensure_ascii=False)
    return json.dumps(data, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
