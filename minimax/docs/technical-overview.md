# 一页技术说明：SDD 上下文管理系统

> 作品：MiniMax × OceanBase 生态赛题「规有所依——面向软件持续演进的 SDD 上下文管理系统」

## 1. 问题

AI 开发助手改代码时，需要知道**当前应遵守哪些要求**、**应该修改哪些代码**、**怎么验证**。
资料分散、规格变化、任务中断，会导致遗漏约束、使用过时信息或重复劳动。

## 2. 解法

一个上下文模块，输入一个开发任务，输出一份可直接交给开发助手的上下文包，
并把任务进展持久化，以便任务中断后继续。

```
开发任务 ──► ① seekdb 全文检索 ──► 适用的规格条目
                （IK 分词 + MATCH/AGAINST）
                        │
                        ▼
              ② 从规格正文提取标识符
                        │
                        ▼
              ③ seekdb 全文检索 ──► 需要修改的代码符号 / 用于验证的测试
                        │
                        ▼
              ④ PowerContext 存取 ──► 已完成 / 待办 / 已有验证结果
                        │
                        ▼
              ⑤ MiniMax 生成修改建议 ──► 代码修改
```

## 3. 模块结构

| 文件 | 职责 |
|---|---|
| `sdd/config.py` | 环境变量配置；不含任何凭据 |
| `sdd/store.py` | seekdb 存储层：三张表 + 三个全文索引；建表幂等、旧库自动迁移 |
| `sdd/context.py` | 两阶段检索与上下文组装 |
| `sdd/state.py` | PowerContext 状态层：写入与读回任务状态 |
| `sdd/minimax_client.py` | MiniMax 开放平台客户端（OpenAI 兼容协议） |
| `sdd/cli.py` | 命令行入口 |
| `scripts/seed.py` | 把样例工程导入 seekdb |
| `scripts/run_verification.py` | 端到端验证样例 |

## 4. 上下文选择方式（关键设计）

样例工程里**规格是中文、代码与测试是英文标识符**，所以单次查询无法同时命中两者。
模块采用两阶段检索，并且**查询词由数据库自己产生**：

1. `tokenize(task, 'ik')` —— 用 seekdb 内置的 IK 分词器切任务文本，
   与全文索引建立时用的是同一个分词器，规则永远一致；
2. 用切出的词检索 `sdd_spec`，得到适用的规格条目；
3. 从这些规格的正文里提取代码标识符（`filter_by_country` 等），
   用它们检索 `sdd_symbol` 与 `sdd_test`，定位要改的代码与要跑的测试。

这样做的收益：模块不猜词、不硬编码，改规格就会改检索结果。

**可核对性**：输出中每一条规格 / 符号 / 测试都带**真实存在的文件路径**，
评审可直接按路径打开比对。

## 5. 三项技术的分工

| 技术 | 必须承担的作用 | 本作品中的落点 |
|---|---|---|
| **seekdb** | 存储工程资料或索引，实际查询结果用于构造任务上下文 | `sdd/store.py` 建三张表并建 IK 全文索引；`sdd/context.py` 每次 `plan` 都发两次真实的 `MATCH/AGAINST` 查询，查询语句与结果见 `evidence/seekdb-queries.md` |
| **PowerContext** | 保存任务进展或验证结果，并在后续运行中读取、使用 | `sdd/state.py` 通过 Memory 应用写入 / 读回；`plan` 写、`status` 读，跨进程读回记录见 `evidence/state-reuse.md` |
| **MiniMax** | 参与本次任务的代码生成或修改 | 本次代码修改由 MiniMax 模型实际完成，完整记录见 `docs/minimax-development-record.md`，对应差异见 `evidence/code-change.patch` |

## 6. 六项必做项的自查

| 验收项 | 自查结果 | 证据 |
|---|---|---|
| 能够运行 | 4 条命令可从零跑通，无需未交付的本地文件 | `README.md` §4；`evidence/*.log` |
| MiniMax 实际参与 | MiniMax 模型完成 `filter_by_country` 的设计与实现，记录含任务、上下文、差异、验证 | `docs/minimax-development-record.md`；`evidence/code-change.patch` |
| 上下文正确 | 输出含规格 / 符号 / 测试三类来源，路径真实存在；改规格并重新导入后输出随之变化 | `evidence/context-output.md`；`evidence/spec-update-check.md` |
| 数据库实际参与 | 规格、符号、测试均存于 seekdb，检索结果直接构成上下文 | `evidence/seekdb-queries.md` |
| 状态能够复用 | 空状态起写入 → 另一进程读回并使用 | `evidence/state-reuse.md` |
| 代码修改有效 | 改前目标功能测试失败（2 failed, 3 passed），改后全通过（5 passed）；回归测试始终通过 | `evidence/tests-before.log`、`evidence/tests-after.log` |

## 7. 扩展点

- **规格变更处理**：`seed` 幂等，重新导入即以新规格为准。
- **跨会话恢复**：`status` 从 PowerContext 读回，含 `done` / `todo` / `verification`。
- **成本与时延**：规格命中后只对规格正文出现的标识符检索代码，
  避免用整句任务去扫三个索引；`code_query` 命中为空时自动退化。
