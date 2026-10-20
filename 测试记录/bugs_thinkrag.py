# -*- coding: utf-8 -*-
"""ThinkRAG 缺陷数据源。

维护方式：在 BUGS 末尾追加一条 dict 即可，然后运行 build_reports.py 重新生成 Excel。
优先级：P1（核心功能不可用/阻断） / P2（功能受损但有替代路径） / P3（体验/可用性）
状态：待修复 / 已定位 / 待复现 / 已验证修复
"""

BUGS = [
    dict(id="BUG-TRAG-001",
         title="索引结构残留时查询 100% 失败，且前端不显示任何错误提示",
         status="待修复", pri="P1", module="智能问答",
         desc=(
             "复现步骤：\n"
             "1. 上传文档并生成索引；\n"
             "2. Manage 页删除全部文档；\n"
             "3. 重新上传文档生成索引；\n"
             "4. Query 页提问任意问题。\n\n"
             "实际结果：\n"
             "页面统一返回 “Couldn't come up with an answer.”，无任何错误提示；\n"
             "服务端日志：KeyError: '19aaf448-d216-4c86-938a-f597e3dd899b'。\n\n"
             "排查证据：\n"
             "storage/index_store.json 中同时存在两个索引——\n"
             "  56547e82… nodes_dict=0（删除文档后残留的空索引壳）\n"
             "  046efa50… nodes_dict=10（真正包含切块的索引）\n"
             "IndexManager.check_index_exists() 取 load_indices_from_storage()[0]，\n"
             "命中的正是空索引；而向量库中仍有 10 条 embedding，\n"
             "检索返回节点 ID 后在 llama_index 内部\n"
             "vector_store/retrievers/retriever.py:147\n"
             "self._index.index_struct.nodes_dict[idx] 抛 KeyError。\n\n"
             "预期结果：\n"
             "删除文档时应同步清理索引结构；加载时应选择含节点的有效索引；\n"
             "查询失败必须向用户抛出可识别的错误信息，不能静默降级为“模型答不出来”。\n\n"
             "影响：核心问答功能完全不可用，且用户无法自行判断故障原因。\n"
             "临时处置：备份并删除 nodes_dict 为空的索引条目后重启服务，问答恢复。"
         ),
         attach="测试记录\\证据\\索引残留.txt"),

    dict(id="BUG-TRAG-002",
         title="知识库为空时提问，服务端抛未捕获异常（bm25s 空语料）",
         status="待修复", pri="P1", module="智能问答",
         desc=(
             "复现步骤：\n"
             "1. Manage 页删除全部文档；\n"
             "2. 不刷新页面，直接在 Query 页提问。\n\n"
             "实际结果：\n"
             "页面显示 “Couldn't come up with an answer.”；\n"
             "服务端堆栈：Document_QA.py:119 create_query_engine →\n"
             "retriever.py:143 SimpleFusionRetriever/SimpleHybridRetriever 构建 →\n"
             "retriever.py:52 SimpleBM25Retriever.from_defaults →\n"
             "bm25s/__init__.py:501 vocab_dict[''] = max(vocab_dict.values())+1 →\n"
             "ValueError: max() iterable argument is empty。\n\n"
             "已独立复现：构造空索引 VectorStoreIndex([])（docstore.docs=0）后\n"
             "调用 SimpleBM25Retriever.from_defaults，稳定抛出同一异常（见附件）。\n\n"
             "预期结果：\n"
             "建索引前判断语料是否为空，给出“知识库为空，请先上传文档”的提示，\n"
             "不应进入 BM25 构建流程。\n\n"
             "备注：与本地 RAG 项目发现的“空语料除零/取最大值崩溃”属同类问题——\n"
             "空集合边界未做前置判断。"
         ),
         attach="测试记录\\证据\\空库崩溃.txt"),

    dict(id="BUG-TRAG-003",
         title="问答耗时统计不含 LLM 生成，显示值严重失真",
         status="待修复", pri="P2", module="智能问答",
         desc=(
             "复现步骤：\n"
             "1. Query 页提问；\n"
             "2. 记录页面显示的 Took N second(s)；\n"
             "3. 与端到端实际耗时对比。\n\n"
             "实际结果：\n"
             "三次实测显示 0.03 / 0.02 / 0.02 秒；\n"
             "而 DeepSeek 生成答案实际需要 1~3 秒。\n\n"
             "根因：\n"
             "Document_QA.py:64-67 的计时器只包住 perform_query(prompt)，\n"
             "即 query_engine.query() 返回 StreamingResponse 的时刻；\n"
             "真正的 token 生成发生在之后的 st.write_stream(response.response_gen)，\n"
             "不在计时范围内。\n\n"
             "预期结果：\n"
             "耗时统计应覆盖端到端（含流式生成），或明确标注为“检索耗时”。\n\n"
             "影响：用户与测试人员会误判系统性能，压测数据不可用。"
         ),
         attach="用例 TC-PERF-001"),

    dict(id="BUG-TRAG-004",
         title="每次页面 rerun 都重新加载嵌入模型并重建检索器",
         status="待修复", pri="P2", module="性能",
         desc=(
             "复现步骤：\n"
             "1. 启动服务并打开 Query 页；\n"
             "2. 触发任意 rerun（切换页面、点击展开引用等）；\n"
             "3. 观察服务端控制台日志。\n\n"
             "实际结果：\n"
             "每次 rerun 都输出一轮完整初始化日志：\n"
             "  Loading SentenceTransformer model from ./localmodels/BAAI/bge-small-zh-v1.5\n"
             "  created embed model: ...\n"
             "  Split strings / Stem Tokens / Building index from IDs objects\n\n"
             "根因：\n"
             "frontend/state.py:218 init_state() 无条件调用\n"
             "create_embedding_model()（第 226 行），函数内部\n"
             "server/models/embedding.py 直接 new HuggingFaceEmbedding，无缓存判断；\n"
             "Document_QA.main() 每次 rerun 还重新执行\n"
             "check_index_exists() → load_index() → create_query_engine()，\n"
             "导致 BM25 索引被反复重建。\n\n"
             "实测成本：嵌入模型单次实例化 0.17 秒（首次 1.67 秒），\n"
             "叠加索引加载与 BM25 重建，每次交互累计开销明显。\n\n"
             "预期结果：\n"
             "模型与检索器初始化一次后放入 session_state 复用，仅在配置变更时重建。"
         ),
         attach="用例 TC-PERF-002"),

    dict(id="BUG-TRAG-005",
         title="知识库管理页无法查看切块内容，切块质量不可核对",
         status="待修复", pri="P2", module="知识库管理",
         desc=(
             "复现步骤：\n"
             "1. 上传文档并生成索引；\n"
             "2. 打开 Manage 页；\n"
             "3. 尝试查看该文档的切块列表与每块正文。\n\n"
             "实际结果：\n"
             "页面仅提供文档列表（文件名/创建日期/删除），无任何切块查看入口；\n"
             "而 README 中描述支持知识库管理与分页查看。\n\n"
             "预期结果：\n"
             "可查看每个文档的切块数量与每块正文，用于核对是否切碎、串段、丢内容。\n\n"
             "影响：切块质量只能靠提问间接推断（例如 2048 参数下 1165 字被切成 1 块，\n"
             "用户无法在界面确认），显著增加排查成本。"
         ),
         attach="用例 TC-MGMT-005"),

    dict(id="BUG-TRAG-006",
         title="删除按钮仅在勾选行后渲染，无任何操作引导",
         status="待修复", pri="P3", module="知识库管理",
         desc=(
             "复现步骤：\n"
             "1. 打开 Manage 页（存在文档）；\n"
             "2. 不勾选任何行，观察页面。\n\n"
             "实际结果：\n"
             "页面上不存在删除按钮，KB_Manage.py:105-107 中\n"
             "仅当 len(selected_docs) > 0 才渲染按钮，且无文字提示先勾选。\n"
             "用户反馈“好像删不掉”“找不到删除”。\n\n"
             "预期结果：\n"
             "按钮常驻但未勾选时置灰，或显式提示“请先勾选要删除的文档”。"
         ),
         attach="用例 TC-MGMT-002"),

    dict(id="BUG-TRAG-007",
         title="文档元数据保存本机绝对路径，存在隐私泄露风险",
         status="待修复", pri="P3", module="数据存储",
         desc=(
             "复现步骤：\n"
             "1. 上传文档生成索引；\n"
             "2. 查看 storage/docstore.json 中 ref_doc_info 的 metadata。\n\n"
             "实际结果：\n"
             "metadata.file_path 记录完整本机绝对路径，例如\n"
             "C:\\Users\\<用户名>\\Desktop\\测试项目\\ThinkRAG\\data\\产品手册.txt。\n\n"
             "预期结果：\n"
             "仅保存文件名或相对路径；绝对路径不应落盘，也不应随索引导出分发。\n\n"
             "影响：知识库文件一旦分享或迁移，会暴露使用者本机目录结构与用户名。"
         ),
         attach="测试记录\\证据\\docstore检查.txt"),

    dict(id="BUG-TRAG-008",
         title="Office 文档（pptx / xlsx）上传直接抛 ImportError，README 却明示支持 PPTX",
         status="待修复", pri="P1", module="知识库上传",
         desc=(
             "复现步骤：\n"
             "1. File 页上传 答辩演示.pptx（6.9MB）；\n"
             "2. 点击 Save。\n\n"
             "实际结果：\n"
             "ImportError: Please install extra dependencies that are required for the PptxReader:\n"
             "`pip install torch transformers python-pptx Pillow`\n\n"
             "上传 xlsx 时表现相同：\n"
             "ImportError: Please install openpyxl to read Excel files.\n\n"
             "根因：\n"
             "1. README_zh.md 第 181 行明确写着「支持上传 PDF、DOCX、PPTX 等各类文件」，\n"
             "   但 requirements.txt / requirements-dev.txt 中并未声明\n"
             "   python-pptx、openpyxl 等格式解析依赖；\n"
             "2. File 页 Save 分支（KB_File.py:54-63）没有 try/except，\n"
             "   异常被 Streamlit 原样渲染成红色堆栈；\n"
             "3. 上传控件未按扩展名做前置校验，用户无从预判哪些格式可用。\n\n"
             "预期结果：\n"
             "按 README 承诺支持 PPTX；或在依赖缺失时给出「当前环境不支持该格式」的业务提示，\n"
             "而不是暴露 Python 异常堆栈。\n\n"
             "影响：README 承诺的核心能力不可用，用户按文档操作必然失败。"
         ),
         attach="测试记录\\结果\\result_format.json"),

    dict(id="BUG-TRAG-009",
         title="0 字节空文件未拦截，向索引写入空节点",
         status="待修复", pri="P2", module="知识库上传",
         desc=(
             "复现步骤：\n"
             "1. 上传 0 字节的 空文件.txt；\n"
             "2. 点击 Save；\n"
             "3. 检查索引内容。\n\n"
             "实际结果：\n"
             "未做任何校验，索引中新增 1 个节点，其 text 为空字符串；\n"
             "docstore 写入 2 条记录（1 空节点 + 1 文档记录）。\n\n"
             "预期结果：\n"
             "上传阶段校验文件大小与解析后正文，为空则拒绝并提示，不写入索引。\n\n"
             "影响：空节点会占用 top_k 召回名额，可能挤掉有效片段，\n"
             "并使后续问答拿到无信息上下文。"
         ),
         attach="测试记录\\结果\\result_format.json"),

    dict(id="BUG-TRAG-010",
         title="重复上传同一文件不去重，切块与向量成倍增长",
         status="待修复", pri="P2", module="知识库上传",
         desc=(
             "复现步骤：\n"
             "1. 上传 产品手册.txt 并 Save；\n"
             "2. 不做任何删除，再次上传同一文件并 Save；\n"
             "3. 统计索引规模。\n\n"
             "实际结果：\n"
             "第一次：docstore 11、nodes_dict 10、向量 10；\n"
             "第二次：docstore 22、nodes_dict 20、向量 20。\n"
             "同一份文档存在两套完整切块，且界面无任何提示。\n\n"
             "预期结果：\n"
             "按文件内容或文件名去重；若设计为追加，应在保存前明确提示「将重复入库」。\n\n"
             "影响：用户重复点击 Save 或重新上传即造成索引翻倍，\n"
             "检索时同一内容占据多个 top_k 名额，浪费上下文并降低答案多样性。"
         ),
         attach="测试记录\\结果\\result_data.json"),

    dict(id="BUG-TRAG-011",
         title="同名文件重新上传不会覆盖，旧内容继续生效",
         status="待修复", pri="P1", module="知识库上传",
         desc=(
             "复现步骤：\n"
             "1. 上传 产品手册.txt（标准版 1899 元）并 Save；\n"
             "2. 把本地同名文件内容改为「标准版 9999 元」，再次上传并 Save；\n"
             "3. 提问「标准版多少钱？」。\n\n"
             "实际结果：\n"
             "索引规模 docstore 11→22、向量 10→20，新旧内容并存；\n"
             "回答仍为「标准版 1899 元」——旧版本胜出，新内容未生效。\n\n"
             "预期结果：\n"
             "同名文件应覆盖旧版本（先删旧 ref_doc 再入库），\n"
             "或明确提示用户当前为追加模式、需手动删除旧版。\n\n"
             "影响：用户无法通过重新上传来更新知识库，\n"
             "且系统会给出一份已经过期的答案，且没有任何迹象表明数据是旧的。"
         ),
         attach="测试记录\\结果\\result_data.json"),

    dict(id="BUG-TRAG-012",
         title="chunk_overlap ≥ chunk_size 无参数校验，切块内容膨胀 4.78 倍",
         status="待修复", pri="P2", module="知识库上传",
         desc=(
             "复现步骤：\n"
             "1. Text Splitter Settings 设置 chunk_size=100、chunk_overlap=100；\n"
             "2. 上传 1165 字的 产品手册.txt；\n"
             "3. 统计切块数与所有切块正文总字符数。\n\n"
             "实际结果：\n"
             "100/100：53 块，总字符 5568，为原文的 4.78 倍；\n"
             "512/600（overlap 大于 chunk_size）：10 块，总字符 5574，同样 4.78 倍；\n"
             "两次均无任何校验或提示。\n\n"
             "预期结果：\n"
             "提交前校验 overlap < chunk_size，不满足时阻止保存并提示；\n"
             "或将 overlap 自动收敛到安全值并告知用户。\n\n"
             "影响：向量库体积成倍膨胀、检索结果高度重复、\n"
             "top_k 名额被同一段落的多个副本占满，直接拉低答案质量。"
         ),
         attach="测试记录\\结果\\result_chunk.json"),

    dict(id="BUG-TRAG-013",
         title="无格式白名单：.exe 与无扩展名文件被当作纯文本读入索引",
         status="待修复", pri="P3", module="知识库上传",
         desc=(
             "复现步骤：\n"
             "1. 上传 伪装文件.exe（文本内容加 MZ 头）；\n"
             "2. 上传无扩展名的 无扩展名文件；\n"
             "3. 分别点击 Save。\n\n"
             "实际结果：\n"
             "两者均按纯文本成功读入，分别生成 3 个节点，无任何格式校验或提示。\n\n"
             "预期结果：\n"
             "维护可解析格式白名单，未知格式拒绝并提示；\n"
             "对二进制内容做可读性检测，避免乱码进入索引。\n\n"
             "影响：真实二进制文件（如 exe、压缩包）被读入后会产生大量乱码切块，\n"
             "污染知识库并干扰检索，且用户无法从界面察觉。"
         ),
         attach="测试记录\\结果\\result_format.json"),

    dict(id="BUG-TRAG-014",
         title="HTML 文件未剥离标签，原始源码直接入库",
         status="待修复", pri="P3", module="知识库上传",
         desc=(
             "复现步骤：\n"
             "1. 上传 产品页.html；\n"
             "2. 点击 Save；\n"
             "3. 查看入库正文。\n\n"
             "实际结果：\n"
             "入库内容为 HTML 源码原文：\n"
             "'<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>…'，\n"
             "标签未被剥离。\n\n"
             "预期结果：\n"
             "解析时抽取 body 纯文本，剔除 DOCTYPE、head、script、style 等标签。\n\n"
             "影响：切块中混入大量标签噪音，稀释语义密度，\n"
             "检索命中率与答案质量下降，引用展示也会出现源码。"
         ),
         attach="测试记录\\结果\\result_format.json"),

    dict(id="BUG-TRAG-015",
         title="空字符串查询在引擎层抛 TypeError（仅靠 UI 层拦截）",
         status="待修复", pri="P3", module="智能问答",
         desc=(
             "复现步骤：\n"
             "1. 不经页面，直接调用 query_engine.query(\"\")；\n"
             "2. 观察异常。\n\n"
             "实际结果：\n"
             "TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'\n\n"
             "补充：纯空格（\"   \"）未被拦截，会正常发起检索并让模型回复\n"
             "「您的问题似乎是空的」。\n\n"
             "当前影响有限：\n"
             "Document_QA.perform_query 中有 (not prompt) or prompt.strip()==\"\" 的守卫，\n"
             "因此从页面提交空输入暂不可达；但引擎层本身没有防御，\n"
             "任何绕过 UI 的调用（脚本、二次开发、接口化）都会直接崩溃。\n\n"
             "预期结果：\n"
             "在 create_query_engine 或检索入口统一做空值/空白校验并返回业务错误。"
         ),
         attach="测试记录\\结果\\result_robust.json"),

    dict(id="BUG-TRAG-016",
         title="大文件无大小限制且无进度反馈，2.5MB 文档切块耗时 147 秒",
         status="待修复", pri="P3", module="知识库上传",
         desc=(
             "复现步骤：\n"
             "1. 上传 2,521,800 字节的 大文件.txt；\n"
             "2. 设置 chunk 512/100 并 Save；\n"
             "3. 观察耗时与页面反馈。\n\n"
             "实际结果：\n"
             "切块阶段耗时 147.47 秒（进程总耗时 171 秒），生成 2700 个节点；\n"
             "期间仅有静态 spinner 文案「may take a minute or two」，\n"
             "无进度百分比、无已处理块数、无取消入口。\n\n"
             "预期结果：\n"
             "设置文件大小与切块数上限，超限时提示；\n"
             "长任务提供进度回调与取消能力。\n\n"
             "影响：用户无法判断任务是卡死还是在跑，\n"
             "容易重复点击 Save 造成重复入库（与 BUG-TRAG-010 叠加）。"
         ),
         attach="测试记录\\结果\\result_format.json"),
]

