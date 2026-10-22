# Image Inspector

用外部多模态模型理解图片：问答、描述、OCR、JSON 结构化抽取、批量处理、长图切块，
以及 **2D / 3D grounding**（框、点、三维边界框）。

基于原 [`understand-image-mcp`](https://github.com/xuechenwang-cienet/understand-image-mcp)
改造：MCP 只保留单张问答（`scripts/server.py`），其余能力集中到单文件 CLI
`scripts/vision.py`。

## 安装

```bash
npx -y skills@latest add zenanswer/agent-skills -g -s image-inspector \
  -a opencode claude-code -y
```

依赖：`uv`（推荐，PEP 723 自动装 httpx + pillow）或 Python 3.10+ 自行 `pip install httpx pillow`。

## 配置

```bash
cp ~/.agents/skills/image-inspector/.env.example \
   ~/.agents/skills/image-inspector/.env
# 填入 LLM_API_URL / LLM_MODEL_NAME / LLM_API_KEY
```

或用环境变量。模型家族决定能力：

| 模型 | 问答/OCR/抽取 | 2D grounding | 3D grounding |
|---|---|---|---|
| `qwen3.7-plus` / `qwen3-vl-*` | ✅ | ✅ 0–1000 相对坐标 | ✅ |
| `qwen2.5-vl-*` | ✅ | ⚠️ 绝对坐标，需 `--sent-size` | ❌ |
| `gpt-4o` 等 | ✅ | ❌ | ❌ |

## 用法

```bash
cd ~/.agents/skills/image-inspector

# 问答 / 描述 / OCR
uv run scripts/vision.py ask -i shot.png -p "报错原因是什么？"
uv run scripts/vision.py describe -i shot.png
uv run scripts/vision.py ocr -i scan.png --lang zh

# 结构化抽取（schema.json 见 references/providers.md 示例）
uv run scripts/vision.py extract -i table.png --schema schema.json

# 批量 / 长图
uv run scripts/vision.py batch --glob "frames/*.png" -p "描述画面" --jobs 4 --out out.jsonl
uv run scripts/vision.py tile -i tall.png -p "提取所有文字"

# 2D grounding（框 / 点）
uv run scripts/vision.py ground2d -i street.jpg -p "car, bus, pedestrian" --draw boxes.png
uv run scripts/vision.py ground2d -i field.jpg -p "person" --point --json

# 3D grounding
uv run scripts/vision.py ground3d -i drive.jpg -p "all cars" --draw boxes3d.png
uv run scripts/vision.py ground3d -i drive.jpg -p "all cars" --cam 1200,1200,960,540 --json

# 环境与能力
uv run scripts/vision.py providers --probe

# MCP（兼容旧用法）
uv run scripts/vision.py serve
```

输出坐标：

- `bbox_2d_norm` / `point_2d_norm`：0–1000 归一化（模型原始输出）
- `bbox_2d` / `point_2d`：原图像素（已处理 EXIF、等比缩放、反向框、越界）

## 2D / 3D grounding 要点

- Qwen3-VL 用 **0–1000 相对坐标**，不需要计算 resize 后的宽高
- 等比缩放不影响相对坐标；**裁切会**改变参考系
- EXIF 方向已在读取时纠正，坐标基于纠正后的宽高
- 3D 角度默认按 **π 弧度**（0.5 = 90°），旋转顺序默认复刻 cookbook 代码；
  可用 `--angle-unit rad|deg`、`--rot-order spec` 覆盖
- 无相机内参时用 `--fov 60`，结果仅供示意

详细说明见 [`references/grounding.md`](references/grounding.md) 与
[`references/providers.md`](references/providers.md)。

## MCP 配置

```json
{
  "mcp": {
    "understand_image": {
      "type": "local",
      "command": ["uv", "run", "--with", "mcp<2", "--with", "httpx",
                  "--with", "pydantic", "python3",
                  "/home/<you>/.agents/skills/image-inspector/scripts/server.py"],
      "environment": {
        "LLM_API_URL": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "LLM_MODEL_NAME": "qwen3.7-plus",
        "LLM_API_KEY": "sk-..."
      },
      "enabled": true
    }
  }
}
```

## 设计取舍

- **不是「看一眼」的替代品**：多模态宿主模型能直接看图时，不应调用本工具
- **批量/结构化/grounding 才是价值点**：单次 MCP 调用做不了这些编排
- 不做定时任务、不发通知、不猜图片内容