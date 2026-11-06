# NOTES —— 设计说明

> 作品：《雾隐镇 · 夜班档案室》（Dify Chatflow × seekdb）
> 本文件解释**为什么这么做**；**怎么跑**看 `README.md`；**跑出什么**看 `验证样例.md`。

---

## 1. 创意从哪来

题目是"Just for Fun"。我想要的不是"给文档问答"或"给记账本加个 AI"，而是那种**让人愿意多问两句**的东西。

于是定了一个设定：**雾隐镇，海边小镇，海雾不散**。你新来当夜班档案员，办公室里那盏旧灯会说话，它叫**阿灯**。
镇上最近出了四桩怪事，你用大白话问，阿灯去"镇档案室"（也就是数据库）里翻卷宗、找物证、盘镇民。

三个让它"好玩"的设计：

1. **阿灯有记性，而且记性写在数据库里。** 不是靠模型的上下文，而是靠 `player_progress` 表。
   你换了个会话、关了页面、第二天再来，它第一句就会说"你上次已经排除了丁叔，铜屑那条线你还没查清"。
   ——这是"记忆要落库"这件事最好玩的表现形式。
2. **阿灯不瞎编。** 提示词里写死了：只能引用卷宗里翻出来的东西，查不到就说查不到。
   于是"查不到"也是一种玩法：你问"外星人的事"，阿灯会说"卷宗里没有这一条"。
3. **引用即归档。** 阿灯在回答里写 `【EV-0301】`、`【SUS-05】`，
   系统自动把这些编号写回数据库。于是**你跟阿灯的聊天记录，天然就是一份可检索的案件笔记**。

### 为什么这个题目能同时满足评分维度

| 维度 | 本作品的落点 |
|------|-------------|
| 创意 | 把"检索增强 + 持久化记忆"包装成一个有角色、有场景、有悬疑推进的小游戏 |
| 趣味与互动 | 玩家输入直接决定查到哪条卷宗；已排除的嫌疑人会真的被排除掉；可以结案 |
| 体验与完成度 | 有开场、有失败反馈（查不到）、有正反馈（结案陈词）、有跨会话记忆、有可回放的档案记录 |
| 技术结合 | 读：卷宗/物证/镇民/镇志的混合检索；写：进度、问答日志、结案状态。**全部真的落在 seekdb 上** |
| 工程质量 | 自定义工具服务带 `sql_trace`、有降级策略（全文→LIKE）、有 19 项自动冒烟测试、离线 mock 模式 |

---

## 2. 数据流：Dify 与 seekdb 怎么分工

```
玩家在 Dify 网页里提问
        │
        ▼
┌─────────────────────────── Dify（编排 / 理解 / 叙事）────────────────────────────┐
│                                                                                │
│  [开始]  侦探代号 player_id ／ 接手案件 case_id                                  │
│     │                                                                          │
│     ▼                                                                          │
│  [解析提问] Code        判定 intent=close/ask，抽出引号里的显式关键词               │
│     │                                                                          │
│     ▼                                                                          │
│  [检索卷宗·物证·镇志] Tool ──┐                                                 │
│     │                        │  HTTP POST /search_archive                       │
│     ▼                        │                                                 │
│  [读取调查进度] Tool ───────┤                                                 │
│     │                        │                                                 │
│     ▼                        │                                                 │
│  [判定结案条件] Code         │  拼提示词 + 算 can_close                          │
│     │                        │                                                 │
│     ▼                        │                                                 │
│  [阿灯·推理] LLM             │  只依据卷宗作答，标注【EV-xxxx】【SUS-xx】           │
│     │                        │                                                 │
│     ▼                        │                                                 │
│  [抽取引用编号] Code          │  从回答里抽出编号，决定写回什么                      │
│     │                        │                                                 │
│     ▼                        │                                                 │
│  [可以结案吗] If/Else ───────┤                                                 │
│     ├── true  → [写回·结案] Tool ──→ [组装结案报告] Code → [回答] Answer         │
│     └── false → [写回·线索笔记] Tool → [组装调查简报] Code → [回答] Answer        │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
                                          │  MySQL 协议（pymysql，2881）
                                          ▼
┌────────────────────────── 自定义工具服务（service/app.py，FastAPI）─────────────────┐
│                                                                                   │
│  POST /search_archive      POST /get_player_progress      POST /record_progress    │
│      │                          │                              │                   │
│      ▼                          ▼                              ▼                   │
│  seekdb: case_files / evidence / suspects / town_lore                              │
│  seekdb: player_progress                                          （UPSERT + INSERT   │
│  seekdb: investigation_log                                        + UPDATE case_files）│
│                                                                                   │
│  每次响应都附 sql_trace：真实执行的 SQL + 返回行数 + 耗时                            │
└────────────────────────────────────────────────────────────────────────────────┘
```

