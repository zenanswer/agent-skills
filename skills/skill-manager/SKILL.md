---
name: skill-manager
description: "Inventory, audit, find, install and update agent skills using the official tooling (npx skills / officecli / bsk). Use when the user asks which skills are installed, where a skill came from, whether any skills have updates, how to tidy up a messy skill setup, how to find or install a new skill, or how to fix a broken/duplicated/mismatched skill install. Triggers: '已安装哪些 skill', 'skill 清单', '帮我梳理一下 skill', '哪些技能可以更新', '检查 skill 更新', '这个 skill 哪来的', '安装 skill', '找一个 skill', 'skill 装在哪', 'skill 冲突/重复/失效', 'skill inventory', 'scan my skills', 'list installed skills', 'update skills', 'install a skill'."
---

# Skill Manager

本机 agent skills 的**盘点、体检、来源识别、查找、安装、更新**入口。所有变更都走各来源的官方安装器，不手工复制文件。

## 核心原则

1. **`~/.agents/skills/` 是唯一实体安装根**（`npx skills` 写入），`~/.claude/skills/` 是它的软链，`~/.config/opencode/skills/` 只放自建技能与厂商安装器产物。
2. **绝不手工编辑安装目录**：`npx skills update` 是整体覆盖，改了会丢。要改内容 → 改源仓库 → 更新。
3. **不要把 `git clone` + 软链当正式安装**，那是开发模式；正式安装用 `npx skills add`。
4. 更新前如需回滚点，先跑 `skillkit backup`（本机有该工具时）。

## 命令

脚本 `scripts/skillmgr.py`，只依赖 `python3` 标准库、`git`、`npx`。下文 `skillmgr` 指：

```bash
python3 <skill-dir>/scripts/skillmgr.py    # 或 `skillmgr install-cli` 后直接用 skillmgr
```

| 命令 | 作用 | 会联网吗 |
|---|---|---|
| `skillmgr inventory` | 已安装清单：名称 / 来源 / ref / 路径 / agents / 时间 / 一句话功能 | 否（读 lock + 本地目录） |
| `skillmgr check` | 只读检查上游有无更新（不下载、不安装、不写 lock） | 是（按来源 fetch，带缓存） |
| `skillmgr scan` | **体检 + 整理建议**：分类已安装技能、识别未登记技能来源、给出官方接管命令 | 是（skills.sh / GitHub，结果缓存 7 天） |
| `skillmgr doctor` | 结构故障：断链、缺 SKILL.md、`name` ≠ 目录名、同名副本、lock/磁盘不一致 | 默认否，加 `--deep` 才比对上游 |
| `skillmgr find <关键词>` | 封装 `npx skills find` | 是 |
| `skillmgr add <owner/repo> [-s a b] [-a opencode claude-code]` | 封装 `npx skills add -g` | 是 |
| `skillmgr update [名称...]` | 封装 `npx skills update -g -y` | 是 |
| `skillmgr install-cli` | 复制脚本到 `~/.local/bin/skillmgr` | 否 |

所有命令都支持 `--json`（`install-cli`/`find`/`add`/`update` 除外）；`scan` 另有 `--no-resolve`（纯离线，最快的结构体检）和 `--refresh`（忽略来源识别缓存）。

## 工作流

### 1. 盘点：用户问「装了哪些技能 / 这个技能哪来的」

```bash
skillmgr inventory
```

回答时**只挑相关行**，不要整表倾倒；被问「装在哪」就直接给 `path` 与 `source`。

### 2. 梳理：用户说「帮我理一下 / 太乱了 / 怎么管理」

```bash
skillmgr scan
```

`scan` 把每个技能归入 6 个桶，并按「异常 → 重复副本 → 可接管来源 → 自建技能 → 厂商」给出可复制命令：

| 桶 | 含义 | 正确处理 |
|---|---|---|
| 官方管理 | lock 有登记、实体在 `~/.agents/skills` | 只跑 `npx skills update -g`，不用管 |
| 厂商管理 | officecli / browser-skill | 用各自官方安装器刷新，**不要**用 npx 覆盖 |
| 重复副本 | 同名技能在多个 agent 目录各一份且内容不同 | 保留 `~/.agents/skills` 那份，删其余（`scan` 会列出待删路径） |
| 未登记·已识别来源 | skills.sh 命中且验证过仓库里确有同名技能 | `npx skills add <source> -s <name>` 接管 |
| 未登记·自建/未知 | 本地 git 仓库、或 skills.sh 无命中 | 推到自建仓库后用 `npx skills add` 管理；纯本地 add 只会得到 `sourceType=local`（不跟上游） |
| 异常 | 断链 / 缺 SKILL.md / `name` ≠ 目录名 / lock 有磁盘无 | 先修，再谈更新 |

识别依据的优先级与置信度见 `references/provenance.md`。**同名的不同技能很常见**，所以 `skillmgr` 会去候选仓库读 `SKILL.md` 比对描述，不靠名字直接下结论。

### 3. 检查更新

```bash
skillmgr check            # 全部
skillmgr check foo bar    # 指定技能
skillmgr check --deep     # 额外检测安装目录是否被本地改过
```

- `可更新`：给更新命令
- `已钉 tag`：安装时用了 `#vX.Y.Z`，不会跟上游；要跟就重新 add（去掉 tag）
- `无法检查`：local / well-known / 缺 `skillPath` 或 hash，附原因
- 用户确认后再执行 `skillmgr update`

只读语义很重要：`npx skills check` 在 1.7.x 里其实是 `update` 的别名，**会真更新**。原理见 `references/update-check.md`。

### 4. 查找并安装

```bash
skillmgr find "logo"
skillmgr add vercel-labs/agent-skills -s web-design-guidelines -a opencode claude-code
```

私有仓库、子目录、monorepo、项目级安装、tag 语义见 `references/install-matrix.md`。

### 5. 排障

```bash
skillmgr doctor
skillmgr doctor --deep    # 再查「安装目录被本地改动」
```

| 结论 | 处理 |
|---|---|
| 断链 | 删掉失效软链，重新 `npx skills add` |
| 同名多副本 | 只保留 `~/.agents/skills/<name>`；厂商技能除外（各 agent 目录各一份是设计如此） |
| `name` ≠ 目录名 | 改源仓库 frontmatter 或目录名后重新 add（`npx skills` 直接用 name 作目录名） |
| 安装目录有本地改动 | 改动提回源仓库再 `update`，否则下次更新被覆盖 |
| lock 有、磁盘没有 | `npx skills update -g <name> -y` 重装 |

### 6. 非 npx 来源

```bash
officecli skills list                    # 看可选子技能
officecli skills install <skill-name>    # 装/刷新
bsk update && bsk install-skill --all -y --force
```

## 输出约定

- 表格优先：能一条结论说清就不要贴原始 JSON
- 功能说明取 `SKILL.md` frontmatter 的 `description`，截断到一行；不要臆造功能
- 检查/识别失败必须显式标 `error` 或「需人工确认」，不要静默跳过
- 给命令时用可直接复制的完整命令（带 `-y`、`-a opencode claude-code`）

## 边界

- 不做定时任务、不发通知、不写历史报告（只按需执行）
- `scan` / `check` / `doctor` **只读**：不改安装目录、不改 lock；只写 `~/.cache/skill-manager/`
- 不实现 `npx skills` 已有的 add/update/remove/ls/find，只做封装与解释
- 不建议用户手改 `~/.agents/.skill-lock.json`