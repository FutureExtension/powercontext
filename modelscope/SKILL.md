---
name: oceanbase-seekdb-agent-memory
version: 1.0.0
description: "把 AI Agent 应用落地到 OceanBase seekdb + PowerContext 上的数据底座助手。当你要为 Agent/RAG 应用做检索选型（纯向量 / 纯全文 / 混合检索）、写 seekdb 建表与查询 SQL（VECTOR 列 + FULLTEXT INDEX + VECTOR INDEX、MATCH AGAINST、AI COLUMN 异步 embedding、COW 沙箱 FORK/MERGE）、或用 PowerContext 接管 Agent 的上下文采集与长期记忆（CaptureSource 采集、SourceDefinition 注册来源与投影、MemoryCitation 精确引用、search_memory 的 fts|vector|hybrid|auto 模式）时使用本技能；同时覆盖“混合检索没走索引”“向量维度不匹配”“记忆写进去却搜不到”“命中重复/引用过期”等排错。触发词：seekdb、OceanBase、PowerContext、混合检索、hybrid search、向量检索、全文检索、MATCH AGAINST、AI COLUMN、Agent 记忆、上下文采集、MemoryCitation、embedding、EXPLAIN 索引验证。不涉及：模型训练与微调、非 OceanBase 系数据库的选型迁移、以及与检索/记忆无关的通用 Agent 编排。"
---

# OceanBase seekdb + PowerContext：AI Agent 数据底座助手

本技能把「一个 AI Agent 应用」拆成两件可落地的事，并给出**能直接跑**的产物：

- **检索底座**（seekdb）：向量 / 全文 / 混合检索的建表与查询 SQL，以及「一条 SQL 同时取全文候选与向量候选」的写法。
- **上下文与记忆**（PowerContext）：采集（Source）→ 加工（Memory）→ 检索（search）→ 精确引用（MemoryCitation）的完整链路。

所有 SQL 均为 MySQL 兼容语法（seekdb 走 MySQL 协议，默认端口 2881）。所有凭据一律使用占位符，**不要**把真实 Key/Token 写进代码或文档。

---

## 1. 能力边界

### 1.1 本技能做什么

1. **检索选型**：把业务需求映射到「纯向量 / 纯全文 / 混合」三种方案，输出建表 DDL 与查询 SQL。
2. **单条 SQL 混合检索**：给出「全文候选 + 向量候选 + 标量过滤」写在同一条 SQL 里的写法，以及用 `EXPLAIN` 证明两类索引**真的**被使用的方法。
3. **AI COLUMN**：用 seekdb 的 `AI COLUMN` + `AI_EMBED` / `AI_COMPLETE` 把 embedding 与摘要下沉到数据库，异步生成、失败可重试。
4. **COW 沙箱**：用 `FORK DATABASE` / `MERGE TABLE` 让 Agent 安全试错并可回滚。
5. **PowerContext 记忆链路**：`CaptureSource`（采集）、`SourceDefinition`（注册来源与投影）、`MemoryCitation`（精确引用）的真实 Python 代码，以及 `search_memory` 的 `fts|vector|hybrid|auto` 模式选择。
6. **验证与排错**：可执行的 `EXPLAIN` 校验、一致性校验清单、常见故障定位表。

### 1.2 本技能**不**做什么（先看这里）

| 不做的事 | 说明 / 你应该改用什么 |
| --- | --- |
| **不做**模型训练、微调、权重优化 | 只负责「用哪个 embedding 模型、维度多少、怎么存、怎么查」。要训模型请用训练框架。 |
| **不做**非 OceanBase 系数据库的选型与迁移 | 本技能的 SQL 依赖 seekdb 的 `VECTOR` 类型、`MATCH ... AGAINST`、`FULLTEXT INDEX`、`FORK/MERGE`。你的库若是 Milvus / ES / Qdrant / pgvector，**不适用**本技能的 SQL。 |
| **不**代替 PowerContext 服务端本身 | 不能替你部署/升级服务端、改判题内核逻辑，也**不承诺**任何 Recall@10 / MRR 指标。 |
| **不**生成或索取 API Key / 密码 / Token | 文档与代码中一律使用 `<YOUR_TOKEN>`、`<YOUR_API_KEY>`、`<scope_id>` 等占位符；密钥只走环境变量。 |
| **不**做与检索/记忆无关的通用 Agent 编排 | 工具调用、路由、工作流编排属于 Agent 框架层，本技能只管数据底座。 |
| **不**在缺少真实需求时硬编 SQL | 选型必须走第 2 节决策表；需求要素（数据类型、语种、数据量、过滤维度、延迟预算）缺失时，先向用户确认。 |
| **不**建议把敏感原文写进宽表检索列 | 需要合规隔离时，用 PowerContext 的 Scope 隔离 + 标签过滤，而不是把密文塞进 `searchable_text`。 |
| **不**承诺「一键搞定」 | 若需求涉及跨库联邦检索、超大规模亿级向量、跨机房同步，本技能不覆盖，请改用专用方案。 |

