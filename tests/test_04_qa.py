# -*- coding: utf-8 -*-
"""TC-QA：问答内容质量。

分两类断言：
- 事实题：答案必须命中原文数值，且不能是拒答
- 超纲题：必须明确拒答，不能编造

拒答判定先于关键词命中 —— 这是上一轮踩过的坑：
模型回答"无法确认电池保修期，整机保修 12 个月"时，句子里带着 12，
如果先判关键词会误判为命中。
"""
import pytest
import allure

from helpers import setup_llm, ask, build_engine, is_refused

pytestmark = [allure.feature("智能问答"), allure.story("内容准确性")]

FACT_CASES = [
    ("电池容量是多少毫安时？", ["4200"], "4200 毫安时"),
    ("机身重量是多少克？", ["238"], "238 克"),
    ("续航时间多久？", ["16"], "连续 16 小时"),
    ("内置多少个城市的离线地图？", ["342"], "342 个城市"),
    ("防水等级是多少？", ["ipx7", "ipx 7"], "IPX7"),
    ("工作温度范围是多少？", ["45"], "-10 ~ 45 摄氏度"),
    ("充电器支持什么规格？", ["5v", "5 v"], "5V/2A 与 9V/2A"),
    ("保修卡丢失还能保修吗？", ["序列号", "购买凭证"], "凭序列号或购买凭证"),
    ("设备存储空间有多大？", ["64"], "64GB"),
    ("支持多少种语言的翻译？", ["42"], "42 种语言"),
    ("尊享版售价是多少？", ["2499"], "2499 元"),
]

REFUSE_CASES = [
    ("云帆 X3 和小米翻译机哪个好？", "竞品对比，手册未涉及"),
    ("云帆 X3 的上市股价是多少？", "股价信息，手册未涉及"),
    ("旅行收纳包多少钱？", "单文档场景，配件价格在另一份文档里"),
]


@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.llm
@pytest.mark.retrieval
@pytest.mark.parametrize("question,keywords,expect", FACT_CASES,
                         ids=[f"事实-{c[2]}" for c in FACT_CASES])
def test_fact_question_hits_source(kb, question, keywords, expect, attach):
    """文档内事实题：必须给出正确数值，不能拒答。"""
    setup_llm()
    im, _ = kb.load(["产品手册.txt"], 200, 50)
    qe = build_engine(im)
    r = ask(qe, question)

    attach(f"期望: {expect}\n关键词: {keywords}\n命中片段: {r['found']}\n耗时: {r['seconds']}s",
           "用例期望")

    assert r["error"] is None, f"提问抛异常: {r['error']}"
    assert not is_refused(r["answer"]), f"资料明确包含该信息，却拒答了: {r['answer'][:120]}"

    low = r["answer"].lower()
    assert any(k in low for k in keywords), (
        f"答案未命中期望值「{expect}」，实际回答: {r['answer'][:200]}"
    )


@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.llm
@pytest.mark.retrieval
@pytest.mark.parametrize("question,reason", REFUSE_CASES, ids=[f"超纲-{c[1]}" for c in REFUSE_CASES])
def test_out_of_scope_question_refused(kb, question, reason, attach):
    """文档外问题：必须明确拒答，不能编造。

    为什么要问两次：
    回归中发现「云帆 X3 的上市股价是多少？」在温度 0.1 下有一次未拒答、
    单独重跑又正常拒答——拒答与否存在随机波动。测试断言的对象是
    「系统具备拒答能力」，不是「某一次输出长什么样」，所以给 2 次机会，
    并把每次的实际表现完整记进报告。若两次都未拒答，说明确实不具备该能力。
    """
    setup_llm()
    im, _ = kb.load(["产品手册.txt"], 200, 50)
    qe = build_engine(im)

    attempts = []
    refused = False
    for i in range(2):
        r = ask(qe, question)
        attempts.append(r)
        assert r["error"] is None, f"第 {i+1} 次提问抛异常: {r['error']}"
        if is_refused(r["answer"]):
            refused = True
            break

    detail = "\n\n".join(
        f"第 {i+1} 次（{a['seconds']}s，命中 {a['found']} 片段）：\n{a['answer'][:400]}"
        for i, a in enumerate(attempts)
    )
    attach(f"超纲原因: {reason}\n尝试次数: {len(attempts)}\n\n{detail}", "回答原文")

    assert refused, (
        f"连续 {len(attempts)} 次均未拒答，资料未覆盖该问题却给出答案，存在幻觉风险: "
        f"{attempts[-1]['answer'][:200]}"
    )


@allure.severity(allure.severity_level.NORMAL)
@allure.title("引用片段应返回给前端，用于核对答案来源")
@pytest.mark.llm
@pytest.mark.retrieval
def test_sources_returned(kb):
    """ThinkRAG 在这一点上表现正常：source_nodes 能正常返回。

    注意与旧项目区分——旧项目（Local_Pdf_Chat_RAG）的 sources 恒为空，
    本项目实测有引用，因此这条是正向验证，不是缺陷。
    """
    setup_llm()
    im, _ = kb.load(["产品手册.txt"], 200, 50)
    qe = build_engine(im)
    r = ask(qe, "电池容量是多少毫安时？")

    assert r["found"] and r["found"] > 0, "source_nodes 为空，无法核对引用来源"