**一句话**：Dify 负责"听懂、编排、讲得像人话"，seekdb 负责"存着、查得到、改得动"。
Dify 本身**不碰数据库**，它只通过 OpenAPI 自定义工具去调一个 Python 服务。

---

## 3. 为什么用"自定义工具 + HTTP"而不是别的接法

赛题允许三种接法：HTTP Request 节点、自定义工具、自定义插件。我选了**自定义工具（OpenAPI）**：

| 方案 | 优点 | 为什么没用 |
|------|------|-----------|
| **自定义工具（OpenAPI）** ✅ | 工具参数自动出现在 LLM 的工具列表里；Dify 自动做参数校验；评审能在 Dify UI 里直接看到 3 个工具的名字和参数说明；`operationId` 就是工具名，DSL 里一一对应 | — |
| HTTP Request 节点 | 零额外服务 | 参数要靠代码节点拼 JSON；Dify 侧看不到"工具"的语义；评审要读 URL 和 body 才知道发生了什么 |
| Dify 插件（.difypkg） | 能进 Marketplace | 要打成插件包、要有 manifest、要处理凭据同步，评审复现成本最高；而且它并不能让 seekdb 更容易被核对 |

**唯一的代价**：Dify 的 DSL 不携带工作区内部 UUID，导入后工具节点需要**手动重新绑定一次**（README `6.7 / 验证样例 `5）。
这是 Dify 的机制限制，我在 README 里写清楚了具体点法。

---

## 4. 为什么用"全文 + 标量"混合检索，而不是向量检索

seekdb 最亮眼的能力是"向量 + 全文 + 标量，一条 SQL 搞定"。我**没有**用向量，理由是**可复现性**：

- 向量检索必须依赖一个 **Embedding 服务**（OpenAI / DashScope / 本地 bge-m3 …）。
  评审机器上不一定有；就算有，**换模型就要重建向量索引**，样例的"预期输出"会漂移。
- 基础验收里"过程可以复现"是硬指标。多一个外部模型依赖，就多一处不确定性。

所以我选择：

| 能力 | 用了吗 | 怎么用的 |
|------|--------|---------|
| **标量/结构化条件** | ✅ | 一条 SQL 里同时过滤 `case_id`、`location`、`status`，再按 `severity` / `weight` 排序 |
| **全文检索** | ✅（可降级） | `MATCH(keywords, summary) AGAINST(...)`，服务启动时自动探测/补建 FULLTEXT 索引；**建不起来就自动退回 LIKE**，并在 `strategy` 字段里明说 |
| **向量检索** | ❌（刻意） | 见上。`NOTES` 里写明理由与"要加的话怎么加" |

### 中文分词是怎么解决的

MySQL/OceanBase 默认分词器对中文不友好（按空白切）。我的做法是**语料反查**：

1. 先从 seekdb 把 4 张表的语料（卷宗标题+关键词+摘要、物证名+关键词+描述、镇民、镇志）读出来；
2. 把玩家的话按标点切成中文片段，做 2-gram / 3-gram / 4-gram；
3. **只保留在语料里真实出现过的字串**；
4. 再叠加从 `case_files.location`、`evidence.location`、`suspects.name/alias` 取到的地点与人名词典。

于是"雾钟是谁弄坏的"会变成 `["雾钟是谁弄坏", "雾钟是", "是谁弄", "谁弄坏", ...]`，
而只有**数据库里真的有的**那些（"雾钟""钟楼""铜锤"…）会被留下。
"外星人"这种库里没有的词，一个都留不下 —— 所以阿灯会说"卷宗里没有这一条"。

**词典本身来自数据库**，这是这个设计的要点：不是硬编码词表，是现场从库里反查。

---

## 5. 工作流节点逐个说明（14 节点 / 13 连线）

| # | 节点 | 类型 | 作用 | 与 seekdb 的关系 |
|---|------|------|------|----------------|
| 1 | 开始 | start | 收集 `player_id`（侦探代号）、`case_id`（接手卷宗） | `player_id` 是记忆的关联键 |
| 2 | 解析提问 | code | 判定 `intent=close/ask`，抽出引号关键词 / 英文编号 | 无（纯文本处理） |
| 3 | 检索卷宗·物证·镇志 | **tool** | 调 `search_archive` | **读** 4 张表，混合检索 |
| 4 | 读取调查进度 | **tool** | 调 `get_player_progress` | **读** `player_progress` + `investigation_log` |
| 5 | 判定结案条件 | code | 拼提示词；算 `can_close`（意图=结案 ∧ 关键物证≥2 ∧ 有未排除镇民） | 用到了第 4 步读到的进度 |
| 6 | 阿灯·推理 | llm | 以阿灯口吻推理，只用给定卷宗，标注引用编号 | 提示词里的内容全部来自第 3、4 步 |
| 7 | 抽取引用编号 | code | 从回答里抽 `【EV-xxxx】`/`【SUS-xx】`，抽不到就退回第 5 步的默认列表 | 无 |
| 8 | 可以结案吗 | if-else | 按 `can_close` 分流 | 无 |
| 9 | 写回·结案 | **tool** | `action=close` | **写** `player_progress`+ `investigation_log`+`UPDATE case_files.status='closed'` |
| 10 | 组装结案报告 | code | 把回答 + 写回结果合成最终回复 | 读第 9 步返回的 `written` |
| 11 | 回答·结案 | answer | 输出 | — |
| 12 | 写回·线索笔记 | **tool** | `action=note` | **写** `player_progress`+ `investigation_log` |
| 13 | 组装调查简报 | code | 同上，但文案是"继续查" | 读第 12 步返回的 `written` |
| 14 | 回答·继续调查 | answer | 输出 | — |

