# 安装矩阵：每种来源的正确命令

先判断技能来自哪类来源，再选命令。**不要**用「git clone + 软链」当正式安装。

## 1. 公共 GitHub 仓库（最常见）

```bash
# 先看仓库里有哪些技能，不安装
npx -y skills@latest add owner/repo -l

# 装全部（全局，所有 agent）
npx -y skills@latest add owner/repo -g --all

# 只装指定技能，只给指定 agent
npx -y skills@latest add owner/repo -g -s skill-a skill-b -a opencode claude-code -y
```

- 省略 `-g` = 装到当前项目（`.agents/skills/` + 自动生成 `skills-lock.json`）
- `-a '*'` = 所有已检测到的 agent
- `--copy` = 复制而不是软链（默认对 `~/.agents/skills` 是实体目录，其它 agent 建软链）

## 2. 私有仓库

同一套命令，认证走 git 已有配置：

```bash
# HTTPS：git credential helper / gh 登录态
npx -y skills@latest add owner/private-skills -g -s foo -a opencode -y

# 或显式 SSH
npx -y skills@latest add git@github.com:owner/private-skills.git -g -s foo -y
```

更新检查优先用 GitHub API（匿名 → `GITHUB_TOKEN`/`GH_TOKEN` → `gh api`），API 不可用时回退到 `git clone`。私有仓库缺少 token 时 `check` 会显示「无版本记录」或 `error`，属预期。

## 3. 仓库里的子目录 / monorepo

```bash
# 直接指向技能目录
npx -y skills@latest add https://github.com/owner/repo/tree/main/skills/foo -g -y

# 或按名字挑（技能在 skills/、skills/<category>/<name>/ 等标准容器下最多 3 层）
npx -y skills@latest add owner/repo -g -s foo -y

# 技能藏在非标准目录（如 examples/）时
npx -y skills@latest add owner/repo -g -s foo --full-depth -y
```

## 4. 本地路径（开发中）

```bash
# 正式安装本机目录（会记录 sourceType=local，后续 update 不会跟 git 走）
npx -y skills@latest add ./my-skill -g -y

# 或开发期软链（不写 lock，改完立即生效）
ln -sfn "$PWD/my-skill" ~/.agents/skills/my-skill
```

开发期软链验证通过后，改为「推仓库 → npx skills add」的正式安装。

## 5. 厂商官方安装器

| 来源 | 查看 | 安装 / 刷新 | 说明 |
|---|---|---|---|
| officecli | `officecli skills list` | `officecli skills install <name>` | 10 个子技能：pptx / word / excel / word-form / morph-ppt / morph-ppt-3d / pitch-deck / academic-paper / data-dashboard / financial-model |
| browser-skill | `bsk status` | `bsk update && bsk install-skill --all -y --force` | bsk 自身升级 + 技能重装 |

这两类**不要**用 `npx skills` 管理，会绕开厂商的版本与依赖处理。

## 6. ref：分支 vs tag

```bash
npx -y skills@latest add owner/repo#v1.2.0 -g -s foo -y   # 钉 tag
npx -y skills@latest add owner/repo#main   -g -s foo -y   # 跟分支
```

- 钉 tag = 稳定但**不会自动更新**，`skillmgr check` 会标 `pinned`
- 想让 `npx skills update` 持续跟随上游，就别带 `#tag`

## 7. 更新与卸载

```bash
npx -y skills@latest update -g -y                 # 全部
npx -y skills@latest update -g foo bar -y         # 指定
npx -y skills@latest remove -g foo -y             # 卸载
npx -y skills@latest remove -g owner/repo -y      # 按来源整批卸载
```

## 8. 装完要确认的三件事

1. `npx -y skills@latest ls -g` 里有该技能，且 `source` 正确
2. 实际路径是 `~/.agents/skills/<name>`（不是某个开发目录的软链）
3. `SKILL.md` 的 `name` 等于目录名（`skillmgr doctor` 会查）