# -*- coding: utf-8 -*-
"""TC-CORE：核心能力补充用例。

这一组不是为凑覆盖率，而是补上之前矩阵遗漏的真实入口：

1. **目录批量加载 load_dir**
   File 页除了单文件上传，还支持指定目录批量导入，走的是另一个入口，
   之前矩阵只测了 load_files。

2. **索引重载 load_index**
   服务重启后必须先读回磁盘上的索引才能问答。BUG-TRAG-001
   （空索引残留导致查询全崩）就发生在这条路径上，属于高风险区。

3. **中文分块器**
   中文文档的切块质量直接决定召回效果。默认 pipeline 走 SentenceSplitter，
   但项目内置的两个中文分块器是可选能力，需要有回归用例兜住。

4. **metadata 清洗 sanitize_for_json**
   Web 抓取时 bs4.Tag 混进 metadata 会让 json.dumps 直接失败，
   这一层是防止存储损坏的兜底。
"""
import json
from datetime import datetime
from pathlib import Path

import pytest
import allure

pytestmark = [pytest.mark.smoke, allure.feature("核心能力")]


# --------------------------------------------------------------------------- 目录加载
@allure.story("知识库加载入口")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("目录批量加载应把目录下所有可解析文件都建入索引")
def test_load_dir_indexes_all_files(kb, attach):
    """load_dir 是 File 页「批量导入」的入口，必须覆盖目录下全部文件。"""
    kb.put("产品手册.txt", "补充说明.txt")

    im = kb.manager()
    nodes = im.load_dir(str(kb.data_dir), 512, 100) or []
    stats = kb.stats(im)
    text = kb.text(nodes)

    attach(f"节点数={len(nodes)}\n索引规模={stats}\n正文前 200 字:\n{text[:200]}", "目录加载结果")

    assert nodes, "目录加载未产出任何节点"
    assert stats["docstore"] >= 2, f"目录下 2 个文件，docstore 只有 {stats['docstore']} 条记录"
    assert "云帆" in text, "产品手册内容未进入索引"
    assert "收纳包" in text or "补充" in text, "补充说明内容未进入索引"


# --------------------------------------------------------------------------- 索引重载
@allure.story("索引加载与重载")
@allure.severity(allure.severity_level.BLOCKER)
@allure.title("服务重启后应能从磁盘读回索引，且节点数与持久化前一致")
def test_index_reload_after_restart(kb, attach):
    """模拟重启：新建 IndexManager 重新读盘，节点数必须与上次一致。

    这是 BUG-TRAG-001 的同一条路径——只要这里读错索引，查询就会 100% 失败。
    """
    from server.index import IndexManager

    im, nodes = kb.load(["产品手册.txt"], 200, 50)
    before = kb.stats(im)

    im2 = IndexManager("kb")
    exists = im2.check_index_exists()
    ix = im2.load_index()
    after_nodes = len(ix.index_struct.nodes_dict)

    attach(f"持久化前={before}\n重载后 nodes_dict={after_nodes}\ncheck_index_exists={exists}",
           "重载结果")

    assert exists is True, "重新加载时未发现已有索引"
    assert after_nodes == before["nodes_dict"], \
        f"重载后节点数 {after_nodes} 与持久化前 {before['nodes_dict']} 不一致"
    assert after_nodes > 0, "重载到了空索引（BUG-TRAG-001 的触发形态）"


@allure.story("索引加载与重载")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("仅有 index_id 未加载过索引时，应能按 id 从存储中载入")
def test_load_index_by_id(kb):
    """load_index 的另一条分支：只给 index_id，靠 id 从存储里载入。"""
    from server.index import IndexManager

    im, _ = kb.load(["产品手册.txt"], 200, 50)
    expect = kb.stats(im)["nodes_dict"]

    im2 = IndexManager("kb")
    im2.check_index_exists()
    index_id = im2.index_id

    im3 = IndexManager("kb")
    im3.index_id = index_id  # 有 id、但 index 还是 None，强制走按 id 载入分支
    ix = im3.load_index()

    assert len(ix.index_struct.nodes_dict) == expect, "按 index_id 载入的索引内容不完整"


# --------------------------------------------------------------------------- 中文分块
@allure.story("中文文本切分")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("中文分块器应按句末标点切分，且不丢失正文内容")
def test_chinese_text_splitter_sentence_split():
    """中文句子切分：句号/问号/感叹号都应作为切分点，内容不得丢失。"""
    from server.splitters import ChineseTextSplitter

    text = ("云帆 X3 标准版售价 1899 元。整机保修期为 12 个月。电池容量 4200 毫安时！"
            "是否支持 5G？产品重量为 238 克。")
    parts = ChineseTextSplitter(pdf=False, sentence_size=250, chunk_size=250,
                                chunk_overlap=0).split_text(text)

    assert len(parts) >= 4, f"5 句话只切出 {len(parts)} 段，切分粒度不足"
    joined = "".join(parts)
    for kw in ("1899", "12 个月", "4200", "5G", "238 克"):
        assert kw in joined, f"切分后丢失关键内容：{kw}"


@allure.story("中文文本切分")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("递归分块器切出的每块不应显著超出 chunk_size")
def test_chinese_recursive_splitter_chunk_size():
    """chunk_size 是硬约束，超长文本必须被切到限制以内。"""
    from server.splitters import ChineseRecursiveTextSplitter

    text = "云帆 X3 使用说明。" * 200  # 约 2000 字
    splitter = ChineseRecursiveTextSplitter(chunk_size=120, chunk_overlap=20)
    parts = splitter.split_text(text)

    assert len(parts) > 1, "长文本未被切分"
    over = [p for p in parts if len(p) > 120 * 1.5]
    assert not over, f"{len(over)} 个分块显著超出 chunk_size，最长 {max(len(p) for p in over)} 字"


# --------------------------------------------------------------------------- metadata 清洗
@allure.story("存储健壮性")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("metadata 混入不可序列化对象时应能清洗，保证可写入 JSON 存储")
def test_sanitize_metadata_for_json():
    """Web 抓取会把 bs4.Tag 之类对象塞进 metadata，不清洗会导致持久化失败。"""
    from server.utils_json import sanitize_for_json

    class FakeTag:
        def __str__(self):
            return "<div class='x'>"

    raw = {
        "title": "产品页",
        "fetched_at": datetime(2026, 10, 20, 12, 0, 0),
        "file_path": Path("data/产品页.html"),
        "tag": FakeTag(),
        "nested": {"items": [1, 2, {"obj": FakeTag()}]},
    }
    clean = sanitize_for_json(raw)

    serialized = json.dumps(clean, ensure_ascii=False)  # 清洗后必须可序列化
    assert "产品页" in serialized
    assert "2026-10-20" in serialized, "datetime 未被转成字符串"
    assert "产品页.html" in serialized, "Path 未被转成字符串"
    assert "<div" in serialized, "自定义对象未被兜底转成 str"
    assert "nested" in clean and isinstance(clean["nested"], dict), "嵌套结构被破坏"