---

## 2. 决策流程

### 2.1 五步选型（按顺序问，不要跳步）

1. **Step 0 · 数据形态**：是「长文档/对话/代码/日志原文」还是「短文本片段」？是否需要**回读原文**（原文必须能按 `entry_version_id` 精确取回）？
2. **Step 1 · 查询形态**：用户输入是**关键词/专有名词/编号**为主，还是**同义改写/模糊表述**为主？还是两者都有？
3. **Step 2 · 过滤维度**：是否需要「按用户/租户/时间/标签」等**标量过滤**？过滤是在库内做还是应用层做？
4. **Step 3 · 规模与预算**：数据量级、写入是否持续流式、查询 p50 延迟目标（毫秒级 vs 百毫秒级）、是否允许**近似**（ANN）召回？
5. **Step 4 · 是否需要长期记忆**：记忆的**生命周期**（是否跨会话、是否需要版本/修订/停用/恢复）是否比「一次性 RAG」更关键？

### 2.2 决策表（需求 → 选型）

| 需求特征 | 检索方案 | seekdb 索引 | PowerContext `mode` | SQL 形态 |
| --- | --- | --- | --- | --- |
| 查询几乎都是精确关键词、产品编号、错误码 | **纯全文** | `FULLTEXT INDEX ... WITH PARSER` | `"fts"` | `WHERE MATCH(col) AGAINST('...')` |
| 查询是同义改写、语义相似、跨语言表述 | **纯向量** | `VECTOR INDEX ... (DISTANCE=l2, TYPE=hnsw)` | `"vector"` | `ORDER BY l2_distance(emb, ?) APPROXIMATE` |
| 关键词与语义混合；既要精确命中又要覆盖改写 | **混合**（默认推荐） | 全文索引 + 向量索引**同时**建 | `"hybrid"` | 一条 SQL 内 `MATCH` + `ORDER BY ... APPROXIMATE` |
| 语料同时含中英文 | **混合** | 中文 `PARSER ik` / 英文 `PARSER beng` | `"hybrid"` | 同上 |
| 强标量过滤 + 需要低延迟 | **混合**（过滤下推到库内） | 同上 + `scope/tenant` 普通索引 | `"hybrid"` + `tag_filter` | `WHERE tenant_id=? AND MATCH(...)` |
| 原文必须能被逐字引用、需修订/停用/恢复 | **混合 + PowerContext 记忆模型** | `pc_memory_entry_heads` + `pc_memory_entry_versions` | `"auto"` | 检索拿 `entry_version_id`，再按版本取正文 |
| 需要跨会话长期记忆 + 预算/压缩控制 | **PowerContext Memory** | 同上（`pc_memory_vector_entries` 存向量） | `"auto"` | 采集 → flush → remember → search |
| 需要在数据库内自动算向量/摘要 | **AI COLUMN** | `AI COLUMN (AI_EMBED(...))` | — | `ALTER TABLE ... RETRY AI COLUMN ...` |
| Agent 要安全试错并可回滚 | **COW 沙箱** | `FORK DATABASE` / `MERGE TABLE` | — | `FORK DATABASE a TO b; ... ; MERGE TABLE ...` |

> **默认建议**：拿不准就选 **混合**。全文负责「命中确定性」，向量负责「召回覆盖度」，两者在库内合成候选，再由应用层做融合/精排。

### 2.3 embedding profile 约束（PowerContext 侧，硬约束）

PowerContext 的向量索引实现要求**单位化 L2**：

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `profile_id` | 字符串 | 部署内唯一标识；换模型 = 换 profile = **需要重建向量投影** |
| `model` | 字符串 | embedding 模型名 |
| `dimension` | 正整数 | 必须与建表 `VECTOR(dim)` **完全一致** |
| `distance` | `"l2"` | 仅支持 L2 |
| `normalization` | `"unit"` | 仅支持单位化（模型输出必须先归一化） |

违反 `distance/normalization` 约束时，PowerContext 会在初始化阶段直接抛 `CapabilityNotSupportedError`，不会「降级运行」。

---

## 3. 可直接复制的代码与 SQL 片段

> 以下 `CREATE TABLE` / 索引 DDL 来自 seekdb 官方仓库（2026-competition 分支）README；PowerContext 侧的表结构与索引名来自 `oceanbase/powercontext` 仓库的 `builtin/persistence/oceanbase/memory_index.py`（seekdb 后端复用同一套 MySQL 兼容索引实现，只是连接走嵌入式 seekdb）。

### 3.1 建表：向量列 + 全文索引 + 向量索引

```sql
-- 1) 通用文档表（AI Agent 知识库最常见形态）
CREATE TABLE articles (
  id         INT PRIMARY KEY,
  title      TEXT,
  content    TEXT,
  author_id  INT NOT NULL,
  created_at DATETIME NOT NULL,
  embedding  VECTOR(384),
  FULLTEXT INDEX idx_fts (content) WITH PARSER ik,
  VECTOR    INDEX idx_vec (embedding) WITH (DISTANCE=l2, TYPE=hnsw, LIB=vsag)
) ORGANIZATION = HEAP;
```

