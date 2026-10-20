# -*- coding: utf-8 -*-
"""TC-CHUNK：切块参数边界矩阵。

原文 1165 字，判定两条：
1. 不能崩（chunk_size=1 这类非法值应被前置校验并给出提示）
2. 不能重复膨胀（overlap >= chunk_size 时内容被反复复制）

对应缺陷 BUG-TRAG-012。
"""
import pytest
import allure

from helpers import ORIG_TEXT_LEN

pytestmark = [pytest.mark.smoke, allure.feature("切块参数")]

VALID_PARAMS = [
    (200, 50, 10),
    (512, 100, 3),
    (1024, 200, 2),
    (4096, 512, 1),
]


@allure.story("合理参数")
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.parametrize("cs,ov,expect_nodes", VALID_PARAMS,
                         ids=[f"chunk{c[0]}_overlap{c[1]}" for c in VALID_PARAMS])
def test_valid_chunk_params(kb, cs, ov, expect_nodes, attach):
    """合理参数下：节点数符合预期，内容总量不出现成倍膨胀。"""
    with allure.step(f"以 chunk={cs} / overlap={ov} 建索引"):
        im, nodes = kb.load(["产品手册.txt"], cs, ov)
        total = sum(len(n.text or "") for n in nodes)
        ratio = total / ORIG_TEXT_LEN

    attach(f"参数={cs}/{ov}\n节点数={len(nodes)}（预期 {expect_nodes}）\n"
           f"内容总字符={total}\n原文={ORIG_TEXT_LEN} 字\n膨胀率={ratio:.2f}x", "切块统计")

    assert abs(len(nodes) - expect_nodes) <= 2, \
        f"节点数 {len(nodes)} 与预期 {expect_nodes}（±2）不符"
    # 允许 2% 误差：切块会裁掉首尾空白，不能按字节严格相等
    assert total >= ORIG_TEXT_LEN * 0.98, f"切块后内容 {total} 字，明显少于原文 {ORIG_TEXT_LEN} 字"
    assert ratio < 2.0, f"内容膨胀 {ratio:.2f}x，overlap 设置不合理"


@allure.story("非法参数")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("chunk_size=1 应给出参数校验提示，而不是抛底层库异常")
@pytest.mark.xfail(reason="BUG-TRAG-012：chunk_size 无下限校验，抛 ValueError(Metadata length ...)", strict=False)
def test_chunk_size_too_small(kb):
    try:
        kb.load(["产品手册.txt"], 1, 0)
    except ValueError as e:
        if "Metadata length" in str(e):
            pytest.fail(f"底层库原始异常直接抛出，未做参数校验: {e}")
        return


@allure.story("非法参数")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("overlap >= chunk_size 时内容不应成倍重复")
@pytest.mark.parametrize("cs,ov", [(100, 100), (512, 600)], ids=["100_100", "512_600"])
@pytest.mark.xfail(reason="BUG-TRAG-012：overlap>=chunk_size 无校验，内容膨胀 4.78 倍", strict=False)
def test_overlap_not_less_than_chunk(kb, cs, ov):
    im, nodes = kb.load(["产品手册.txt"], cs, ov)
    total = sum(len(n.text or "") for n in nodes)
    ratio = total / ORIG_TEXT_LEN
    assert ratio < 2.0, f"overlap({ov}) >= chunk_size({cs}) 导致内容膨胀 {ratio:.2f}x"
