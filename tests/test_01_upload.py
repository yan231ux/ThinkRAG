# -*- coding: utf-8 -*-
"""TC-UPLOAD：知识库上传 —— 文件格式支持矩阵。

对应缺陷报告 BUG-TRAG-008 / 009 / 013 / 014 / 016。
用例判定不看"能不能跑通"，而看"入库内容是否正确"：
能建索引不等于测通过，HTML 源码入库、二进制当文本读，都属于失败。
"""
from pathlib import Path

import pytest
import allure

pytestmark = [pytest.mark.smoke, allure.feature("知识库上传")]


TEXT_FORMATS = [
    ("产品手册.md", "标题分段"),
    ("产品价格表.csv", "表格行"),
    ("产品说明书.docx", "中文正文"),
    ("测试文档.pdf", "中文正文"),
    ("结构化数据.json", "JSON 原文"),
    ("产品 手册(最终版)#1.txt", "特殊字符文件名"),
]


@allure.story("文件格式支持矩阵")
@allure.severity(allure.severity_level.CRITICAL)
@pytest.mark.parametrize("fname,kind", TEXT_FORMATS, ids=[f[0] for f in TEXT_FORMATS])
def test_supported_format_indexed(kb, fname, kind, attach):
    """支持的文档格式应能解析出非空文本并成功入库。"""
    with allure.step(f"上传 {fname} 并构建索引"):
        im, nodes = kb.load([fname], chunk_size=512, overlap=100)
        stats = kb.stats(im)
        text = kb.text(nodes)

    attach(f"节点数={len(nodes)}\n索引规模={stats}\n\n前 300 字:\n{text[:300]}", "解析结果")

    assert nodes, f"{fname} 未解析出任何节点"
    assert text.strip(), f"{fname} 解析结果为空"
    assert stats["docstore"] and stats["docstore"] > 0, "docstore 中无文档记录"


@allure.story("文件格式支持矩阵")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("上传 Excel 表格应正常解析入库")
@pytest.mark.xfail(reason="BUG-TRAG-008：requirements.txt 未声明 openpyxl，Excel 解析直接抛 ImportError", strict=False)
def test_xlsx_supported(kb):
    im, nodes = kb.load(["产品配置表.xlsx"], chunk_size=512, overlap=100)
    assert kb.text(nodes).strip(), "xlsx 未解析出内容"


@allure.story("文件格式支持矩阵")
@allure.severity(allure.severity_level.CRITICAL)
@allure.title("上传 PPTX 应正常解析入库")
@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "测试记录" / "测试数据" / "答辩演示.pptx").exists(),
    reason="PPTX 样本 6.9MB，未纳入版本库；CI 环境跳过，本地有样本时执行",
)
@pytest.mark.xfail(reason="BUG-TRAG-008：README 声称支持 PPTX，但 python-pptx 等依赖未声明", strict=False)
def test_pptx_supported(kb):
    im, nodes = kb.load(["答辩演示.pptx"], chunk_size=512, overlap=100)
    assert kb.text(nodes).strip(), "pptx 未解析出内容"


@allure.story("内容入库质量")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("HTML 文件入库前应剥离标签，不应把源码写入向量索引")
@pytest.mark.xfail(reason="BUG-TRAG-014：HTML 未剥离标签，<html>/<div> 等源码直接入库", strict=False)
def test_html_strips_markup(kb):
    im, nodes = kb.load(["产品页.html"], chunk_size=512, overlap=100)
    text = kb.text(nodes).lower()
    assert "<div" not in text and "<html" not in text and "<p>" not in text, \
        "HTML 标签未剥离，原始源码进入索引"


@allure.story("文件类型校验")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("二进制文件（.exe）应被拒绝，不应作为纯文本入库")
@pytest.mark.xfail(reason="BUG-TRAG-013：无扩展名白名单，.exe 被当作纯文本读入索引", strict=False)
def test_binary_file_rejected(kb):
    try:
        im, nodes = kb.load(["伪装文件.exe"], chunk_size=512, overlap=100)
    except Exception:
        return  # 被正确拦截
    pytest.fail(f"exe 未被拦截，仍写入了 {len(nodes)} 个节点")


@allure.story("文件类型校验")
@allure.severity(allure.severity_level.MINOR)
@allure.title("无扩展名文件应被拒绝或明确提示不支持")
@pytest.mark.xfail(reason="BUG-TRAG-013：无扩展名文件被按纯文本读入", strict=False)
def test_no_extension_rejected(kb):
    try:
        im, nodes = kb.load(["无扩展名文件"], chunk_size=512, overlap=100)
    except Exception:
        return
    pytest.fail(f"无扩展名文件未被拦截，写入了 {len(nodes)} 个节点")


@allure.story("空文件边界")
@allure.severity(allure.severity_level.NORMAL)
@allure.title("0 字节空文件不应产生任何节点")
@pytest.mark.xfail(reason="BUG-TRAG-009：0 字节文件未拦截，向索引写入空节点", strict=False)
def test_empty_file_produces_no_node(kb):
    im, nodes = kb.load(["空文件.txt"], chunk_size=512, overlap=100)
    assert not nodes, f"0 字节文件生成了 {len(nodes)} 个节点"
