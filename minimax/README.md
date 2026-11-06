# MiniMax × OceanBase — 规有所依：面向软件持续演进的 SDD 上下文管理系统

本目录是 2026 年 OceanBase 数据库大赛 MiniMax 赛题的参赛作品。

一句话说明：这是一个**工程上下文模块**，回答开发助手的一个问题——*给定一个开发任务，
哪些规格、哪些代码、哪些测试适用，以及这项任务已经做到哪一步了？*
规格与代码资料存放在 **seekdb**，任务状态存放在 **PowerContext**，
代码修改由 **MiniMax** 模型实际完成。

---

## 1. 一页技术说明

### 模块结构

```
minimax/
  sdd/                     上下文模块本体
    config.py              运行配置（全部来自环境变量，仓库内无凭据）
    store.py               seekdb 存储层：规格 / 代码符号 / 测试用例的建表、导入与全文检索
    context.py             上下文组装：两阶段检索 + 上下文包
    state.py               PowerContext 状态层：任务状态写入与读回
    minimax_client.py      MiniMax 开放平台客户端（OpenAI 兼容 chat/completions）
    cli.py                 命令行入口
  scripts/
    seed.py                把样例工程的规格、代码与测试导入 seekdb
    run_verification.py    端到端验证样例：检索 → 改前测试 → 改后测试 → 落库状态
  sample_project/          被修改的业务工程（真实可运行、带单元测试）
  docs/                    技术与验证文档
  evidence/                运行日志与证据文件
```

### 上下文是怎么选出来的（两阶段检索）

题目要求「根据任务选择相关资料」，而样例工程里**规格是中文、代码与测试是英文标识符**，
一句话任务无法直接命中代码索引。因此模块采用两阶段：

1. **第一阶段 · 找规格**：任务文本交给 **seekdb 自己的 IK 分词器**（`tokenize(task, 'ik')`）切词，
   再用 `MATCH(body) AGAINST (... IN BOOLEAN MODE)` 命中 `sdd_spec`。
   查询词由数据库产生，索引侧与查询侧的分词规则永远一致。
2. **第二阶段 · 找代码与测试**：规格正文里写明了它约束的函数名（如 `filter_by_country`、
   `filter_by_status`），模块从中提取标识符，用这些标识符去检索 `sdd_symbol` 与 `sdd_test`。

因此输出能定位到**适用的规格条目**、**需要修改的代码文件或符号**、**用于验证的测试**，
且每一条都带真实存在的文件路径。

### 三项技术的分工

| 技术 | 承担的作用 | 在流程中的位置 |
|---|---|---|
| **seekdb** | 存储工程资料并提供全文检索 | `sdd/store.py`：三张表 + 三个全文索引；`sdd/context.py`：两阶段检索的两次查询 |
| **PowerContext** | 保存任务状态并在后续运行中复用 | `sdd/state.py`：通过 Memory 应用写入/读回任务状态；`sdd/cli.py`：`plan` 写、`status` 读 |
| **MiniMax** | 参与本次任务的代码生成与修改 | `sdd/minimax_client.py` 调用 MiniMax 开放平台；本次提交的实际修改由 MiniMax 模型完成，记录见 `docs/minimax-development-record.md` |

---

## 2. 运行环境与依赖

| 项 | 值 |
|---|---|
| Python | 3.12 |
| 数据库 | seekdb v1.3.0.0（MySQL 协议兼容），本地实例端口 2881 起 |
| 必需 Python 包 | `pymysql`、`powercontext`（本仓库 `src/`）、`pytest` |
| 可选 | `MINIMAX_API_KEY`（仅 `ask` 子命令需要；`seed`/`plan`/`status` 不需要） |

> 仓库中不含任何真实凭据。所有连接信息与 API Key 都从环境变量读取。

## 3. 配置

全部通过环境变量设置，默认值见 `sdd/config.py`：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SDD_SEEKDB_HOST` | `127.0.0.1` | seekdb 主机 |
| `SDD_SEEKDB_PORT` | `2884` | seekdb 端口 |
| `SDD_SEEKDB_USER` | `root` | 用户名 |
| `SDD_SEEKDB_PASSWORD` | 空 | 密码 |
| `SDD_SEEKDB_DATABASE` | `sdd` | 存放工程资料的库名 |
| `SDD_STATE_PATH` | `minimax/state/sdd-state.db` | PowerContext 状态库（SQLite） |
| `SDD_SAMPLE_PROJECT` | `minimax/sample_project` | 被修改的业务工程 |
| `MINIMAX_API_KEY` | 无 | MiniMax 开放平台 Key，仅 `ask` 需要 |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/v1` | MiniMax 接口地址 |
| `MINIMAX_MODEL` | `MiniMax-Text-01` | 使用的模型名 |

