# StepFun × seekdb 迷你知识库（端侧向量化 + 数据库侧混合检索）

> OceanBase 大赛 2026 · 生态赛题「阶跃星辰」（20 分）
> 题目：端侧 AI 推理性能优化与 seekdb 混合检索
> 一页技术说明 · 本文件中的所有数字均来自本机实测，原始数据见 `data/bench.json`、`data/verify-report.json`。

---

## 0. 一条命令跑起来

```bash
cd stepfun
npm install                 # 只装项目内 node_modules，不装任何系统级软件
npm run fetch-models        # 把 ONNX 权重下载到本地 .model-cache/（只需一次）
npm run seekdb              # 启动本地 seekdb server（127.0.0.1:2883，库名 stepfun）
npm start                   # 启动应用 → http://127.0.0.1:5173/
```

一条命令完成端到端验证与基准：

```bash
npm run verify              # 21 条断言全绿，退出码 0
npm run bench               # 分阶段计时，输出 JSON
npm run models:info         # 各模型 fp32/fp16/q8 体积与压缩比
npm run verify:browser      # 浏览器端验证（16 条断言全绿，见 §9.3）
```

| 项目 | 值 |
|---|---|
| 应用地址 | `http://127.0.0.1:5173/` |
| seekdb 地址 | `127.0.0.1:2883`（MySQL 协议），库名 `stepfun`，租户 `sys` |
| seekdb 数据目录 | `C:/codex-work/ob-00001/work/seekdb-stepfun`（**本项目独占**，不与其它 base-dir 混用） |
| seekdb 可执行文件 | `C:/codex-work/ob-00001/tools/seekdb/PFiles64/seekdb/bin/seekdb.exe` |
| 模型缓存目录 | `C:/codex-work/ob-00001/work/powercontext/stepfun/.model-cache/`（浏览器通过 `/models` 镜像加载，**完全离线可用**） |
| 浏览器要求 | Chrome / Edge 最新版（需支持 ES Modules + WebGPU 或 WASM SIMD） |

`npm start` 会在 seekdb 未启动时自动拉起一个本地 seekdb 进程（`scripts/start-seekdb.mjs` 单独起也可以）。

---

## 1. 应用形态

一个可在浏览器本地运行的迷你知识库 Web 应用：

```
用户粘贴/拖入文档
      │
      ▼
浏览器本地切块（public/embedder.js，与服务端 src/corpus.mjs 同一套规则）
      │
      ▼
浏览器本地向量化（Transformers.js + ONNX Runtime Web）──► 得到 512 维向量
      │
      ▼  POST /api/documents  { id, text, vector, metadata }
本地 Node 服务（server.mjs）──► seekdb 写入 + 刷新索引
      │
用户输入查询 ─► 浏览器本地向量化（同一个模型、同一精度）
      │  POST /api/search { queryText, queryVector, topK, rrf }
      ▼
本地 Node 服务 ─► seekdb collection.hybridSearch()  ←─ 融合全部发生在数据库内
      │
      ▼
浏览器渲染排序结果 + 原文高亮 + 本次执行的真实 SQL
```

关键边界：**后端（`server.mjs`）不做任何 embedding 计算**。它只做三件事：静态资源托管、把浏览器已经算好的向量写进 seekdb、调用 seekdb 的混合检索。源码里没有服务端 embedding 调用、没有预计算向量表、没有结果回放。

| 文件 | 作用 |
|---|---|
| `server.mjs` | Express 服务：静态资源 + `/models` 本地模型镜像 + `/api/documents` `/api/search` `/api/collection/*` |
| `public/index.html` `app.js` `embedder.js` `styles.css` | 前端：浏览器端向量化 + 导入/检索 UI + 后端提示 + 分阶段计时面板 |
| `src/config.mjs` | 模型注册表（模型 id / 维度 / pooling / 精度 / 许可证 / revision）、seekdb 连接参数、集合命名规则 |
| `src/corpus.mjs` | 示例语料 36 篇（中 24 + 英 12）+ 评测查询集 28 条（带相关性标注）+ 切块算法 |
| `src/embedder.mjs` | Node 端嵌入器（与浏览器同模型同精度），供 verify / bench 使用 |
| `src/seekdb-service.mjs` | seekdb 数据访问层：集合/表、写入、刷新、混合检索、SQL 记录 |
| `src/native-deps.mjs` | onnxruntime-node 原生依赖引导（仅 Node 端） |
| `scripts/verify.mjs` | **核心验证脚本**（21 条断言） |
| `scripts/bench.mjs` | 分阶段计时 + 精度对比 + batch 扫描，输出 JSON |
| `scripts/model-info.mjs` | 模型体积 / 压缩比 / 维度 / 许可证报告 |
| `scripts/verify-browser.mjs` | 浏览器端验证（CDP 驱动 Edge/Chrome） |
| `scripts/fetch-models.mjs` | 下载 ONNX 权重到 `.model-cache/` |
| `scripts/start-seekdb.mjs` | 独立启动本地 seekdb server |
| `data/bench.json` `data/verify-report.json` | 实测原始数据（本说明所有数字的来源） |

