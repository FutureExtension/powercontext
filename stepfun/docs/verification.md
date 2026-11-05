# 验证报告：SQL、表结构与写入核对

> 全部内容来自本机实际执行 `npm run verify`（`scripts/verify.mjs`）的真实输出。
> 机器可读的原始报告：`../data/verify-report.json`（含每条断言、每条 SQL、全部计时）。

---

## 1. 验证命令与结论

```bash
cd stepfun
npm run seekdb     # 确保数据库在跑
npm run verify     # 核心验证脚本
```

| 项 | 值 |
|---|---|
| 退出码 | **0** |
| 断言总数 | **21** |
| 通过 / 失败 | **21 / 0** |
| 模型 | `Xenova/bge-small-zh-v1.5`（512 维），精度 `q8`（INT8） |
| 集合 | `kb_bge_small_zh_v1_5_q8` |
| 物理表 | `c$v2$9c767e801de011b29f82525400f705f0`（本次运行；集合每次 reset 会生成新的 collectionId） |
| 语料 / 切块 | 36 篇 → 36 块 |
| 评测查询 | 28 条 |

验证脚本的 8 个阶段：

| 阶段 | 内容 |
|---|---|
| 1 | 环境与模型加载 |
| 2 | 文档切块（与服务端/前端同一套规则） |
| 3 | 端侧向量化（维度 / L2 范数 / 条数） |
| 4 | 写入 seekdb + 索引刷新 + `count()` |
| 5 | **从 seekdb 回读核对**（原文列 + 向量列） |
| 6 | seekdb 混合检索（命中数 / 原文一致 / 融合发生在库内 / 保留字降级） |
| 7 | 增量写入 + 刷新后可见性 |
| 8 | 检索质量（Recall@5 / HitRate@5 / nDCG@5） |

---

## 2. 断言清单（21 条全部通过）

| # | 阶段 | 断言 | 实测 |
|---|---|---|---|
| 1 | 1/8 | 模型在本地加载成功 | dtype=q8, 1401.01 ms, backend=cpu(onnxruntime-node) |
| 2 | 2/8 | 每篇文档至少切出 1 个块 | 36 篇 → 36 块 |
| 3 | 2/8 | 所有块原文非空 | ✅ |
| 4 | 2/8 | 所有块都带 doc_id 元数据（可回溯） | ✅ |
| 5 | 3/8 | 向量条数 == 切块数 | 36 == 36 |
| 6 | 3/8 | **每个向量维度 == 模型声明维度** | dim=512 |
| 7 | 3/8 | 所有向量 L2 范数 ≈ 1（normalize 生效） | min=1.000000 max=1.000000 |
| 8 | 4/8 | 集合已创建（reset 后重建，保证可复现） | `kb_bge_small_zh_v1_5_q8` → 表 `c$v2$9c767e801de011b29f82525400f705f0` |
| 9 | 4/8 | **seekdb `count()` == 写入条数** | 36 == 36 |
| 10 | 5/8 | 回读行数 == 写入条数 | 36 == 36 |
| 11 | 5/8 | **原文列与写入原文逐字一致** | 不一致 **0** 行 |
| 12 | 5/8 | **向量列与端侧算出的向量一致（余弦 ≥ 0.999）** | 不一致 **0** 行，最小余弦 **1.000000** |
| 13 | 6/8 | **`hybridSearch` 返回条数 > 0** | 5 条 |
| 14 | 6/8 | **检索结果中的原文与写入原文一致** | 不一致 **0** 条 |
| 15 | 6/8 | **混合检索由 seekdb 完成（SQL 中出现 DBMS_HYBRID_SEARCH）** | `DBMS_HYBRID_SEARCH.GET_SQL` |
| 16 | 6/8 | 融合在数据库侧完成（同一 SQL 内含 `_keyword_rank` + `_semantic_rank` 的 RRF 融合式） | ✅ |
| 17 | 6/8 | 查询文本含数据库保留字时仍可完成混合检索（全文通道安全降级） | 命中 3 条 |
| 18 | 6/8 | 降级时给出明确提示（warnings 非空） | 「查询文本包含数据库保留字 [CALL]，全文通道已剔除这些字面量后重试；向量通道（查询向量）未受影响，融合仍在 seekdb 内完成。」 |
| 19 | 7/8 | **增量写入后 count 正确增长** | 37 == 36 + 1 |
| 20 | 7/8 | 刷新后新增文档可被检索到 | 命中（排名第 1） |
| 21 | 8/8 | Recall@5 > 0 | Recall@5=0.8095 · HitRate@5=0.9643 · nDCG@5=0.7725（28 条查询） |

