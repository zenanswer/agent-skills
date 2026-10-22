# 来源识别：证据、置信度与缓存

`skillmgr scan` 要回答一个看似简单的问题：**这个没登记来源的技能，到底是从哪来的？**
答案分四层，代价从低到高，命中即停。

## 1. 本地 git 证据（零网络，置信度高）

适用：技能目录本身是软链，或位于某个 git 仓库内（典型：开发期 `ln -sfn`）。

```bash
git -C <skill-dir> rev-parse --show-toplevel
git -C <top> remote get-url origin
```

结论：`本地仓库 <top>（远端 owner/repo）`，并给出「推送到哪个仓库后可被 npx 接管」的命令。

注意：如果 `top` 就是 `~/.agents/skills` 或 `~/.config/opencode/skills` 本身（说明这些目录被整体纳入了某个仓库），**不当作来源证据**，继续往下查。

## 2. frontmatter / README 里的仓库链接

尚未实现为独立步骤；当前由第 3 步的仓库内容校验覆盖（见下）。若要扩展，优先读 `repository:` / `homepage:` / README 里的 `github.com/<owner>/<repo>`。

## 3. skills.sh 检索（官方生态索引）

```bash
curl 'https://skills.sh/api/search?q=icon-finder'
```

返回：

```json
{"skills": [{"id":"wukangcheng2944/claude-skill-icon-finder/icon-finder",
             "source":"wukangcheng2944/claude-skill-icon-finder",
             "skillId":"icon-finder", "installs":4}]}
```

只接受 `skillId` **与本地技能名完全相等**（大小写不敏感）的候选，按 installs 降序取前 5 个。
模糊匹配到别的名字（`llm-icon-finder`、`pf-icon-finder`）一律不算命中。

## 4. 候选验证（必须有，否则会张冠李戴）

同名不等于同一个技能。每个候选都要做两步：

1. `GET /repos/{source}/git/trees/HEAD?recursive=1`
   → 找 `<...>/<skill-name>/SKILL.md`（或仓库根 `SKILL.md`），确认**目录存在**
2. 读 `https://raw.githubusercontent.com/{source}/HEAD/<path>`
   → 取候选的 `name` 与 `description`，与本地描述做词元 Jaccard 相似度

判定：

| 条件 | 结论 | 用法 |
|---|---|---|
| `name` 相同 + 相似度 ≥ 0.35 | `exact-verified`（高置信） | 可给「remove + add」接管命令 |
| 目录存在但描述不符 | `candidates`（低置信） | 只建议 `npx skills use <source>@<skill>` 试用，不直接安装 |
| 索引有条目但仓库已无此目录 | `not-found` | 按本地自建处理（索引会滞后） |
| skills.sh 无同名条目 | `not-found` | 按本地自建处理 |

相似度阈值 0.35 是经验值：同一技能不同版本改写描述通常仍在 0.5 以上；同名不同物通常低于 0.2。

## 缓存

- 位置：`~/.cache/skill-manager/resolve.json`
- key：`sha1(技能名 + 本地 description)` 前 16 位
- TTL：7 天；`skillmgr scan --refresh` 强制刷新
- 缓存只存结论（含候选与分数），不存 SKILL.md 原文

## 为什么 scan 有快慢两档

| 场景 | 耗时 | 原因 |
|---|---|---|
| `scan` 首次 | 约 3–6s | 需要对每个未登记技能查 skills.sh + 候选仓库 |
| `scan` 命中缓存 | < 0.5s | 只读 resolve.json |
| `scan --no-resolve` | < 0.5s | 完全不联网，未登记技能统一标「未联网识别」 |

联网失败（无代理 / 限流）不会报错：候选置空，结论降级为「未登记」，不会误判来源。

## 常见误判与对策

| 现象 | 原因 | 对策 |
|---|---|---|
| 同名候选一大堆 | 名字太通用（如 `review`、`test`） | 只信 `exact-verified`，其余让用户 `use` 试用 |
| 索引里有、add 失败 | 仓库已删/转私有/路径变更 | 以验证步骤结果为准，不用索引当事实 |
| 本地自建被判成某个开源技能 | 描述撞词 | 相似度阈值 + 必须 `name` 相等；仍存疑就 `use` 试 |
| 私有仓库技能永远 not-found | 索引只收公开技能 | 认命：私有技能只能靠离线登记（本地 git 证据） |