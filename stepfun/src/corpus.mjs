/**
 * 语料与评测集。
 *
 * DEMO_DOCS  : 演示用知识库（中文 24 篇 + 英文 12 篇），覆盖赛题相关主题。
 * EVAL_QUERIES: 检索质量评测集，带人工标注的相关性等级（3=完全相关，2=部分相关，1=弱相关）。
 *               用于量化前（fp32 / fp16 / q8）Recall@K 与 nDCG@K 的对比。
 */

export const DEMO_DOCS = [
  // ---------------- 中文语料 ----------------
  { id: 'zh-01', title: '阶跃星辰公司介绍', lang: 'zh',
    text: '阶跃星辰（StepFun）成立于 2023 年，总部位于上海，是一家专注于人工智能大模型研发的公司。公司主打多模态大模型 Step 系列，其中 Step-1 是千亿参数级别的基座语言模型，Step-2 面向数学与代码能力，Step-1V 和 Step-Video 则分别面向视觉理解与视频生成任务。阶跃星辰的产品线覆盖预训练模型、推理服务以及面向企业的行业解决方案。' },
  { id: 'zh-02', title: '阶跃星辰大模型 API 定价', lang: 'zh',
    text: '阶跃星辰开放平台提供 step-1、step-1v、step-2 等模型的在线推理 API。定价按输入 token 与输出 token 分别计费，step-1 的输入价格约为每百万 token 若干元人民币，长上下文会按阶梯价格累加。企业客户可以申请并发配额与私有化部署授权。' },
  { id: 'zh-03', title: 'OceanBase 分布式数据库概述', lang: 'zh',
    text: 'OceanBase 是蚂蚁集团开源的分布式关系型数据库，兼容 MySQL 协议，支持多租户、水平分区、 LSM-Tree 存储引擎以及强一致性复制。它同时提供社区版与商业版，在金融、运营商等场景有大规模落地。OceanBase 4.x 引入了向量化检索与多模态能力。' },
  { id: 'zh-04', title: 'seekdb 是什么', lang: 'zh',
    text: 'seekdb 是 OceanBase 团队推出的轻量级向量数据库，与 OceanBase 共享同一套内核代码，支持嵌入式与本地 server 两种部署形态。它提供向量索引、全文索引与混合检索能力，并提供官方 JavaScript SDK（seekdb-js），可以直接用 SQL 或 SDK 访问。' },
  { id: 'zh-05', title: 'seekdb 混合检索原理', lang: 'zh',
    text: 'seekdb 的混合检索由数据库内部的 DBMS_HYBRID_SEARCH 包完成。它接收一份 search_parm 参数，其中 query 描述全文检索条件、knn 描述向量近邻条件、rank 描述融合算法，然后生成一条可执行的 SQL。默认融合算法是 RRF，即 Reciprocal Rank Fusion，把两路结果的排名倒数加权求和。' },
  { id: 'zh-06', title: 'RRF 融合算法', lang: 'zh',
    text: 'RRF（Reciprocal Rank Fusion）把每个文档在两路召回中的排名转换成分数：score = Σ 1 / (k + rank_i)，其中 k 是 rank_constant，用来平滑头部排名的差距。rank_window_size 则限定参与融合的排名窗口。RRF 不需要归一化分数，因此非常适合把 BM25 分数和向量距离两种量纲完全不同的信号融合在一起。' },
  { id: 'zh-07', title: 'BM25 全文检索算法', lang: 'zh',
    text: 'BM25 是最经典的词袋全文检索排序函数，核心是词频饱和、逆文档频率 IDF 以及文档长度归一化三项因子的乘积。BM25 在长查询和高频词场景下比 TF-IDF 更稳健，Elasticsearch、Lucene、OceanBase 的全文索引都默认使用 BM25 作为排序函数。' },
  { id: 'zh-08', title: 'HNSW 向量索引', lang: 'zh',
    text: 'HNSW 是一种基于分层可导航小世界图（Hierarchical Navigable Small World）的近似最近邻索引。它把向量组织成多层图，查询时从顶层稀疏图贪心下降到底层稠密图，兼具高召回率和低查询延迟。常用超参包括 M（每个节点的出边数）、ef_construction（建图时的候选队列大小）与 ef_search（查询时的候选队列大小）。' },
  { id: 'zh-09', title: '向量距离度量与余弦相似度', lang: 'zh',
    text: '向量检索常用距离度量包括欧氏距离 L2、内积 IP 与余弦距离 cosine。归一化之后，余弦距离与内积排序等价。bge 与 MiniLM 系列模型默认输出 L2 归一化向量，因此用 cosine 或 inner_product 都可以。维度越高、分布越均匀，索引效果越好。' },
  { id: 'zh-10', title: 'Transformers.js 简介', lang: 'zh',
    text: 'Transformers.js 是 Hugging Face 官方的 JavaScript 推理库，把 transformers 的模型推理能力带到浏览器和 Node.js。它基于 ONNX Runtime Web，支持 WebGPU、WebGL 与 WASM 三种后端，并提供 pipeline、AutoTokenizer、AutoModel 等高层 API，同一个模型可以通过 Xenova 组织下的 ONNX 权重直接加载。' },
  { id: 'zh-11', title: '端侧向量化的意义', lang: 'zh',
    text: '在浏览器本地完成向量化有三个核心价值：第一，原始语料不需要上传到服务器，隐私边界清晰；第二，没有推理 API 的网络往返与计费成本；第三，文档内容与向量可以在本地同批次生成，便于做增量索引与离线知识库。端侧推理的主要约束是设备算力与内存，因此量化非常关键。' },
  { id: 'zh-12', title: '模型量化 INT8 与 FP16', lang: 'zh',
    text: 'INT8 量化把权重从 32 位浮点压缩到 8 位整数，通常可以带来接近 4 倍的体积压缩与更快的矩阵乘吞吐；FP16 把权重降到 16 位，压缩比接近 2 倍，对 GPU 友好但对 WASM 后端收益有限。量化会引入精度损失，嵌入模型通常表现为召回率小幅下降、余弦相似度略微变差。' },
  { id: 'zh-13', title: 'ONNX Runtime Web 与 WebGPU', lang: 'zh',
    text: 'ONNX Runtime Web 是 ONNX Runtime 的浏览器版本，通过 WebAssembly 与 WebGPU 两套执行提供器在浏览器中运行模型。WebGPU 后端需要显式申请 GPUAdapter，失败时会抛出异常；使用 transformers.js 时应当显式指定 device 参数为 webgpu 或 wasm，并做好异常捕获以完成自动降级。' },
  { id: 'zh-14', title: 'WebGPU 不可用时的降级策略', lang: 'zh',
    text: '常见的降级策略是：先检测 navigator.gpu 是否存在，再尝试 requestAdapter，拿到适配器才使用 webgpu 后端；任何一步失败就回退到 wasm 后端。界面上必须明确展示当前实际使用的后端与降级原因，否则用户会误判性能差异的来源。WASM 后端通常启用 SIMD 与多线程以接近原生性能。' },
  { id: 'zh-15', title: 'bge-small-zh-v1.5 模型卡片', lang: 'zh',
    text: 'bge-small-zh-v1.5 是北京智源人工智能研究院 BGE 系列的中文小模型，隐藏层维度 512，训练数据规模远大于同尺寸的英文模型，在中文检索基准 C-MTEB 上表现优异。官方推荐使用 CLS pooling 并做 L2 归一化，查询侧建议加指令前缀以提升效果。' },
  { id: 'zh-16', title: 'all-MiniLM-L6-v2 模型卡片', lang: 'zh',
    text: 'all-MiniLM-L6-v2 是 sentence-transformers 发布的英文小型嵌入模型，6 层 Transformer，隐藏维度 384，参数量约 2200 万。它在 MTEB 英文榜单上表现稳定，是端侧最常用的英文嵌入模型之一，配合 mean pooling 与 L2 归一化使用。' },
  { id: 'zh-17', title: '嵌入批处理与吞吐优化', lang: 'zh',
    text: '端侧推理的吞吐主要由批大小决定。批量把多个句子拼成一个 batch 送入模型，可以把一次矩阵乘变成更大的矩阵乘，显著提升每秒处理文档数。代价是内存峰值与首字节延迟上升，因此在线查询场景适合小批次，离线导入场景适合大批次。transformers.js 的 pipeline 调用接受字符串数组即可自动批处理。' },
  { id: 'zh-18', title: '索引刷新策略', lang: 'zh',
    text: '向量索引是增量构建的近似结构，新写入的数据要等索引刷新后才能被完整召回。seekdb 提供 dbms_index_manager.refresh 接口触发刷新。工程上常见的策略是：批量导入结束后统一刷新一次，兼顾导入吞吐与检索可见性；如果业务要求写后立即可查，则每批写完都刷新，代价是刷新耗时线性增长。' },
  { id: 'zh-19', title: 'RAG 检索增强生成', lang: 'zh',
    text: 'RAG 把外部知识库检索到的原文片段作为上下文拼接进大模型提示词，从而缓解幻觉并支持知识更新。典型流程是：文档切块 → 离线向量化入库 → 用户问题向量化 → 混合检索召回 → 重排序 → 拼装提示词 → 大模型生成。检索环节的召回率直接决定生成质量的上限。' },
  { id: 'zh-20', title: '文档切块策略', lang: 'zh',
    text: '文档切块需要在语义完整性与检索粒度之间取舍。固定长度切块实现简单但容易截断语义，按段落切块能保留语义单元但长度不均。实践中常用带重叠的滑动窗口，重叠部分避免关键信息正好落在切分边界上被截断，同时用元数据记录来源文档、段落序号与字符区间以便回溯。' },
  { id: 'zh-21', title: 'Recall@K 与 nDCG 指标', lang: 'zh',
    text: 'Recall@K 衡量相关文档被召回的比例，适合只有二值相关性的评测集。nDCG@K 使用折损累积增益 DCG 除以理想排序的 IDCG，适合分级相关性场景，能同时反映召回与排序质量。评测检索质量必须固定语料、查询集与 K 值，并且要覆盖量化前后两种模型配置的对比。' },
  { id: 'zh-22', title: 'seekdb JS SDK 集合管理', lang: 'zh',
    text: 'seekdb-js SDK 提供 createCollection、getCollection、listCollections、deleteCollection 等集合级操作，以及 collection.add、upsert、update、delete、get、query、hybridSearch 等数据级操作。每个集合在数据库里对应一张物理表，包含 id、document、embedding、metadata 四个字段以及全文索引和向量索引。' },
  { id: 'zh-23', title: '嵌入式与 server 部署形态', lang: 'zh',
    text: 'seekdb 既可以以嵌入式方式嵌入 Node.js 进程运行（通过 @seekdb/js-bindings 原生绑定），也可以以本地 server 方式运行，通过 MySQL 协议对外提供 2881 端口的服务。嵌入式部署省去进程管理，适合单机工具；server 形态便于多个客户端共享，也更接近生产部署。' },
  { id: 'zh-24', title: '端到端延迟拆解', lang: 'zh',
    text: '一次端到端查询延迟可以拆成：模型下载与加载、查询文本向量化、网络往返到数据库、seekdb 混合检索执行、结果序列化与渲染。其中首次加载远大于后续请求，必须把首次与预热后的数据分开报告。报告时建议给出中位数而不是最快的一次，以避免偶然因素干扰。' },
  // ---------------- 英文语料 ----------------
  { id: 'en-01', title: 'About StepFun', lang: 'en',
    text: 'StepFun is a Chinese artificial intelligence company founded in 2023 and headquartered in Shanghai. It develops the Step series of multimodal foundation models, including Step-1 a hundred-billion parameter base language model, Step-2 for mathematics and code, and Step-Video for video generation.' },
  { id: 'en-02', title: 'OceanBase overview', lang: 'en',
    text: 'OceanBase is an open-source distributed relational database developed by Ant Group. It is MySQL compatible, uses an LSM-Tree storage engine, and supports multi-tenancy, horizontal partitioning, and strong consistency replication. Version 4 added vector search capabilities.' },
  { id: 'en-03', title: 'seekdb introduction', lang: 'en',
    text: 'seekdb is a lightweight vector database built on the OceanBase kernel. It can run embedded inside a Node.js process or as a standalone server speaking the MySQL protocol. It ships dense vector indexes, fulltext indexes and a built-in hybrid search package.' },
  { id: 'en-04', title: 'Hybrid search with RRF', lang: 'en',
    text: 'Hybrid search combines a lexical BM25 search over an inverted index with an approximate nearest neighbour vector search, then fuses both ranked lists. Reciprocal Rank Fusion is the usual fusion method because it only depends on ranks, not on the raw scores of each modality.' },
  { id: 'en-05', title: 'ONNX Runtime Web backends', lang: 'en',
    text: 'ONNX Runtime Web runs ONNX models inside the browser. It provides a WebAssembly CPU execution provider and a WebGPU execution provider. The WebGPU path must be requested explicitly and guarded with try/catch so that applications can fall back to WebAssembly when the adapter is unavailable.' },
  { id: 'en-06', title: 'Transformers.js in the browser', lang: 'en',
    text: 'Transformers.js is the JavaScript port of Hugging Face transformers powered by ONNX Runtime Web. It runs entirely client side, supports WebGPU and WASM devices, and can load pre-converted ONNX weights published by the Xenova organisation on the Hugging Face Hub.' },
  { id: 'en-07', title: 'all-MiniLM-L6-v2', lang: 'en',
    text: 'all-MiniLM-L6-v2 is a compact English sentence embedding model with six transformer layers and a 384 dimensional hidden size. It uses mean pooling followed by L2 normalisation and is one of the most widely deployed embedding models for local and edge applications.' },
  { id: 'en-08', title: 'bge-small-zh-v1.5', lang: 'en',
    text: 'bge-small-zh-v1.5 is a small Chinese embedding model released by BAAI with a 512 dimensional hidden size. It is trained on large scale Chinese corpora and is evaluated on the C-MTEB benchmark. The official usage recommends CLS pooling with L2 normalisation.' },
  { id: 'en-09', title: 'Quantisation of embedding models', lang: 'en',
    text: 'Quantising an embedding model to INT8 typically shrinks the ONNX weights by close to four times while keeping the sentence level ranking almost unchanged. FP16 halves the size and is a better fit for GPU execution providers. The quality impact must be measured with recall or nDCG rather than eyeballed.' },
  { id: 'en-10', title: 'Batching for throughput', lang: 'en',
    text: 'Embedding throughput improves dramatically with batching because a larger matrix multiplication amortises per-call overhead. The trade-off is higher peak memory and longer time to first result. Offline ingestion should use large batches while interactive queries should use small batches or a single sentence.' },
  { id: 'en-11', title: 'Vector index refresh', lang: 'en',
    text: 'Approximate vector indexes are built incrementally, so newly written rows only become fully searchable after an index refresh. seekdb exposes dbms_index_manager.refresh for that purpose. A good ingestion strategy refreshes once after a batch rather than after every single write.' },
  { id: 'en-12', title: 'Evaluating retrieval quality', lang: 'en',
    text: 'Recall at K measures how many relevant documents are retrieved, while nDCG at K accounts for both relevance grades and their position in the ranking. To compare two model variants you need a fixed corpus, a fixed query set with human judgements, and identical index and ranking parameters.' },
];