---

## 3. seekdb 集合与表结构

### 3.1 集合注册表（真实 `sdk_collections` 表内容）

```
collection_id                            collection_name              settings.schema
ad48b5cb1de011b29f82525400f705f0        kb_bge_small_zh_v1_5_fp32    vectorIndex.hnsw{distance:cosine, dimension:512}
                                                                    fulltextIndex{analyzer:ik, properties:{ik_mode:smart}}
                                                                    version: v2
b9d19a7e1de011b29f82525400f705f0        kb_bge_small_zh_v1_5_fp16    同上
f481a7251de011b29f82525400f705f0        kb_bge_small_zh_v1_5_q8      同上
```

> 集合命名规则：`kb_<模型短名>_<精度>`（`src/config.mjs` 的 `collectionNameFor`）。三个精度的集合互相独立，用于演示「集合/会话状态管理」。

### 3.2 真实 `DESC` 输出

对 `c$v2$ad48b5cb1de011b29f82525400f705f0`（= `kb_bge_small_zh_v1_5_fp32`）：

```
Field        | Type            | Null | Key
------------+-----------------+------+-----
_id         | varbinary(512)  | NO   | PRI
document    | string          | YES  |
embedding   | VECTOR(512)     | YES  |
metadata    | json            | YES  |
```

### 3.3 真实 `SHOW CREATE TABLE` 输出（含两个索引）

```sql
CREATE TABLE `c$v2$ad48b5cb1de011b29f82525400f705f0` (
  `_id` varbinary(512) NOT NULL,
  `document` string DEFAULT NULL,
  `embedding` VECTOR(512) DEFAULT NULL,
  `metadata` json DEFAULT NULL,
  PRIMARY KEY (`_id`),
  FULLTEXT KEY `idx_fts` (`document`) WITH PARSER ik PARSER_PROPERTIES=(ik_mode="smart") BLOCK_SIZE 16384,
  VECTOR KEY `idx_vec` (`embedding`) WITH (DISTANCE=COSINE, TYPE=HNSW, LIB=VSAG, M=16, EF_CONSTRUCTION=200, EF_SEARCH=64, SYNC_MODE=ASYNC) BLOCK_SIZE 16384
) ORGANIZATION HEAP DEFAULT CHARSET = utf8mb4 ROW_FORMAT = DYNAMIC COMPRESSION = 'zstd_1.3.8'
  REPLICA_NUM = 1 BLOCK_SIZE = 16384 USE_BLOOM_FILTER = FALSE ENABLE_MACRO_BLOCK_BLOOM_FILTER = FALSE
  TABLET_SIZE = 134217728 PCTFREE = 0 LOB_INROW_THRESHOLD=78643
```

| 索引 | 类型 | 配置 | 作用 |
|---|---|---|---|
| `idx_fts` | FULLTEXT | `PARSER ik`，`ik_mode="smart"`，BLOCK_SIZE 16384 | 全文通道（BM25 排序），分词器 = ik 智能分词 |
| `idx_vec` | VECTOR | `DISTANCE=COSINE`, `TYPE=HNSW`, `LIB=VSAG`, `M=16`, `EF_CONSTRUCTION=200`, `EF_SEARCH=64`, `SYNC_MODE=ASYNC` | 向量通道（余弦近邻） |

三个精度的集合建表语句完全一致（仅数据不同），实测 `SELECT COUNT(*)` 均为 36。

---

## 4. 写入核对（向量列 + 原文列）

核对方法（`scripts/verify.mjs` 阶段 5）：写入完成后，**从 seekdb 直接回读全表**，与端侧算出的向量 / 原文逐条比对。

执行的 SQL：

```sql
SELECT _id, document, metadata, embedding
FROM `c$v2$9c767e801de011b29f82525400f705f0`
ORDER BY _id
```

