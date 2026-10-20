# -*- coding: utf-8 -*-
"""pytest 公共夹具。

设计要点（面试可直接讲）：

1. **用例隔离方式换了**
   原脚本用「每个场景起一个独立 Python 进程」来做隔离，代价是每个场景都要
   重新加载一次嵌入模型（实测首次 1.67s，且 torch 导入更慢）。
   pytest 版改成「单进程 + 每个用例独立的 StorageContext 与 data 目录」，
   隔离效果一样，但整个套件只需要加载一次模型。

2. **不碰真实数据**
   ThinkRAG 的 STORAGE_CONTEXT 是模块级单例，import 时就把 storage/ 读进内存了，
   所以测试不能靠"清空 storage 目录"来重置。这里用 monkeypatch 把
   server.index 模块里的 STORAGE_CONTEXT 和 get_save_dir 替换成 tmp_path 下的
   全新实例，跑测试不会动到本地知识库。

3. **CI 与本地两套嵌入**
   本地用真实的 bge-small-zh-v1.5；CI 里设置 USE_MOCK_EMBED=1 换成 MockEmbedding，
   避免在 runner 上下载 367MB 模型。Mock 只影响"检索质量"类断言，
   解析、切块、计数这些逻辑完全一致。
"""
import os
import sys
import json
import shutil
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parent.parent
FIXTURES = PROJ / "测试记录" / "测试数据"
ORIG_TEXT_LEN = 1165  # 产品手册.txt 正文字数，用于切块膨胀率计算

sys.path.insert(0, str(PROJ))
os.chdir(PROJ)


# --------------------------------------------------------------------------- 嵌入模型
@pytest.fixture(scope="session", autouse=True)
def embedding():
    """整个会话只加载一次嵌入模型。"""
    from llama_index.core import Settings

    if os.getenv("USE_MOCK_EMBED") == "1":
        from llama_index.core.embeddings import MockEmbedding

        Settings.embed_model = MockEmbedding(embed_dim=8)
        yield Settings.embed_model
        return

    from server.models.embedding import create_embedding_model

    model = create_embedding_model("bge-small-zh-v1.5")
    if model is None:
        pytest.exit("嵌入模型加载失败，请检查 localmodels/BAAI/bge-small-zh-v1.5", returncode=1)
    yield model


# --------------------------------------------------------------------------- 沙箱
class Sandbox:
    """一个用例专属的知识库沙箱：独立 storage 目录 + 独立 data 目录。"""

    def __init__(self, data_dir: Path, storage_dir: Path):
        self.data_dir = data_dir
        self.storage_dir = storage_dir

    def put(self, *names: str) -> None:
        """把测试数据从 测试记录/测试数据 复制到沙箱的 data 目录。"""
        for n in names:
            src = FIXTURES / n
            if not src.exists():
                raise FileNotFoundError(f"缺少测试数据: {src}")
            shutil.copy(src, self.data_dir / n)

    def manager(self):
        """等价于 File 页点击 Save 时的入口对象。"""
        from server.index import IndexManager

        im = IndexManager("kb")
        im.check_index_exists()
        return im

    def load(self, names, chunk_size=512, overlap=100, manager=None):
        """走真实入口 IndexManager.load_files 建索引。"""
        self.put(*names)
        im = manager or self.manager()
        nodes = im.load_files([{"name": n} for n in names], chunk_size, overlap) or []
        return im, nodes

    @staticmethod
    def stats(im) -> dict:
        ix = im.index
        if ix is None:
            return {"docstore": 0, "nodes_dict": 0, "vectors": 0}
        out = {}
        try:
            out["docstore"] = len(ix.docstore.docs)
        except Exception:
            out["docstore"] = None
        try:
            out["nodes_dict"] = len(ix.index_struct.nodes_dict)
        except Exception:
            out["nodes_dict"] = None
        try:
            vs = ix.vector_store
            data = getattr(vs, "data", None)
            if data is not None and hasattr(data, "embedding_dict"):
                out["vectors"] = len(data.embedding_dict)
            else:
                out["vectors"] = None
        except Exception:
            out["vectors"] = None
        return out

    @staticmethod
    def text(nodes) -> str:
        return "\n".join((getattr(n, "text", "") or "") for n in (nodes or []))


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """每个用例一套全新环境，用例之间互不可见。"""
    import server.index as index_mod
    from llama_index.core import Settings, StorageContext
    from llama_index.core.storage.docstore import SimpleDocumentStore
    from llama_index.core.storage.index_store import SimpleIndexStore
    from llama_index.core.vector_stores import SimpleVectorStore

    storage_dir = tmp_path / "storage"
    data_dir = tmp_path / "data"
    storage_dir.mkdir()
    data_dir.mkdir()

    # 显式传三个空 store：直接 from_defaults(persist_dir=空目录) 会去读 docstore.json 并抛 FileNotFoundError
    ctx = StorageContext.from_defaults(
        docstore=SimpleDocumentStore(),
        index_store=SimpleIndexStore(),
        vector_store=SimpleVectorStore(),
    )
    ctx.persist_dir = str(storage_dir)
    monkeypatch.setattr(index_mod, "STORAGE_CONTEXT", ctx)
    # get_save_dir 在 server.index 里是 from ... import 的值绑定，必须 patch 这一处
    monkeypatch.setattr(index_mod, "get_save_dir", lambda: str(data_dir))

    # 全局切块参数会跨用例残留，每个用例前复位
    Settings.chunk_size = 1024
    Settings.chunk_overlap = 200

    yield Sandbox(data_dir, storage_dir)

    Settings.chunk_size = 1024
    Settings.chunk_overlap = 200


# --------------------------------------------------------------------------- 附件工具
@pytest.fixture
def attach():
    """把一段文本挂到 allure 报告里，便于回看当时真实返回。"""
    import allure

    def _attach(body, name="证据"):
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False, indent=2)
        allure.attach(body, name=name, attachment_type=allure.attachment_type.TEXT)

    return _attach