/**
 * 评测查询集。relevant 为相关文档 id，grade 为 {docId: 3|2|1} 分级相关性。
 */
export const EVAL_QUERIES = [
  { qid: 'q01', query: '阶跃星辰是一家什么公司', relevant: ['zh-01'] },
  { qid: 'q02', query: 'Step-1 大模型的参数量规模', relevant: ['zh-01'] },
  { qid: 'q03', query: 'OceanBase 和 MySQL 兼容吗', relevant: ['zh-03', 'en-02'] },
  { qid: 'q04', query: 'seekdb 支持哪些部署方式', relevant: ['zh-04', 'zh-23', 'en-03'] },
  { qid: 'q05', query: '混合检索是怎么融合两路结果的', relevant: ['zh-05', 'zh-06', 'en-04'] },
  { qid: 'q06', query: 'RRF 公式里的 rank_constant 是什么作用', relevant: ['zh-06', 'en-04'] },
  { qid: 'q07', query: 'BM25 排序函数的三个组成部分', relevant: ['zh-07'] },
  { qid: 'q08', query: 'HNSW 的 ef_construction 参数调大有什么影响', relevant: ['zh-08'] },
  { qid: 'q09', query: '余弦距离和内积什么时候等价', relevant: ['zh-09'] },
  { qid: 'q10', query: 'Transformers.js 支持哪些推理后端', relevant: ['zh-10', 'en-06'] },
  { qid: 'q11', query: '为什么要在浏览器本地做向量化', relevant: ['zh-11'] },
  { qid: 'q12', query: 'INT8 量化的压缩比是多少', relevant: ['zh-12', 'en-09'] },
  { qid: 'q13', query: 'WebGPU adapter 申请失败怎么办', relevant: ['zh-13', 'zh-14', 'en-05'] },
  { qid: 'q14', query: 'bge-small-zh 的向量维度是多少', relevant: ['zh-15', 'en-08'] },
  { qid: 'q15', query: 'all-MiniLM-L6-v2 的隐藏层维度', relevant: ['zh-16', 'en-07'] },
  { qid: 'q16', query: '批量推理如何提升吞吐量', relevant: ['zh-17', 'en-10'] },
  { qid: 'q17', query: '写入后多久新文档可以被检索到', relevant: ['zh-18', 'en-11'] },
  { qid: 'q18', query: 'RAG 的典型流程是什么', relevant: ['zh-19'] },
  { qid: 'q19', query: '文档切块的重叠窗口有什么作用', relevant: ['zh-20'] },
  { qid: 'q20', query: 'nDCG 和 Recall 的区别', relevant: ['zh-21', 'en-12'] },
  { qid: 'q21', query: 'seekdb-js SDK 有哪些集合操作方法', relevant: ['zh-22'] },
  { qid: 'q22', query: '端到端延迟应该怎么分阶段统计', relevant: ['zh-24'] },
  { qid: 'q23', query: 'StepFun model API pricing', relevant: ['zh-02', 'en-01'] },
  { qid: 'q24', query: 'How does hybrid search fuse BM25 and vector results', relevant: ['en-04', 'zh-05'] },
  { qid: 'q25', query: 'batch size 对 embedding 吞吐的影响', relevant: ['zh-17', 'en-10'] },
  { qid: 'q26', query: 'embedding model quantization size reduction', relevant: ['en-09', 'zh-12'] },
  { qid: 'q27', query: '数据库索引刷新 call dbms_index_manager', relevant: ['zh-18', 'en-11'] },
  { qid: 'q28', query: '浏览器 WebGPU 不可用时降级到 WASM', relevant: ['zh-14', 'en-05'] },
];