| 核对项 | 期望 | 实测 | 结论 |
|---|---|---|---|
| 回读行数 | = 写入条数 36 | **36** | ✅ |
| `document` 列 vs 写入原文（逐字比较） | 0 条不一致 | **`textMismatches = 0`** | ✅ |
| `embedding` 列 vs 端侧算出的向量（余弦 ≥ 0.999） | 0 条不一致 | **`vectorMismatches = 0`** | ✅ |
| 全部向量中最小余弦 | ≈ 1.0 | **`minStoredVectorCosine = 1.000000`** | ✅ |

> 这条比对是「向量确实存进了 seekdb、且存的就是浏览器/Node 端算出来的那个向量」的直接证据，而不是只看接口返回。

`metadata` 中保存的元数据示例结构：

```json
{
  "doc_id": "zh-05",
  "title": "seekdb 混合检索与 DBMS_HYBRID_SEARCH",
  "lang": "zh",
  "part": 0,
  "char_start": 0,
  "char_end": 137
}
```

---

## 5. 混合检索：真实 SQL 与结果原文

### 5.1 实际执行的三条语句

`src/seekdb-service.mjs` 拦截客户端的 `execute`，把本次混合检索真正执行的 SQL 记录下来（完整原文见 `data/verify-report.json` → `hybridSearchSql`）。

**① 绑定检索参数**

```sql
SET @search_parm = ?
```

其中 `@search_parm` 的内容（由 SDK 构造）：

```json
{
  "query": {
    "query_string": { "fields": ["document"], "query": "RRF 融合算法是怎么工作的" }
  },
  "knn": {
    "field": "embedding",
    "k": 5,
    "query_vector": ["-0.04847294837236405", "...", "0.11807307968950272"]
  },
  "rank": { "rrf": { "rank_window_size": 60, "rank_constant": 60 } },
  "size": 5
}
```

**② 由 seekdb 生成这条混合检索 SQL**

```sql
SELECT DBMS_HYBRID_SEARCH.GET_SQL('c$v2$9c767e801de011b29f82525400f705f0', @search_parm) as query_sql FROM dual
```

**③ 数据库生成、并由数据库执行的那一条 SQL**（向量字面量已折叠，其余为原文）

```sql
SELECT ifnull(`_fts`.`_id`, `_vs`.`_id`) as `_id`,
       ifnull(`_fts`.`document`, `_vs`.`document`) as `document`,
       ifnull(`_fts`.`embedding`, `_vs`.`embedding`) as `embedding`,
       ifnull(`_fts`.`metadata`, `_vs`.`metadata`) as `metadata`,
       (ifnull(1 / (`_fts`.`_keyword_rank` + 60), 0)
      + ifnull(1 / (`_vs`.`_semantic_rank`  + 60), 0)) as `_score`
FROM (
  (SELECT *, RANK() over( ORDER BY `_keyword_score` DESC) as `_keyword_rank`
     FROM (SELECT /*+ opt_param('hidden_column_visible', 'true') */
                  `__pk_increment`, `_id`, `document`, `embedding`, `metadata`,
                  match(`document`) against('RRF 融合算法是怎么工作的' in natural language mode) as `_keyword_score`
             FROM `stepfun`.`c$v2$9c767e801de011b29f82525400f705f0`
            WHERE match(`document`) against('RRF 融合算法是怎么工作的' in natural language mode)
            ORDER BY `_keyword_score` DESC LIMIT 1200)) `_fts`
  full join
  (SELECT *, RANK() over( ORDER BY `_semantic_score` DESC) as `_semantic_rank`
     FROM (SELECT /*+ opt_param('hidden_column_visible', 'true') */
                  cosine_distance(`embedding`, '[-0.04847294837236405, -0.009530396200716496, ..., 0.11807307968950272]') / 2, 8) as `_semantic_score`
             FROM `stepfun`.`c$v2$9c767e801de011b29f82525400f705f0`
            ORDER BY `_distance` APPROXIMATE LIMIT 5)) `_vs`
    on `_fts`.`__pk_increment` = `_vs`.`__pk_increment`
) ORDER BY `_score` DESC, ifnull(`_vs`.`__pk_increment`, `_fts`.`__pk_increment`) LIMIT 5
```

