# -*- coding: utf-8 -*-
"""TC-DATA：知识库数据一致性。

覆盖四条真实用户路径：重复上传、同名覆盖、多文档共存、删除单文档。
对应缺陷 BUG-TRAG-002 / 010 / 011。
"""
import pytest
import allure

from helpers import setup_llm, ask, build_engine, is_refused

pytestmark = allure.feature("数据一致性")


# ------------------------------------------------------------------ 重复上传
@allure.story("重复上传")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("同一文件重复上传不应重复入库")
@pytest.mark.smoke
@pytest.mark.xfail(reason="BUG-TRAG-010：重复上传不去重，切块与向量成倍增长", strict=False)
def test_duplicate_upload_does_not_grow(kb, attach):
    im, n1 = kb.load(["产品手册.txt"], 200, 50)
    st1 = kb.stats(im)

    n2 = im.load_files([{"name": "产品手册.txt"}], 200, 50)
    st2 = kb.stats(im)

    attach(f"第一次: 节点 {len(n1)} / 索引 {st1}\n第二次: 节点 {len(n2)} / 索引 {st2}", "两次上传对比")

    assert st2["docstore"] <= st1["docstore"], (
        f"重复上传后 docstore 从 {st1['docstore']} 增长到 {st2['docstore']}，同一文档存在多套切块"
    )


# ------------------------------------------------------------------ 同名覆盖
@allure.story("同名覆盖")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("同名文件重新上传后，回答应反映新内容")
@pytest.mark.llm
@pytest.mark.retrieval
@pytest.mark.xfail(reason="BUG-TRAG-011：同名文件不覆盖，旧内容继续生效", strict=False)
def test_same_name_overwrite_effective(kb, attach):
    setup_llm()
    im, _ = kb.load(["产品手册.txt"], 200, 50)

    qe = build_engine(im)
    before = ask(qe, "标准版售价是多少元？")
    assert "1899" in before["answer"], f"基线回答异常: {before['answer'][:120]}"

    # 用户修改同名文件后重新上传
    path = kb.data_dir / "产品手册.txt"
    path.write_text(
        path.read_text(encoding="utf-8").replace("标准版 1899 元", "标准版 9999 元"),
        encoding="utf-8",
    )
    im.load_files([{"name": "产品手册.txt"}], 200, 50)
    st_after = kb.stats(im)
    attach(f"覆盖后索引规模: {st_after}", "索引规模")

    qe2 = build_engine(im)
    after = ask(qe2, "标准版售价是多少元？")

    assert "9999" in after["answer"], (
        f"文件已改为 9999 元，回答仍为「{after['answer'][:80]}」，旧内容未被替换"
    )


# ------------------------------------------------------------------ 多文档
@allure.story("多文档共存")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("上传两份文档后，三个问题应分别命中正确来源")
@pytest.mark.llm
@pytest.mark.retrieval
def test_multi_document_retrieval(kb, attach):
    setup_llm()
    im, _ = kb.load(["产品手册.txt"], 200, 50)
    kb.put("补充说明.txt")
    im.load_files([{"name": "补充说明.txt"}], 200, 50)
    st = kb.stats(im)
    attach(f"索引规模: {st}", "多文档索引")

    qe = build_engine(im)
    r1 = ask(qe, "企业采购 50 台有折扣吗？")   # 补充说明
    r2 = ask(qe, "旅行收纳包多少钱？")          # 补充说明
    r3 = ask(qe, "整机保修期多久？")            # 产品手册

    assert "折" in r1["answer"] or "80" in r1["answer"], f"采购折扣未命中: {r1['answer'][:80]}"
    assert "129" in r2["answer"], f"收纳包价格未命中: {r2['answer'][:80]}"
    assert "12" in r3["answer"], f"保修期未命中: {r3['answer'][:80]}"


# ------------------------------------------------------------------ 删除
@allure.story("删除一致性")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("删除单份文档后，其切块与向量应同步清理")
@pytest.mark.llm
@pytest.mark.retrieval
def test_delete_document_cleanup(kb, attach):
    setup_llm()
    im, _ = kb.load(["产品手册.txt"], 200, 50)
    kb.put("补充说明.txt")
    im.load_files([{"name": "补充说明.txt"}], 200, 50)
    before = kb.stats(im)

    qe = build_engine(im)
    a_before = ask(qe, "旅行收纳包多少钱？")
    assert "129" in a_before["answer"], "删除前应能回答收纳包价格"

    target = None
    for rid, info in im.index.ref_doc_info.items():
        if "补充说明" in ((info.metadata or {}).get("file_name") or ""):
            target = rid
    assert target, "未找到补充说明的 ref_doc_id"

    im.delete_ref_doc(target)
    after = kb.stats(im)
    attach(f"删除前 {before}\n删除后 {after}", "索引规模变化")

    assert after["docstore"] < before["docstore"], "删除文档后 docstore 未减少"
    assert after["nodes_dict"] < before["nodes_dict"], "删除文档后索引结构节点数未减少"
    assert after["vectors"] < before["vectors"], "删除文档后向量条目未减少，存在残留"

    qe2 = build_engine(im)
    a_after = ask(qe2, "旅行收纳包多少钱？")
    assert is_refused(a_after["answer"]), f"文档已删除，仍编造出答案: {a_after['answer'][:100]}"


# ------------------------------------------------------------------ 空库边界
@allure.story("空知识库边界")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("知识库被删空后提问，应给出明确提示而不是抛底层异常")
@pytest.mark.llm
@pytest.mark.xfail(reason="BUG-TRAG-002：空语料构建 BM25 时抛 ValueError(max() empty)", strict=False)
def test_query_after_all_deleted(kb):
    setup_llm()
    im, _ = kb.load(["产品手册.txt"], 200, 50)
    for rid in list(im.index.ref_doc_info.keys()):
        im.delete_ref_doc(rid)

    try:
        qe = build_engine(im)
        qe.query("整机保修期多久？")
    except ValueError as e:
        pytest.fail(f"知识库为空时抛出未捕获异常: {e}")
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"知识库为空时抛出未捕获异常: {type(e).__name__}: {e}")
