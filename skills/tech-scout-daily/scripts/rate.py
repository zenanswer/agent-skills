#!/usr/bin/env python3
"""LLM 评分：给每条资讯打技术价值 / 商用价值分，替换关键词启发式。

关键词计分只看「摘要里命中多少个术语」，论文摘要长、术语密就必然满分，
新闻摘要短就必然低分——分数衡量的是文本长度而不是内容质量。这里改用 LLM
读标题+摘要做判断，并与 generate_daily.py 的来源配额配合，避免单一来源刷屏。
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from llm_common import (
    RATE_MODEL,
    chat,
    extract_json_array,
    llm_available,
)

RUBRIC = """你是资深 AI 技术侦察编辑，请给下面每条资讯打分。

对每条给出两个 0-10 分（允许一位小数）：

tech（技术价值）——这条内容本身的技术含量，而不是标题里有多少热词：
- 9-10：提出新范式/新机制，或给出可复现的关键结果，明显改变领域做法
- 7-8：有实质新方法、新评测或新系统，同行能直接复用
- 5-6：扎实的增量改进、有价值的综述/基准
- 3-4：工程优化、复现、调参，或宣传性很强的产品发布
- 1-2：纯营销、榜单页、教程、基本没有技术信息

biz（商用价值）——1-3 年内能否变成生意：
- 9-10：百亿级市场，窗口已开，路径清晰
- 7-8：十亿级市场，1-2 年可落地，有明确买家
- 5-6：场景明确但需验证（新硬件、新合规、新品类）
- 3-4：远期（5 年以上）或客户极窄
- 1-2：纯学术，没有商业路径

校准要求：
1. 论文不等于高分：摘要很长、术语密集但贡献平庸的给 5-6。
2. 新闻不等于低技术分：真实的产业技术事件（安全事故、并购、能力评测、
   价格/成本变化）可以给 6-8。
3. 不要因为摘要长短调分；summary 缺失时只按标题判断，并在 why 里写"仅标题"。
4. 分布要散开，不要给一半条目 7 或 8 分，也不要全部压在 5-6。
5. 开源仓库只是今天上了 trending 榜、没有新版本/新能力时，tech ≤5、biz ≤6；
   知名度高不等于当日情报价值高（数据库、前端框架这类通用基础设施尤其如此）。
6. 若内容明显是 6 个月前的旧论文/旧项目重新上榜（看 date 字段），tech 和 biz 各降 1-2：
   影响已经发生，不是新情报。
7. why 用一句中文（不超过 40 字）说明最关键的依据。

