#!/usr/bin/env python3
"""tech-scout-daily 的 LLM 公共工具：配置加载、Chat 调用、JSON 解析。

translate.py（翻译）与 rate.py（评分）共用，避免重复实现 OpenAI 兼容调用。
"""

import json
import os
import re
from pathlib import Path

import requests


def load_env_file() -> None:
    """把 ~/.config/tech-scout-daily/env 与 ./.env 的键值读进 os.environ。"""
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


load_env_file()

LLM_URL = os.environ.get("LLM_API_URL", "").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL_NAME", "")
LLM_KEY = os.environ.get("LLM_API_KEY", "")
# 评分与翻译都适合快模型；RATE_LLM_MODEL 未配则复用翻译模型
RATE_MODEL = (
    os.environ.get("RATE_LLM_MODEL")
    or os.environ.get("TRANSLATE_LLM_MODEL")
    or LLM_MODEL
)


def llm_available() -> bool:
    return bool(LLM_URL and LLM_MODEL and LLM_KEY)


def extract_json_array(text: str) -> list:
    """从模型输出里抠出 JSON 数组（容忍 ```json 围栏和前后解释文字）。"""
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start, end = body.find("["), body.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("no JSON array in response")
    return json.loads(body[start : end + 1])


def chat(
    prompt: str,
    model: str,
    *,
    temperature: float = 0,
    max_tokens: int = 4096,
    timeout: int = 180,
    disable_thinking: bool = True,
) -> str:
    """调用 OpenAI 兼容的 /chat/completions，返回首条消息内容。"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # Qwen3 的 thinking 会把短任务拖到几分钟；评分/翻译都不需要推理
    if disable_thinking and "qwen3" in model.lower():
        payload["enable_thinking"] = False
    resp = requests.post(
        f"{LLM_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {LLM_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
