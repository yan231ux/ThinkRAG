# -*- coding: utf-8 -*-
"""批量执行场景并收集结果到 测试记录/结果/*.json。

用法：python run_matrix.py [组名]
组名：format / chunk / data / qa / all
"""
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(BASE)
OUT = os.path.join(BASE, "结果")
os.makedirs(OUT, exist_ok=True)

PY = os.path.join(PROJ, ".venv", "Scripts", "python.exe")

ENV = dict(os.environ)
ENV["PYTHONPATH"] = os.path.join(PROJ, ".venv", "Lib", "site-packages")
ENV["HF_ENDPOINT"] = "https://hf-mirror.com"
ENV["PYTHONUTF8"] = "1"

GROUPS = {
    "format": [
        "fmt:产品手册.md", "fmt:产品价格表.csv", "fmt:产品配置表.xlsx",
        "fmt:产品说明书.docx", "fmt:测试文档.pdf", "fmt:结构化数据.json",
        "fmt:产品页.html", "fmt:伪装文件.exe", "fmt:空文件.txt",
        "fmt:无扩展名文件", "fmt:产品 手册(最终版)#1.txt", "fmt:大文件.txt",
    ],
    "chunk": [
        "chunk:200:50", "chunk:1:0", "chunk:100:100", "chunk:512:600",
        "chunk:4096:512", "chunk:50:0",
    ],
    "data": ["dup", "overwrite", "multidoc", "delete"],
    "qa": ["qa", "topk", "temp"],
}


def run(scenario):
    t0 = time.time()
    p = subprocess.run([PY, os.path.join(BASE, "matrix_worker.py"), scenario],
                       cwd=PROJ, env=ENV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    out = p.stdout or ""
    res = None
    for line in out.splitlines():
        if line.startswith("RESULT:"):
            res = json.loads(line[len("RESULT:"):])
    if res is None:
        res = {"scenario": scenario, "ok": False,
               "error": "no RESULT line",
               "stderr": (p.stderr or "")[-800:]}
    res["wall_seconds"] = round(time.time() - t0, 1)
    return res


def main():
    group = sys.argv[1] if len(sys.argv) > 1 else "all"
    scenarios = []
    if group == "all":
        for v in GROUPS.values():
            scenarios.extend(v)
    else:
        scenarios = GROUPS[group]

    results = []
    for s in scenarios:
        print(f"[RUN] {s}", flush=True)
        r = run(s)
        results.append(r)
        brief = {k: v for k, v in r.items()
                 if k in ("ok", "nodes", "vectors", "docstore", "seconds",
                          "wall_seconds", "error", "duplicated", "file")}
        print(f"      -> {json.dumps(brief, ensure_ascii=False)}", flush=True)

    path = os.path.join(OUT, f"result_{group}.json")
    json.dump(results, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n[done] {len(results)} 个场景，结果写入 {path}")


if __name__ == "__main__":
    main()
