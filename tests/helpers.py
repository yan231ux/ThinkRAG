# -*- coding: utf-8 -*-
"""测试公共工具：LLM 初始化、单次提问、拒答判定。"""
import os
import time

import allure

# 产品手册.txt 正文字数，切块膨胀率的分母
ORIG_TEXT_LEN = 1165

# 拒答词表：模型在资料未覆盖时会用这些表达
REFUSE_WORDS = [
    "无法", "未包含", "未提及", "没有提供", "未提供",
    "不清楚", "未说明", "无法确认", "没有提到", "未提到",
    "资料中没有", "文档中没有", "不包含", "无从得知",
]


def setup_llm(temperature=None):
    """按 config_store 里已保存的 DeepSeek 配置初始化 LLM。"""
    from server.models.llm_api import create_openai_llm
    from server.stores.config_store import CONFIG_STORE

    info = CONFIG_STORE.get(key="current_llm_info")
    settings = CONFIG_STORE.get(key="current_llm_settings") or {}
    if not info or not info.get("api_key"):
        raise RuntimeError("config_store 中没有可用的 LLM 配置，无法执行问答类用例")

    return create_openai_llm(
        model_name=info["model"],
        api_base=info["api_base"],
        api_key=info["api_key"],
        temperature=settings.get("temperature", 0.1) if temperature is None else temperature,
        system_prompt=settings.get("system_prompt"),
    )


def ask(query_engine, question, timeout=120):
    """执行一次提问，返回结构化结果。

    注意：response_gen 是流式生成器，必须消费完才算真正拿到答案，
    否则计时会严重偏小（这也是 BUG-TRAG-003 的成因）。
    """
    t0 = time.time()
    answer, found, error = "", None, None
    try:
        resp = query_engine.query(question)
        try:
            found = len(resp.source_nodes)
        except Exception:
            found = None
        gen = getattr(resp, "response_gen", None)
        answer = "".join(list(gen)) if gen is not None else str(getattr(resp, "response", resp))
    except Exception as e:  # noqa: BLE001 - 测试需要如实记录异常类型
        error = f"{type(e).__name__}: {e}"
    cost = round(time.time() - t0, 2)

    row = {"q": question, "answer": answer.strip(), "found": found,
           "seconds": cost, "error": error}
    allure.attach(
        f"问题: {question}\n"
        f"命中片段: {found}\n"
        f"耗时: {cost}s\n"
        f"异常: {error or '无'}\n\n"
        f"回答:\n{row['answer'][:1200] or '(空)'}",
        name=f"Q: {question[:40]}",
        attachment_type=allure.attachment_type.TEXT,
    )
    return row


def is_refused(answer: str) -> bool:
    """是否属于拒答。判定必须先于关键词命中，否则拒答句里顺带出现的数字会造成误判。"""
    return any(w in (answer or "") for w in REFUSE_WORDS)


def build_engine(im, top_k=5, response_mode="simple_summarize", use_reranker=False):
    from server.engine import create_query_engine

    return create_query_engine(
        index=im.index,
        top_k=top_k,
        response_mode=response_mode,
        use_reranker=use_reranker,
    )
