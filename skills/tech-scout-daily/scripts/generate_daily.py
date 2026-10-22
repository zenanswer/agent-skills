#!/usr/bin/env python3
"""
Tech Scout Daily Generator
Reads scraped JSON and produces a formatted daily newspaper in Markdown or HTML.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _stars_label(stars: int) -> str:
    if stars >= 10000:
        return f"⭐ {stars // 1000}k"
    if stars >= 1000:
        return f"⭐ {stars / 1000:.1f}k"
    return f"⭐ {stars}"


def _value_bar(value: float) -> str:
    """Return a visual bar for a value 0-10."""
    filled = int(value)
    empty = 10 - filled
    return "█" * filled + "░" * empty


def _source_emoji(source: str) -> str:
    mapping = {
        "HuggingFace Daily Papers": "🔬",
        "HuggingFace Trending Papers": "📈",
        "LLM Stats News": "🏭",
        "AI News": "📰",
        "MIT News": "🎓",
        "Google AI Blog": "🔬",
        "GitHub Trending": "💻",
    }
    return mapping.get(source, "📌")


# ──────────────────────────────────────────────
#  Markdown Generator
# ──────────────────────────────────────────────

def generate_markdown(data: dict) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    items = data.get("items", [])
    total = len(items)

    # Count by type
    paper_count = sum(1 for i in items if i.get("source_type") == "paper")
    news_count = sum(1 for i in items if i.get("source_type") in ("news", "corporate", "academic"))
    repo_count = sum(1 for i in items if i.get("source_type") == "repo")
    avg_tech = sum(i.get("tech_value", 0) for i in items) / max(total, 1)
    avg_biz = sum(i.get("business_value", 0) for i in items) / max(total, 1)

    lines = []

    # ── Header ──
    lines.append(f"# 🤖 AI Tech Scout Daily — {today}")
    lines.append("")
    lines.append(f"> 生成时间：{now_str}")
    lines.append(f"> 收录来源：{', '.join(data.get('sources_used', []))}")
    if data.get("sources_failed"):
        lines.append(f"> ⚠️ 未获取：{', '.join(data['sources_failed'])}")
    lines.append(f"> 今日收录：{total} 篇")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Overview ──
    lines.append("## 📊 今日概览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 总收录 | {total} 篇 |")
    lines.append(f"| 论文 | {paper_count} 篇 |")
    lines.append(f"| 产业新闻 | {news_count} 篇 |")
    lines.append(f"| 开源项目 | {repo_count} 个 |")
    lines.append(f"| 平均技术价值 | {avg_tech:.1f} / 10 |")
    lines.append(f"| 平均商用价值 | {avg_biz:.1f} / 10 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Level 1 Index: by Source ──
    lines.append("## 📑 一级索引：按来源")
    lines.append("")

    source_groups = defaultdict(list)
    for item in items:
        source_groups[item["source"]].append(item)

    source_order = [
        "HuggingFace Daily Papers",
        "HuggingFace Trending Papers",
        "LLM Stats News",
        "AI News",
        "MIT News",
        "Google AI Blog",
        "GitHub Trending",
    ]

    for source in source_order:
        group = source_groups.get(source, [])
        if not group:
            continue
        emoji = _source_emoji(source)
        lines.append(f"### {emoji} {source}（{len(group)} 篇）")
        lines.append("")

        if source == "GitHub Trending":
            lines.append("| # | 项目 | Stars | 技术价值 | 商用价值 |")
            lines.append("|---|------|-------|---------|---------|")
            for idx, item in enumerate(group, 1):
                title = item["title"]
                url = item["url"]
                stars = _stars_label(item.get("upvotes", 0))
                tv = item.get("tech_value", 0)
                bv = item.get("business_value", 0)
                lines.append(f"| {idx} | [{title}]({url}) | {stars} | {tv}/10 | {bv}/10 |")
        else:
            lines.append("| # | 标题 | 技术价值 | 商用价值 |")
            lines.append("|---|------|---------|---------|")
            for idx, item in enumerate(group, 1):
                title = item["title"]
                url = item["url"]
                tv = item.get("tech_value", 0)
                bv = item.get("business_value", 0)
                link = f"[{title}]({url})" if url else title
                lines.append(f"| {idx} | {link} | {tv}/10 | {bv}/10 |")

        lines.append("")

    lines.append("---")
    lines.append("")

    # ── Level 2 Index: by Company/Institution ──
    lines.append("## 📇 二级索引：按公司/机构")
    lines.append("")

    company_groups = defaultdict(list)
    for item in items:
        for company in item.get("companies", []):
            company_groups[company].append(item)
        if not item.get("companies"):
            company_groups["其他"].append(item)

    major_companies = [
        "OpenAI", "Google", "Meta", "Anthropic", "Microsoft", "Nvidia",
        "Apple", "Amazon", "xAI", "DeepSeek", "Mistral", "HuggingFace",
        "MIT", "Stanford", "Berkeley", "CMU",
    ]

    for company in major_companies:
        group = company_groups.get(company, [])
        if not group:
            continue
        lines.append(f"### {company}（{len(group)} 篇）")
        lines.append("")
        lines.append("| 标题 | 来源 | 技术价值 | 商用价值 |")
        lines.append("|------|------|---------|---------|")
        for item in group:
            title = item["title"]
            url = item["url"]
            source = item["source"]
            tv = item.get("tech_value", 0)
            bv = item.get("business_value", 0)
            link = f"[{title}]({url})" if url else title
            lines.append(f"| {link} | {source} | {tv}/10 | {bv}/10 |")
        lines.append("")

    # Other companies
    other = {k: v for k, v in company_groups.items() if k not in major_companies and k != "其他"}
    if other:
        lines.append("### 其他机构")
        lines.append("")
        lines.append("| 标题 | 机构 | 来源 | 技术价值 | 商用价值 |")
        lines.append("|------|------|------|---------|---------|")
        for company, group in sorted(other.items()):
            for item in group:
                title = item["title"]
                url = item["url"]
                source = item["source"]
                tv = item.get("tech_value", 0)
                bv = item.get("business_value", 0)
                link = f"[{title}]({url})" if url else title
                lines.append(f"| {link} | {company} | {source} | {tv}/10 | {bv}/10 |")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ── Level 2 Index: by People ──
    lines.append("## 📇 二级索引：按人物")
    lines.append("")

    people_groups = defaultdict(list)
    for item in items:
        for p in item.get("people", []):
            people_groups[p["name"]].append((item, p.get("affiliation", "")))

    if people_groups:
        lines.append("| 人物 | 所属机构 | 标题 | 来源 |")
        lines.append("|------|---------|------|------|")
        for name in sorted(people_groups.keys()):
            for item, affiliation in people_groups[name]:
                title = item["title"]
                url = item["url"]
                source = item["source"]
                link = f"[{title}]({url})" if url else title
                lines.append(f"| {name} | {affiliation} | {link} | {source} |")
    else:
        lines.append("（今日未识别到知名人物）")
    lines.append("")

    lines.append("---")
    lines.append("")

    # ── Top Stories: Top 20 by Tech Value + Top 20 by Business Value ──
    lines.append("## 🔥 头条深度 / Top Stories")
    lines.append("")
    lines.append(f"> 共 40 条：按技术价值 Top 20 + 按商用价值 Top 20")
    lines.append("")

    top_by_tech = sorted(items, key=lambda x: x.get("tech_value", 0), reverse=True)[:20]
    top_by_biz = sorted(items, key=lambda x: x.get("business_value", 0), reverse=True)[:20]

    def _render_top_section(section_title: str, section_items: list, value_key: str, value_label: str, value_label_en: str):
        lines.append(f"### 🧪 {section_title}（{len(section_items)} 条）")
        lines.append("")
        for rank, item in enumerate(section_items, 1):
            title = item["title"]
            title_zh = item.get("title_zh", "")
            url = item["url"]
            source = item["source"]
            summary = item.get("summary", "")
            summary_zh = item.get("summary_zh", "")
            tv = item.get("tech_value", 0)
            bv = item.get("business_value", 0)
            companies = item.get("companies", [])

            # Bilingual title
            if title_zh:
                lines.append(f"#### #{rank} {title_zh}")
                lines.append(f"##### {title}")
            else:
                lines.append(f"#### #{rank} {title}")
            lines.append("")
            lines.append(f"**来源 / Source**：{source}")
            if url:
                lines.append(f"**链接 / Link**：{url}")
            if companies:
                lines.append(f"**相关公司/机构**：{', '.join(companies)}")
            lines.append("")

            if summary_zh:
                lines.append(f"**大致内容 / Summary**：")
                lines.append(f"> {summary_zh}")
                lines.append("")
            if summary:
                lines.append(f"**English Summary**：")
                lines.append(f"> {summary}")
                lines.append("")

            lines.append(f"**技术价值 / Tech Value**：{tv}/10 {_value_bar(tv)}")
            lines.append(f"**商用价值 / Business Value**：{bv}/10 {_value_bar(bv)}")
            lines.append(f"**{value_label} / {value_label_en}**：{item.get(value_key, 0)}/10")
            lines.append("")
            lines.append("---")
            lines.append("")

    # By Tech Value
    _render_top_section(
        "技术价值 Top 20 / Top 20 by Tech Value",
        top_by_tech,
        "tech_value",
        "技术价值",
        "Tech Value",
    )

    # By Business Value
    _render_top_section(
        "商用价值 Top 20 / Top 20 by Business Value",
        top_by_biz,
        "business_value",
        "商用价值",
        "Business Value",
    )

    lines.append("---")
    lines.append("")

    # ── Tag Cloud ──
    lines.append("## 🔖 标签云")
    lines.append("")

    tag_counts = defaultdict(int)
    for item in items:
        for tag in item.get("tags", []):
            tag_counts[tag] += 1
        for company in item.get("companies", []):
            tag_counts[company] += 1

    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:30]
    tags = [f"`#{tag}`" for tag, _ in top_tags]
    lines.append(" ".join(tags))
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Scoring Guide ──
    lines.append("## 📝 评分说明")
    lines.append("")
    lines.append("| 技术价值 | 评分标准 |")
    lines.append("|---------|---------|")
    lines.append("| 9-10 | 突破性创新，改变领域范式 |")
    lines.append("| 7-8 | 显著创新，有重要技术贡献 |")
    lines.append("| 5-6 | 有一定创新，改进现有方法 |")
    lines.append("| 3-4 | 增量改进，工程优化 |")
    lines.append("| 1-2 | 无明显技术创新 |")
    lines.append("")
    lines.append("| 商用价值 | 评分标准 |")
    lines.append("|---------|---------|")
    lines.append("| 9-10 | 百亿级市场，近期可商业化 |")
    lines.append("| 7-8 | 十亿级市场，1-2年内可商业化 |")
    lines.append("| 5-6 | 明确商业场景，需要进一步验证 |")
    lines.append("| 3-4 | 远期商业潜力，5年以上 |")
    lines.append("| 1-2 | 纯学术研究，商业前景不明 |")

    return "\n".join(lines)


# ──────────────────────────────────────────────
#  HTML Generator
# ──────────────────────────────────────────────

def generate_html(data: dict) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    items = data.get("items", [])
    total = len(items)

    paper_count = sum(1 for i in items if i.get("source_type") == "paper")
    news_count = sum(1 for i in items if i.get("source_type") in ("news", "corporate", "academic"))
    repo_count = sum(1 for i in items if i.get("source_type") == "repo")
    avg_tech = sum(i.get("tech_value", 0) for i in items) / max(total, 1)
    avg_biz = sum(i.get("business_value", 0) for i in items) / max(total, 1)

    source_groups = defaultdict(list)
    for item in items:
        source_groups[item["source"]].append(item)

    source_order = [
        "HuggingFace Daily Papers",
        "HuggingFace Trending Papers",
        "LLM Stats News",
        "AI News",
        "MIT News",
        "Google AI Blog",
        "GitHub Trending",
    ]

    company_groups = defaultdict(list)
    for item in items:
        for company in item.get("companies", []):
            company_groups[company].append(item)
        if not item.get("companies"):
            company_groups["其他"].append(item)

    major_companies = [
        "OpenAI", "Google", "Meta", "Anthropic", "Microsoft", "Nvidia",
        "Apple", "Amazon", "xAI", "DeepSeek", "Mistral", "HuggingFace",
        "MIT", "Stanford", "Berkeley", "CMU",
    ]

    # Build HTML with embedded CSS & JS
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Tech Scout Daily — {today}</title>
<style>
  :root {{
    --bg: #0d1117; --bg-elev: #161b22; --border: #30363d;
    --text: #c9d1d9; --text-dim: #8b949e; --text-bright: #f0f6fc;
    --accent: #58a6ff; --accent-2: #79c0ff; --accent-3: #a5d6ff;
    --green: #3fb950; --yellow: #d29922; --red: #f85149;
    --purple: #d2a8ff; --orange: #ffa657;
  }}
  body.light {{
    --bg: #ffffff; --bg-elev: #f6f8fa; --border: #d0d7de;
    --text: #1f2328; --text-dim: #656d76; --text-bright: #0d1117;
    --accent: #0969da; --accent-2: #218bff; --accent-3: #54aeff;
    --green: #1a7f37; --yellow: #9a6700; --red: #cf222e;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 1200px; margin: 0 auto; padding: 24px; background: var(--bg); color: var(--text); line-height: 1.6; transition: background 0.3s, color 0.3s; }}
  .container {{ display: flex; gap: 24px; }}
  .main {{ flex: 1; min-width: 0; }}
  .sidebar {{ width: 240px; flex-shrink: 0; position: sticky; top: 24px; align-self: start; max-height: 90vh; overflow-y: auto; }}
  h1 {{ color: var(--accent); border-bottom: 2px solid var(--border); padding-bottom: 12px; }}
  h2 {{ color: var(--accent); margin-top: 36px; padding-top: 12px; border-top: 1px solid var(--border); }}
  h2:first-of-type {{ border-top: none; }}
  h3 {{ color: var(--accent-2); margin-top: 24px; }}
  h4 {{ color: var(--accent-3); margin-top: 20px; margin-bottom: 8px; }}
  h5 {{ color: var(--text-dim); font-weight: normal; font-size: 0.9em; margin: 4px 0 12px; font-style: italic; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid var(--border); padding: 8px 12px; text-align: left; }}
  th {{ background: var(--bg-elev); color: var(--accent); font-weight: 600; }}
  tr:hover {{ background: var(--bg-elev); }}
  blockquote {{ border-left: 3px solid var(--accent); margin: 12px 0; padding: 8px 16px; color: var(--text-dim); background: var(--bg-elev); border-radius: 0 4px 4px 0; }}
  blockquote.english {{ color: var(--text-dim); font-style: italic; }}
  .bar {{ font-family: monospace; letter-spacing: 1px; }}
  .tag {{ background: #1f6feb22; color: var(--accent); border-radius: 12px; padding: 2px 10px; margin: 2px; font-size: 0.9em; display: inline-block; }}
  hr {{ border: none; border-top: 1px solid var(--border); margin: 32px 0; }}
  .score {{ font-weight: bold; }}
  .score-high {{ color: var(--green); }}
  .score-mid {{ color: var(--yellow); }}
  .score-low {{ color: var(--red); }}
  .toolbar {{ display: flex; gap: 8px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }}
  .toolbar input {{ flex: 1; min-width: 200px; padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-elev); color: var(--text); font-size: 14px; }}
  .toolbar button {{ padding: 8px 14px; background: var(--accent); color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }}
  .toolbar button:hover {{ opacity: 0.85; }}
  .toc {{ background: var(--bg-elev); border: 1px solid var(--border); border-radius: 8px; padding: 16px; font-size: 13px; }}
  .toc h3 {{ margin-top: 0; font-size: 14px; color: var(--accent); text-transform: uppercase; letter-spacing: 0.5px; }}
  .toc ul {{ list-style: none; padding-left: 0; margin: 0; }}
  .toc li {{ padding: 4px 0; }}
  .toc a {{ color: var(--text-dim); display: block; padding: 4px 8px; border-radius: 4px; }}
  .toc a:hover {{ background: var(--bg); color: var(--accent); text-decoration: none; }}
  details {{ margin: 12px 0; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-elev); overflow: hidden; }}
  details > summary {{ cursor: pointer; padding: 12px 16px; font-weight: 600; color: var(--accent-2); user-select: none; }}
  details[open] > summary {{ border-bottom: 1px solid var(--border); }}
  details .content {{ padding: 12px 16px; }}
  .item-card {{ padding: 16px; margin: 12px 0; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-elev); }}
  .item-meta {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 8px 0; font-size: 0.9em; color: var(--text-dim); }}
  .item-meta strong {{ color: var(--text); }}
  .highlight {{ background: var(--yellow); color: var(--bg); padding: 0 2px; border-radius: 2px; }}
  .company-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin: 12px 0; }}
  .company-card {{ padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-elev); }}
  .company-card h4 {{ margin-top: 0; }}
  .company-card .item {{ padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 0.9em; }}
  .company-card .item:last-child {{ border-bottom: none; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 16px 0; }}
  .stat-card {{ padding: 16px; background: var(--bg-elev); border: 1px solid var(--border); border-radius: 8px; text-align: center; }}
  .stat-card .value {{ font-size: 2em; font-weight: bold; color: var(--accent); }}
  .stat-card .label {{ font-size: 0.85em; color: var(--text-dim); margin-top: 4px; }}
  @media (max-width: 900px) {{ .container {{ flex-direction: column; }} .sidebar {{ width: 100%; position: static; max-height: none; }} }}
</style>
</head>
<body>
<div class="toolbar">
  <input type="text" id="search" placeholder="🔍 搜索标题、摘要、公司、URL..." />
  <button onclick="toggleTheme()">🌗 主题切换</button>
  <button onclick="window.print()">🖨️ 打印</button>
</div>

<h1>🤖 AI Tech Scout Daily — {today}</h1>
<blockquote>
  生成时间：{now_str}<br>
  收录来源：{', '.join(data.get('sources_used', []))}<br>
  {"⚠️ 未获取：" + ', '.join(data['sources_failed']) + "<br>" if data.get('sources_failed') else ""}
  今日收录：{total} 篇
</blockquote>

<div class="container">
<div class="main">

<h2 id="overview">📊 今日概览</h2>
<div class="stats-grid">
  <div class="stat-card"><div class="value">{total}</div><div class="label">总收录</div></div>
  <div class="stat-card"><div class="value">{paper_count}</div><div class="label">论文</div></div>
  <div class="stat-card"><div class="value">{news_count}</div><div class="label">产业新闻</div></div>
  <div class="stat-card"><div class="value">{repo_count}</div><div class="label">开源项目</div></div>
  <div class="stat-card"><div class="value">{avg_tech:.1f}</div><div class="label">平均技术价值</div></div>
  <div class="stat-card"><div class="value">{avg_biz:.1f}</div><div class="label">平均商用价值</div></div>
</div>

<h2 id="by-source">📑 一级索引：按来源</h2>
"""

    for source in source_order:
        group = source_groups.get(source, [])
        if not group:
            continue
        emoji = _source_emoji(source)
        html += f"<h3>{emoji} {source}（{len(group)} 篇）</h3>\n"
        html += "<details><summary>展开 / 收起</summary><div class='content'>\n<table>\n"

        if source == "GitHub Trending":
            html += "<tr><th>#</th><th>项目</th><th>Stars</th><th>技术价值</th><th>商用价值</th></tr>\n"
            for idx, item in enumerate(group, 1):
                title = item["title"]
                url = item["url"]
                stars = _stars_label(item.get("upvotes", 0))
                tv = item.get("tech_value", 0)
                bv = item.get("business_value", 0)
                html += f"<tr><td>{idx}</td><td><a href='{url}'>{title}</a></td><td>{stars}</td><td class='score'>{tv}/10</td><td class='score'>{bv}/10</td></tr>\n"
        else:
            html += "<tr><th>#</th><th>标题</th><th>技术价值</th><th>商用价值</th></tr>\n"
            for idx, item in enumerate(group, 1):
                title = item["title"]
                url = item["url"]
                tv = item.get("tech_value", 0)
                bv = item.get("business_value", 0)
                link = f"<a href='{url}'>{title}</a>" if url else title
                html += f"<tr><td>{idx}</td><td>{link}</td><td class='score'>{tv}/10</td><td class='score'>{bv}/10</td></tr>\n"
        html += "</table>\n</div></details>\n"

    html += "<h2 id='by-company'>📇 二级索引：按公司/机构</h2>\n<div class='company-grid'>\n"

    for company in major_companies:
        group = company_groups.get(company, [])
        if not group:
            continue
        html += f"<div class='company-card'><h4>{company} ({len(group)})</h4>\n"
        for item in group[:5]:
            title = item["title"]
            url = item["url"]
            tv = item.get("tech_value", 0)
            bv = item.get("business_value", 0)
            link = f"<a href='{url}'>{title}</a>" if url else title
            html += f"<div class='item'>{link} <span class='score'>{tv}/{bv}</span></div>\n"
        if len(group) > 5:
            html += f"<div class='item' style='color:var(--text-dim);'>...还有 {len(group)-5} 条</div>\n"
        html += "</div>\n"

    html += "</div>\n"

    # Top stories
    html += "<h2 id='top-stories'>🔥 头条深度 / Top Stories</h2>\n"
    html += "<p>共 40 条：按技术价值 Top 20 + 按商用价值 Top 20</p>\n"

    top_by_tech_html = sorted(items, key=lambda x: x.get("tech_value", 0), reverse=True)[:20]
    top_by_biz_html = sorted(items, key=lambda x: x.get("business_value", 0), reverse=True)[:20]

    def _render_html_section(section_title: str, section_items: list, value_key: str, value_label_en: str, anchor: str):
        html_local = f"<h3 id='{anchor}'>{section_title}</h3>\n"
        for rank, item in enumerate(section_items, 1):
            title = item["title"]
            title_zh = item.get("title_zh", "")
            url = item["url"]
            source = item["source"]
            summary = item.get("summary", "")
            summary_zh = item.get("summary_zh", "")
            tv = item.get("tech_value", 0)
            bv = item.get("business_value", 0)
            companies = item.get("companies", [])

            html_local += "<div class='item-card'>"
            if title_zh:
                html_local += f"<h4>#{rank} {title_zh}</h4>\n"
                html_local += f"<h5>{title}</h5>\n"
            else:
                html_local += f"<h4>#{rank} {title}</h4>\n"
            html_local += "<div class='item-meta'>"
            html_local += f"<span><strong>来源</strong>：{source}</span>"
            if url:
                html_local += f"<span><strong>链接</strong>：<a href='{url}'>{url}</a></span>"
            if companies:
                html_local += f"<span><strong>公司</strong>：{', '.join(companies)}</span>"
            html_local += "</div>"

            if summary_zh:
                html_local += f"<blockquote><strong>大致内容 / Summary</strong>：<br>{summary_zh}</blockquote>\n"
            if summary:
                html_local += f"<blockquote class='english'><strong>English Summary</strong>：<br>{summary}</blockquote>\n"
            html_local += f"<p><strong>技术价值</strong>：{tv}/10 <span class='bar'>{_value_bar(tv)}</span> &nbsp; "
            html_local += f"<strong>商用价值</strong>：{bv}/10 <span class='bar'>{_value_bar(bv)}</span> &nbsp; "
            html_local += f"<strong style='color:var(--accent);'>{value_label_en}：{item.get(value_key, 0)}/10</strong></p>\n"
            html_local += "</div>"
        return html_local

    html += _render_html_section(
        "🧪 技术价值 Top 20 / Top 20 by Tech Value",
        top_by_tech_html,
        "tech_value",
        "Tech Value",
        "top-tech",
    )
    html += _render_html_section(
        "💰 商用价值 Top 20 / Top 20 by Business Value",
        top_by_biz_html,
        "business_value",
        "Business Value",
        "top-biz",
    )

    # Tag cloud
    html += "<h2 id='tags'>🔖 标签云</h2>\n"
    tag_counts = defaultdict(int)
    for item in items:
        for tag in item.get("tags", []):
            tag_counts[tag] += 1
        for company in item.get("companies", []):
            tag_counts[company] += 1
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:30]
    html += "<div style='line-height:2.5;'>\n"
    for tag, count in top_tags:
        html += f"<span class='tag'>#{tag} ({count})</span>\n"
    html += "</div>\n"

    # Scoring guide
    html += "<h2 id='scoring'>📝 评分说明</h2>\n"
    html += """<table>
  <tr><th>技术价值</th><th>评分标准</th></tr>
  <tr><td class="score-high">9-10</td><td>突破性创新，改变领域范式</td></tr>
  <tr><td class="score-high">7-8</td><td>显著创新，有重要技术贡献</td></tr>
  <tr><td class="score-mid">5-6</td><td>有一定创新，改进现有方法</td></tr>
  <tr><td class="score-mid">3-4</td><td>增量改进，工程优化</td></tr>
  <tr><td class="score-low">1-2</td><td>无明显技术创新</td></tr>
</table>
<table>
  <tr><th>商用价值</th><th>评分标准</th></tr>
  <tr><td class="score-high">9-10</td><td>百亿级市场，近期可商业化</td></tr>
  <tr><td class="score-high">7-8</td><td>十亿级市场，1-2年内可商业化</td></tr>
  <tr><td class="score-mid">5-6</td><td>明确商业场景，需要进一步验证</td></tr>
  <tr><td class="score-mid">3-4</td><td>远期商业潜力，5年以上</td></tr>
  <tr><td class="score-low">1-2</td><td>纯学术研究，商业前景不明</td></tr>
</table>"""

    # Sidebar TOC
    html += "</div><!-- main -->\n<div class='sidebar'>\n<nav class='toc'>\n"
    html += "<h3>目录 / TOC</h3>\n<ul>\n"
    html += "<li><a href='#overview'>📊 今日概览</a></li>\n"
    html += "<li><a href='#by-source'>📑 按来源</a></li>\n"
    html += "<li><a href='#by-company'>📇 按公司</a></li>\n"
    html += "<li><a href='#top-stories'>🔥 头条深度</a></li>\n"
    html += "<li><a href='#top-tech'>🧪 技术 Top 20</a></li>\n"
    html += "<li><a href='#top-biz'>💰 商用 Top 20</a></li>\n"
    html += "<li><a href='#tags'>🔖 标签云</a></li>\n"
    html += "<li><a href='#scoring'>📝 评分说明</a></li>\n"
    html += "</ul>\n</nav>\n</div><!-- sidebar -->\n</div><!-- container -->\n"

    # JS for search and theme toggle
    html += """
<script>
  function toggleTheme() {
    document.body.classList.toggle('light');
    localStorage.setItem('theme', document.body.classList.contains('light') ? 'light' : 'dark');
  }
  if (localStorage.getItem('theme') === 'light') document.body.classList.add('light');

  const search = document.getElementById('search');
  if (search) {
    let timer;
    search.addEventListener('input', function() {
      clearTimeout(timer);
      const q = this.value.toLowerCase().trim();
      timer = setTimeout(() => doSearch(q), 200);
    });
  }
  function doSearch(q) {
    // Clear previous highlights
    document.querySelectorAll('.highlight').forEach(el => {
      el.outerHTML = el.innerHTML;
    });
    if (!q) {
      document.querySelectorAll('.item-card, details, tr, .item').forEach(el => el.style.display = '');
      return;
    }
    document.querySelectorAll('.item-card, details, tr, .item').forEach(el => el.style.display = '');
    document.querySelectorAll('.item-card, tr, .item').forEach(el => {
      const text = el.textContent.toLowerCase();
      if (text.indexOf(q) === -1) {
        el.style.display = 'none';
      } else {
        // Highlight matches
        el.innerHTML = el.innerHTML.replace(new RegExp('(' + q.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi'), '<span class="highlight">$1</span>');
      }
    });
  }
</script>
</body>
</html>"""

    return html


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Tech Scout Daily Generator")
    parser.add_argument("--input", required=True, help="Input JSON file from scraper")
    parser.add_argument("--output", default="/tmp/tech_scout_daily.md", help="Output file (extension auto-determined if --format=both)")
    parser.add_argument("--format", choices=["md", "html", "both"], default="md", help="Output format: md / html / both")
    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: Cannot read input file: {e}", file=sys.stderr)
        sys.exit(1)

    if not data.get("items"):
        print("ERROR: No items in input file.", file=sys.stderr)
        sys.exit(1)

    base = args.output.rsplit(".", 1)[0] if args.output.endswith((".md", ".html")) else args.output

    outputs = []
    if args.format in ("md", "both"):
        md_path = f"{base}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(generate_markdown(data))
        outputs.append(md_path)

    if args.format in ("html", "both"):
        html_path = f"{base}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(generate_html(data))
        outputs.append(html_path)

    print(f"Done. Output: {', '.join(outputs)}", file=sys.stderr)


if __name__ == "__main__":
    main()