### 5.2 为什么这证明了「混合检索由 seekdb 完成」

| 观察点 | 说明 |
|---|---|
| `DBMS_HYBRID_SEARCH.GET_SQL(...)` | 检索 SQL 由**数据库**生成，不是客户端拼的 |
| `match(\`document\`) against('...' in natural language mode)` | 全文通道在库内走 `idx_fts`（ik 分词 + BM25） |
| `cosine_distance(\`embedding\`, '[...]')` + `ORDER BY \`_distance\` APPROXIMATE` | 向量通道在库内走 `idx_vec`（HNSW/vsag） |
| `1/(_keyword_rank + 60) + 1/(_semantic_rank + 60)` | **RRF 融合分数在同一条 SQL 内由数据库算出** |
| `ORDER BY \`_score\` DESC` | 排序也由数据库完成 |
| 客户端行为 | 只发一次 `hybridSearch()` 调用、接收已排好序的结果；**没有分别查两路再在客户端拼合** |

对应断言：#15「混合检索由 seekdb 完成（SQL 中出现 `DBMS_HYBRID_SEARCH`）」、#16「融合在数据库侧完成」。

### 5.3 检索结果原文

查询：`RRF 融合算法是怎么工作的`　·　topK=5　·　seekdb 侧耗时 148.23 ms（该次运行）

| 排名 | 文档 ID | score | 原文（截取） |
|---|---|---|---|
| 1 | `zh-05#0` | 0.032800 | seekdb 的混合检索由数据库内部的 DBMS_HYBRID_SEARCH 包完成。它接收一份 search_parm 参数，其中 query 描述全文检索条件、knn 描述向量近邻条件、rank 描述融合算法，然后生成一条可执行的 SQL。默认融合算法是 RRF，即 Reciprocal Rank Fusion，把两路结果的排名倒数加权求和。 |
| 2 | `zh-03#0` | 0.029000 | OceanBase 是蚂蚁集团开源的分布式关系型数据库，兼容 MySQL 协议，支持多租户、… |
| 3 | `zh-02#0` | 0.028400 | 阶跃星辰开放平台提供 step-1、step-1v、step-2 等模型的在线推理 API。… |
| 4 | `zh-06#0` | 0.016100 | RRF（Reciprocal Rank Fusion）把每个文档在两路召回中的排名转换成分数：score = Σ 1 / (k + rank_i)，其中 k 是 rank_constant，用来平滑头部排名的差距。rank_window_size 则限定参与融合的排名窗口。RRF 不需要归一化分数，因此非常适合把 BM25 分数和向量距离两种量纲完全不同的信号融合在一起。 |
| 5 | `en-01#0` | 0.016100 | StepFun is a Chinese artificial intelligence c… |

**原文一致性核对**：以上 5 条命中的 `document` 与写入 seekdb 的原文**逐字一致（不一致 0 条）** —— 见断言 #14。
（`zh-05#0` / `zh-06#0` 的完整原文见 `src/corpus.mjs` 的 `DEMO_DOCS`。）

### 5.4 保留字降级路径（如实记录）

seekdb-js 客户端会扫描上面那条**由数据库生成**的 SQL；一旦查询文本里出现 `CALL / LOAD / SELECT / DELETE` 等字面量，就会判定为注入并拒绝执行。

实现上的处理（`src/seekdb-service.mjs` 的 `sanitizeFulltextQuery` + `hybridSearch` 的 catch 分支）：

* **只降级全文通道**：剔除这些字面量后，用**同一个 `collection.hybridSearch()`** 重试；
* **向量通道完全不变**：查询向量原样传入，语义召回不受影响；
* **融合仍在库内**：重试走的还是 `DBMS_HYBRID_SEARCH.GET_SQL` 那条路；
* **前端可见**：降级原因通过 `warnings` 字段回传，`public/app.js` 用横幅提示用户。

实测：查询 `数据库索引刷新 call dbms_index_manager` → **命中 3 条**，提示
「查询文本包含数据库保留字 [CALL]，全文通道已剔除这些字面量后重试；向量通道（查询向量）未受影响，融合仍在 seekdb 内完成。」