要点：

- `FULLTEXT INDEX ... WITH PARSER ik` —— `ik` 为中文分词器；英文语料用 `beng`。PowerContext 的 OceanBase 兼容后端用的是 `WITH PARSER SPACE`（空格分词），两边不要混抄。
- `VECTOR INDEX ... WITH (DISTANCE=l2, TYPE=hnsw, LIB=vsag)` —— HNSW + vsag 实现；`DISTANCE` 必须与查询里的 `l2_distance` 一致。
- `embedding VECTOR(384)` 的 `384` 只是示例，**必须换成你自己模型的真实维度**。

### 3.2 混合检索：一条 SQL 同时取全文候选与向量候选

这是本技能最核心的片段。全文条件与向量排序写在**同一条** SQL 里，由数据库一次执行完成，不需要应用层发两条查询再合并：

```sql
SELECT id, title,
       l2_distance(embedding, '[0.12, 0.34, ...]') AS dist,
       MATCH(content) AGAINST ('quarterly report') AS fts_score
FROM articles
WHERE MATCH(content) AGAINST ('quarterly report')
  AND author_id = 42
  AND created_at > '2026-01-01'
ORDER BY dist APPROXIMATE
LIMIT 10;
```

关键点：

- `ORDER BY dist APPROXIMATE` —— **`APPROXIMATE` 关键字是走 ANN 向量索引的前提**。去掉它会退化成对全表做精确距离计算（结果更准但全表扫描）。
- `WHERE MATCH(...) AGAINST(...)` —— 全文过滤，会走全文倒排索引。
- 标量过滤（`author_id`、`created_at`）在库内生效，先过滤再检索。
- 向量字面量按 `'[0.12, 0.34, ...]'` 书写；在 Python 侧请用**参数化**查询（见 3.9），不要拼接字符串。

### 3.3 纯全文检索

```sql
SELECT id, title, MATCH(content) AGAINST ('vector index tuning') AS score
FROM articles
WHERE MATCH(content) AGAINST ('vector index tuning')
ORDER BY score DESC
LIMIT 10;
```

### 3.4 纯向量检索

```sql
SELECT id, title, l2_distance(embedding, '[0.12, 0.34, ...]') AS dist
FROM articles
WHERE author_id = 42
ORDER BY dist APPROXIMATE
LIMIT 10;
```

### 3.5 用 EXPLAIN 证明两类索引真的被使用

**这一步不能省。** 很多「混合检索」实现是全表扫描后在 Python 里算距离，性能与语义都退化。验证方法：

```sql
EXPLAIN
SELECT id, title, l2_distance(embedding, '[0.12, 0.34, ...]') AS dist
FROM articles
WHERE MATCH(content) AGAINST ('quarterly report')
ORDER BY dist APPROXIMATE
LIMIT 10;
```

期望在执行计划里**同时**看到：

- 全文侧：`TEXT RETRIEVAL SCAN`（或等价的全文索引访问路径）
- 向量侧：`VECTOR INDEX`

如果只看到全表扫描，按第 5 节「排错表」逐项排查。

### 3.6 AI COLUMN：把 embedding / 摘要下沉到数据库

seekdb 支持声明式 AI 列：业务事务提交后由后台任务调用模型并写回结果，支持失败重试与「只重算受影响的行」。

```sql
CREATE TABLE docs (
  id      BIGINT PRIMARY KEY,
  title   VARCHAR(100),
  content VARCHAR(2000),
  tags    JSON AI COLUMN (
    AI_COMPLETE('text_model', CONCAT('提取分类标签，返回 JSON：', content))
  ) WITH (sync_mode='async', max_retries=2),
  emb     VECTOR(4) AI COLUMN (
    AI_EMBED('embed_model', content)
  ) WITH (sync_mode='async', max_retries=2)
);

INSERT INTO docs(id, title, content)
VALUES (1, '示例文档', '数据库支持自动生成文本标签和检索向量。');

-- 默认模式下未完成的结果为 NULL；后台完成后可直接读取。
SELECT id, tags, emb FROM docs;

-- 更新依赖列：旧结果失效并重新生成。
UPDATE docs SET content = '更新后的正文' WHERE id = 1;

-- 更新无关列：不触发重新生成。
UPDATE docs SET title = '新的标题' WHERE id = 1;

-- 按条件手动重试（status 是伪列；反引号表示同名业务列）。
ALTER TABLE docs RETRY AI COLUMN tags WHERE status = 'FAILED';
ALTER TABLE docs RETRY AI COLUMN emb  WHERE id = 1;
```

配合严格读取：

```sql
SET SESSION ai_column_strict_read = ON;
-- 之后任何引用到未就绪 AI 列的语句都会报错（列级检查）。
SELECT id, tags FROM docs;
```

