---
name: image-inspector
description: "Analyze, read, and localize image content with an external vision model. Use when native vision is unavailable or insufficient: text-only models, unreadable or oversized/tall screenshots, HEIC/TIFF files, batch analysis of many screenshots or video frames, strict JSON/table extraction with a schema, or 2D/3D grounding (bounding boxes, points, 3D boxes with camera intrinsics) on Qwen3-VL models. Do NOT use it for a single image you can already see. Triggers: '看图', '识别图片', 'OCR', '提取截图文字', '框出/定位/坐标/bbox', '2d grounding', '3d grounding', '三维边界框', '批量识别截图', '批量抽帧', 'image to json', 'read this screenshot', 'locate object', 'bounding box'."
---

# Image Inspector

用外部多模态模型理解图片：问答、OCR、结构化抽取、批量处理、**2D/3D grounding**。所有能力都通过 `scripts/vision.py`（单文件，PEP 723）调用，MCP 形态保留在 `scripts/server.py`。

## 先判断：要不要用本技能

1. **你能直接看到这张图吗？**（多模态模型 + `read` 工具成功返回图像）
   - 能 → 直接看，**不要**调用本技能。除非用户要结构化 JSON、批量处理或 grounding。
2. **工具列表里已经有 `understand_image` / `MiniMax.understand_image`？**
   - 单张问答优先用那个工具；本技能用于批量、结构化、切图、多模型降级、2D/3D grounding。
3. **你看不到图？**（文本模型、`read` 无法返回图像、HEIC/TIFF、超大图）
   - 必须用本技能。**禁止根据文件名、大小、路径猜测图片内容。**

## 快速检查环境

```bash
python3 scripts/vision.py providers
```

输出当前 provider、模型、能力标记（`vision` / `ground2d` / `ground3d`）。没有配置时先按 `references/providers.md` 设置：

```bash
export LLM_API_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
export LLM_MODEL_NAME=qwen3.7-plus
export LLM_API_KEY=sk-...
```

或写进技能目录的 `.env`（优先级：shell env > `.env`）。**不要**把 key 提交到仓库。

## 命令

```bash
# 单张问答
python3 scripts/vision.py ask -i shot.png -p "这个报错是什么原因？"

# 描述 / OCR
python3 scripts/vision.py describe -i shot.png
python3 scripts/vision.py ocr -i scan.png --lang zh

# 结构化抽取（JSON Schema 校验 + 失败重试一次）
python3 scripts/vision.py extract -i table.png --schema schema.json

# 批量（并发 + jsonl 输出 + 失败清单）
python3 scripts/vision.py batch --glob "frames/*.png" -p "描述画面" --jobs 4 --out out.jsonl

# 长截图切块后逐块识别（10% 重叠）
python3 scripts/vision.py tile -i very_tall.png -p "提取所有文字"

# 2D grounding：框 / 点
python3 scripts/vision.py ground2d -i street.jpg -p "car, bus, pedestrian" --draw boxes.png
python3 scripts/vision.py ground2d -i field.jpg -p "person" --point --json

# 3D grounding（需要 Qwen3-VL）
python3 scripts/vision.py ground3d -i drive.jpg -p "all cars" --draw boxes3d.png
python3 scripts/vision.py ground3d -i drive.jpg -p "all cars" --cam 1200,1200,960,540 --json

# 起 MCP（兼容旧用法）
python3 scripts/vision.py serve

# 查看配置 / 连通性
python3 scripts/vision.py providers --probe
```

通用参数：`--json`（机器可读）、`--model` / `--api-url` / `--api-key` 临时覆盖、`--max-tokens`、`--temperature`、`--no-cache`。

## Grounding 规则（重要）

### 只有 Qwen 系模型可用

| 模型 | 2D | 3D |
|---|---|---|
| `qwen3-vl*` / `qwen3.*-plus` / `qwen3.*-max*` | ✅ 0–1000 相对坐标 | ✅ `bbox_3d` |
| `qwen2.5-vl*` / `qwen-vl-*` | ⚠️ 绝对坐标，需 `--sent-size` | ❌ |
| 其它（gpt-4o / GLM / …） | ❌ 默认拒绝，`--force` 才发 | ❌ |

模型不支持时**直接告诉用户换模型**，不要硬跑或编造坐标。

### 2D 坐标

- Qwen3-VL 输出 **0–1000 相对坐标**，与图片实际像素无关。
- 输出里同时给 `bbox_2d_norm`（0–1000）和 `bbox_2d`（原图像素），直接使用后者画图/点击。
- 不要自己算 resize 后的宽高（Qwen3-VL 不需要）；只要发送前保持**等比缩放、不裁切**，映射就是 `px = norm / 1000 * 原图边长`。
- `--point` 输出 `point_2d`；点和框不能混用同一个 prompt。

### 3D 坐标

- 格式：`[x_center, y_center, z_center, x_size, y_size, z_size, roll, pitch, yaw]`，中心与尺寸单位是**米**，相机坐标系 X 右 / Y 下 / Z 前。
- 角度默认按 **π 弧度**解释（0.5 = 90°，与 Qwen cookbook 的可视化代码一致）；可用 `--angle-unit rad|deg` 覆盖。
- 旋转顺序默认 `code`（复刻 cookbook 代码的 pitch→yaw→roll 应用顺序）；`--rot-order spec` 按文档的 roll→pitch→yaw。
- 没有相机内参时用 `--fov 60` 生成近似内参，并在 JSON 里标 `"source": "assumed-fov60"`；此时 3D 框**仅供示意**，不要据此给出精确距离。
- 细节与 cookbook 的不一致点见 `references/grounding.md`。

## 输出约定

- 默认人类可读摘要；`--json` 时输出结构化结果（含 `raw` 原始响应，便于排障）
- 坐标一律给像素值，并在必要时附 0–1000 归一化值
- 失败必须显式说明原因（缺 key / 模型不支持 grounding / HTTP 429 / 图片过大），不要静默返回空

## 边界

- 不做「一眼能看懂」的重复工作（见开头决策）
- 不猜图片内容；不把文件名当结论
- 不把 API key 写进仓库；`.env` 已被 `.gitignore` 排除
- `ground3d` 不做点云/多视角融合，只做单图 3D 框估计