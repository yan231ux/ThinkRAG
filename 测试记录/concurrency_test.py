# -*- coding: utf-8 -*-
"""ThinkRAG 并发压测。

为什么不用 JMeter / locust 打 HTTP：
    ThinkRAG 是 Streamlit 应用，前后端靠 WebSocket 通信，没有 REST 接口。
    压 _stcore/health 只能验证进程活着，测不到检索与生成的真实负载。
    所以这里在「业务入口」施压：直接调用 Query 页同一套 create_query_engine。

两层压测，目的是把瓶颈定位清楚：
    A. 检索层   并发调用 query engine 的检索部分（纯本地：向量 + BM25 + RRF），
                不含 LLM，反映本地算力上限。
    B. 端到端   并发提问，含 DeepSeek 生成，反映用户实际体感。

每个请求都新建一次 query engine（与 Streamlit 每次 rerun 的行为一致），
所以结果里已经包含了 BUG-TRAG-004「重复加载检索器」的开销。

用法：
    .venv/Scripts/python.exe 测试记录/concurrency_test.py
输出：
    测试记录/结果/concurrency.json
"""
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))
os.chdir(PROJ)

OUT = PROJ / "测试记录" / "结果" / "concurrency.json"
FIXTURES = PROJ / "测试记录" / "测试数据"

# 并发梯度 -> 每档请求数。总请求数保持一致，便于横向对比吞吐
LEVELS = [(1, 8), (2, 8), (4, 8), (8, 8)]
QUESTION = "电池容量是多少毫安时？"


def pct(values, p):
    """线性插值分位数，小样本下比 statistics.quantiles 更稳定。"""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return round(s[0], 3)
    k = (len(s) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 3)


def build_env():
    """搭一个与真实启动一致的沙箱环境，不碰本地知识库。"""
    import server.index as index_mod
    from llama_index.core import Settings, StorageContext
    from llama_index.core.storage.docstore import SimpleDocumentStore
    from llama_index.core.storage.index_store import SimpleIndexStore
    from llama_index.core.vector_stores import SimpleVectorStore

    tmp = Path(tempfile.mkdtemp(prefix="thinkrag_conc_"))
    storage_dir, data_dir = tmp / "storage", tmp / "data"
    storage_dir.mkdir()
    data_dir.mkdir()

    ctx = StorageContext.from_defaults(
        docstore=SimpleDocumentStore(),
        index_store=SimpleIndexStore(),
        vector_store=SimpleVectorStore(),
    )
    ctx.persist_dir = str(storage_dir)
    index_mod.STORAGE_CONTEXT = ctx
    index_mod.get_save_dir = lambda: str(data_dir)

    from server.models.embedding import create_embedding_model

    model = create_embedding_model("bge-small-zh-v1.5")
    if model is None:
        raise RuntimeError("嵌入模型加载失败")
    Settings.embed_model = model
    Settings.chunk_size = 1024
    Settings.chunk_overlap = 200

    shutil.copy(FIXTURES / "产品手册.txt", data_dir / "产品手册.txt")
    im = index_mod.IndexManager("kb")
    im.check_index_exists()
    im.load_files([{"name": "产品手册.txt"}], 200, 50)  # 基线：切成 10 块
    return im, tmp


def setup_llm():
    from server.models.llm_api import create_openai_llm
    from server.stores.config_store import CONFIG_STORE

    info = CONFIG_STORE.get(key="current_llm_info")
    settings = CONFIG_STORE.get(key="current_llm_settings") or {}
    if not info:
        raise RuntimeError("未读到 LLM 配置，请先在界面完成模型配置")
    create_openai_llm(
        model_name=info["model"],
        api_base=info["api_base"],
        api_key=info["api_key"],
        temperature=settings.get("temperature", 0.1),
        system_prompt=settings.get("system_prompt"),
    )