> `AI COLUMN` 需要先注册模型 Endpoint（`text_model` / `embed_model` 为已注册的模型名，不是真实 URL）。
> 维度必须与 `VECTOR(dim)` 声明一致；`emb VECTOR(4)` 只是示例。

### 3.7 COW 沙箱：让 Agent 安全试错

```sql
-- 秒级快照，无数据拷贝
FORK DATABASE agent_state TO agent_sandbox_42;

USE agent_sandbox_42;
INSERT INTO memory (session_id, embedding, content) VALUES (...);  -- 随便试

-- 接受改动（策略 FAIL / THEIRS / OURS）
MERGE TABLE agent_sandbox_42.memory INTO agent_state.memory STRATEGY THEIRS;

-- 或者直接丢弃
DROP DATABASE agent_sandbox_42;
```

### 3.8 PowerContext：采集、注册来源、精确引用

#### 3.8.1 `CaptureSource` —— 采集一段外部内容作为 Source

```python
from powercontext.builtin.runtime import CaptureSource

capture = CaptureSource(
    source_id="chat-2026-11-05-0001",
    content="用户确认：2026 财年 Q3 的营收口径以合并报表为准，GAAP 与 non-GAAP 差额 1.2%。",
    metadata={
        "channel": "im",
        "occurred_at": "2026-11-05T09:12:00+08:00",
        "thread_id": "t-8842",
    },
)
```

字段语义：`source_id` 需在当前 Scope 内稳定且唯一（建议带时间戳或业务主键）；`content` 是原始内容；`metadata` 放可检索的结构化元信息。**注意**：`CaptureSource` 只是「内容被接收」，不等于「已生成记忆」，更不等于「下次能搜到」——记忆要显式写入。

#### 3.8.2 `SourceDefinition` —— 注册来源类型与命名投影

```python
from pydantic import BaseModel

from powercontext.sources import (
    AdapterSourceDefinition,
    Source,
    SourceDefinitionRegistry,
    SourceProjection,
    SourceProjectionKey,
)
from powercontext.sources.models import SourceMaterialization


class ChatMessage(BaseModel):
    """适配器接受的原始输入类型。"""

    thread_id: str
    text: str
    occurred_at: str


class ChatMessageSource(Source):
    """适配器产出的 Source 类型。"""

    name: str = "chat-message"
    thread_id: str
    text: str
    occurred_at: str
    materialization: SourceMaterialization = SourceMaterialization.CAPTURED


class ChatMessageAdapter:
    """SourceAdapter 协议：input_class / name / source_class / resolve() / read()。"""

    input_class = ChatMessage
    name = "chat-message"
    source_class = ChatMessageSource

    async def resolve(self, value: ChatMessage, /) -> ChatMessageSource:
        return ChatMessageSource(
            thread_id=value.thread_id,
            text=value.text,
            occurred_at=value.occurred_at,
        )

    async def read(self, source: ChatMessageSource, /) -> str:
        return source.text


class ChatTextProjection:
    """SourceProjection 协议：name / version / source_class / output_class / project()。"""

    name = "chat-text"
    version = "1"
    source_class = ChatMessageSource
    output_class = ChatMessage

    def project(self, source: ChatMessageSource, /) -> object:
        return ChatMessage(
            thread_id=source.thread_id,
            text=source.text,
            occurred_at=source.occurred_at,
        )


# 提升为显式、带版本的 Definition
definition = AdapterSourceDefinition(
    adapter=ChatMessageAdapter(),
    version="1",
    projections=(ChatTextProjection(),),
)

# 注意：from_adapters() 只会把 adapter 包成「版本 1、无投影」的 Definition；
# 要注册命名投影，必须用构造函数直接传入上面这个 definition。
registry = SourceDefinitionRegistry([definition])

async def demo() -> None:
    adapter = ChatMessageAdapter()
    source = await adapter.resolve(
        ChatMessage(
            thread_id="t-8842",
            text="已确认按 company_id 做数据隔离。",
            occurred_at="2026-11-05T09:12:00+08:00",
        )
    )

    # 列出该 Source 可用的命名投影
    print(registry.projection_keys(source))
    # -> (SourceProjectionKey(name='chat-text', version='1'),)

    # 按投影键产出结构化视图
    print(registry.project(source, SourceProjectionKey(name="chat-text", version="1")))


import asyncio

asyncio.run(demo())
```

> 上面 `print(registry.projection_keys(...))` 那行只是演示 `projection_keys` 的形状，**真实用法**是先 `await adapter.resolve(value)` 得到 `source`，再 `registry.projection_keys(source)`。
> `SourceDefinitionRegistry` 在构造时会校验：`input_class` / `source_class` / `name` 不重复、`version` 为非空去空白字符串、`projections` 必须是 tuple、`output_class` 必须是 `BaseModel` 子类、投影的 `source_class` 必须与 Definition 一致。任一不满足会抛对应 `InvalidSource*Error`。
> 另外，`definition_for_source(source)` 会校验 `source.definition_version` 与 Definition 的 `version` 一致 —— 所以 Source 上的 `definition_version` 需与注册时保持相同（`Source` 默认即 `"1"`）。