---

## 2. 端侧推理（本地完成，禁止云端推理 API）

* **文档向量化**：在浏览器页面内由 `public/embedder.js` 的 `Embedder.embed()` 完成。
* **查询向量化**：同样在浏览器页面内完成（`Embedder.embed([query], { batchSize: 1 })`）。
* **运行时**：Transformers.js v4（`@huggingface/transformers`）+ ONNX Runtime Web（`onnxruntime-web`）。
* **零云端推理**：代码中不存在任何推理 API 调用；页面只请求同源的 `/models/...`（本机模型文件）与 `/api/*`（本机 Node 服务）。
  浏览器端把 `env.localModelPath = '/models/'`，ONNX Runtime 的 wasm 运行时也从本机 `/vendor/ort/...` 加载，因此**首次运行也不需要访问 huggingface.co**。
* **可验证**：服务端只接受「已经算好的向量」，且 `scripts/verify.mjs` 会把 seekdb 里存下的向量与本地算出的向量逐条做余弦比对（§8）。

---

## 3. 模型来源与版本

| 项 | 主模型 | 备选模型 |
|---|---|---|
| HuggingFace 仓库 | [`Xenova/bge-small-zh-v1.5`](https://huggingface.co/Xenova/bge-small-zh-v1.5) | [`Xenova/all-MiniLM-L6-v2`](https://huggingface.co/Xenova/all-MiniLM-L6-v2) |
| 原始出处 | BAAI `bge-small-zh-v1.5`（中文，CLS pooling，官方推荐 L2 归一化） | sentence-transformers `all-MiniLM-L6-v2`（英文，mean pooling） |
| 维度 | **512** | 384 |
| pooling / normalize | `cls` / L2 normalize=true | `mean` / L2 normalize=true |
| 许可证 | **MIT** | Apache-2.0 |
| revision | `75c43b06…`（**已固定到 commit SHA**） | `751bff37…`（**已固定到 commit SHA**） |
| 默认精度 | `q8`（INT8 动态量化） | `q8` |

> revision 说明（2026-11-06 更新）：`src/config.mjs` 里的 `revision` **已固定到具体 commit SHA**：`Xenova/bge-small-zh-v1.5` = `75c43b069aac4d136ba6bc1122f995fedcfd2781`，`Xenova/all-MiniLM-L6-v2` = `751bff37182d3f1213fa05d7196b954e230abad9`。`scripts/fetch-models.mjs` 按这个 SHA 下载（不是会漂移的 `main`），并把每个文件的字节数与 **sha256** 写进 `data/model-manifest.json`；`scripts/model-info.mjs` 会**离线重算 sha256 并逐文件核对**本地缓存，当前输出为「✔ 已核对 7 个 / 6 个文件与固定 revision 清单（sha256 全部一致）」。因此「版本已固定」是可当场验证的事实，而不是一句声明。

---

## 4. 模型量化：INT8 / FP16 方案、体积与压缩比、检索质量变化

### 4.1 方案

* **INT8 (`q8`)**：`onnx/model_quantized.onnx`，Transformers.js 默认的动态量化权重（int8），**默认精度**。
* **FP16**：`onnx/model_fp16.onnx`，半精度权重。
* **FP32**：`onnx/model.onnx`，基线。
* 三种精度由 `src/config.mjs` 的 `dtypes: ['q8','fp16','fp32']` 注册，前端下拉框可实时切换；**每个精度使用独立集合**（`kb_<模型>_<精度>`），互不污染。

### 4.2 体积与压缩比（实测字节数，口径见 `scripts/model-info.mjs` 文件头）

`Xenova/bge-small-zh-v1.5`：

| 精度 | 权重文件 | 权重体积 | + tokenizer/配置 | 总体积 | 压缩比（权重） | 压缩比（总体积） |
|---|---|---|---|---|---|---|
| FP32（基线） | `onnx/model.onnx` | 94,851,877 B / 90.46 MiB | 440,333 B | 95,292,210 B / 90.88 MiB | 1.000× | 1.000× |
| FP16 | `onnx/model_fp16.onnx` | 47,497,427 B / 45.30 MiB | 440,333 B | 47,937,760 B / 45.72 MiB | **1.997×** | **1.988×** |
| INT8 (`q8`) | `onnx/model_quantized.onnx` | 24,010,842 B / 22.90 MiB | 440,333 B | 24,451,175 B / 23.32 MiB | **3.950×** | **3.897×** |

`Xenova/all-MiniLM-L6-v2`：FP32 90,387,606 B (86.20 MiB) / FP16 45,297,825 B (43.20 MiB) / INT8 22,972,370 B (21.91 MiB)；压缩比 1.995× / 3.934×（权重口径）。

> 口径：`权重体积` = 该精度真正参与推理的那一个 ONNX 文件；`总体积` = 该 ONNX + 推理必需的 `config.json / tokenizer.json / tokenizer_config.json / special_tokens_map.json`（各精度共用同一套 tokenizer，所以可直接相除）。压缩比 = FP32 体积 ÷ 该精度体积。

### 4.3 检索质量变化（固定语料 36 篇 + 固定查询集 28 条，Top-K = 5）

| 配置 | 模型体积 | 向量化吞吐 | seekdb 检索延迟 | 端到端查询延迟 | Recall@5 | HitRate@5 | nDCG@5 |
|---|---|---|---|---|---|---|---|
| 量化前基线 FP32 | 90.46 MiB | 5.33 块/秒 | 32.52 ms | 102.12 ms | 0.7917 | 0.9286 | 0.7762 |
| FP16 | 45.30 MiB | 10.43 块/秒 | 16.78 ms | 54.79 ms | 0.7917 | 0.9286 | 0.7762 |
| **INT8 + 降级路径（本机 ONNX CPU）** | **22.90 MiB** | **10.68 块/秒** | **18.78 ms** | **25.93 ms** | **0.8274** | **0.9643** | **0.7900** |

**质量结论（重要且如实）**：在本次评测集上，INT8 相对 FP32 的 Recall@5 变化为 **+0.036**（0.7917 → 0.8274），nDCG@5 变化为 **+0.014**（0.7762 → 0.7900），**没有出现检索质量下降**。
但必须说明两点：
1. 差异幅度（0.036 / 0.014）**与评测集规模同量级**（28 条查询，1 条查询命中与否就会让 Recall@5 变化 0.036），因此**不能据此断言「INT8 一定优于 FP32」**，只能说「在本评测集上 INT8 未观察到质量下降」。
2. FP16 与 FP32 的三个指标完全一致，说明两者在本数据集上的排序结果基本相同；这是量化不改变语义排序的正常表现。
3. 评测方法：Recall@K = 命中的相关文档数 ÷ 相关文档总数（文档级，按 `metadata.doc_id` 归并切块后平均）；HitRate@K = 至少命中一条相关文档的查询占比；nDCG@K 用二值增益、DCG/IDCG 归一化。详见 `scripts/verify.mjs` 阶段 8 与 `scripts/bench.mjs`。
4. **本表是 Node 端 onnxruntime-node（CPU）口径**。浏览器端（WebGPU/WASM）的**分阶段耗时已实测**（§9.3），但浏览器侧的**检索质量指标**（Recall@5 / HitRate@5 / nDCG@5）仍只有这张 Node 端表——浏览器验证跑的是 3 块样例语料，不足以复算质量指标。

---

## 5. 推理后端：优先 WebGPU，不可用自动降级 WASM，界面明确提示

实现位于 `public/embedder.js`：

1. **探测**：`probeBackend()` 检查 `navigator.gpu` 是否存在 → `navigator.gpu.requestAdapter({ powerPreference: 'high-performance' })` 申请适配器 → 读取 `adapter.info`。
2. **显式配置后端**：拿到适配器则尝试 `pipeline('feature-extraction', modelId, { dtype, device: 'webgpu' })`。
3. **自动降级**：任何一步失败（无 `navigator.gpu` / `requestAdapter()` 返回 null / 创建会话抛异常），都回退到 `device: 'wasm'` 重试。
4. **界面提示**：顶部状态芯片 `#backend-value` 始终显示当前后端（`WebGPU` 或 `WASM`），并给出降级原因横幅：

   ```
   推理后端：WASM（已从 WebGPU 降级）— navigator.gpu.requestAdapter() 返回 null（没有可用的 GPU 适配器）。
   文档与查询向量仍全部在本机浏览器内计算。
   ```

   样式上 WebGPU 用 `.badge-webgpu`、WASM 用 `.badge-wasm` 区分；`public/app.js` 的 `paintBackend()` 同时更新芯片与横幅。

5. **WASM 侧优化**：服务端下发 `Cross-Origin-Opener-Policy: same-origin` + `Cross-Origin-Embedder-Policy: credentialless`，使浏览器可启用 `SharedArrayBuffer`；`env.backends.onnx.wasm.numThreads = min(4, hardwareConcurrency - 1)`，并开启 SIMD，ORT 的 wasm/mjs 运行时也从本机 `/vendor/ort/` 加载（不走 CDN）。

**本机实测情况（如实标注）**：本机为 Intel i5-5250U（3 核 / 1.60 GHz）笔记本，**没有可用的独立 GPU**。但 2026-11-06 用无头 Edge 156 实测时，浏览器**确实暴露了一个 WebGPU 适配器**——`vendor=google, architecture=swiftshader`，即 Chromium 的**软件光栅化**实现，不是真实 GPU。两个分支都真实跑通了：WebGPU 分支创建了推理会话并完成向量化与检索；强制禁用 WebGPU 的场景则自动降级到 WASM。**因此 WebGPU 代码路径是实测过的，但耗时反映的是 CPU 软件渲染，不能代表真实显卡性能**（详见 §9.3）。

---

## 6. seekdb 存储：集合、表结构与实际 SQL

* **接入方式**：`seekdb` npm SDK（v1.4.0）的 `SeekdbClient`，连接 `127.0.0.1:2883`，租户 `sys`，**库名 `stepfun`**。
* **集合命名**：`kb_<模型短名>_<精度>`，例如 `kb_bge_small_zh_v1_5_q8`。集合/会话状态由 `src/seekdb-service.mjs` 的 `collections` Map 管理，支持按模型+精度切换与重建（`resetCollection`）。
* **物理表**：seekdb v2 集合对应物理表 `c$v2$<collectionId>`（例如 `c$v2$f481a7251de011b29f82525400f705f0`）。

真实 `SHOW CREATE TABLE` 输出（`c$v2$ad48b5cb1de011b29f82525400f705f0`，`kb_bge_small_zh_v1_5_fp32`）：

```sql
CREATE TABLE `c$v2$ad48b5cb1de011b29f82525400f705f0` (
  `_id` varbinary(512) NOT NULL,
  `document` string DEFAULT NULL,
  `embedding` VECTOR(512) DEFAULT NULL,
  `metadata` json DEFAULT NULL,
  PRIMARY KEY (`_id`),
  FULLTEXT KEY `idx_fts` (`document`) WITH PARSER ik PARSER_PROPERTIES=(ik_mode="smart") BLOCK_SIZE 16384,
  VECTOR KEY `idx_vec` (`embedding`) WITH (DISTANCE=COSINE, TYPE=HNSW, LIB=VSAG, M=16, EF_CONSTRUCTION=200, EF_SEARCH=64, SYNC_MODE=ASYNC) BLOCK_SIZE 16384
) ORGANIZATION HEAP DEFAULT CHARSET = utf8mb4 ROW_FORMAT = DYNAMIC COMPRESSION = 'zstd_1.3.8' ...
```

| 列 | 类型 | 含义 |
|---|---|---|
| `_id` | `varbinary(512)` | 文档 ID（切块 ID，形如 `zh-05#0`），主键 |
| `document` | `string` | **原文**（切块后的文本），`idx_fts` 全文索引（ik 分词，smart 模式） |
| `embedding` | `VECTOR(512)` | **向量**，HNSW/vsag 向量索引，余弦距离 |
| `metadata` | `json` | 元数据：`doc_id` / `title` / `lang` / `part` / `char_start` / `char_end` |

索引配置（`src/seekdb-service.mjs` 的 `ensureCollection`）：

```js
new Schema({
  fulltextIndex: new FulltextIndexConfig('ik', { ik_mode: 'smart' }),
  vectorIndex: new VectorIndexConfig({
    hnsw: { distance: 'cosine', type: 'hnsw', lib: 'vsag', m: 16, ef_construction: 200, ef_search: 64, dimension: model.dim },
    embeddingFunction: null,   // 向量由浏览器端算好后写入，禁止 SDK 在服务端做嵌入
  }),
})
```

`embeddingFunction: null` 是刻意设置的：它明确告诉 SDK「不要去加载 `@seekdb/default-embed` 在服务端算向量」，从而在数据层杜绝服务端推理的可能。

---

## 7. 混合检索：**由 seekdb 完成**，不是客户端拼合

调用点只有一处：`src/seekdb-service.mjs` 的 `hybridSearch()` → `collection.hybridSearch({ query, knn, rank, nResults, include })`。

* `query.whereDocument.$contains` → `query_string`（全文通道，ik 分词 BM25）
* `knn.queryEmbeddings` → HNSW 近邻（向量通道，余弦距离）
* `rank.rrf` → **seekdb 内 RRF 融合**（`rankWindowSize` / `rankConstant`，前端可调）

**客户端从头到尾没有分别取两路结果再自行拼合**：融合分数 `_score` 由数据库算好并直接排序返回。数据库侧实际执行的三条语句（完整原文见 `data/verify-report.json` 的 `hybridSearchSql`）：

```sql
-- ① 绑定检索参数
SET @search_parm = ?

-- ② 让 seekdb 自己生成这条混合检索 SQL
SELECT DBMS_HYBRID_SEARCH.GET_SQL('c$v2$9c767e801de011b29f82525400f705f0', @search_parm) as query_sql FROM dual

-- ③ 数据库生成的那一条 SQL（节选，向量字面量已省略）
SELECT ifnull(`_fts`.`_id`, `_vs`.`_id`) as `_id`,
       ifnull(`_fts`.`document`, `_vs`.`document`) as `document`,
       ifnull(`_fts`.`embedding`, `_vs`.`embedding`) as `embedding`,
       ifnull(`_fts`.`metadata`, `_vs`.`metadata`) as `metadata`,
       (ifnull(1 / (`_fts`.`_keyword_rank` + 60), 0)
      + ifnull(1 / (`_vs`.`_semantic_rank`  + 60), 0)) as `_score`
FROM (
  (SELECT *, RANK() over( ORDER BY `_keyword_score` DESC) as `_keyword_rank`
     FROM (SELECT `__pk_increment`, `_id`, `document`, `embedding`, `metadata`,
                  match(`document`) against('RRF 融合算法是怎么工作的' in natural language mode) as `_keyword_score`
             FROM `stepfun`.`c$v2$9c767e801de011b29f82525400f705f0`
            WHERE match(`document`) against('RRF 融合算法是怎么工作的' in natural language mode)
            ORDER BY `_keyword_score` DESC LIMIT 1200)) `_fts`
  full join
  (SELECT *, RANK() over( ORDER BY `_semantic_score` DESC) as `_semantic_rank`
     FROM (SELECT cosine_distance(`embedding`, '[...512 维向量字面量...]') / 2, 8) as `_semantic_score`
             FROM `stepfun`.`c$v2$9c767e801de011b29f82525400f705f0`
            ORDER BY `_distance` APPROXIMATE LIMIT 5)) `_vs`
    on `_fts`.`__pk_increment` = `_vs`.`__pk_increment`
) ORDER BY `_score` DESC, ifnull(`_vs`.`__pk_increment`, `_fts`.`__pk_increment`) LIMIT 5
```

可以看到：**全文通道 `match(document) against(...)`、向量通道 `cosine_distance(...)`、以及 `1/(rank+60) + 1/(rank+60)` 的 RRF 融合，全部在同一条数据库 SQL 内部完成**。`scripts/verify.mjs` 对此有两条硬断言：「混合检索由 seekdb 完成（SQL 中出现 `DBMS_HYBRID_SEARCH`）」与「融合在数据库侧完成（同一 SQL 内含 `_keyword_rank` 与 `_semantic_rank`）」。

**已知限制（如实记录）**：seekdb-js 客户端会扫描这条生成的 SQL，遇到 `CALL / LOAD / SELECT / DELETE` 等字面量就判定为注入并拒绝执行。实现上做了**只降级全文通道**的安全处理：剔除这些字面量后用**同一个 seekdb 混合检索**重试，向量通道的查询向量完全不变，融合依旧在库内完成，并通过 `warnings` 字段把降级原因回传给前端提示。实测：查询 `数据库索引刷新 call dbms_index_manager` → 命中 3 条，提示「查询文本包含数据库保留字 [CALL]…」。

---

## 8. 写入、索引刷新与状态管理

* **写入**：`collection.upsert({ ids, documents, embeddings, metadatas })` —— 同一 ID 重复导入不会产生重复行（增量导入安全）。
* **索引刷新**：写入后调用 `collection.refresh_index()`（底层为 `dbms_index_manager` 刷新接口），保证新数据立刻可被检索。实测见 §9。
* **批量刷新策略**：导入一批 → 统一写一次 → 统一刷新一次（写入 473.60 ms + 刷新 312.58 ms / 36 块，INT8 口径）。若业务要求「写后立即可查」，可按批刷新，代价是刷新耗时随批次数线性增长。
* **状态管理**：`collections` Map 缓存集合句柄；`/api/collection/reset` 可重建集合；不同模型/精度使用不同集合，互不干扰；前端状态芯片实时显示当前集合名与文档数。

**写入正确性已被逐条核对**（`scripts/verify.mjs` 阶段 5，从 seekdb 回读后比对）：

| 核对项 | 结果 |
|---|---|
| 回读行数 == 写入条数 | 36 == 36 ✅ |
| `document` 列与写入原文**逐字一致** | 不一致 **0** 行 ✅ |
| `embedding` 列与端侧算出的向量余弦 ≥ 0.999 | 不一致 **0** 行，最小余弦 **1.000000** ✅ |
| 增量写入 1 条并刷新后 | 行数 36 → **37** ✅，且新文档能被检索命中（排名第 1）✅ |

---

## 9. 性能优化与实测数字

完整原始数据：`data/bench.json`；逐项说明：`docs/performance.md`；验证与 SQL 原文：`docs/verification.md`。

### 9.1 分阶段计时（INT8 / bge-small-zh-v1.5 / batch=16 / 36 块 / Node 端 CPU 口径）

| 阶段 | 实测 |
|---|---|
| 模型获取（本地缓存命中，读盘） | 334.44 ms（22.90 MiB） |
| 模型加载 / 推理会话初始化 | 11,760.08 ms ⚠ 见下方说明 |
| 文档向量化（36 块） | 4,288.13 ms（8.40 块/秒） |
| 写入 seekdb | 2,995.80 ms |
| 索引刷新 | 614.04 ms |
| 查询向量化 | 33.96 ms |
| seekdb 混合检索 | 44.96 ms |
| **合计** | **20,071.41 ms** |
| 端到端查询延迟（查询向量化 + 检索） | 中位数 **127.87 ms**，P95 **139.11 ms** |

> ⚠ `模型加载 11,760.08 ms` 是该次运行的一次**异常值**（当时机器上还有其它负载）。同一模型在同一次运行的精度对比轮里重复测量为 **335.44 ms**（INT8）/ 1,150.75 ms（FP16）/ 1,647.40 ms（FP32）。表内保留原始值不做美化。

### 9.2 实际做过的性能优化与「优化前 → 优化后」

| 优化点 | 优化前 | 优化后 | 依据 |
|---|---|---|---|
| **INT8 动态量化**（相对 FP32 基线） | 体积 90.46 MiB · 吞吐 5.33 块/秒 · 端到端 102.12 ms | 体积 **22.90 MiB（3.950×）** · 吞吐 **10.68 块/秒（2.00×）** · 端到端 **25.93 ms（3.94×）** | `data/bench.json` → `comparison` |
| **模型本地镜像**（`/models` + 本机 ORT wasm，消除 CDN 往返） | 需联网从 HF 拉权重 | 模型获取 **18.60 ~ 334.44 ms**（纯读盘），首次运行即可离线 | `data/bench.json` → `stages.modelFetchMs` |
| **跨源隔离头 + WASM 多线程**（COOP/COEP → SharedArrayBuffer，线程数 = min(4, 核数-1)） | WASM 单线程 | 浏览器端多线程可用的前提 | `server.mjs` / `public/embedder.js` |
| **批量推理**（batch 扫描 1/4/8/16/32/64） | batch=1 → 13.77 块/秒 | batch=16 → 13.54 块/秒；**本机吞吐在 9.88 ~ 13.77 块/秒区间基本持平** | `data/bench.json` → `batchSweep` |
| **批量 upsert + 单次索引刷新**（导入结束后统一刷新一次） | 每条一次刷新 | 36 块：写入 473.60 ms + 刷新 312.58 ms | `data/bench.json` → `comparison` |
| **HNSW 参数** m=16 / ef_construction=200 / ef_search=64 | SDK 默认 | 显式配置 + 余弦距离 | `src/seekdb-service.mjs` |
| **预热与中位数统计**（排除首次懒初始化，报告 median 而非最快一次） | 报最快一次 | 全部阶段报中位数并保留全部原始样本 | `scripts/_lib.mjs` |

> **关于 batch size 的实测结论（如实）**：在这台 3 核 / 1.60 GHz 的老 CPU 上，中文长序列（512 token）的 embedding 是**内存带宽瓶颈而非调度瓶颈**，因此加大 batch 没有带来吞吐提升（batch=1 的 13.77 块/秒甚至略高于 batch=16 的 13.54 块/秒，差异在噪声范围内，样本见 `data/bench.json` → `batchSweep.embedSamplesMs`）。这与「批量必然更快」的直觉不同，故此处如实给出扫描数据而不是只报最好的一组。在核数更多的机器上结论可能相反。

---

### 9.3 浏览器端实测（本机无头 Edge 156.0.4314.58，2026-11-06，`npm run verify:browser`）

浏览器自动化验证**已跑通**：**16 条断言全绿**，报告 `data/browser-verify-report.json`，截图
`data/browser-verify-webgpu-or-wasm.png`、`data/browser-verify-wasm-fallback.png`。

| 阶段 | 场景 A：WebGPU（SwiftShader 软件适配器） | 场景 B：强制无适配器 → 自动降级 WASM |
|---|---|---|
| 模型加载状态探测 | 4,237.0 ms | 3,195.7 ms |
| 文档向量化（浏览器本地，3 块） | 4,935.3 ms（0.61 块/秒） | 898.5 ms（3.34 块/秒） |
| 写入 seekdb | 819.8 ms | 263.7 ms |
| 索引刷新 | 424.7 ms | 524.8 ms |
| 导入端到端 | 6,180.4 ms | 1,687.5 ms |
| 查询向量化 | 601.2 ms | 25.5 ms |
| seekdb 混合检索 | 69.5 ms | 46.7 ms |
| 查询端到端 | 679.7 ms | 81.1 ms |
| 浏览器控制台未捕获异常 | 0 | 0 |

两个场景都验证了同一条链路：**浏览器内加载模型 → 浏览器内文档/查询向量化 → 写入 seekdb → 浏览器内检索 → DOM 渲染**；
命中结果带回 512 维向量，混合检索 SQL 由 seekdb 生成（`DBMS_HYBRID_SEARCH`）。

**必须说明的两点（如实）**：

1. 场景 A 的 WebGPU 适配器是 **SwiftShader 软件实现**（`vendor=google, architecture=swiftshader`）。本机没有真实 GPU，
   所以场景 A 的吞吐反而**低于** WASM 分支（0.61 vs 3.34 块/秒）——这是软件光栅化的开销，**不能**用来评价真实显卡上的 WebGPU 性能。
2. 浏览器验证使用 3 块样例语料，证明的是**链路与后端选择正确**；检索质量指标仍只有 Node 端 §4.3 的那一组。

### 9.4 为了跑通浏览器端而修复的三个真实缺陷

| # | 缺陷 | 现象 | 修复 |
|---|---|---|---|
| 1 | 前端模块说明符无法解析 | `TypeError: Failed to resolve module specifier "onnxruntime-web/webgpu"`；页面永远不初始化，`window.stepfunReady` 永不出现 | transformers 的 web bundle 用**裸说明符**引入 ORT，浏览器无法解析 → `public/index.html` 增加 **import map**；`server.mjs` 本机镜像 ORT web bundle 与 wasm 运行时（`ort.webgpu.min.mjs`、`ort.min.mjs`、`ort-wasm-simd-threaded[.jsep].{mjs,wasm}`），并把 `onnxruntime-common` 的 ESM 产物整目录镜像到 `/vendor/ort/common/`；`env.backends.onnx.wasm.wasmPaths` 改为本机前缀 `/vendor/ort/`，由 transformers 按后端自动选 `.jsep` 或普通变体 |
| 2 | seekdb 写入被可选依赖卡住 | `Embedding function 'default-embed' is not registered.`，任何写入都失败 | SDK 的 `getCollection()` 默认会解析默认嵌入函数；本应用的向量由浏览器算好后写入，必须显式传 `embeddingFunction: null`（`src/seekdb-service.mjs`），否则会去加载未安装的可选依赖 `@seekdb/default-embed` |
| 3 | 验证脚本自身的三个问题 | ① `Runtime.evaluate` 里用顶层 `await` → SyntaxError；② 场景 A 的 Edge 进程不退出、占着 CDP 端口，场景 B 永远等不到 DevTools 就绪；③ 集合残留历史数据，导致「写入条数 == 浏览器算出的向量条数」断言失败 | ① 改成 async IIFE；② 每个场景用**独立 CDP 端口**，并在结束时通过浏览器级 CDP 端点发送 `Browser.close`；③ 导入前先调用 `/api/collection/reset` 重置集合 |

---

## 10. 局限与未完成项（如实，不粉饰）

1. **浏览器端的链路与后端选择已实测；真实 GPU 性能与浏览器侧质量指标仍未测。**
   `scripts/verify-browser.mjs`（Node 22 内置 `WebSocket`/`fetch` 手写最小 CDP 客户端驱动本机 Edge 156）已在本机**跑通**：
   **16 条断言全绿**（§9.3），覆盖首页加载、浏览器内加载模型、浏览器内导入→写入、浏览器内检索、DOM 后端提示、
   以及「强制关闭 WebGPU 后自动降级 WASM」的第二场景与截图留证。
   * 仍未测：① **真实显卡**上的 WebGPU 性能（本机只有 SwiftShader 软件适配器）；② 浏览器侧的检索质量指标（验证语料只有 3 块）。
   * 过程中修掉了三个真实缺陷（模块说明符、seekdb 写入、验证脚本自身），逐条记录在 §9.4。

2. ~~**模型 revision 未固定到 commit SHA**（§3）~~ —— **已修复**（2026-11-06）：两个模型的 `revision` 都已固定到具体 commit SHA，下载脚本按 SHA 取文件并记录逐文件 sha256，`npm run models:info` 会离线核对本地缓存与该清单（当前全部一致）。

3. **质量评测集偏小**：28 条查询 / 36 篇文档，Recall@5 的最小刻度就是 0.036，因此 §4.3 里量化前后的差异幅度**与噪声同量级**，只支持「未观察到质量下降」这一结论，不支持「INT8 更好」。

4. **语料与向量检索均为本项目自带的演示语料**，没有接入真实业务数据；跨领域/长文档场景的召回表现未评估。

5. **图片内容未支持**：赛题说明「图片内容支持可作为扩展」，本实现只做文本知识库。

6. ~~**服务端的 `/api/collection/:name/rows` 校验接口**在集合已存在但当前进程未创建它时会报 `Embedding function 'default-embed' is not registered.`~~ —— **已修复**：`ensureCollection` 现在统一用 `getCollection({ name, embeddingFunction: null })` 取集合，不再触发 SDK 去加载可选嵌入依赖；浏览器写入路径与该校验接口都已恢复。

7. **单机单进程**：应用服务与 seekdb 都跑在本机，`server.mjs` 的 seekdb 子进程随父进程退出而结束；多用户/生产部署需要把 seekdb 独立常驻。

8. **本机没有真实 GPU**（Intel i5-5250U，无独立显卡）。无头 Edge 暴露的是 Chromium 的 **SwiftShader 软件 WebGPU 适配器**，
   所以 §9.3 场景 A 的数字反映的是 CPU 软件渲染，**不代表真实显卡上的 WebGPU 性能**；「WebGPU 优先 + 自动降级」的代码路径已在真实浏览器里执行过，
   但**硬件口径的 WebGPU 性能仍需在有真实 GPU 的机器上重跑 `npm run verify:browser`**。