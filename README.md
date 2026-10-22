# agent-skills

自建 agent skills 集合，统一用 [`npx skills`](https://skills.sh) 安装与更新。

## 技能清单

| 技能 | 作用 | 依赖 |
|---|---|---|
| [`create-icon`](skills/create-icon/) | 用文生图模型（MiniMax / 通义千问 / Seedream / OpenAI / 兼容网关）生成 PPT 图标：16 种预设风格、整套一致出图、抠透明底、统一 1024+512 归一化、质量检查 | `uv` + 一个图片模型 API Key |
| [`icon-finder`](skills/icon-finder/) | 找 Logo 与概念图标：`--mode logo` 搜品牌（Iconify / svgl / lobe-icons / Simple Icons），`--mode ui` 在 29 个许可清晰的图标集里按概念检索（含中英文概念扩展），输出等比不变形、统一留白的 1024+512 透明 PNG，附许可信息、署名清单与联系表 | `uv`（`requests`、`pillow`、`resvg-py`，无需系统 cairo） |
| [`skill-manager`](skills/skill-manager/) | 盘点本机已安装的 skills（来源 / 版本 / 路径 / 功能），按需检查上游有无更新，并指导用官方安装器查找、安装、更新、排障 | 仅 `python3` 标准库 + `npx` |
| [`it-product-research`](skills/it-product-research/) | IT 产品竞品调研与横向对比：需求澄清 → 动态维度 → 加权评分 → 中英双语报告 | 纯 prompt，无脚本 |
| [`tech-scout-daily`](skills/tech-scout-daily/) | AI 技术侦察日报：抓取多源资讯，按来源/公司/人物索引，附技术价值与商用价值评分 | `requests`、`beautifulsoup4`、`deep-translator`；**crawl4ai 服务为全量源必需**（不配仅 3/7 源），LLM 翻译可选 |
| [`image-inspector`](skills/image-inspector/) | 外部视觉模型做问答 / OCR / JSON 抽取 / 批量 / 长图切块，以及 Qwen3-VL 的 2D・3D grounding（框、点、三维框） | `uv` + 一个多模态模型 API |

## 安装

```bash
# 全部安装（全局，Claude Code + OpenCode）
npx -y skills@latest add zenanswer/agent-skills -g \
  -s create-icon icon-finder skill-manager image-inspector \
  it-product-research tech-scout-daily \
  -a claude-code opencode -y

# 只装其中一个
npx -y skills@latest add zenanswer/agent-skills -g -s icon-finder -a opencode -y
```

安装位置：`~/.agents/skills/<name>`（实体目录），其它 agent 目录由 `npx skills` 自动建软链。

> 安装时**不要**带 `#v0.1.0` 这类 tag ref。钉住 ref 后 `npx skills update` 不会跟随上游变化；tag 只用于标记发布点。

## 更新 / 卸载

```bash
npx -y skills@latest update -g -y                 # 更新全部全局技能
npx -y skills@latest update -g icon-finder -y     # 只更新一个
npx -y skills@latest remove -g icon-finder -y     # 卸载
npx -y skills@latest ls -g                        # 查看已安装
```

`npx skills` 的更新是**整体覆盖、无 merge**：不要直接改 `~/.agents/skills/` 下的文件，改动请提到本仓库，再执行更新。

## 管理本机 skills

装好 `skill-manager` 后（先 `skillmgr install-cli` 可省掉脚本路径）：

```bash
skillmgr inventory      # 已安装清单 + 来源 + 一句话功能
skillmgr scan           # 体检：分类 + 识别未登记来源 + 官方接管命令
skillmgr check          # 只读检查上游更新（check 不会安装）
skillmgr update         # 真正更新（npx skills update -g -y）
```

`image-inspector` 的用法（安装后）：

```bash
cd ~/.agents/skills/image-inspector
uv run scripts/vision.py providers --probe
uv run scripts/vision.py ground2d -i shot.png -p "car, bus" --draw boxes.png
uv run scripts/vision.py ground3d -i drive.jpg -p "all cars" --draw boxes3d.png
```

## 本仓库开发流程

```bash
git clone https://github.com/zenanswer/agent-skills.git
cd agent-skills

# 本地开发：用软链直接生效（不影响已安装副本）
ln -sfn "$PWD/skills/create-icon" ~/.agents/skills/create-icon

# 改完验证、提交、让安装端更新
npx -y skills@latest update -g -y
```

规范（会被 `npx skills` 直接当作目录名，必须遵守）：

- 目录名 = `SKILL.md` frontmatter 的 `name`，全小写 ASCII + 连字符，例如 `create-icon`
- 每个技能目录必须自带 `SKILL.md`，`description` 写清「做什么 + 什么时候用 + 触发词」
- 不要把 `.env`、`.venv/`、`__pycache__/`、生成产物提交进仓库

## 目录结构

```
skills/
├── create-icon/     SKILL.md + 脚本（prompt/生成/抠图/归一化/质检）+ styles.json + tests/
├── icon-finder/     SKILL.md + scripts/（搜索 / 下载 / 渲染 / 归一化）+ logokit/ + tests/
├── skill-manager/    SKILL.md + scripts/skillmgr.py + references/
├── image-inspector/  SKILL.md + scripts/vision.py + scripts/server.py + references/
├── it-product-research/  SKILL.md
└── tech-scout-daily/     SKILL.md + scripts/（抓取 / 翻译 / 生成）
```

## License

MIT