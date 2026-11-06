# 验证样例

> 评审可从干净环境开始，按本文件逐步执行。
> 所有命令的预期输出都是**实测**得到的，不是手写的。

## 0. 前置

- seekdb 实例可用（本机为 `127.0.0.1:2883`）。
- Python 3.12，依赖 `pymysql`、`pytest`，以及本仓库的 `src/`（PowerContext）。
- 环境变量：

```bash
export SDD_SEEKDB_HOST=127.0.0.1
export SDD_SEEKDB_PORT=2883
export PYTHONPATH=<repo>/src:<repo>/minimax
```

## 1. 初始数据

样例工程 `sample_project/` 即初始数据，**随作品一起提交**，无需另行准备：

| 类别 | 内容 |
|---|---|
| 规格 | `specs/order_filtering.md`（SPEC-ORDER-FILTERING）、`specs/currency_rounding.md`（SPEC-CURRENCY-ROUNDING）、`specs/change_request.md`（SPEC-CHANGE-REQUEST） |
| 代码 | `src/orders/filters.py`（4 个函数 + 1 个 dataclass）、`src/orders/__init__.py` |
| 测试 | `tests/test_filters.py`（5 个用例） |

数据库侧初始为空，由第 2 步导入。

## 2. 操作步骤与预期结果

### 步骤 1 · 导入工程资料

```bash
python -m sdd.cli seed
```

**预期输出**：

```
seekdb `sdd` 已导入 3 条规格、3 个代码符号、5 个测试用例。
```

**核对数据库**（可选）：

```sql
-- 在 seekdb 中执行
USE sdd;
SELECT COUNT(*) FROM sdd_spec;    -- 3
SELECT COUNT(*) FROM sdd_symbol;  -- 3
SELECT COUNT(*) FROM sdd_test;    -- 5
SHOW INDEX FROM sdd_spec;         -- 含 idx_sdd_spec_body (FULLTEXT)
```

### 步骤 2 · 检索任务上下文

```bash
python -m sdd.cli plan --task "为订单筛选增加按国家过滤的能力"
```

**预期输出**（节选，实际全文见 `evidence/context-output.md`）：

```
## 适用的规格条目
- [SPEC-ORDER-FILTERING] 订单筛选接口约定  （来源 sample_project/specs/order_filtering.md，相关度 1.0175）
- [SPEC-CURRENCY-ROUNDING] 币种汇总与精度  （来源 sample_project/specs/currency_rounding.md，相关度 0.4588）
- [SPEC-CHANGE-REQUEST] 变更请求流程  （来源 sample_project/specs/change_request.md，相关度 0.1031）

## 需要修改的代码文件或符号
- filter_by_status  （src/orders/filters.py，相关度 1.7293）
- filter_by_amount  （src/orders/filters.py，相关度 1.1595）
- sum_by_currency  （src/orders/filters.py，相关度 0.6399）

## 用于验证功能及兼容性的测试
- test_filter_by_status_keeps_exact_matches  （tests/test_filters.py，相关度 1.4591）
- test_filter_by_amount_uses_a_lower_bound  （tests/test_filters.py，相关度 1.4591）
- test_sum_by_currency_reports_cents_and_uses_other  （tests/test_filters.py，相关度 1.1321）
- test_filter_by_country_ignores_case_and_padding  （tests/test_filters.py，相关度 0.6807）
- test_filter_by_country_does_not_mutate_the_input  （tests/test_filters.py，相关度 0.6666）
```

**必须核对的三件事**：

1. 三个「来源」路径真实存在，且指向 `sample_project/` 下实际文件；
2. `test_filter_by_country_*` 两个**目标功能测试**出现在「用于验证」的列表里；
3. 检索词由数据库 IK 分词器切出，代码检索词来自规格正文中的标识符。

### 步骤 3 · 验证「规格更新后输出必须变化」

题目要求：更新规格并重新导入后，模块必须使用更新后的内容，不能始终返回固定答案。

