---
name: tech-scout-daily
description: >
  AI技术侦察每日报纸。从 HuggingFace Papers、LLM Stats、AI News、MIT News、Google AI Blog、GitHub Trending 等来源抓取最新 AI 资讯，按来源/公司/人物做一级二级索引，生成包含标题、大致内容、技术价值、商用价值的每日技术报纸。触发场景：用户提到"每日报纸"、"技术侦察"、"tech scout"、"AI早报"、"AI晚报"、"技术早报"、"AI资讯汇总"、"今日AI新闻"、"获取最新AI资讯"、"每日AI动态"、"AI daily"、"tech daily"。
---

# Tech Scout Daily — AI 技术侦察每日报纸

## 概述

本 Skill 从多个权威 AI 信息源聚合每日最新资讯，生成结构化的技术侦察报纸。报纸包含一级索引（按来源）和二级索引（按公司/机构/人物），每篇资讯附带标题、大致内容、技术价值评分、商用价值评分。

## 运行前提

| 类别 | 依赖 | 不满足时 |
|---|---|---|
| 必需 | Python 3.10+、`requests`、`beautifulsoup4`、`deep-translator` | 无法运行 |
| **全量源必需** | **crawl4ai 服务**（`CRAWL4AI_URL` + Bearer token） | 只能拿到 3/7 源（HF ×2、Google 拿不到），仍能出报 |
| 推荐 | LLM 翻译 + LLM 评分（`LLM_API_URL` / `LLM_MODEL_NAME` / `LLM_API_KEY`） | 翻译退回 Google；评分退回关键词启发式（区分度差，见「评分机制」） |
| 可选 | Playwright + chromium | 仅少一个本地浏览器兜底，不影响 crawl4ai 路径 |

配置放在 `~/.config/tech-scout-daily/env`（`chmod 600`），模板见技能根目录 `.env.example`。
**不要把 token / key 提交到仓库**；技能目录会被 `npx skills update` 覆盖。

## 信息源

| 编号 | 来源 | URL | 类型 |
|------|------|-----|------|
| 1 | HuggingFace Daily Papers | https://huggingface.co/api/daily_papers | 学术论文 |
| 2 | HuggingFace Trending Papers | https://huggingface.co/papers/trending | 热门论文 |
| 3 | LLM Stats News | https://llm-stats.com/ai-news | 模型/产业新闻 |
| 4 | The Decoder | https://the-decoder.com/feed/ | 产业新闻（RSS） |
| 5 | MIT AI News | https://news.mit.edu/topic/artificial-intelligence2 | 学术/研究 |
| 6 | Google AI Blog | https://blog.google/innovation-and-ai/technology/ai/rss/ | 企业研究（RSS） |
| 7 | GitHub Trending | https://github.com/trending | 开源项目 |

## 抓取后端

`scraper.py` 支持三种抓取方式，用 `--fetcher` 选择：

| 模式 | 行为 |
|---|---|
| `auto`（默认） | 先本地 `requests`；失败后自动走 crawl4ai；最后才尝试 Playwright |
| `requests` | 只用本地 HTTP（快，但受 DNS/反爬限制） |
| `crawl4ai` | 全部走 crawl4ai 服务，一次 POST 批量抓 6 个源（约 10s） |

### crawl4ai 配置（全量源必需）

crawl4ai 服务在远端完成 JS 渲染、反爬与出口网络，能解决本机 DNS 污染/SSL EOF 问题。
不配置它时只能拿到 3/7 源；配置后 **7/7**（原 AI News 被 captcha 永久拦截，已换成 The Decoder RSS）。

```bash
# ~/.config/tech-scout-daily/env（chmod 600）
CRAWL4AI_URL=http://<your-crawl4ai-host>:11235
CRAWL4AI_TOKEN=<bearer token>

# 可选：LLM 批量翻译（不配则退回 Google，慢且容易被限流）
LLM_API_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL_NAME=qwen3.7-plus
LLM_API_KEY=sk-...
# 翻译单独用快模型（实测 138 条约 1.5 分钟；用 3.7-plus 会到 10 分钟以上）
TRANSLATE_LLM_MODEL=qwen3.6-flash

# 评分模型（不配则复用 TRANSLATE_LLM_MODEL；实测 143 条约 1.5 分钟，workers=4）
RATE_LLM_MODEL=qwen3.6-flash
```

