#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27", "pillow>=10"]
# ///
"""vision — 图像理解 / OCR / 结构化抽取 / 2D・3D grounding。

只依赖 httpx + pillow；`uv run vision.py ...` 会自动装依赖。
MCP 形态见同目录 server.py（`vision.py serve` 直接拉起）。

配置（shell env 优先，其次技能目录 .env）:
  LLM_API_URL        OpenAI 兼容 base URL，例如
                     https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
  LLM_MODEL_NAME     多模态模型名，grounding 需要 qwen3-vl 系列
  LLM_API_KEY        Bearer token
可选:
  VISION_FALLBACKS   JSON 数组，主 provider 失败时依次尝试
                     [{"url": "...", "model": "...", "key": "..."}]
  VISION_FETCH_REMOTE  默认 true：远程图片本地抓取后转 base64（阿里云 Token Plan 必需）
  VISION_MAX_EDGE      默认 2048：发送前等比缩放到长边不超过该值
  VISION_TIMEOUT       默认 180 秒
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import base64
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    RESAMPLE = Image.LANCZOS

SKILL_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = Path.home() / ".cache" / "image-inspector"
EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


# ---------------------------------------------------------------- 配置


def load_env() -> None:
    """把技能目录/当前目录的 .env 读进 os.environ（shell env 优先）。"""
    for candidate in (
        SKILL_DIR / ".env",
        Path.home() / ".config" / "image-inspector" / ".env",
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
                key, value = key.strip(), value.strip().strip("\"'")
                os.environ.setdefault(key, value)
        except OSError:
            pass


load_env()

MAX_EDGE = int(os.environ.get("VISION_MAX_EDGE", "2048"))
TIMEOUT = float(os.environ.get("VISION_TIMEOUT", "180"))
FETCH_REMOTE = os.environ.get("VISION_FETCH_REMOTE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


class VisionError(Exception):
    pass


@dataclass
class Provider:
    name: str
    url: str
    model: str
    key: str


def load_providers(args: argparse.Namespace | None = None) -> list[Provider]:
    url = os.environ.get("LLM_API_URL", "").rstrip("/")
    model = os.environ.get("LLM_MODEL_NAME", "")
    key = os.environ.get("LLM_API_KEY", "")
    if args is not None:
        url = getattr(args, "api_url", None) or url
        model = getattr(args, "model", None) or model
        key = getattr(args, "api_key", None) or key
    missing = [
        name
        for name, value in (
            ("LLM_API_URL", url),
            ("LLM_MODEL_NAME", model),
            ("LLM_API_KEY", key),
        )
        if not value
    ]
    if missing:
        raise VisionError(
            "未配置 vision provider，缺少: "
            + ", ".join(missing)
            + "。参考 SKILL.md / references/providers.md 设置环境变量或 .env。"
        )
    providers = [Provider("primary", url, model, key)]
    raw = os.environ.get("VISION_FALLBACKS", "").strip()
    if raw:
        try:
            for i, item in enumerate(json.loads(raw), start=1):
                providers.append(
                    Provider(
                        f"fallback{i}",
                        str(item.get("url", "")).rstrip("/"),
                        str(item.get("model", "")),
                        str(item.get("key", "")),
                    )
                )
        except json.JSONDecodeError:
            raise VisionError("VISION_FALLBACKS 不是合法 JSON 数组")
    return [p for p in providers if p.url and p.model and p.key]


def model_family(model: str) -> str:
    m = model.lower()
    if "qwen3" in m or "qwen-3" in m:
        return "qwen3"
    if "qwen2.5" in m or "qwen2-5" in m or m.startswith("qwen-vl") or "qwen2-vl" in m:
        return "qwen2.5"
    return "other"


def capabilities(model: str) -> dict[str, bool]:
    family = model_family(model)
    return {
        "vision": True,
        "ground2d": family in ("qwen3", "qwen2.5"),
        "ground3d": family == "qwen3",
    }


# ---------------------------------------------------------------- 图片处理


def _read_source(source: str) -> tuple[bytes, str]:
    if source.lower().startswith(("http://", "https://")):
        if not FETCH_REMOTE:
            return b"", "url"
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
                resp = client.get(source)
                resp.raise_for_status()
                mime = resp.headers.get("content-type", "").split(";")[0].strip()
                return resp.content, mime or "image/jpeg"
        except httpx.HTTPError as exc:
            raise VisionError(f"下载图片失败 {source}: {exc}")
    path = Path(source).expanduser()
    if not path.is_file():
        raise VisionError(f"图片不存在: {source}")
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return path.read_bytes(), mime


def load_image(source: str) -> tuple[Image.Image, bytes, str]:
    raw, mime = _read_source(source)
    if mime == "url":
        return Image.new("RGB", (1, 1)), b"", mime
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img.load()
    except (OSError, ValueError) as exc:
        raise VisionError(f"无法解析图片 {source}: {exc}")
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return img, raw, mime


def encode_image(source: str) -> dict:
    """→ {data_uri|url, orig_size, sent_size, sha}"""
    img, raw, mime = load_image(source)
    if mime == "url":
        return {
            "url": source,
            "orig_size": None,
            "sent_size": None,
            "sha": hashlib.sha256(source.encode()).hexdigest(),
        }
    orig_size = img.size
    sent = img.copy()
    if max(sent.size) > MAX_EDGE:
        sent.thumbnail((MAX_EDGE, MAX_EDGE), RESAMPLE)
    buf = io.BytesIO()
    sent.save(buf, format="JPEG", quality=90)
    payload = buf.getvalue()
    return {
        "data_uri": "data:image/jpeg;base64," + base64.b64encode(payload).decode(),
        "orig_size": list(orig_size),
        "sent_size": list(sent.size),
        "sha": hashlib.sha256(payload).hexdigest(),
    }


def encode_remote_or_local(source: str) -> dict:
    info = encode_image(source)
    if "url" in info and not FETCH_REMOTE:
        info["image_url"] = source
    else:
        info["image_url"] = info.pop("data_uri")
    return info


# ---------------------------------------------------------------- HTTP


def _endpoint(base: str) -> str:
    base = base.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


async def _post(provider: Provider, payload: dict) -> str:
    headers = {
        "Authorization": f"Bearer {provider.key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                _endpoint(provider.url), headers=headers, json=payload
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        body = ""
        try:
            body = exc.response.text[:300]
        except Exception:
            pass
        hint = {
            401: "鉴权失败，检查 LLM_API_KEY",
            403: "无权限，检查 key 是否开通该模型",
            404: "端点或模型不存在，检查 LLM_API_URL / LLM_MODEL_NAME",
            429: "限流，稍后重试或切换 fallback provider",
        }.get(status, "")
        raise VisionError(f"HTTP {status} {hint} {body}".strip())
    except httpx.TimeoutException:
        raise VisionError(f"请求超时（{TIMEOUT}s）")
    except httpx.HTTPError as exc:
        raise VisionError(f"连接失败: {exc}")
    choices = data.get("choices") or []
    if not choices:
        return json.dumps(data, ensure_ascii=False)
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return json.dumps(data, ensure_ascii=False)


async def chat(
    providers: list[Provider],
    image_url: str | None,
    prompt: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    cache_key: str | None = None,
    use_cache: bool = True,
) -> tuple[str, str]:
    if use_cache and cache_key:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached, "cache"
    errors = []
    for provider in providers:
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_url:
            content.insert(0, {"type": "image_url", "image_url": {"url": image_url}})
        payload = {
            "model": provider.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            text = await _post(provider, payload)
        except VisionError as exc:
            errors.append(f"{provider.name}({provider.model}): {exc}")
            continue
        if use_cache and cache_key:
            _cache_put(cache_key, text)
        return text, provider.name
    raise VisionError("所有 provider 均失败:\n  " + "\n  ".join(errors))


def _cache_path(key: str) -> Path:
    return CACHE_DIR / key[:2] / f"{key}.json"


def _cache_get(key: str) -> str | None:
    path = _cache_path(key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("text")
    except (OSError, json.JSONDecodeError):
        return None


def _cache_put(key: str, text: str) -> None:
    path = _cache_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"text": text, "ts": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def cache_key(parts: dict) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------- 解析


def extract_json(text: str):
    """从模型回复里抠出 JSON（兼容围栏/单引号/尾随文字/被 max_tokens 截断）。"""
    body = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    elif "```" in body:
        body = re.sub(r"^\s*json\s*", "", body.split("```", 1)[1])

    for opener, closer in (("[", "]"), ("{", "}")):
        start = body.find(opener)
        if start == -1:
            continue
        tail = body[start:]
        candidates = []
        end = tail.rfind(closer)
        if end > 0:
            candidates.append(tail[: end + 1])
        # 截断修复：保留最后一个完整对象，补右括号
        last_complete = tail.rfind("}")
        if last_complete > 0:
            repaired = tail[: last_complete + 1].rstrip().rstrip(",")
            if opener == "[" and not repaired.endswith("]"):
                candidates.append(repaired + "]")
            candidates.append(repaired)
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                try:
                    return ast.literal_eval(candidate)
                except (ValueError, SyntaxError):
                    continue
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise VisionError(
            "模型没有返回可解析的 JSON（可能被 max_tokens 截断，"
            "可调大 --max-tokens）：" + text[:200]
        )


# ---------------------------------------------------------------- grounding


COORD_MODES = ("auto", "rel1000", "abs", "norm1")


def resolve_coord(mode: str, model: str) -> str:
    if mode != "auto":
        return mode
    family = model_family(model)
    return "rel1000" if family == "qwen3" else "abs"


def norm_to_px(value: float, dim: int, coord: str, sent_dim: int | None) -> int:
    if coord == "rel1000":
        px = value / 1000.0 * dim
    elif coord == "norm1":
        px = value * dim
    elif coord == "abs":
        if not sent_dim:
            raise VisionError(
                "abs 坐标模式需要 --sent-size（模型返回的是服务端 resize 后的绝对像素）"
            )
        px = value * dim / sent_dim
    else:
        raise VisionError(f"未知坐标模式: {coord}")
    return max(0, min(dim, int(round(px))))


def parse_bbox2d(result, coord: str, orig, sent) -> list[dict]:
    items = result if isinstance(result, list) else [result]
    objects = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("bbox_2d") or item.get("bbox")
        if not raw or len(raw) < 4:
            continue
        try:
            x1, y1, x2, y2 = (float(v) for v in raw[:4])
        except (TypeError, ValueError):
            continue
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        objects.append(
            {
                "label": str(item.get("label") or item.get("type") or "object"),
                "bbox_2d_norm": [
                    round(x1, 1),
                    round(y1, 1),
                    round(x2, 1),
                    round(y2, 1),
                ],
                "bbox_2d": [
                    norm_to_px(x1, orig[0], coord, sent[0]),
                    norm_to_px(y1, orig[1], coord, sent[1]),
                    norm_to_px(x2, orig[0], coord, sent[0]),
                    norm_to_px(y2, orig[1], coord, sent[1]),
                ],
                "raw": item,
            }
        )
    return objects


def parse_points2d(result, coord: str, orig, sent) -> list[dict]:
    items = result if isinstance(result, list) else [result]
    points = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("point_2d") or item.get("point")
        if not raw or len(raw) < 2:
            continue
        try:
            x, y = float(raw[0]), float(raw[1])
        except (TypeError, ValueError):
            continue
        points.append(
            {
                "label": str(item.get("label") or "point"),
                "point_2d_norm": [round(x, 1), round(y, 1)],
                "point_2d": [
                    norm_to_px(x, orig[0], coord, sent[0]),
                    norm_to_px(y, orig[1], coord, sent[1]),
                ],
                "raw": item,
            }
        )
    return points


def bbox2d_prompt(target: str, point: bool = False) -> str:
    if point:
        return (
            f"Locate every {target} in the image with points. Report point "
            "coordinates in JSON format like this: "
            '{"point_2d": [x, y], "label": "..."}'
        )
    return (
        "Locate every instance that belongs to the following categories: "
        f'"{target}". Report bbox coordinates in JSON format like this: '
        '{"bbox_2d": [x1, y1, x2, y2], "label": "..."}'
    )


def bbox3d_prompt(target: str) -> str:
    return (
        f"Find all {target} in this image. For each, provide its 3D bounding "
        "box. The output format required is JSON: "
        '[{"bbox_3d":[x_center, y_center, z_center, x_size, y_size, z_size, '
        'roll, pitch, yaw],"label":"category"}].'
    )


def parse_bbox3d(result) -> list[dict]:
    items = result if isinstance(result, list) else [result]
    objects = []
    for item in items:
        if isinstance(item, dict) and "bbox_3d" in item:
            raw, label = item["bbox_3d"], item.get("label", "object")
        elif isinstance(item, list) and len(item) >= 9:
            raw, label = item, "object"
        else:
            continue
        if len(raw) < 9:
            continue
        try:
            values = [float(v) for v in raw[:9]]
        except (TypeError, ValueError):
            continue
        objects.append(
            {
                "label": str(label),
                "bbox_3d": values,
                "bbox_3d_named": dict(
                    zip(
                        [
                            "x",
                            "y",
                            "z",
                            "x_size",
                            "y_size",
                            "z_size",
                            "roll",
                            "pitch",
                            "yaw",
                        ],
                        values,
                    )
                ),
            }
        )
    return objects


def _angles_to_rad(bbox: list[float], unit: str) -> list[float]:
    out = []
    for v in bbox[6:9]:
        if unit == "pi":
            out.append(v * 3.141592653589793)
        elif unit == "deg":
            out.append(v * 3.141592653589793 / 180.0)
        else:
            out.append(v)
    return out


def _rotate(point, pitch, yaw, roll):
    x0, y0, z0 = point
    x1 = x0
    y1 = y0 * math.cos(pitch) - z0 * math.sin(pitch)
    z1 = y0 * math.sin(pitch) + z0 * math.cos(pitch)
    x2 = x1 * math.cos(yaw) + z1 * math.sin(yaw)
    y2 = y1
    z2 = -x1 * math.sin(yaw) + z1 * math.cos(yaw)
    x3 = x2 * math.cos(roll) - y2 * math.sin(roll)
    y3 = x2 * math.sin(roll) + y2 * math.cos(roll)
    return x3, y3, z2


def intrinsics_for(size: tuple[int, int], cam: str | None, fov: float) -> dict:
    import math

    width, height = size
    if cam:
        try:
            fx, fy, cx, cy = (float(v) for v in cam.split(","))
        except ValueError:
            raise VisionError("--cam 格式应为 fx,fy,cx,cy")
        return {"fx": fx, "fy": fy, "cx": cx, "cy": cy, "source": "user"}
    fx = round(width / (2 * math.tan(math.radians(fov) / 2)), 2)
    fy = round(height / (2 * math.tan(math.radians(fov) / 2)), 2)
    return {
        "fx": fx,
        "fy": fy,
        "cx": round(width / 2, 2),
        "cy": round(height / 2, 2),
        "source": f"assumed-fov{int(fov)}",
    }


def project_bbox3d(
    bbox: list[float], cam: dict, angle_unit: str, rot_order: str
) -> dict | None:
    import math

    x, y, z, sx, sy, sz = bbox[:6]
    a, b, c = _angles_to_rad(bbox, angle_unit)
    if rot_order == "code":
        pitch, yaw, roll = a, b, c  # cookbook: 第三个参数被当作 pitch 使用
    else:
        roll, pitch, yaw = a, b, c
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    corners = [
        (hx, hy, hz),
        (hx, hy, -hz),
        (hx, -hy, hz),
        (hx, -hy, -hz),
        (-hx, hy, hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (-hx, -hy, -hz),
    ]
    projected = []
    for corner in corners:
        rx, ry, rz = _rotate(corner, pitch, yaw, roll)
        X, Y, Z = rx + x, ry + y, rz + z
        if Z <= 1e-6:
            return None
        projected.append(
            [
                int(cam["fx"] * (X / Z) + cam["cx"]),
                int(cam["fy"] * (Y / Z) + cam["cy"]),
            ]
        )
    xs = [p[0] for p in projected]
    ys = [p[1] for p in projected]
    return {
        "corners": projected,
        "bbox_2d": [min(xs), min(ys), max(xs), max(ys)],
    }


# ---------------------------------------------------------------- 绘图


def _font(size: int = 14):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size), size
            except OSError:
                continue
    try:
        return ImageFont.load_default(size), size
    except TypeError:
        return ImageFont.load_default(), size


def draw_boxes(source: str, objects: list[dict], out: str, points: bool = False) -> str:
    img, _, _ = load_image(source)
    draw = ImageDraw.Draw(img)
    font, fsize = _font(max(12, int(min(img.size) / 60)))
    palette = [
        "#e6194b",
        "#3cb44b",
        "#4363d8",
        "#f58231",
        "#911eb4",
        "#008080",
        "#9a6324",
        "#800000",
        "#808000",
        "#000075",
    ]
    for i, obj in enumerate(objects):
        color = palette[i % len(palette)]
        if points:
            x, y = obj["point_2d"]
            r = 6
            draw.ellipse([x - r, y - r, x + r, y + r], outline=color, width=3)
            draw.text((x + r + 2, y - r), obj["label"], fill=color, font=font)
        else:
            x1, y1, x2, y2 = obj["bbox_2d"]
            draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
            draw.text(
                (x1 + 3, max(0, y1 - fsize - 2)),
                obj["label"],
                fill=color,
                font=font,
            )
    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return str(path)


def draw_boxes3d(source: str, objects: list[dict], out: str) -> str:
    img, _, _ = load_image(source)
    draw = ImageDraw.Draw(img)
    font, fsize = _font(max(12, int(min(img.size) / 60)))
    edges = [
        (0, 1),
        (2, 3),
        (4, 5),
        (6, 7),
        (0, 2),
        (1, 3),
        (4, 6),
        (5, 7),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    palette = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4"]
    for i, obj in enumerate(objects):
        projected = obj.get("projection")
        if not projected:
            continue
        color = palette[i % len(palette)]
        corners = projected["corners"]
        for a, b in edges:
            draw.line([tuple(corners[a]), tuple(corners[b])], fill=color, width=2)
        x1, y1, _, _ = projected["bbox_2d"]
        draw.text((x1 + 3, max(0, y1 - fsize - 2)), obj["label"], fill=color, font=font)
    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return str(path)


# ---------------------------------------------------------------- 命令


def _prepare(args) -> tuple[list[Provider], dict]:
    providers = load_providers(args)
    info = encode_remote_or_local(args.image)
    return providers, info


def _print_or_json(args, payload: dict, human: str) -> None:
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(human)


def cmd_ask(args) -> int:
    providers, info = _prepare(args)
    key = cache_key(
        {
            "sha": info["sha"],
            "p": args.prompt,
            "m": f"{args.max_tokens}",
            "t": f"{args.temperature}",
        }
    )
    text, _ = asyncio.run(
        chat(
            providers,
            info["image_url"],
            args.prompt,
            args.max_tokens,
            args.temperature,
            key,
            not args.no_cache,
        )
    )
    payload = {
        "model": providers[0].model,
        "image": args.image,
        "image_size": info["orig_size"],
        "sent_size": info["sent_size"],
        "text": text,
    }
    _print_or_json(args, payload, text)
    return EXIT_OK


def cmd_describe(args) -> int:
    args.prompt = (
        "Describe this image concisely: what it shows, any text, "
        "and anything unusual. Answer in the user's language if obvious."
    )
    return cmd_ask(args)


def cmd_ocr(args) -> int:
    lang = {"zh": "Chinese", "en": "English", "auto": "the original"}.get(
        args.lang, args.lang
    )
    args.prompt = (
        f"Extract all text from this image in reading order. Preserve line "
        f"breaks, keep {lang} as-is (do not translate). Output plain text only."
    )
    return cmd_ask(args)


def validate_schema(value, schema: dict, path: str = "$") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
    }
    if expected and not isinstance(value, type_map.get(expected, object)):
        return [f"{path}: 期望 {expected}"]
    if expected == "object":
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}.{name}: 缺少必填字段")
        for name, sub in (schema.get("properties") or {}).items():
            if name in value:
                errors.extend(validate_schema(value[name], sub, f"{path}.{name}"))
    if expected == "array" and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            errors.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))
    return errors


def cmd_extract(args) -> int:
    try:
        schema = json.loads(Path(args.schema).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisionError(f"无法读取 schema: {exc}")
    providers, info = _prepare(args)
    base_prompt = args.prompt or "Extract the requested data from this image."
    prompt = (
        f"{base_prompt}\nReturn ONLY valid JSON that conforms to this JSON "
        f"Schema (no markdown, no commentary):\n{json.dumps(schema, ensure_ascii=False)}"
    )
    text, _ = asyncio.run(
        chat(
            providers,
            info["image_url"],
            prompt,
            args.max_tokens,
            args.temperature,
            None,
            False,
        )
    )
    errors: list[str] = []
    for attempt in range(2):
        try:
            data = extract_json(text)
        except VisionError as exc:
            errors = [str(exc)]
        else:
            errors = validate_schema(data, schema)
            if not errors:
                payload = {
                    "image": args.image,
                    "data": data,
                    "attempt": attempt + 1,
                    "raw": text,
                }
                _print_or_json(
                    args, payload, json.dumps(data, ensure_ascii=False, indent=2)
                )
                return EXIT_OK
        if attempt == 0:
            fix = (
                f"{prompt}\n\nYour previous answer was invalid: {'; '.join(errors)}. "
                "Return corrected JSON only."
            )
            text, _ = asyncio.run(
                chat(
                    providers,
                    info["image_url"],
                    fix,
                    args.max_tokens,
                    args.temperature,
                    None,
                    False,
                )
            )
    raise VisionError("结构化抽取失败: " + "; ".join(errors))


def _iter_glob(pattern: str) -> list[str]:
    from glob import glob

    return sorted(p for p in glob(pattern, recursive=True) if Path(p).is_file())


def cmd_batch(args) -> int:
    paths = _iter_glob(args.glob)
    if not paths:
        raise VisionError(f"没有匹配的文件: {args.glob}")
    providers = load_providers(args)
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max(1, args.jobs))

    async def worker(path: str) -> dict:
        async with semaphore:
            try:
                info = encode_remote_or_local(path)
                key = cache_key(
                    {"sha": info["sha"], "p": args.prompt, "m": str(args.max_tokens)}
                )
                text, _ = await chat(
                    providers,
                    info["image_url"],
                    args.prompt,
                    args.max_tokens,
                    args.temperature,
                    key,
                    not args.no_cache,
                )
                return {"image": path, "ok": True, "text": text}
            except VisionError as exc:
                return {"image": path, "ok": False, "error": str(exc)}

    async def run_all():
        return await asyncio.gather(*(worker(p) for p in paths))

    results = asyncio.run(run_all())
    with out_path.open("w", encoding="utf-8") as fh:
        for row in results:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    failed = [r for r in results if not r["ok"]]
    print(
        f"处理 {len(results)} 张，成功 {len(results) - len(failed)}，失败 {len(failed)}"
    )
    print(f"结果: {out_path}")
    for row in failed[:10]:
        print(f"  失败 {row['image']}: {row['error']}")
    return EXIT_OK if not failed else EXIT_FAIL


def cmd_tile(args) -> int:
    providers = load_providers(args)
    img, _, _ = load_image(args.image)
    width, height = img.size
    overlap = int(height * 0.1)
    step = max(1, args.tile_height - overlap)
    tiles = [(y, min(y + args.tile_height, height)) for y in range(0, height, step)]
    pieces: list[str] = []
    for index, (top, bottom) in enumerate(tiles, start=1):
        crop = img.crop((0, top, width, bottom))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=90)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        prompt = (
            f"{args.prompt}\nThis is part {index}/{len(tiles)} of a taller "
            f"image (rows {top}-{bottom}); return the content of this part only."
        )
        text, _ = asyncio.run(
            chat(
                providers,
                uri,
                prompt,
                args.max_tokens,
                args.temperature,
                None,
                not args.no_cache,
            )
        )
        pieces.append(text.strip())
    merged = "\n".join(pieces)
    if args.json:
        print(
            json.dumps(
                {
                    "image": args.image,
                    "size": [width, height],
                    "tiles": len(tiles),
                    "parts": pieces,
                    "text": merged,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(merged)
    return EXIT_OK


def _grounding_guard(model: str, kind: str, force: bool) -> None:
    caps = capabilities(model)
    if caps.get(kind):
        return
    if force:
        print(
            f"警告: 模型 {model} 未声明支持 {kind}，结果可能不可用（--force）。",
            file=sys.stderr,
        )
        return
    raise VisionError(
        f"模型 {model} 不支持 {kind}。2D/3D grounding 需要 qwen3-vl 系列；"
        "请用 --model 指定，或设置 LLM_MODEL_NAME=qwen3-vl-*。"
        "确需尝试可加 --force。"
    )


def cmd_ground2d(args) -> int:
    providers = load_providers(args)
    model = getattr(args, "model", None) or providers[0].model
    _grounding_guard(model, "ground2d", args.force)
    coord = resolve_coord(args.coord, model)
    info = encode_remote_or_local(args.image)
    if not info.get("orig_size"):
        raise VisionError(
            "grounding 需要本地图片，或设置 VISION_FETCH_REMOTE=true 以抓取远程图片"
        )
    if coord == "abs" and not args.sent_size:
        raise VisionError(
            "qwen2.5-vl 返回的是服务端 resize 后的绝对坐标，必须提供 --sent-size WxH；"
            "推荐改用 qwen3-vl（0-1000 相对坐标，不需要该参数）。"
        )
    sent = info["sent_size"]
    if args.sent_size:
        try:
            sent = [int(v) for v in args.sent_size.lower().split("x")]
        except ValueError:
            raise VisionError("--sent-size 格式应为 WxH，例如 1280x720")
    prompt = args.prompt or ""
    built = bbox2d_prompt(prompt, point=args.point)
    text, _ = asyncio.run(
        chat(
            providers,
            info["image_url"],
            built,
            args.max_tokens,
            args.temperature,
            None,
            not args.no_cache,
        )
    )
    try:
        result = extract_json(text)
    except VisionError:
        # 模型可能明确回答「没有该类目标」，这不算错误
        result = []
    orig = info["orig_size"] or [0, 0]
    if args.point:
        objects = parse_points2d(result, coord, orig, sent)
    else:
        objects = parse_bbox2d(result, coord, orig, sent)
    payload = {
        "image": args.image,
        "model": model,
        "coord": coord,
        "image_size": orig,
        "sent_size": sent,
        "prompt": built,
        "objects": objects,
        "raw": text,
        "note": "" if objects else text.strip()[:200],
    }
    if args.draw and objects:
        payload["drawn"] = draw_boxes(args.image, objects, args.draw, points=args.point)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        kind = "点" if args.point else "框"
        print(f"{len(objects)} 个{kind}（coord={coord}，原图 {orig[0]}x{orig[1]}）")
        for obj in objects:
            coords = obj.get("point_2d") or obj.get("bbox_2d")
            print(f"  {obj['label']}: {coords}")
        if payload.get("drawn"):
            print(f"标注图: {payload['drawn']}")
    return EXIT_OK


def cmd_ground3d(args) -> int:
    providers = load_providers(args)
    model = getattr(args, "model", None) or providers[0].model
    _grounding_guard(model, "ground3d", args.force)
    info = encode_remote_or_local(args.image)
    if not info.get("orig_size"):
        raise VisionError(
            "grounding 需要本地图片，或设置 VISION_FETCH_REMOTE=true 以抓取远程图片"
        )
    orig = info["orig_size"]
    prompt = bbox3d_prompt(args.prompt)
    text, _ = asyncio.run(
        chat(
            providers,
            info["image_url"],
            prompt,
            args.max_tokens,
            args.temperature,
            None,
            not args.no_cache,
        )
    )
    try:
        result = extract_json(text)
    except VisionError:
        result = []
    objects = parse_bbox3d(result)
    cam = intrinsics_for(tuple(orig), args.cam, args.fov)
    for obj in objects:
        obj["projection"] = project_bbox3d(
            obj["bbox_3d"], cam, args.angle_unit, args.rot_order
        )
        obj["bbox_2d"] = (obj["projection"] or {}).get("bbox_2d")
    payload = {
        "image": args.image,
        "model": model,
        "prompt": prompt,
        "image_size": orig,
        "intrinsics": cam,
        "angle_unit": args.angle_unit,
        "rot_order": args.rot_order,
        "objects": objects,
        "raw": text,
        "note": "" if objects else text.strip()[:200],
    }
    if args.draw and objects:
        payload["drawn"] = draw_boxes3d(args.image, objects, args.draw)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"{len(objects)} 个 3D 框（内参 {cam['source']}，角度单位 {args.angle_unit}）"
        )
        for obj in objects:
            b = obj["bbox_3d_named"]
            print(
                f"  {obj['label']}: center=({b['x']}, {b['y']}, {b['z']})m "
                f"size=({b['x_size']}, {b['y_size']}, {b['z_size']})m"
            )
        if payload.get("drawn"):
            print(f"标注图: {payload['drawn']}")
        if cam["source"].startswith("assumed"):
            print("注意: 没有真实相机内参，3D 框仅示意，不要据此给出精确距离。")
    return EXIT_OK


def cmd_providers(args) -> int:
    providers = load_providers(args)
    rows = []
    for p in providers:
        caps = capabilities(p.model)
        rows.append(
            {
                "name": p.name,
                "url": p.url,
                "model": p.model,
                "family": model_family(p.model),
                **caps,
            }
        )
        if args.probe:
            key = None
            text, used = asyncio.run(
                chat([p], None, "Reply with OK only.", 8, 0.0, key, False)
            )
            rows[-1]["probe"] = text.strip()[:80]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            flags = ",".join(k for k in ("vision", "ground2d", "ground3d") if row[k])
            print(
                f"{row['name']}: {row['model']} [{row['family']}] "
                f"{row['url']} → {flags}"
            )
            if "probe" in row:
                print(f"  probe: {row['probe']}")
    if not capabilities(providers[0].model)["ground2d"]:
        print(
            "提示: 当前模型不支持 grounding；需要 2D/3D 定位请配置 qwen3-vl 模型。",
            file=sys.stderr,
        )
    return EXIT_OK


def cmd_serve(args) -> int:
    server = SKILL_DIR / "scripts" / "server.py"
    os.execv(sys.executable, [sys.executable, str(server)])
    return EXIT_OK


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vision", description="图像理解 / OCR / 结构化抽取 / 2D・3D grounding"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, image: bool = True):
        if image:
            p.add_argument("-i", "--image", required=True, help="本地路径或 URL")
        p.add_argument("--json", action="store_true")
        p.add_argument("--model")
        p.add_argument("--api-url")
        p.add_argument("--api-key")
        p.add_argument("--max-tokens", type=int, default=1024)
        p.add_argument("--temperature", type=float, default=0.0)
        p.add_argument("--no-cache", action="store_true")

    p = sub.add_parser("ask", help="单张问答")
    common(p)
    p.add_argument("-p", "--prompt", required=True)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("describe", help="描述图片")
    common(p)
    p.set_defaults(func=cmd_describe)

    p = sub.add_parser("ocr", help="提取文字")
    common(p)
    p.add_argument("--lang", default="auto")
    p.set_defaults(func=cmd_ocr)

    p = sub.add_parser("extract", help="按 JSON Schema 结构化抽取")
    common(p)
    p.add_argument("--schema", required=True)
    p.add_argument("-p", "--prompt")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("batch", help="批量处理图片")
    p.add_argument("--glob", required=True)
    p.add_argument("-p", "--prompt", required=True)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--out", default="vision-batch.jsonl")
    p.add_argument("--json", action="store_true")
    p.add_argument("--model")
    p.add_argument("--api-url")
    p.add_argument("--api-key")
    p.add_argument("--max-tokens", type=int, default=512)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--no-cache", action="store_true")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("tile", help="长图切块识别")
    common(p)
    p.add_argument("-p", "--prompt", required=True)
    p.add_argument("--tile-height", type=int, default=1200)
    p.set_defaults(func=cmd_tile)

    p = sub.add_parser("ground2d", help="2D grounding（框/点）")
    common(p)
    p.add_argument("-p", "--prompt", required=True, help="目标，如 'car, bus'")
    p.add_argument("--point", action="store_true", help="输出点而不是框")
    p.add_argument("--coord", choices=COORD_MODES, default="auto")
    p.add_argument("--sent-size", help="abs 坐标模式下模型实际看到的尺寸 WxH")
    p.add_argument("--draw", help="输出标注图路径")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_ground2d, max_tokens=2048)

    p = sub.add_parser("ground3d", help="3D grounding（Qwen3-VL）")
    common(p)
    p.add_argument("-p", "--prompt", required=True, help="目标，如 'all cars'")
    p.add_argument("--cam", help="相机内参 fx,fy,cx,cy（原图像素）")
    p.add_argument("--fov", type=float, default=60.0)
    p.add_argument("--angle-unit", choices=("pi", "rad", "deg"), default="pi")
    p.add_argument("--rot-order", choices=("code", "spec"), default="code")
    p.add_argument("--draw", help="输出标注图路径")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_ground3d, max_tokens=2048)

    p = sub.add_parser("providers", help="查看配置与能力")
    p.add_argument("--json", action="store_true")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--model")
    p.add_argument("--api-url")
    p.add_argument("--api-key")
    p.set_defaults(func=cmd_providers)

    p = sub.add_parser("serve", help="启动 MCP server")
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except VisionError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