只输出 JSON 数组，元素形如 {"i":0,"tech":7.5,"biz":3,"why":"…"}，
i 必须原样回传，不要输出任何其他文字。
"""


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _rows_for(items: list[dict], indexes: list[int]) -> list[dict]:
    rows = []
    for i in indexes:
        item = items[i]
        rows.append(
            {
                "i": i,
                "source": item.get("source", ""),
                "type": item.get("source_type", ""),
                "title": _truncate(item.get("title", ""), 200),
                "summary": _truncate(item.get("summary", ""), 900),
                "date": item.get("date", ""),
            }
        )
    return rows


def _rate_batch(rows: list[dict], model: str) -> dict[int, dict]:
    """请求一批评分；失败重试一次，仍失败则抛异常交给上层降级。"""
    prompt = RUBRIC + "\n" + json.dumps(rows, ensure_ascii=False)
    last_error: Exception | None = None
    for _ in range(2):
        try:
            return _parse_ratings(extract_json_array(chat(prompt, model)))
        except Exception as exc:  # 网络错误、JSON 解析失败、字段缺失都走重试
            last_error = exc
    raise RuntimeError(f"LLM 评分失败: {last_error}")


def _parse_ratings(payload: list) -> dict[int, dict]:
    ratings: dict[int, dict] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("i"))
            tech = float(row.get("tech"))
            biz = float(row.get("biz"))
        except (TypeError, ValueError):
            continue
        ratings[idx] = {
            "tech": max(0.0, min(10.0, tech)),
            "biz": max(0.0, min(10.0, biz)),
            "why": str(row.get("why") or "").strip()[:120],
        }
    if not ratings:
        raise ValueError("响应里没有可用的评分")
    return ratings


def rate_items(
    items: list[dict],
    model: str = "",
    batch_size: int = 8,
    workers: int = 4,
    limit: int = 0,
    skip_rated: bool = True,
) -> dict:
    """给 items 打 LLM 分（原地修改），返回统计信息。"""
    model = model or RATE_MODEL
    todo = [
        i
        for i, item in enumerate(items)
        if not (skip_rated and item.get("score_method") == "llm")
    ]
    if limit:
        todo = todo[:limit]
    if not todo:
        return {"rated": 0, "failed": 0, "chunks": 0, "model": model}

    batches = [
        (start, todo[start : start + batch_size])
        for start in range(0, len(todo), batch_size)
    ]
    print(
        f"  LLM 评分（{model}，{len(todo)} 条 / {len(batches)} 批，workers={workers}）…",
        file=sys.stderr,
    )

    rated = failed = 0

    def _run(chunk: tuple) -> tuple[list[int], dict[int, dict]]:
        _, indexes = chunk
        return indexes, _rate_batch(_rows_for(items, indexes), model)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for done, (chunk, result) in enumerate(
            zip(batches, pool.map(_run, batches)), 1
        ):
            indexes = chunk[1]
            try:
                _, ratings = result
            except Exception as exc:
                print(
                    f"  [WARN] 第 {done}/{len(batches)} 批评分失败，保留关键词分：{exc}",
                    file=sys.stderr,
                )
                failed += len(indexes)
                continue
            for idx in indexes:
                rating = ratings.get(idx)
                if not rating:
                    failed += 1
                    continue
                item = items[idx]
                item.setdefault("keyword_tech_value", item.get("tech_value"))
                item.setdefault("keyword_business_value", item.get("business_value"))
                tech, biz = rating["tech"], rating["biz"]
                # 摘要过短时信息量不足，分数向中间压，避免凭品牌名给高分
                if len((item.get("summary") or "").strip()) < 60:
                    tech, biz = min(tech, 7.0), min(biz, 7.0)
                item["tech_value"] = round(tech, 1)
                item["business_value"] = round(biz, 1)
                item["rating_reason"] = rating["why"]
                item["score_method"] = "llm"
                item["scored_model"] = model
                rated += 1
            print(
                f"  [{sum(len(c[1]) for c in batches[:done])}/{len(todo)}] rated",
                file=sys.stderr,
            )

    return {"rated": rated, "failed": failed, "chunks": len(batches), "model": model}


def main():
    parser = argparse.ArgumentParser(description="Tech Scout Daily — LLM 评分")
    parser.add_argument(
        "--input", required=True, help="输入 JSON（scraper 或翻译产物）"
    )
    parser.add_argument("--output", required=True, help="输出 JSON（带 LLM 评分）")
    parser.add_argument("--model", default="", help="评分模型（默认 RATE_LLM_MODEL）")
    parser.add_argument("--batch", type=int, default=8, help="每批条数（默认 8）")
    parser.add_argument("--workers", type=int, default=4, help="并发批数（默认 4）")
    parser.add_argument("--limit", type=int, default=0, help="只评前 N 条（调试用）")
    parser.add_argument(
        "--rater",
        choices=["auto", "llm", "keyword"],
        default="auto",
        help="auto=有 LLM 配置就评；keyword=跳过评分",
    )
    parser.add_argument("--force", action="store_true", help="已评过的也重评")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])

    use_llm = args.rater == "llm" or (args.rater == "auto" and llm_available())
    if not use_llm:
        reason = (
            "指定的 rater=keyword"
            if args.rater == "keyword"
            else "未配置 LLM_API_URL / LLM_API_KEY"
        )
        print(f"  跳过 LLM 评分（{reason}），沿用关键词启发式分", file=sys.stderr)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return

    stats = rate_items(
        items,
        model=args.model,
        batch_size=args.batch,
        workers=args.workers,
        limit=args.limit,
        skip_rated=not args.force,
    )

    data["scoring"] = stats
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(
        f"Done. LLM 评分 {stats['rated']} 条，失败 {stats['failed']} 条"
        f"（模型 {stats['model']}）。Output: {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