```bash
python scripts/run.py --fetcher crawl4ai --output-dir ./daily

# 只检查源可达性（不出报纸，适合排障/定时巡检）
python scripts/run.py --fetcher crawl4ai --health
```

**降级行为**：

| 情况 | 结果 |
|---|---|
| `--fetcher auto`（默认）+ crawl4ai 可用 | requests 失败后自动走 crawl4ai，6–7 源 |
| 不配 crawl4ai | 仅 3/7 源（LLM Stats、MIT、GitHub） |
| crawl4ai 服务挂 / token 失效 | `auto` 降到 3/7；`--fetcher crawl4ai` 默认再回退 requests（`--strict` 可关闭） |
| 所有源都失败 | run.py 立即报错退出（退出码 2），列出失败源与排查建议 |
| LLM 翻译失败 | 单批回退 Google；仍失败则保留英文，不中断 |

crawl4ai 抓到的 HTML 会按天缓存到 `~/.cache/tech-scout-daily/<date>/`，
同一天重跑翻译/生成不必重抓；`TECH_SCOUT_REFRESH=1` 强制刷新。

实测（本机网络）：

| 源 | requests | crawl4ai |
|---|---|---|
| HuggingFace Daily / Trending | ❌ DNS 污染 | ✅ 50 + 30 篇（Trending 现带摘要与日期） |
| LLM Stats | ✅（易被 challenge） | ✅ 13 篇（10 条外链新闻 + 3 篇模型发布，含摘要与原文链接） |
| MIT News | ✅ | ✅ 30 篇 |
| Google AI Blog | ❌ SSL EOF | ✅ 20 篇（改用 RSS） |
| GitHub Trending | ✅ | ✅ 11 篇 |
| The Decoder | ❌ 需代理 | ✅ 10 篇（RSS） |

crawl4ai 模式下总量约 140–160 篇（实测 143，跨源去重后）；`--fetcher crawl4ai` 全程约 2 分钟
（抓取 ~10s + LLM 翻译 ~90s + 生成 ~10s）。

### 其他说明

- Playwright 兜底是**可选**的：没装时只跳过失败源，不会中断整次运行
- 翻译默认 `auto`：检测到 `LLM_API_URL` 就用 LLM 批量翻译，否则用 Google（已加 1 req/s 限速，仍可能被限流）
- 抓取结果写入 `--output-dir`（默认 `/tmp`），不污染仓库

## 执行流程

### 快捷模式：一键运行（中英双语）

```bash
python scripts/run.py
```

脚本会按顺序执行 **抓取 → 翻译 → LLM 评分 → 生成 → 打印**，输出中英双语日报到 `/tmp/tech_scout_daily_<date>.md`。
（未配置 LLM 或加 `--no-rate` 时跳过评分，评分步骤不出现，流程回到 3 步。）

**参数**：
- `--output-dir`：输出目录（默认 `/tmp`）
- `--format`：输出格式，`md` / `html` / `both`（默认 `md`）
- `--insecure-ssl`：跳过 SSL 校验（用于受限网络环境）
- `--proxy <url>`：HTTP 代理（如 `http://<host>:<port>`），用于解决 HuggingFace 等不可直连的源
- `--fetcher`：`auto` / `requests` / `crawl4ai`（推荐 `crawl4ai`，见上节）
- `--strict`：`crawl4ai` 失败时不回退 requests（默认会部分降级）
- `--health`：只做源连通性检查，不出报纸
- `--ask-on-failure`：抓取后仍有源失败时，交互式询问是否提供代理 URL（仅 requests 路径有意义）
- `--use-playwright` / `--playwright-only-failures`：可选的本地浏览器兜底（需额外安装），与 crawl4ai 模式互斥，一般不必要
- `--no-translate`：跳过翻译步骤（仅英文）
- `--no-rate`：跳过 LLM 评分（沿抓取阶段的 keywords 分）
- `--rater`：`auto`（默认，有 LLM 配置就评）/ `llm` / `keyword`
- `--rate-model`：评分模型（默认 `RATE_LLM_MODEL` → `TRANSLATE_LLM_MODEL` → `LLM_MODEL_NAME`）
- `--no-print`：不打印报纸内容到 stdout（仅生成文件）