# 缺陷闭环记录（针对已完成完整闭环的缺陷）
CLOSURE = [
    dict(step="1. 发现", date="2026-10-20",
         content="执行 TC-QA-001/002/003 三条问答用例，页面统一返回“Couldn't come up with an answer.”，"
                 "与知识库实际内容不符，登记为异常现象。"),
    dict(step="2. 定位", date="2026-10-20",
         content="查看服务端控制台日志，拿到 KeyError: '19aaf448-...'；"
                 "进一步打印全部索引，发现 index_store.json 中存在 1 个 nodes_dict=0 的空索引与 1 个 nodes_dict=10 的有效索引；"
                 "确认 check_index_exists() 取 indices[0] 命中空索引，"
                 "堆栈定位到 llama_index vector_store/retrievers/retriever.py:147。"),
    dict(step="3. 提交", date="2026-10-20",
         content="登记为 BUG-TRAG-001，优先级 P1，模块「智能问答」，"
                 "同时补充“异常被吞导致前端无提示”的可观测性问题。"),
    dict(step="4. 处置", date="2026-10-20",
         content="因属上游开源项目代码缺陷，采用数据层临时处置：备份 index_store.json 为 .bak，"
                 "删除 nodes_dict 为空的索引条目，重启服务使有效索引被加载。"),
    dict(step="5. 验证", date="2026-10-20",
         content="重启后回归三问：标准版价格 1899 元、整机保修 12 个月、5G 问题正确拒答，"
                 "均返回 Found 5 document(s)，与修复前对比确认问题消失。"),
    dict(step="6. 关闭", date="2026-10-20",
         content="功能已恢复，但代码层根因未修复（删除文档时未清理索引结构、加载时未校验索引有效性），"
                 "缺陷状态保留为「待修复」，回归用例 TC-QA-006 保留在用例集中作为回归项。"),
]