def one_query(im, question, with_llm):
    """一次完整的用户提问，返回 (耗时, 是否成功, 错误信息, 答案片段)。"""
    from server.engine import create_query_engine

    t0 = time.perf_counter()
    try:
        # 与 Query 页一致：每次 rerun 都重新建一次 query engine（含检索器）
        qe = create_query_engine(index=im.index, top_k=5,
                                 response_mode="simple_summarize", use_reranker=False)
        if with_llm:
            resp = qe.query(question)
            # streaming=True，必须把生成器消费完才算真正拿到答案，
            # 否则计时会像页面上那样严重偏小（BUG-TRAG-003 的成因）
            gen = getattr(resp, "response_gen", None)
            answer = "".join(list(gen)) if gen is not None else str(getattr(resp, "response", resp))
            if not answer.strip():
                raise RuntimeError("生成结果为空")
        else:
            # 只走检索：取回召回节点，不调用 LLM
            nodes = qe.retriever.retrieve(question)
            answer = f"hit={len(nodes)}"
            if not nodes:
                raise RuntimeError("检索无结果")
        dur = time.perf_counter() - t0
        return dur, True, None, answer[:120]
    except Exception as e:
        dur = time.perf_counter() - t0
        return dur, False, f"{type(e).__name__}: {e}", ""


def run_level(im, concurrency, total, with_llm):
    """跑一档并发，返回该档统计。"""
    latencies, errors, answers = [], [], []
    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(one_query, im, QUESTION, with_llm) for _ in range(total)]
        for f in as_completed(futures):
            dur, ok, err, ans = f.result()
            latencies.append(dur)
            if not ok:
                errors.append(err)
            else:
                answers.append(ans)
    wall = time.perf_counter() - t_start

    ok_n = len(latencies) - len(errors)
    # 错误类型归并，便于看是限流还是代码问题
    err_kinds = {}
    for e in errors:
        kind = e.split(":")[0]
        err_kinds[kind] = err_kinds.get(kind, 0) + 1

    return {
        "concurrency": concurrency,
        "requests": total,
        "success": ok_n,
        "success_rate": round(ok_n / total * 100, 1),
        "wall_seconds": round(wall, 2),
        "throughput_qps": round(total / wall, 2),
        "p50": pct(latencies, 50),
        "p95": pct(latencies, 95),
        "max": round(max(latencies), 3) if latencies else None,
        "min": round(min(latencies), 3) if latencies else None,
        "error_kinds": err_kinds,
        "sample_answers": answers[:2],
    }


def main():
    print("[1/4] 搭建沙箱环境并建索引…", flush=True)
    im, tmp = build_env()
    ix = im.index
    print(f"      索引就绪：向量 {len(ix.vector_store.data.embedding_dict)} 条", flush=True)

    result = {"question": QUESTION, "levels": LEVELS, "layers": {}}

    print("[2/4] A 层：纯检索并发（不含 LLM）", flush=True)
    retr = []
    for c, n in LEVELS:
        r = run_level(im, c, n, with_llm=False)
        retr.append(r)
        print(f"      并发 {c}: 成功 {r['success_rate']}% | P50 {r['p50']}s | "
              f"P95 {r['p95']}s | QPS {r['throughput_qps']}", flush=True)
    result["layers"]["retrieval"] = retr

    print("[3/4] B 层：端到端并发（含 DeepSeek 生成）", flush=True)
    setup_llm()
    e2e = []
    for c, n in LEVELS:
        r = run_level(im, c, n, with_llm=True)
        e2e.append(r)
        print(f"      并发 {c}: 成功 {r['success_rate']}% | P50 {r['p50']}s | "
              f"P95 {r['p95']}s | QPS {r['throughput_qps']} | 错误 {r['error_kinds']}", flush=True)
    result["layers"]["end2end"] = e2e

    print("[4/4] 写结果…", flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    shutil.rmtree(tmp, ignore_errors=True)
    print("完成 ->", OUT, flush=True)


if __name__ == "__main__":
    main()