> 推荐组合：`--fetcher crawl4ai --output-dir ./daily --format both`
> 本地没有 crawl4ai 时：`--fetcher auto --proxy "$HTTPS_PROXY"`

### 失败时询问代理（推荐）

加上 `--ask-on-failure` 后，若初次抓取 + Playwright 兜底后仍有源失败，脚本会交互式询问：

```
⚠️  以下源未获取: hf_daily, ai_news
   1) 跳过失败的源，继续生成报纸
   2) 提供 HTTP 代理 URL 重试（如 http://<host>:<port>）
   3) 退出
   请选择 [1/2/3]:
```

选 2 后会提示输入代理 URL，脚本会重新用代理抓取失败的源。非交互式环境（管道、opencode 调度）下自动选 1（跳过）。

**为什么这样做**：避免在脚本里硬编码任何代理信息（隐私 + 安全），同时在网络失败时给用户一个补救机会。

### HTML 输出特色

生成的 HTML 自包含（CSS/JS 内联），可直接用浏览器打开，无需服务器：

- 🌗 **主题切换**：深色 / 浅色模式切换（状态保存在 localStorage）
- 🔍 **全文搜索**：实时搜索标题、摘要、公司、URL，自动高亮命中片段
- 📑 **悬浮目录**：右侧 sticky TOC，一键跳转
- 📦 **可折叠区块**：可折叠 <details> 节省纵向空间
- 🖨️ **打印友好**：内置 `@media print` 样式
- 📊 **统计卡片**：6 个 stat-card 直观展示今日指标
- 🏢 **公司网格**：按公司索引用 grid 卡片展示
- 🔖 **标签云**：frekuensi 加权标签

直接打开：
```bash
open /tmp/tech_scout_daily_2026-07-30.html
```

### 手动模式：分步执行

#### 第一步：使用 `scripts/scraper.py` 抓取数据

```bash
python scripts/scraper.py --output /tmp/tech_scout_raw.json
```

**参数说明**：
- `--output`：输出 JSON 文件路径（默认 `/tmp/tech_scout_raw.json`）
- `--days`：抓取最近几天的数据（默认 1）
- `--sources`：逗号分隔的来源编号，如 `1,3,5`（默认全部）
- `--proxy <url>`：HTTP 代理 URL（如 `http://<host>:<port>`）
- `--use-playwright`：所有源都使用 Playwright（headless Chromium + 代理）
- `--insecure-ssl`：跳过 SSL 校验

**环境变量**：
- `TECH_SCOUT_INSECURE_SSL=1`：等价于 `--insecure-ssl`

**抓取策略**：
1. 默认：requests 库快速抓取
2. `--use-playwright`：所有源都用 Playwright（慢但能绕过反爬）
3. **混合策略**（脚本内置）：requests 失败 → 自动 fallback 到 Playwright

#### 第二步：使用 `scripts/translate.py` 翻译

```bash
python scripts/translate.py --input /tmp/tech_scout_raw.json --output /tmp/tech_scout_translated.json
```

**参数**：
- `--input`：第一步输出的 JSON 文件
- `--output`：翻译后的 JSON 文件
- `--fields`：要翻译的字段，逗号分隔（默认 `title,summary`）

#### 第三步：使用 `scripts/rate.py` 做 LLM 评分

```bash
python scripts/rate.py --input /tmp/tech_scout_translated.json --output /tmp/tech_scout_rated.json
```

**参数**：
- `--input` / `--output`：输入（翻译产物即可）与输出 JSON
- `--model`：评分模型（默认 `RATE_LLM_MODEL`）
- `--batch` / `--workers`：每批条数与并发批数（默认 8 / 4）
- `--limit`：只评前 N 条（调试）
- `--rater`：`auto` / `llm` / `keyword`；`keyword` 等于不评分、原样透传
- `--force`：已评过的条目也重评（默认跳过 `score_method=llm` 的条目，便于断点续跑）

