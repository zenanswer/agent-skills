# 更新检测：hash 语义与坑

## 1. lock 文件结构与字段

`~/.agents/.skill-lock.json`（v3）：

```json
{
  "version": 3,
  "skills": {
    "create-icon": {
      "source": "zenanswer/agent-skills",
      "sourceType": "github",
      "sourceUrl": "https://github.com/zenanswer/agent-skills.git",
      "skillPath": "skills/create-icon/SKILL.md",
      "skillFolderHash": "3f0c…（40 位）",
      "installedAt": "2026-10-22T02:11:03.000Z",
      "updatedAt": "2026-10-22T02:11:03.000Z"
    }
  }
}
```

| 字段 | 含义 |
|---|---|
| `sourceType` | `github` / `git` / `local` / `well-known` |
| `skillPath` | 技能在仓库内的 `SKILL.md` 相对路径 |
| `skillFolderHash` | **GitHub 源**：技能目录的 **git tree SHA（40 位）**；**local/git 源**：目录内容的 sha256（64 位） |
| `ref` | 安装时指定的分支/tag；缺省 = 默认分支 |

## 2. 为什么不能用 `npx skills check`

`skills@1.7.x` 的源码里：

```js
case "check":
case "update":
case "upgrade":
  await runUpdate(restArgs);
```

`check` 只是 `update` 的别名 —— 它会**真的更新**（没有 dry-run 参数）。所以：

- `npx skills check` 不能用来「只看有没有更新」
- 想只读检查，必须自己比 hash（`skillmgr check` 就是这么做的）

## 3. `skillmgr check` 的判定逻辑

1. 按 `(source, ref)` 分组 lock 条目，**每个来源只 `git fetch` 一次**（组内技能共用 `FETCH_HEAD`），来源之间并行
2. 每个来源在 `~/.cache/skill-manager/repos/<slug>` 下 `git clone --filter=blob:none --depth 1 --no-checkout`（只取 tree，不取文件内容），后续 `git fetch --depth 1 origin <ref>` 增量更新
3. 取上游对应目录的 hash 与 lock 比对：
   - lock 是 40 位 → `git rev-parse FETCH_HEAD:<skillFolder>`（**子目录**返回 subtree tree sha；**仓库根目录**返回 commit sha —— 这正是 GitHub `git/trees/<ref>` API 的行为，必须复刻，否则根目录技能会被误判为「可更新」）
   - lock 是 64 位 → 检出该目录后按「相对路径 + 内容」排序 sha256（复刻 CLI 的 `computeSkillFolderHash`）
4. 结论：
   - hash 相同 → `已最新`
   - hash 不同且 ref 是 tag → `已钉 tag`（需要重新 add 才能跟上游）
   - hash 不同 → `可更新`
   - 缺 `skillFolderHash` / `skillPath` / local / well-known → `无法检查`（附原因）
5. 判定不依赖网络 API 配额，只用 git 协议；失败会标 `error` 并给出原因

**性能**：63 个技能、6 个来源，热缓存约 4s（此前逐技能 fetch 的实现要 60–90s）。冷缓存首次需要 clone 各来源（每仓几 MB 的 tree），一次性成本。

## 4. `--deep`：本地改动检测

`skillmgr check --deep`（或 `doctor`）会额外把上游目录检出到临时目录，做内容 hash 对比：

- 上游 hash ≠ 安装目录 hash → 「安装目录有本地改动」
- 意义：`npx skills update` 是**整体覆盖、无 merge**，本地改动一定会在下次更新时丢失

注意：对 GitHub 源，lock 里存的是 tree SHA，无法直接和内容 hash 比，所以必须检出才能判定；这一步会下载技能文件（通常很小）。

## 5. 已知限制

| 情况 | 表现 | 说明 |
|---|---|---|
| 仓库被删 / 变私有且无凭据 | `error` 或 `无法检查` | 需要 `gh auth login` 或 `GITHUB_TOKEN` |
| 技能在仓库里改了路径 | `error: 路径不存在` | 需要重新 `add` 让 lock 更新 `skillPath` |
| 旧版安装（无 `skillPath`） | `无法检查` | `npx skills update` 同样会跳过，只能重装 |
| tag 被强推后移动 | 显示 `可更新` 但更新后仍不跟随 | tag 语义如此，建议改用分支 |
| 没有被 npx 管理的技能（officecli / bsk / 手放） | `无法检查` | 用各自官方安装器刷新 |
| 网络不可达 | 整组 `error: fetch 失败` | 检查代理（`HTTPS_PROXY`），或先 `scan --no-resolve` 做离线体检 |

## 6. 缓存布局

```
~/.cache/skill-manager/
├── repos/<url-slug>/        # blobless/no-checkout 克隆，check 复用
│   └── checkout-*/          # --deep 时的临时检出，用完即删
└── resolve.json             # scan 的来源识别结果（7 天 TTL）
```

`check` / `scan` / `doctor` 都不会写入安装目录或 lock。

## 6. 手工核对（排障用）

```bash
# 看 lock 里记录的 hash
python3 -c "import json;print(json.load(open('$HOME/.agents/.skill-lock.json'))['skills']['create-icon']['skillFolderHash'])"

# 看上游当前 tree sha（不需要 clone 全仓）
git clone --filter=blob:none --depth 1 --no-checkout https://github.com/zenanswer/agent-skills.git /tmp/as
git -C /tmp/as rev-parse HEAD:skills/create-icon
```