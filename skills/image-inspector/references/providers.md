# Providers 与配置

## 必填

| 变量 | 说明 | 示例 |
|---|---|---|
| `LLM_API_URL` | OpenAI 兼容 base URL（自动补 `/chat/completions`） | `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` |
| `LLM_MODEL_NAME` | 多模态模型名 | `qwen3.7-plus` |
| `LLM_API_KEY` | Bearer token | `sk-...` |

优先级：shell 环境变量 > 技能目录 `.env` > 当前目录 `.env`。

## 可选

| 变量 | 默认 | 说明 |
|---|---|---|
| `VISION_FALLBACKS` | 空 | JSON 数组，主 provider 失败（429/5xx/超时）时依次尝试：`[{"url":"...","model":"...","key":"..."}]` |
| `VISION_FETCH_REMOTE` | `true` | 远程图片是否本地抓取后转 base64。**阿里云 Token Plan 必须为 true**（它不自己去抓 URL，直接传 URL 会 400） |
| `VISION_MAX_EDGE` | `2048` | 发送前等比缩放到长边不超过该值（保比例、不裁切） |
| `VISION_TIMEOUT` | `180` | 单次请求秒数 |

## 常见端点

| 提供方 | `LLM_API_URL` | 视觉模型示例 | 2D grounding | 3D grounding |
|---|---|---|---|---|
| 阿里云 Token Plan | `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | `qwen3.7-plus` | ✅ | ✅（实测） |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3-vl-plus` / `qwen3-vl-235b-a22b-instruct` | ✅ | ✅ |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` | ❌ | ❌ |
| DeepSeek | `https://api.deepseek.com/v1` | 视觉模型（若有） | ❌ | ❌ |
| Ollama | `http://localhost:11434/v1` | `llama3.2-vision` | ❌ | ❌ |
| vLLM / LM Studio | `http://localhost:1234/v1` | 任意 VLM | 视模型 | 视模型 |

> grounding 能力只由**模型家族**决定，与端点无关。`vision.py providers` 会按
> 模型名推断能力；`--probe` 额外做一次最小请求验证连通性。

## 模型家族判定

```
qwen3-vl* / qwen3.*-plus / qwen3.*-max*   → qwen3    （2D ✅ / 3D ✅）
qwen2.5-vl* / qwen-vl-* / qwen2-vl*       → qwen2.5  （2D ⚠️ 绝对坐标 / 3D ❌）
其它                                        → other    （grounding 拒绝）
```

判定是字符串匹配，不是远程探测；换模型后用 `providers` 复核。

## 代理

脚本使用 `httpx`，自动读取 `HTTPS_PROXY` / `HTTP_PROXY`。公司网络下拉取远程图片
或访问外网端点时：

```bash
export HTTPS_PROXY=http://10.10.11.13:7897
export HTTP_PROXY=http://10.10.11.13:7897
export NO_PROXY=localhost,127.0.0.1,10.0.0.0/8
```

## 缓存

- 位置：`~/.cache/image-inspector/<hash前2位>/<hash>.json`
- key：图片内容 sha256 + prompt + max_tokens + temperature
- 命中时不发请求；`--no-cache` 跳过读写
- batch 同样走缓存，重复跑第二遍几乎零成本

## 与 MCP 的关系

`scripts/server.py` 与 `vision.py` 共用同一套 `LLM_*` 配置：

```json
{
  "mcp": {
    "understand_image": {
      "type": "local",
      "command": ["uv", "run", "--with", "mcp<2", "--with", "httpx",
                  "--with", "pydantic", "python3",
                  "/home/<you>/.agents/skills/image-inspector/scripts/server.py"],
      "environment": {"LLM_API_URL": "...", "LLM_MODEL_NAME": "...", "LLM_API_KEY": "..."},
      "enabled": true
    }
  }
}
```

建议分工：MCP 只负责单张问答；批量 / 结构化 / grounding 走 `vision.py`，避免同质工具互相竞争。