#### 3.8.3 `MemoryCitation` —— 指向「某个记忆修订里的某一条目的某个版本」

```python
from powercontext.artifacts import ArtifactRef, MemoryCitation

citation = MemoryCitation(
    memory_ref=ArtifactRef(family="memory", artifact_id="mem-7f3a", revision=4),
    entry_id="entry-0007",
    entry_version_id="ver-0007-003",
)
```

语义（务必理解）：

- `memory_ref.revision` 是**记忆修订号**，随内容修订递增。
- `entry_id` 是**逻辑条目**（一个事实槽位），`entry_version_id` 是该条目的**具体版本**。
- 停用/恢复只改条目状态，不改 `entry_version_id`；**正文必须与该版本逐字一致**，引用才有效。
- 检索结果里 `matched_by` 取值为 `"fts"` / `"vector"`，表示这条命中来自哪条检索通道。

### 3.9 PowerContext：HTTP 侧的记忆写入与检索

PowerContext 的 HTTP 接口（真实路由）：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/v1/sources/content` | 采集内容为 Source（`capture_content_source`） |
| `POST` | `/v1/memory/flush` | 处理已采集的 Source，产出/更新 Memory（`flush_memory`） |
| `POST` | `/v1/memory/remember` | 显式写入一条记忆（`remember_memory`） |
| `POST` | `/v1/memory/search` | 检索记忆（`search_memory`），`mode` 可选 `fts`/`vector`/`hybrid`/`auto` |
| `POST` | `/v1/memory/entries/list` | 盘点记忆条目 |
| `GET` | `/v1/capabilities` | 查询当前部署支持的检索能力 |

完整可跑示例（占位符请替换）：

```python
import json
import os
import urllib.request

BASE = os.environ.get("POWERCONTEXT_BASE", "http://127.0.0.1:8000")
TOKEN = os.environ.get("POWERCONTEXT_TOKEN", "<YOUR_TOKEN>")
SCOPE_ID = os.environ.get("POWERCONTEXT_SCOPE_ID", "<scope_id>")


def call(path: str, payload: dict) -> dict:
    """调用 PowerContext HTTP 接口；凭据只从环境变量读取。"""

    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


# 1) 采集：把一段对话变成 Source
capture = call(
    "/v1/sources/content",
    {
        "scope_id": SCOPE_ID,
        "source_id": "chat-2026-11-05-0001",
        "content": "已确认 2026 财年 Q3 营收口径以合并报表为准。",
        "metadata": {"channel": "im", "thread_id": "t-8842"},
    },
)
print("capture:", capture["status"], capture["source"], capture["position"])

# 2) 加工：把 Source 窗口处理成记忆
flushed = call("/v1/memory/flush", {"scope_id": SCOPE_ID})
print("flush:", flushed["status"], flushed["current_cursor"], flushed["processed_source_count"])

# 3) 显式记忆：写入一条不可含糊的结论
remembered = call(
    "/v1/memory/remember",
    {
        "scope_id": SCOPE_ID,
        "kind": "decision",
        "text": "2026 财年 Q3 营收口径以合并报表为准，GAAP 与 non-GAAP 差额 1.2%。",
        "reason": "用户在 2026-11-05 的会话中确认",
    },
)
print("remember:", remembered)

# 4) 检索：关键词+语义混合
found = call(
    "/v1/memory/search",
    {
        "scope_id": SCOPE_ID,
        "query": "Q3 营收口径是怎么定的",
        "mode": "hybrid",
        "limit": 5,
    },
)
for hit in found["hits"]:
    citation = hit["citation"]
    print(
        citation["entry_version_id"],
        round(hit["score"], 4),
        hit["matched_by"],
        hit["text"][:60],
    )