每条会写入 `tech_value` / `business_value` / `rating_reason` / `score_method=llm` /
`scored_model`，并把原关键词分保留在 `keyword_tech_value` / `keyword_business_value`。
单批失败会重试一次，仍失败则保留该批的关键词分，不中断整次运行。

prompt 里写死的几条校准规则（都是踩过的坑）：论文不等于高分；新闻不等于低技术分；
只是上了 trending 榜、没有新能力的开源仓库 tech ≤5 / biz ≤6；6 个月前的旧论文/旧项目
重新上榜要降 1–2 分。另外 `rate.py` 兜底一道硬约束：摘要不足 60 字符的条目（信息量不够，
只能靠标题判断）tech 与 biz 都压到 ≤7，避免凭品牌名给高分。

#### 第四步：使用 `scripts/generate_daily.py` 生成报纸

```bash
# Markdown
python scripts/generate_daily.py --input /tmp/tech_scout_rated.json --output /tmp/tech_scout_daily.md

# HTML
python scripts/generate_daily.py --input /tmp/tech_scout_rated.json --output /tmp/tech_scout_daily.html --format html

# 两种格式同时（自动生成 .md + .html）
python scripts/generate_daily.py --input /tmp/tech_scout_rated.json --output /tmp/tech_scout_daily --format both
```

**参数说明**：
- `--input`：评分后的 JSON 文件（没有评过分也能跑，只是分数为关键词分）
- `--output`：输出文件路径（`--format=both` 时扩展名自动）
- `--format`：输出格式 `md` / `html` / `both`（默认 `md`）

#### 第五步：将报纸展示给用户

读取生成的 Markdown 文件，直接展示给用户。

### 备选方案：当脚本不可用时

如果 Python 脚本无法运行（如缺少依赖），按以下手动流程执行：

1. **并行抓取所有来源**：使用 `webfetch` 或 `searxng_web_url_read` 工具同时抓取 7 个信息源
2. **提取关键信息**：从每篇文章中提取标题、链接、摘要、日期、相关公司/人物
3. **按报纸模板组织**：按照下方「报纸模板」的格式组织内容
4. **为每篇文章评估**：技术价值（1-10）和商用价值（1-10）
5. **生成一级二级索引**：按来源（一级）和公司/人物（二级）建立索引

## 报纸模板

```markdown
# 🤖 AI Tech Scout Daily — YYYY-MM-DD

> 生成时间：YYYY-MM-DD HH:MM UTC
> 收录来源：HuggingFace Papers, LLM Stats, AI News, MIT News, Google AI Blog, GitHub Trending
> 今日收录：N 篇

---

## 📊 今日概览

| 指标 | 数值 |
|------|------|
| 总收录 | N 篇 |
| 论文 | N 篇 |
| 产业新闻 | N 篇 |
| 开源项目 | N 个 |
| 平均技术价值 | X.X / 10 |
| 平均商用价值 | X.X / 10 |

---

## 📑 一级索引：按来源

### 🔬 HuggingFace Daily Papers（N 篇）
| # | 标题 | 技术价值 | 商用价值 |
|---|------|---------|---------|
| 1 | [标题] | 8/10 | 5/10 |

### 📈 HuggingFace Trending Papers（N 篇）
| # | 标题 | 技术价值 | 商用价值 |
|---|------|---------|---------|

### 🏭 LLM Stats News（N 篇）
| # | 标题 | 技术价值 | 商用价值 |
|---|------|---------|---------|

### 📰 AI News（N 篇）
| # | 标题 | 技术价值 | 商用价值 |
|---|------|---------|---------|

### 🎓 MIT AI News（N 篇）
| # | 标题 | 技术价值 | 商用价值 |
|---|------|---------|---------|

### 🔬 Google AI Blog（N 篇）
| # | 标题 | 技术价值 | 商用价值 |
|---|------|---------|---------|

### 💻 GitHub Trending（N 个）
| # | 项目 | Stars | 技术价值 | 商用价值 |
|---|------|-------|---------|---------|

---

## 📇 二级索引：按公司/机构

### OpenAI
| 标题 | 来源 | 技术价值 | 商用价值 |
|------|------|---------|---------|

### Google / DeepMind
| 标题 | 来源 | 技术价值 | 商用价值 |
|------|------|---------|---------|

### Meta
| 标题 | 来源 | 技术价值 | 商用价值 |
|------|------|---------|---------|

### Anthropic
| 标题 | 来源 | 技术价值 | 商用价值 |
|------|------|---------|---------|

### Microsoft
| 标题 | 来源 | 技术价值 | 商用价值 |
|------|------|---------|---------|

### MIT
| 标题 | 来源 | 技术价值 | 商用价值 |
|------|------|---------|---------|

### 其他机构
| 标题 | 来源 | 技术价值 | 商用价值 |
|------|------|---------|---------|

---

## 📇 二级索引：按人物

（按姓名首字母排序）

| 人物 | 所属机构 | 标题 | 来源 |
|------|---------|------|------|

---

## 🔥 头条深度

### 今日头条：[标题]

**来源**：[来源名称]
**链接**：[URL]

**大致内容**：
[2-3 段内容摘要]

**技术价值**：X/10
[技术价值分析：创新性、方法论、可复现性、技术难度]

**商用价值**：X/10
[商用价值分析：市场规模、应用场景、时间窗口、竞争格局]

---

### 次条：[标题]

（同上格式）

---

## 🔖 标签云

`#LLM` `#Agent` `#OpenSource` `#Multimodal` `#Robotics` `#Healthcare` ...