---

## 6. 增量写入与索引刷新

| 步骤 | 操作 | 结果 |
|---|---|---|
| 1 | 批量写入 36 块 | `count() = 36` ✅ |
| 2 | `refresh_index()` | 刷新耗时 706.60 ms（该次运行） |
| 3 | 增量 upsert 1 条新文档（`inc-01#0`），文本为「增量写入验证文档：海王星是一颗位于太阳系外围的冰巨星。它的平均直径约 49244 公里，质量约为地球的 17 倍，表面大气以氢和氦为主。」 | ✅ |
| 4 | 再次 `refresh_index()` | ✅ |
| 5 | `count()` | **37 == 36 + 1** ✅ |
| 6 | 查询 `海王星 冰巨星 直径` | **新文档被检索命中，排名第 1** ✅ |

断言 #19（count 正确增长）、#20（刷新后新增文档可被检索到）均通过。
另外，重复导入同 ID 文档使用 `upsert`，不会产生重复行（增量导入语义安全）。

---

## 7. 检索质量指标

固定语料（36 篇 / 36 块）+ 固定查询集（28 条，带人工相关性标注）+ Top-K=5，全部由 `hybridSearch()` 在 seekdb 内完成检索后统计。

| 指标 | 本次 `npm run verify` | `npm run bench`（另一次运行） |
|---|---|---|
| Recall@5 | **0.8095** | 0.8274 |
| HitRate@5 | **0.9643** | 0.9643 |
| nDCG@5 | **0.7725** | 0.7900 |

两次运行的差异来自随机性很小（同一模型/语料/查询集，差异来自 seekdb HNSW 近似检索的非完全确定性）。**两次均未出现质量为零的查询。**

**指标定义**

* `Recall@5` = (Top-5 命中的相关文档数 ÷ 该查询的相关文档总数)，对 28 条查询取平均。切块先按 `metadata.doc_id` 归并回源文档再统计。
* `HitRate@5` = 至少命中 1 条相关文档的查询数 ÷ 28。
* `nDCG@5` = DCG/IDCG，增益取二值（相关=1，不相关=0），DCG = Σ gain_i / log2(i+1)，IDCG 为理想排序。

相关文档标注来自 `src/corpus.mjs` 的 `EVAL_QUERIES`（每条查询带 `relevant` 文档 id 列表）。

---

## 8. 本轮未完成的验证（如实）

| 项 | 状态 | 原因 |
|---|---|---|
| **浏览器端自动化验证** | ❌ **未跑通** | `scripts/verify-browser.mjs` 已完整实现（Node 22 内置 WebSocket 手写最小 CDP 客户端，驱动本机 Edge 156），覆盖首页加载、浏览器内模型加载、浏览器内导入→写入、浏览器内检索、DOM 后端提示、以及强制关闭 WebGPU 的降级场景与截图留证；但本环境执行时 **Edge 的 DevTools 调试端口未能就绪（`Page.enable` 阶段超时）**，断言未跑完。附加原因：本机 `node_modules` 无 puppeteer/playwright 且网络不通无法安装。 |
| WebGPU 可用性实测 | ❌ 未测 | 本机无独立 GPU；浏览器未跑通。代码已按赛题要求实现「探测 → 优先 WebGPU → 失败降级 WASM → 界面提示」。 |
| 浏览器端性能数字 | ❌ 未测 | 同上。本文件与 `performance.md` 的所有数字均为 **Node 端 onnxruntime-node（CPU）口径**。 |

补救方式：换一台可正常启动浏览器的机器，执行 `npm run verify:browser` 即可补齐浏览器侧断言与截图（脚本已交付并接入 `npm run verify:browser`）。

---

## 9. 复现命令汇总

```bash
cd stepfun
npm run seekdb          # 启动本地 seekdb（127.0.0.1:2883 / 库 stepfun）
npm run verify          # 本报告的 21 条断言，退出码 0
npm run bench -- --all # 质量指标 + 精度对比
npm run models:info     # 模型体积 / 压缩比
```

产物：`data/verify-report.json`（断言明细 + 全部 SQL + 计时）、`data/bench.json`（分阶段计时 + 质量 + batch 扫描）。