```

`search_memory` 的请求字段（`extra="forbid"`，多传字段会 422）：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `scope_id` | string | 必填，1~256 字符，不允许全空白 |
| `query` | string | 必填，1~8192 字符 |
| `limit` | int | 1~50，默认 10 |
| `mode` | enum | `"fts"` / `"vector"` / `"hybrid"` / `"auto"`，默认 `"auto"` |
| `tag_filter` | object? | 可选，标签过滤 |

响应 `SearchMemoryResponse`：`memory`（命中的记忆引用，可为 null）、`mode`（**实际执行**的模式：`fts`/`vector`/`hybrid`）、`hits[]`；每条 hit 含 `citation`（`memory_ref` + `entry_id` + `entry_version_id`）、`text`、`score`（0~1）、`matched_by[]`。

---

## 4. 使用示例

### 示例 1：企业制度问答（纯 SQL + seekdb，混合检索）

**输入（需求）**

- 语料：内部制度文档 8 000 篇，中文为主、含英文产品名，正文平均 2 000 字，另有 6 000 字的附录。
- 查询：用户自然语言提问，**既**包含专有名词（如 `OceanBase 租户`、`seekdb`），**也**包含同义表述（「怎么给不同团队分开看数据」）。
- 过滤：只能看本公司制度，按 `company_id` 隔离；结果要能引用到具体条款。
- 规模与预算：持续增量写入；查询 p50 < 200 ms；允许 ANN 近似。

**决策过程**

1. Step 1 查询形态 → 关键词 + 同义改写**都有** → 不能只靠全文，也不能只靠向量。
2. Step 2 过滤维度 → `company_id` 标量过滤，必须**下推到库内**。
3. Step 3 规模 → 8 000 篇持续写入 → 用 `VECTOR INDEX`（HNSW/增量索引），不建全量物化表。
4. Step 4 是否要长期记忆 → 这是一次性 RAG，**不需要** PowerContext 的记忆修订/版本模型；正文自己带条款号即可引用。

→ **选型：混合检索（全文 + 向量），单条 SQL，库内标量过滤。**

**实现**

```sql
-- 1) 建表
CREATE TABLE policy_doc (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  company_id  INT NOT NULL,
  clause_no   VARCHAR(32) NOT NULL,
  title       TEXT,
  content     TEXT,
  updated_at  DATETIME NOT NULL,
  embedding   VECTOR(384),
  FULLTEXT INDEX idx_policy_fts (content) WITH PARSER ik,
  VECTOR    INDEX idx_policy_vec (embedding) WITH (DISTANCE=l2, TYPE=hnsw, LIB=vsag),
  KEY idx_policy_company (company_id, updated_at)
) ORGANIZATION = HEAP;

-- 2) 写入（embedding 由应用侧模型算好后写入，或改用 AI COLUMN，见 3.6）
INSERT INTO policy_doc (company_id, clause_no, title, content, updated_at, embedding)
VALUES (42, '3.2.1', '数据隔离',
        '本公司数据按 company_id 逻辑隔离，不同团队只能访问被授权的租户数据。',
        '2026-11-05 10:00:00',
        '[0.021, -0.118, 0.774, ...]');

-- 3) 混合检索：全文命中 + 向量近邻 + 标量过滤，全部在一条 SQL 内
SELECT id, clause_no, title,
       l2_distance(embedding, '[0.021, -0.118, 0.774, ...]') AS dist
FROM policy_doc
WHERE company_id = 42
  AND MATCH(content) AGAINST ('数据隔离 团队 授权')
ORDER BY dist APPROXIMATE
LIMIT 10;

-- 4) 验证：EXPLAIN 必须同时出现全文与向量索引
EXPLAIN
SELECT id, clause_no, l2_distance(embedding, '[0.021, -0.118, 0.774, ...]') AS dist
FROM policy_doc
WHERE company_id = 42
  AND MATCH(content) AGAINST ('数据隔离 团队 授权')
ORDER BY dist APPROXIMATE
LIMIT 10;
```

**输出（期望）**

```
+------+-------------+------------------+-----------+
| id   | clause_no   | title            | dist      |
+------+-------------+------------------+-----------+
| 1024 | 3.2.1       | 数据隔离         | 0.0834    |
| 2087 | 3.2.3       | 租户授权变更流程 | 0.2217    |
+------+-------------+------------------+-----------+
EXPLAIN: TEXT RETRIEVAL SCAN (idx_policy_fts) + VECTOR INDEX (idx_policy_vec)   ← 两者必须同时出现
```

引用方式：把 `id` + `clause_no` + `dist` 返回给上层，正文用 `id` 回读原文，答案里标注「依据 `3.2.1`」。

---

### 示例 2：Agent 长期记忆（PowerContext + seekdb 后端，Python）

**输入（需求）**

- 场景：客服 Agent 需要记住用户的**长期偏好与历史结论**，跨会话生效。
- 痛点：用户原话里既有专有名词（「OceanBase 租户」），也有口语（「上次说好的那个方案」）。
- 要求：① 新消息要能被采集；② 明确结论要**显式**成为记忆；③ 检索要能同时命中关键词与语义；④ 答案必须能**回溯到具体记忆版本**（给用户看依据）。

**决策过程**

1. Step 0 → 原文是聊天片段，需要逐字回读 → 用 PowerContext 的 Memory 修订/版本模型。
2. Step 1 → 关键词 + 语义混合 → `mode="hybrid"`（后端自动退化为 `"fts"` 或 `"vector"` 并在响应 `mode` 里如实返回）。
3. Step 2 → 需要按用户隔离 → Scope 隔离 + 可选 `tag_filter`。
4. Step 4 → 需要跨会话长期记忆 + 版本化 → **PowerContext Memory**（seekdb 作为持久化后端）。

→ **选型：PowerContext Memory，检索 `mode="hybrid"`，引用用 `MemoryCitation`。**

**实现**（PowerContext 服务端已以 seekdb 作为持久化后端启动）

```python
import json
import os
import urllib.request