---

## 📝 评分说明

| 技术价值 | 评分标准 |
|---------|---------|
| 9-10 | 突破性创新，改变领域范式 |
| 7-8 | 显著创新，有重要技术贡献 |
| 5-6 | 有一定创新，改进现有方法 |
| 3-4 | 增量改进，工程优化 |
| 1-2 | 无明显技术创新 |

| 商用价值 | 评分标准 |
|---------|---------|
| 9-10 | 百亿级市场，近期可商业化 |
| 7-8 | 十亿级市场，1-2年内可商业化 |
| 5-6 | 明确商业场景，需要进一步验证 |
| 3-4 | 远期商业潜力，5年以上 |
| 1-2 | 纯学术研究，商业前景不明 |
```

## 技术价值 & 商用价值 评估指南

为每篇文章/论文评估时，从以下维度考虑：

### 技术价值评估维度
- **创新性**：方法是全新的还是对现有工作的改进？
- **方法论**：技术方案是否严谨、可复现？
- **影响力**：对所在领域的影响力有多大？
- **通用性**：技术是否可以迁移到其他领域？

### 商用价值评估维度
- **市场规模**：潜在市场规模有多大？
- **应用场景**：是否有清晰的落地场景？
- **时间窗口**：距离商业化还有多远？
- **竞争格局**：该领域竞争激烈程度如何？

## 评分机制（重要）

分数决定「头条深度」选谁，所以这里有两层机制：

### 1. 打分：默认 LLM，关键词仅为兜底

- **LLM 评分（推荐，默认开启）**：`scripts/rate.py` 读标题+摘要，按 SKILL 里的
  技术/商用评分标准给 0–10 分（一位小数），并写一句 `rating_reason`。
  校准要求明确写进 prompt：论文不等于高分、新闻不等于低技术分、不要因摘要长短调分、
  分布要散开。
- **关键词启发式（兜底）**：`scraper.py:score_item()`，`3.0 + Σ关键词权重 + 0.5×命中数`，
  上限 10。**它测的是摘要里有多少术语，不是质量**：HF 论文摘要平均 1500+ 字符必然撞满分，
  新闻摘要一两百字符必然 3–6 分。所以不配 LLM 时分数只能用来粗筛。

### 2. 头条选择：来源配额，避免单一来源刷屏

`generate_daily.py:select_top_stories()`：

- **保底**：每个来源先保底 2 条（`min_per_source`），小来源不会完全缺席
- **上限**：单一来源最多占 40%（20 条里最多 8 条），避免论文源凭长摘要垄断
- **并列分打散**：同分时按发布日期（新优先）→ 标题哈希排序，不让「抓取顺序」决定排名
- 来源不足时自动放宽上限凑满，保证头条总有 20 条

### 3. 跨源去重

同一内容出现在多个来源时合并为一条（先按 URL，再按规范化标题，仅对 ≥25 字符的标题生效），
保留信息更全的一条（摘要更长者），并把其它来源记入 `also_in`，在头条里显示为「同源报道」。

## 注意事项

1. **时效性优先**：优先收录当日/近24小时的内容
2. **去重**：同一内容出现在多个来源时，合并为一条，标注多个来源
3. **质量筛选**：跳过纯广告/软文，仅收录有实质内容的信息
4. **中英双语**：报纸默认输出中英双语（"大致内容 / Summary"），如不需翻译可加 `--no-translate`
5. **来源标注**：每条信息必须标注来源和链接
6. **容错**：某个来源抓取失败时，跳过该来源，在报告中标注"未获取"
7. **网络问题 / 代理支持**：
   - **HuggingFace.co** 在受限网络直连经常 SSL EOF，**必须用代理**：加 `--ask-on-failure` 让脚本询问，或直接传 `--proxy http://<host>:<port>`
   - **artificialintelligence-news.com** 在 WAF/Cloudflare 后面，部分地区 403。脚本会自动 fallback 到 Playwright。若仍失败则跳过
   - **Google AI Blog** 在国内可能 SSL EOF，建议用代理
   - **混合策略**：脚本默认先 requests，失败后自动用 Playwright 重试（带代理）