## 4. 从零开始的完整步骤

```bash
# 0) 准备一个可用的 seekdb 实例（本仓库 work/seekdb-final2 等目录即实例）
export SDD_SEEKDB_HOST=127.0.0.1
export SDD_SEEKDB_PORT=2883

# 1) 把规格、代码与测试导入 seekdb（幂等，可重复执行）
python -m sdd.cli seed
# 期望输出：seekdb `sdd` 已导入 3 条规格、3 个代码符号、5 个测试用例。

# 2) 检索任务上下文（同时把状态写入 PowerContext）
python -m sdd.cli plan --task "为订单筛选增加按国家过滤的能力"

# 3) 另起一个进程读回状态，验证「重启后读取并使用」
python -m sdd.cli status --scope sdd-task

# 4) （可选）让 MiniMax 基于同一份上下文给出修改建议
export MINIMAX_API_KEY=<你的 key>
python -m sdd.cli ask --task "为订单筛选增加按国家过滤的能力"
```

> Windows 上如果 `python -m sdd.cli` 不便，可直接运行 `python sdd/cli.py <子命令>`，
> 二者等价。

## 5. 调用入口与输入输出

**入口**：命令行 `python -m sdd.cli {seed|plan|status|ask}`。

| 子命令 | 输入 | 输出 |
|---|---|---|
| `seed` | 无 | 导入统计行 |
| `plan` | `--task <任务描述>` | Markdown 上下文包（规格 / 符号 / 测试 / 状态），`--json` 输出 JSON |
| `status` | `--scope <作用域>` | 已保存的任务状态（JSON）；无记录时退出码 1 |
| `ask` | `--task <任务描述>` | 上下文包 + MiniMax 的修改建议，并把建议写入状态 |

**上下文包内容**（`plan` 的 Markdown 输出）：

```
- 任务：…
- 作用域：…
- 检索词（由数据库 IK 分词器切分）：…
- 代码检索词（来自规格正文中的标识符）：…

## 适用的规格条目          ← [SPEC-XXX] 标题（来源 <文件>，相关度 <分数>）
## 需要修改的代码文件或符号  ← 函数名（<文件>，相关度 <分数>）
## 用于验证功能及兼容性的测试 ← 用例名（<文件>，相关度 <分数>）
## 已完成事项 / 待办事项 / 已有验证结果
```

## 6. 验证样例

见 `docs/verification-sample.md`（含初始数据、操作步骤、预期结果与重置方法）。
端到端脚本：`python scripts/run_verification.py`。

## 7. 测试与代码修改证据

| 证据 | 文件 |
|---|---|
| 代码差异（MiniMax 产出） | `evidence/code-change.patch` |
| 修改前 / 修改后源码快照 | `evidence/filters.before.py`、`evidence/filters.after.py`、`evidence/__init__.before.py`、`evidence/__init__.after.py` |
| 修改前测试失败日志 | `evidence/tests-before.log` |
| 修改后测试通过日志 | `evidence/tests-after.log` |
| 上下文检索输出 | `evidence/context-output.md` |
| seekdb 查询记录 | `evidence/seekdb-queries.md` |
| PowerContext 状态读回记录 | `evidence/state-reuse.md` |
| MiniMax 开发记录 | `docs/minimax-development-record.md` |

## 8. 已知限制

1. `ask` 子命令需要真实的 `MINIMAX_API_KEY`；未设置时它**不静默失败**，而是打印提示并以退出码 2 结束。
   本次提交的代码修改由 MiniMax 模型实际完成，记录与差异一一对应，见 `docs/minimax-development-record.md`。
2. 样例工程的规格为中文、代码为英文标识符，因此检索是两阶段的。若工程改为同一语言，
   第一阶段的命中即可覆盖第二阶段，多余的一步不会引入错误结果，只是多一次查询。
3. `plan` 每调用一次会向 PowerContext 追加一条状态记录（Memory 是追加语义），
   `status` 返回最近命中的一条。若需要干净状态，删除 `SDD_STATE_PATH` 指向的文件即可重置。
4. 检索使用 `MATCH ... AGAINST (... IN BOOLEAN MODE)`，对中文依赖 IK 分词器；
   实例未启用 IK 时需在 `sdd/store.py` 的建表语句中去掉 `WITH PARSER ik`。