/** 生成多语混合的干扰查询，用于考察混合检索里全文通道的作用 */
export const KEYWORD_QUERIES = [
  'dbms_index_manager',
  'rank_window_size',
  'ef_construction',
  'onnxruntime-web',
  'Xenova',
];

export function chunkDocuments(docs, { maxChars = 480, overlap = 60, minChars = 24 } = {}) {
  const out = [];
  for (const doc of docs) {
    const text = (doc.text || '').replace(/\r\n/g, '\n').trim();
    const paragraphs = text.split(/\n{1,}/).map((p) => p.trim()).filter(Boolean);
    let buffer = '';
    let start = 0;
    let part = 0;
    const flush = (end) => {
      const body = buffer.trim();
      if (body.length >= minChars || out.length === 0) {
        out.push({
          id: `${doc.id}#${part}`,
          text: body,
          metadata: {
            doc_id: doc.id,
            title: doc.title || '',
            lang: doc.lang || '',
            part,
            char_start: start,
            char_end: end,
          },
        });
      }
      part += 1;
    };
    for (const p of paragraphs) {
      if (buffer.length + p.length + 1 <= maxChars) {
        buffer = buffer ? `${buffer}\n${p}` : p;
      } else {
        if (buffer) {
          const end = start + buffer.length;
          flush(end);
          // 保留重叠
          const keep = buffer.slice(Math.max(0, buffer.length - overlap));
          start = end - keep.length;
          buffer = keep ? `${keep}\n${p}` : p;
        } else {
          buffer = p;
        }
      }
    }
    if (buffer.trim()) flush(start + buffer.length);
  }
  return out;
}