BASE = os.environ.get("POWERCONTEXT_BASE", "http://127.0.0.1:8000")
TOKEN = os.environ.get("POWERCONTEXT_TOKEN", "<YOUR_TOKEN>")
SCOPE_ID = os.environ.get("POWERCONTEXT_SCOPE_ID", "<scope_id>")


def call(path, payload):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ① 采集：会话原文 → Source（仅表示「被接收」，不等于已成为记忆）
call("/v1/sources/content", {
    "scope_id": SCOPE_ID,
    "source_id": "im-2026-11-05-0001",
    "content": "上次说好的那个方案就用 OceanBase 租户隔离，按 company_id 分。",
    "metadata": {"channel": "im", "thread_id": "t-8842"},
})

# ② 加工：把 Source 窗口过一遍，可能自动产出记忆
flush = call("/v1/memory/flush", {"scope_id": SCOPE_ID})
print("flush status:", flush["status"], "| processed:", flush["processed_source_count"])

# ③ 显式记忆：结论型信息必须显式写入
call("/v1/memory/remember", {
    "scope_id": SCOPE_ID,
    "kind": "decision",
    "text": "多团队数据隔离方案确定为 OceanBase 租户隔离，按 company_id 划分。",
    "reason": "2026-11-05 与用户确认",
})

# ④ 检索：混合模式
res = call("/v1/memory/search", {
    "scope_id": SCOPE_ID,
    "query": "我们当时定的是哪种数据隔离方案",
    "mode": "hybrid",
    "limit": 5,
})
print("实际执行模式:", res["mode"])
for hit in res["hits"]:
    c = hit["citation"]
    print(f"- {c['memory_ref']['artifact_id']}@{c['memory_ref']['revision']} "
          f"{c['entry_id']}/{c['entry_version_id']} "
          f"score={hit['score']:.4f} via={','.join(hit['matched_by'])} :: {hit['text'][:50]}")