```bash
# 3.1 在规格里加入一条新规则
#     在 sample_project/specs/order_filtering.md 的「- 未知国家返回空列表；」后追加一行：
#     - 国家代码按 ISO 3166-1 alpha-2 规范化，例如 ` de ` 视为 `DE`；

python -m sdd.cli seed
python -m sdd.cli plan --task "为订单筛选增加按国家过滤的能力"
```

**预期变化**（实测记录见 `evidence/spec-update-check.md`）：

- 「代码检索词」一栏由 `… country filter_by_status …` 变为 `… country alpha filter_by_status …`
  （新规格里的 `alpha` 被提取为标识符）；
- SPEC-ORDER-FILTERING 的相关度由 `1.0175` 变为 `1.0165`（正文变长、词项分布改变）。

即：**输出确实随规格内容变化**，不是固定答案。

**重置**：把该行删掉，重新执行 `python -m sdd.cli seed` 即可恢复。

### 步骤 4 · 验证「状态能够复用」

```bash
# 4.1 清空状态，从空状态开始
rm -f "$SDD_STATE_PATH"          # Windows: Remove-Item $env:SDD_STATE_PATH

# 4.2 检索一次，这一步会把状态写入 PowerContext
python -m sdd.cli plan --task "为订单筛选增加按国家过滤的能力"

# 4.3 另起一个进程（模拟模块重启）读回
python -m sdd.cli status --scope sdd-task
```

**预期输出**（步骤 4.3，节选）：

```json
{
  "task": "为订单筛选增加按国家过滤的能力",
  "scope": "sdd-task",
  "specs": ["SPEC-ORDER-FILTERING", "SPEC-CURRENCY-ROUNDING", "SPEC-CHANGE-REQUEST"],
  "symbols": ["src/orders/filters.py:filter_by_status", "…"],
  "tests": ["tests/test_filters.py:test_filter_by_status_keeps_exact_matches", "…"],
  "done": [],
  "todo": ["按规格实现修改", "运行目标功能测试", "运行回归测试"],
  "verification": []
}
```

即：**状态被跨进程读回并可继续使用**。完整记录见 `evidence/state-reuse.md`。

### 步骤 5 · 验证「代码修改有效」

**修改前**（原始工程，`filter_by_country` 未实现）：

```bash
cd sample_project && python -m pytest tests -q
```

**预期输出**：

```
...FF                                                                    [100%]
FAILED tests	est_filters.py::test_filter_by_country_ignores_case_and_padding
FAILED tests	est_filters.py::test_filter_by_country_does_not_mutate_the_input
E       ImportError: cannot import name 'filter_by_country' from 'orders.filters'
2 failed, 3 passed in 0.79s
```

**修改后**（本次提交的状态）：

```bash
cd sample_project && python -m pytest tests -q
```

**预期输出**：

```
.....                                                                    [100%]
5 passed in 0.15s
```

关键点：

- 目标功能测试**因目标行为未实现而失败**（`ImportError`，不是环境错误、不是缺依赖）；
- 修改后目标测试与 3 个回归测试**同时通过**；
- 测试文件 `tests/test_filters.py` **在修改前后完全一致**（见 `evidence/tests-before.log` 与
  `evidence/tests-after.log` 的对比，以及 `evidence/code-change.patch` 只含两个源文件）。

## 3. 重置方法

| 要重置的东西 | 怎么做 |
|---|---|
| 数据库中的工程资料 | `python -m sdd.cli seed`（幂等覆盖；或 `DROP DATABASE sdd` 后重新 seed） |
| PowerContext 任务状态 | 删除 `SDD_STATE_PATH` 指向的 SQLite 文件 |
| 样例工程的代码修改 | `git apply --reverse evidence/code-change.patch`（在 `sample_project/` 下执行） |
| 规格改动 | 删掉新增的那一行后重新 `seed` |

## 4. 一次跑完全部步骤

```bash
python scripts/run_verification.py
```

该脚本执行「检索上下文 → 改前跑目标测试 → 改前跑全量测试 → 把状态写入 PowerContext → 输出 JSON 报告」，
报告写到 `sample_project/../verification-report.json`。
