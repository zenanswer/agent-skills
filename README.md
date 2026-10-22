# agent-skills

自建 agent skills 集合，统一用 [`npx skills`](https://skills.sh) 安装与更新。

## 技能清单

| 技能 | 作用 | 依赖 |
|---|---|---|
| [`create-icon`](skills/create-icon/) | 用可配置的文生图模型（MiniMax / 通义千问 / OpenAI / 兼容网关）生成 PPT 图标，支持预设风格、按示例图学风格、批量出图、透明背景 | `uv` + 一个图片模型 API Key |
| [`icon-finder`](skills/icon-finder/) | 搜索并下载品牌 / 技术 Logo（Iconify + Simple Icons），同时输出 SVG 与透明 PNG，可直接插进 PPT | `requests`、`cairosvg`、`Pillow`，系统 `cairo` |
| [`skill-manager`](skills/skill-manager/) | 盘点本机已安装的 skills（来源 / 版本 / 路径 / 功能），按需检查上游有无更新，并指导用官方安装器查找、安装、更新、排障 | 仅 `python3` 标准库 + `npx` |
| [`image-inspector`](skills/image-inspector/) | 外部视觉模型做问答 / OCR / JSON 抽取 / 批量 / 长图切块，以及 Qwen3-VL 的 2D・3D grounding（框、点、三维框） | `uv` + 一个多模态模型 API |

## 安装

```bash
# 全部安装（全局，Claude Code + OpenCode）
npx -y skills@latest add zenanswer/agent-skills -g \
  -s create-icon icon-finder skill-manager image-inspector \
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
├── create-icon/     SKILL.md + 4 个 Python 脚本 + styles.json
├── icon-finder/      SKILL.md + scripts/（搜索 / 下载 / 渲染）
├── skill-manager/    SKILL.md + scripts/skillmgr.py + references/
└── image-inspector/  SKILL.md + scripts/vision.py + scripts/server.py + references/
```

## License

MIT