```

**输出（期望）**

```
flush status: completed | processed: 1
实际执行模式: hybrid
- mem-7f3a@4 entry-0007/ver-0007-003 score=0.9130 via=fts,vector :: 多团队数据隔离方案确定为 OceanBase 租户隔离，按 company_id 划分。
```

**为什么这个答案可信**：

- `matched_by` 同时含 `fts` 与 `vector` → 关键词与语义两条通道都命中了。
- `citation` 给出 `memory_ref.revision` + `entry_id` + `entry_version_id` → 可以回溯到**具体版本的原文**，答案可附依据。
- `res["mode"]` 是**实际执行**的模式，而不是请求的模式；后端能力不足时会如实降级为 `fts`/`vector`。

---

## 5. 常见问题与排错

### 5.1 检索层排错表

| 现象 | 最可能根因 | 定位方法 | 修复 |
| --- | --- | --- | --- |
| `EXPLAIN` 里只有全表扫描，没有 `VECTOR INDEX` | `ORDER BY` 漏了 `APPROXIMATE`；或索引距离度量与查询函数不一致 | 跑 3.5 的 `EXPLAIN` | 加回 `APPROXIMATE`；保证索引 `DISTANCE=l2` 与 `l2_distance()` 一致 |
| `EXPLAIN` 里没有 `TEXT RETRIEVAL SCAN` | 全文索引没建 / 建在错误列 / 解析器不匹配 | `SHOW INDEX FROM <table>;` | 在**被检索的那一列**上建 `FULLTEXT INDEX`；中文 `PARSER ik`、英文 `PARSER beng` |
| 报「向量维度不匹配」 | 建表维度 ≠ embedding 模型维度 | 比对 `VECTOR(dim)` 与模型输出维度 | 改维度需**重建向量投影**（PowerContext 侧换 `profile_id` 后重建） |
| 向量结果明显不准 | 模型输出未归一化 | 检查归一化 | 单位化后再写入；PowerContext 要求 `normalization="unit"` |
| 混合检索命中重复 | 应用层把全文与向量结果简单拼接 | 检查合并逻辑 | 按 `entry_version_id` 去重；PowerContext 的 `matched_by` 是**通道标记**，同一条目可同时出现在两路 |
| 全文召回为 0 | 关键词被分词器切开 / 查询词太短 / 用了未建索引的列 | 用真实业务词单测 | 换更接近原文的词；确认列上确有全文索引 |
| 结果里出现已停用条目 | 状态过滤缺失 | 检查 head/active 过滤 | 只取当前 head + active 条目；停用/恢复靠状态位，不靠删行 |
| 引用与正文对不上 | 引用了旧 `entry_version_id` | 核对版本 | 引用必须用**当前有效版本**，正文逐字一致 |

### 5.2 PowerContext 侧排错表

| 现象 | 根因 | 修复 |
| --- | --- | --- |
| `search` 返回空 | 记忆只被 **采集**、未被加工/写入 | 采集 ≠ 记忆：调用 `/v1/memory/flush` 加工，或 `/v1/memory/remember` 显式写入。**空结果是合法结果**，不要当成报错重试 |
| `scope_id` 相关 4xx | Scope 未绑定 / 越权 | 先解析/绑定 Scope；确认当前主体对该 Scope 有 `scope.contribute` 权限 |
| `CapabilityNotSupportedError` | embedding profile 的 `distance`/`normalization` 不满足 | 只能用 `l2` + `unit`；不满足就换模型或先归一化 |
| `RevisionConflictError` | 并发修改同一记忆 | 带上 `expected_revision` 重试，或先拉最新 revision |
| 写操作超时、结果未知 | 请求可能已落库 | **先查状态再重试**（非幂等操作盲目重试会重复写） |
| 响应 `mode` 与请求 `mode` 不同 | 后端能力不足自动降级 | 以响应里的 `mode` 为准，并在答案里如实说明只用了单通道 |
| 注册来源报 `InvalidSourceDefinitionError` | `version` 为空/含首尾空白、`projections` 不是 tuple | 规范化后再注册；同名/同类型重复注册会抛 `SourceConflictError` |

### 5.3 最小验证清单（照做即可）

- [ ] `EXPLAIN` 同时出现 `TEXT RETRIEVAL SCAN` 与 `VECTOR INDEX`。
- [ ] 同一 query 连续执行两次，**返回顺序稳定**（排序键相同则加 `id` 作为 tiebreaker）。
- [ ] 写入 → 立即可查（向量索引若为异步构建，需确认索引已追平）。
- [ ] 更新正文后，旧版本仍可按 `entry_version_id` 取回，新版本指向当前 head。
- [ ] 停用条目不再出现在检索结果；恢复后重新出现。
- [ ] 同一身份（`entry_version_id`）在结果中**不重复**。
- [ ] 引用条目的正文与该 `entry_version_id` 逐字一致。

---

## 6. 参考资料

**OceanBase / seekdb 官方**

- seekdb 官方仓库（含 `CREATE TABLE ... FULLTEXT INDEX ... WITH PARSER ik` / `VECTOR INDEX ... LIB=vsag` / `l2_distance(...) APPROXIMATE` / `FORK DATABASE` 等写法）：https://github.com/oceanbase/seekdb
- 比赛分支（`2026-competition`，含全文索引压测脚本 `tools/benchmark/fts_large_bench_*.sql`）：https://github.com/oceanbase/seekdb/tree/2026-competition
- seekdb 官方文档站：https://docs.seekdb.ai/
- DeepWiki：https://deepwiki.com/oceanbase/seekdb

**PowerContext 官方**

- PowerContext 仓库：https://github.com/oceanbase/powercontext
- 比赛分支：https://github.com/oceanbase/powercontext/tree/2026-competition
- 关键实现文件（本文引用的表结构与索引 SQL 出处）：`src/powercontext/builtin/persistence/oceanbase/memory_index.py`、`src/powercontext/builtin/runtime/composition.py`、`src/powercontext/builtin/runtime/models.py`（`CaptureSource`）、`src/powercontext/sources/definitions.py`（`SourceDefinition`）、`src/powercontext/artifacts/models.py`（`MemoryCitation`）、`src/powercontext/http/_generated/operations.py`（HTTP 路由）
- 依赖：`pylibseekdb==1.3.0.post4`（嵌入式 seekdb 绑定，Linux/macOS）；Python 3.12

**OceanBase 语雀（大赛官方 wiki）**

- PowerContext 方向总览：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/gp9hi8ikdnef8ryc
- 赛题十一「seekdb 混合检索的单 SQL 候选查询」（`EXPLAIN` 需同时出现 `TEXT RETRIEVAL SCAN` 与 `VECTOR INDEX` 的判据出处）：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hqkh5u47mf5nv8r5
- 赛题三「AI 列」（`AI COLUMN` / `AI_EMBED` / `AI_COMPLETE` / `RETRY AI COLUMN` 语义出处）：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/qenx4sy5s09h2t07
- 赛题四「全文索引调优」（`ik` / `beng` 分词器与基准脚本出处）：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/za7cfo5cazcrihhq
- 赛题一「部署一个 seekdb」（本地实例启动与遥测 ID）：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/lz6ixow11mar233g
- 比赛仓库地址总表：https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/brxxufkegusa86hl

**本文档的核对状态**

- seekdb 的建表/检索 SQL：抄自 seekdb 仓库 `2026-competition` 分支 README 与 `tools/benchmark/fts_large_bench_setup.sql`。
- PowerContext 的表名、索引名、HTTP 路由、模型字段：抄自 `oceanbase/powercontext` 仓库源码（本地检出）。
- 端口 2881、root 用户等默认连接参数：见 `赛题四「全文索引调优」的本地复现命令。

OB-S:2hiQdUuquQuETr2I4saxAA