**为什么两个 Answer 节点而不是一个**：
Dify 当前版本已经不再提供「变量聚合器」节点给普通用户，两条分支的产物没法合并成一个变量。
最稳的做法是**每条分支各自以 Answer 节点收尾**——这也是 Dify 官方 conditional 分支模板的惯用写法。

**为什么最终回复里要写"已写入 seekdb：player_progress 1 行、investigation_log 1 行"**：
让"技术结合"变成**玩家肉眼可见的东西**，而不是只写在文档里。

---

## 6. 数据库设计

### 6.1 六张表

| 表 | 角色 | 读 | 写 |
|----|------|----|----|
| `case_files` | 卷宗：标题、类型、地点、时间、严重度、关键词、摘要、状态 | ✅ 检索 | ✅ 结案时改 `status` |
| `evidence` | 物证：所属案件、名称、描述、地点、发现时间、关键词、关键度(1-3) | ✅ 检索 | ❌（静态设定） |
| `suspects` | 镇民：姓名、绰号、职业、动机、常去地点、不在场证明 | ✅ 检索 | ❌（静态设定） |
| `town_lore` | 镇志常识：话题、内容、关键词 | ✅ 检索 | ❌（静态设定） |
| `player_progress` | **跨会话记忆**：已掌握物证、已排除镇民、笔记、轮次 | ✅ | ✅ UPSERT |
| `investigation_log` | **问答日志**：每轮提问与回答、关联物证/镇民 | ✅ | ✅ INSERT |

### 6.2 几个设计取舍

- **"已排除镇民"和"已掌握物证"存 JSON 数组字符串**，而不是关联表。
  理由：它们永远是"往集合里加东西"，不需要 JOIN、不需要按物证查玩家。
  合并逻辑放在服务端（读旧值 → 集合并 → UPSERT），读多写少，够用且直观。
  如果要按"谁掌握了 EV-0301"反查，就得拆成 `player_evidence` 关联表——那是另一种设计，这里没做。
- **`player_progress` 主键是 `(player_id, case_id)`**：同一个侦探可以同时查四个案子，进度互不干扰。
- **`investigation_log` 有 `action` 字段**（note / close），所以事后能筛出"哪一轮结的案"。
- **`evidence.weight` 是结案条件的核心**：关键度 ≥2 的才算"关键物证"。
  这是给玩家一个可感知的进度条：问到 2 条关键物证，才够格说"结案"。
- **`case_files.status='closed'` 的卷宗会被检索过滤掉**（`status <> 'closed'`），
  所以结案之后这个案子不会再出现在别人的检索结果里——形成"世界在变化"的感觉。

### 6.3 初始记忆状态（预置的跨会话演示）

`init_data.sql` 预置了 `detective_001` 在 `CASE-2403` 上的一轮旧调查：

- 已掌握物证：`["EV-0302"]`（钟楼下的铜屑）
- 已排除镇民：`["SUS-08"]`（老丁）
- 轮次：2
- 笔记："上一夜已排除丁叔……铜屑这条线还没查清是谁留下的。"

外加 2 条 `investigation_log` 历史记录。
**所以评审第一次打开应用就能看到"跨会话记忆"的效果，不用自己先造历史。**

---

## 7. 可核对点清单（AI 评审可以逐条查）