8. **评分说明**：自动评分仅基于关键词匹配，仅为参考。人工/模型对每条资讯的细化分析（如技术路线、商业模式）应另行补充

## 依赖安装

```bash
# 必需（crawl4ai 通过 HTTP 调用，不需要装 Python 包）
pip install -r scripts/requirements.txt

# 可选：仅当需要本地浏览器兜底
pip install -r scripts/requirements-optional.txt
python -m playwright install chromium
```

## 常见问题

**Q: HuggingFace / Google 抓不到？**
A: 本机网络对这两个域名有 DNS/SSL 问题。优先配 crawl4ai（`CRAWL4AI_URL` + `CRAWL4AI_TOKEN`）；
  否则用 `--proxy` / `HTTPS_PROXY`，或 `--health` 先确认哪些源可达。

**Q: 不配 crawl4ai 能用吗？**
A: 能，但只有 3/7 源（LLM Stats、MIT、GitHub），HF 和 Google 会缺失；报告里会标「未获取」。

**Q: crawl4ai 调不通 / 401？**
A: `--health` 会给出每个源的状态；401/403 表示 `CRAWL4AI_TOKEN` 失效。
   `--fetcher crawl4ai` 默认会回退 requests（部分降级），`--strict` 可关闭回退。

**Q: 翻译失败 / 很慢？**
A: 默认有 LLM 配置就用 LLM 批量翻译，否则用 Google。
   - 慢：确认 `TRANSLATE_LLM_MODEL` 是 flash 级模型（如 `qwen3.6-flash`），并确保 `enable_thinking` 生效
   - 被限流：`--no-translate` 跳过，或稍后重跑（crawl4ai 的 HTML 有当天缓存，不会重抓）

**Q: 想换翻译方式？**
A: `translate.py --translator auto|llm|google`；LLM 走任意 OpenAI 兼容端点，Google 走 `deep-translator`。

**Q: 头条（Top Stories）为什么全是同一个来源？**
A: 老版本按分数排序、同分时保持抓取顺序，而论文摘要长、术语密会撞满分，
   HF Daily Papers 又排在最前，于是头条被它垄断。现在两层修正：
   ① 用 `rate.py` 的 LLM 评分替代关键词分（后者实际在奖励「摘要长度」）；
   ② `generate_daily.py` 的 `select_top_stories()` 加来源保底 2 条、单源上限 40%、
   同分按日期+标题哈希打散。若仍想看纯分数榜，改这几个参数即可。

**Q: 评分太慢 / 想跳过？**
A: `--no-rate` 或 `--rater keyword` 跳过；`--rate-model` 换更快模型。
   已评过分的结果可用 `rate.py --force` 重评，否则默认跳过，便于断点续跑。

**Q: 每次都重新抓一遍？**
A: 不会。crawl4ai 返回的 HTML 按天缓存在 `~/.cache/tech-scout-daily/<date>/`，
   同一天重跑只重做翻译/生成；`TECH_SCOUT_REFRESH=1` 可强制刷新。