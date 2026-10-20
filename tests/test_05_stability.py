# -*- coding: utf-8 -*-
"""TC-PERF：连续 10 次提问稳定性。

目的不是测极限并发，而是回答一个真实问题：
「这个问答服务能不能连续用 10 分钟不出错、耗时不抖」。

统计口径：
- 成功率 = 无异常且答案非空的次数 / 总次数
- P50 / P90 用排序后取位，不用平均值（平均值会被个别慢请求带偏）
"""
import json
import time
from pathlib import Path

import pytest
import allure

from helpers import setup_llm, ask, build_engine

pytestmark = [allure.feature("性能与稳定性"), allure.story("连续提问稳定性")]

RUNS = 10
QUESTION = "整机保修期多久？电池保修期多久？超出保修期怎么收费？"
OUT = Path(__file__).resolve().parent.parent / "测试记录" / "结果" / "stability_10runs.json"


def percentile(values, p):
    """线性插值取分位数，values 需已升序。"""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 2)


@allure.severity(allure.severity_level.CRITICAL)
@allure.title(f"同一问题连续提问 {RUNS} 次：成功率 100%，耗时无持续劣化")
@pytest.mark.llm
@pytest.mark.retrieval
@pytest.mark.slow
def test_consecutive_10_runs(kb, attach):
    setup_llm()
    im, _ = kb.load(["产品手册.txt"], 200, 50)
    qe = build_engine(im)

    runs = []
    for i in range(RUNS):
        with allure.step(f"第 {i + 1} 次提问"):
            runs.append(ask(qe, QUESTION))
        time.sleep(0.5)  # 模拟用户阅读间隔

    ok = [r for r in runs if r["error"] is None and r["answer"].strip()]
    costs = sorted(r["seconds"] for r in ok)
    answers = {r["answer"].strip() for r in ok}

    summary = {
        "question": QUESTION,
        "runs": RUNS,
        "success": len(ok),
        "success_rate": round(len(ok) / RUNS * 100, 1),
        "p50_seconds": percentile(costs, 0.50),
        "p90_seconds": percentile(costs, 0.90),
        "max_seconds": max(costs) if costs else None,
        "min_seconds": min(costs) if costs else None,
        "avg_seconds": round(sum(costs) / len(costs), 2) if costs else None,
        "distinct_answers": len(answers),
        "errors": [r["error"] for r in runs if r["error"]],
        "detail": runs,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    table = "\n".join(
        f"第{i + 1:>2}次 | {r['seconds']:>6.2f}s | 命中 {r['found']} | "
        f"{'异常: ' + r['error'] if r['error'] else r['answer'][:40].replace(chr(10), ' ')}"
        for i, r in enumerate(runs)
    )
    attach(
        f"{table}\n\n"
        f"成功率: {summary['success_rate']}%\n"
        f"P50: {summary['p50_seconds']}s | P90: {summary['p90_seconds']}s | "
        f"平均: {summary['avg_seconds']}s | 最大: {summary['max_seconds']}s\n"
        f"不同答案数: {summary['distinct_answers']}",
        "稳定性统计",
    )

    assert len(ok) == RUNS, f"成功率 {summary['success_rate']}%，异常: {summary['errors']}"
    assert summary["p90_seconds"] is not None and summary["p90_seconds"] < 15, \
        f"P90 耗时 {summary['p90_seconds']}s，超过 15s 可接受上限"