| # | 核对方式 | 在哪看 |
|---|---------|--------|
| 1 | 工具服务进程 | `python app.py` 的日志；端口 8100 |
| 2 | 工具服务确实连的是 seekdb | `curl /health` → `"seekdb": {"ok": true, "version": "...", "database": "wuyin_archive"}` |
| 3 | Dify 的工具节点真的发 HTTP 了 | Dify 节点执行记录 → 工具节点"输入/输出" |
| 4 | 执行的 SQL 是什么 | 工具节点输出 JSON 里的 `sql_trace` 数组 |
| 5 | 检索真的过滤了 | `sql_trace` 里的 `WHERE (case_id = %s OR %s = '') AND ... status <> 'closed'` |
| 6 | 写回真的落库 | `SELECT * FROM player_progress WHERE player_id='detective_001'` |
| 7 | 问答日志真的落库 | `SELECT * FROM investigation_log ORDER BY log_id DESC` |
| 8 | 结案真的改了卷宗 | `SELECT case_id,status,closed_at,closed_by FROM case_files` |
| 9 | 跨会话记忆 | 新会话里 `get_player_progress` 返回的 `eliminated_suspects` 含 `SUS-08` |
| 10 | 全文索引是否真的用上了 | `/health` 的 `fulltext_enabled`；每次检索的 `strategy` 字段 |
| 11 | 降级是否有效 | 把 FULLTEXT 索引删掉后重启服务，`strategy` 变 `like`，功能不受影响 |
| 12 | 端到端可复现 | `python smoke_test.py`（19 项断言，含直连 seekdb 复核） |

---

## 8. 来源与改动声明

| 内容 | 来源 | 改动 |
|------|------|------|
| Dify DSL 的**字段格式** | Dify 官方仓库公开示例：`api/tests/fixtures/workflow/http_request_with_json_tool_workflow.yml`、`basic_chatflow.yml`、`conditional_hello_branching_workflow.yml`、`conditional_parallel_code_execution_workflow.yml`、`scripts/stress-test/setup/dsl/workflow_llm.yml` | **只参考了字段结构**（`version/kind/app/workflow.graph/nodes/edges` 的键名与形状）；所有节点、连线、提示词、Python 逻辑均为原创 |
| 自定义工具的 OpenAPI 解析规则 | Dify 源码 `api/core/tools/utils/parser.py`（`ApiBasedToolSchemaParser`） | 仅据此保证 `custom_tool.yml` 能被 Dify 正确解析（`servers[0].url`、`operationId`、`requestBody.schema.properties`） |
| 模型插件标识 | Dify 仓库 `scripts/stress-test/setup/dsl/workflow_llm.yml` 里公开的 `langgenius/openai:0.2.5@...` | 原样引用；评审可改成自己的模型 |
| 雾隐镇的镇民、案子、物证、镇志、对话 | **本作品原创**（虚构） | — |
| `service/` 下全部代码与 SQL | **本作品原创** | — |
| 第三方源码 | **未复制任何第三方源码** | 仅依赖 fastapi / uvicorn / pymysql 三个公开包 |
| 截图/录屏 | **本机环境无 Docker，未能真机截图** | 详见 `验证样例.md` `8；给出了可复现步骤与可自动重跑的证据脚本 |

---

## 9. 已知不足，以及"如果还有时间"会怎么做

1. **检索是全表 + 内存打分**，数据量大了要改成分页 + 索引。
2. **没有向量检索**（见 `4）。要加的话：在 `evidence` 表加 `VECTOR(768)` 列 + `VECTOR INDEX`，
   用一个 Embedding 服务把 `detail` 向量化后入库，检索时把 `l2_distance` 加进 `ORDER BY`。
   seekdb 支持"向量 + 全文 + 标量"同一条 SQL，但那会让样例依赖外部 Embedding 服务。
3. **"已排除镇民"用 JSON 字符串存**，反查不方便（见 `6.2）。
4. **工具需要手动重新绑定**（Dify 机制限制）。
5. **结案条件是硬编码阈值**（关键物证 ≥2）。
6. **没有多用户/权限**。谁的 `player_id` 谁就能看谁的进度——这是刻意的（作品是单机体验），
   但如果要放到公网，`player_progress` 应该加上鉴权。

---

## 附：Windows 上 seekdb 建全文索引会崩（平台问题，已绕开并留证）

- 现象：`ALTER TABLE ... ADD FULLTEXT KEY ...` 在 seekdb 1.3.0 + Windows 上会让服务端进程崩溃，
  客户端表现为连接被断开（本机复现两次：2026-11-07 01:0x，实例 `seekdb-stepfun` 端口 2883 退出）。
- 这与本作品代码无关；作品本来就有 LIKE 兜底，只是「兜底」必须在建索引**之前**就可选。
- 现在有显式开关：`DIFY_FULLTEXT=auto|on|off`，以及 `smoke_test.py --init --no-fulltext`。
  `off` 时初始化完全跳过全文索引语句，服务端也一次都不创建，检索全程走 LIKE。
- 本机证据（`DIFY_FULLTEXT=off`，真实 seekdb 2883）：
  - 初始化：20/20 条语句成功；
  - 端到端冒烟：19/19 通过（真实 SELECT / 跨会话进度 / 写回 / 结案 UPSERT / 直连复核）；
  - 离线 mock：19/19 通过。
