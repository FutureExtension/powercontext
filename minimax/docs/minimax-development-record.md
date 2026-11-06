# MiniMax 开发记录

> 赛题要求：「使用 MiniMax 参与本次任务的代码生成或修改」，且
> 「开发记录包含本次任务、提供的上下文和代码修改过程，并与提交的代码差异对应」。
>
> 本文件记录的就是本次任务中**由 MiniMax 模型实际完成**的代码修改，
> 配套差异见 `evidence/code-change.patch`，两者逐行对应。

---

## 1. 本次任务

在业务工程 `sample_project` 中完成一项局部修改：

> **为订单筛选增加按国家过滤的能力 `filter_by_country`。**

选择该修改的理由（见 `sample_project/specs/change_request.md` 的「变更请求流程」）：

1. 该工程**能够运行且具有测试**（`pytest` 可直接跑，5 个用例）；
2. 目标行为在修改前**尚未实现**，因此存在一个**修改前必然失败、修改后必然通过**的目标功能测试；
3. 修改范围局部，不牵动其他行为，3 个既有回归测试可作为兼容性基线。

## 2. MiniMax 得到的上下文

上下文由本模块 `sdd/` 检索得到，检索过程与结果见 `evidence/context-output.md` 与
`evidence/seekdb-queries.md`。MiniMax 实际收到的内容如下。

### 2.1 适用的规格条目

**[SPEC-ORDER-FILTERING] 订单筛选接口约定**
（来源 `sample_project/specs/order_filtering.md`，检索相关度 1.0175）

> 所有筛选函数遵循同一组约定：
>
> 1. 输入为 `Iterable[Order]`，输出为**新的** `list[Order]`，**不得修改**入参集合或其中的元素；
> 2. 返回顺序与输入顺序一致；
> 3. 文本比较类筛选必须**忽略大小写与首尾空白**；
> 4. 金额类筛选以**分**为单位的整数比较；
> 5. 不满足任何条件的输入返回空列表，而不是 `None`。
>
> ## 按国家筛选
>
> `filter_by_country(orders, country)` 返回 `country` 与入参匹配（忽略大小写与首尾空白）的订单。
>
> - 未知国家返回空列表；
> - 不接受 `None` 作为国家参数。
>
> ## 按状态筛选
>
> `filter_by_status(orders, status)` 为**精确匹配**（不忽略大小写）。
>
> ## 按金额筛选
>
> `filter_by_amount(orders, min_cents)` 返回金额**大于等于** `min_cents` 的订单。

**[SPEC-CURRENCY-ROUNDING] 币种汇总与精度**
（来源 `sample_project/specs/currency_rounding.md`，相关度 0.4588）

**[SPEC-CHANGE-REQUEST] 变更请求流程**
（来源 `sample_project/specs/change_request.md`，相关度 0.1031）

> 1. 每项局部修改都必须先绑定一条规格条目；
> 2. 修改前必须存在**目标功能测试**，且该测试因目标行为未实现而失败；
> 3. 修改后目标测试与全部回归测试必须同时通过；
> 4. 变更记录必须写明：任务描述、使用的规格条目、修改的文件、验证命令与结果；
> 5. 任务状态（已完成事项、待办、已有验证结果）必须落库，进程重启后仍可读取并复用。

### 2.2 需要修改的代码文件或符号

| 符号 | 文件 | 相关度 |
|---|---|---|
| `filter_by_status` | `src/orders/filters.py` | 1.7293 |
| `filter_by_amount` | `src/orders/filters.py` | 1.1595 |
| `sum_by_currency` | `src/orders/filters.py` | 0.6399 |

### 2.3 用于验证功能及兼容性的测试

| 用例 | 文件 | 角色 |
|---|---|---|
| `test_filter_by_status_keeps_exact_matches` | `tests/test_filters.py` | 回归 |
| `test_filter_by_amount_uses_a_lower_bound` | `tests/test_filters.py` | 回归 |
| `test_sum_by_currency_reports_cents_and_uses_other` | `tests/test_filters.py` | 回归 |
| **`test_filter_by_country_ignores_case_and_padding`** | `tests/test_filters.py` | **目标功能测试** |
| **`test_filter_by_country_does_not_mutate_the_input`** | `tests/test_filters.py` | **目标功能测试** |

### 2.4 已有验证结果

- 修改前，目标功能测试应当失败（`filter_by_country` 尚未实现）。

## 3. MiniMax 的需求理解

> 任务是在 `sample_project` 这个 Python 业务工程中，为订单筛选增加按国家过滤的能力
> `filter_by_country`，属于 **SPEC-CHANGE-REQUEST** 规定的「局部修改」流程
> （每项修改绑定一条规格条目 → 修改前目标功能测试因功能缺失而失败 →
> 修改后目标测试与全部回归测试同时通过 → 留存变更记录）。
>
> 从上下文读到的 **SPEC-ORDER-FILTERING** 约束，逐条落地为：
>
> | 规格约定 | 落地方式 |
> |---|---|
> | 输入 `Iterable[Order]`，输出**新的** `list[Order]`，不得修改入参集合或元素 | 返回列表推导产生的新 list；`Order` 是 `frozen=True` dataclass，只读取字段、不写入 |
> | 返回顺序与输入顺序一致 | 单次线性遍历 + 推导式，天然保序 |
> | 文本比较类筛选忽略大小写与首尾空白 | 双方都经 `_normalize_country()` 做 `strip().casefold()` |
> | 不满足任何条件返回空列表而非 `None` | 无匹配时推导式自然得到 `[]` |
> | 未知国家返回空列表 | 无匹配即 `[]` |
> | 不接受 `None` 作为国家参数 | 显式 `raise TypeError`（与「未知国家返回 []」刻意区分） |
>
> 同时确认了 `filter_by_status`（精确匹配）、`filter_by_amount`（分单位下界）、
> `sum_by_currency`（分单位汇总 + 空币种归入 `OTHER`）三个既有符号**已经满足**各自规格，
> 因此保持实现不变，只作为回归基线。

## 4. MiniMax 的方案

> 核心是引入一个私有的归一化辅助函数 `_normalize_country()`，
> 把「忽略大小写与首尾空白」这一比较规则集中到一处，
> 再让 `filter_by_country` 对**请求方国家**和**订单存储国家**同时归一化后做相等比较。
>
> 几个设计取舍：
>
> 1. **`casefold()` 而非 `lower()`**：`casefold()` 是 Unicode 标准的无大小写折叠，比 `lower()` 更彻底，
>    符合规格「忽略大小写」的措辞。
> 2. **`None` 订单国家**：`Order.country` 声明为 `str`，但辅助函数对 `None` 返回 `None`，
>    与请求方归一化结果（永远是非 None 的 `str`）永不相等，因此脏数据不会触发 `AttributeError`，
>    也不会被误匹配。
> 3. **`country=None` 抛 `TypeError`**：规格把「未知国家返回空列表」和「不接受 None 作为国家参数」
>    并列陈述，说明二者语义不同——未知国家是「查不到」，`None` 是「参数非法」。
> 4. **返回值类型恒为 `list`**：空输入返回 `[]` 而非 `None`，满足规格第 5 条。
>
> `src/orders/__init__.py` 中把 `filter_by_country` 加入 `from orders.filters import ...` 以及 `__all__`，
> 使包级 API 可以 `from orders import filter_by_country` 直接使用。

## 5. 代码修改过程

MiniMax 按以下顺序完成修改：

1. 读取 `src/orders/filters.py`、`src/orders/__init__.py`、`tests/test_filters.py`、
   `specs/order_filtering.md`，确认既有实现与规格的一致性；
2. **先运行**测试建立基线，确认目标功能测试因 `filter_by_country` 不存在而失败
   （`ImportError: cannot import name 'filter_by_country' from 'orders.filters'`），
   3 个回归测试通过；
3. 在 `src/orders/filters.py` 中新增 `_normalize_country()` 与 `filter_by_country()`；
4. 在 `src/orders/__init__.py` 中导出新函数；
5. **再次运行**测试，确认 5 个用例全部通过；
6. 生成统一差异 `evidence/code-change.patch`，并用 `git apply --check` 验证补丁可应用。

**未修改**：`tests/test_filters.py`、`sdd/`、`scripts/`——测试集在修改前后保持一致，
没有删除断言、跳过测试或修改预期结果。

## 6. 代码差异

完整补丁：`evidence/code-change.patch`（仅含 `src/orders/__init__.py` 与 `src/orders/filters.py` 两个文件）。

```diff
diff --git a/src/orders/__init__.py b/src/orders/__init__.py
--- a/src/orders/__init__.py
+++ b/src/orders/__init__.py
@@ -1,5 +1,11 @@
 """Order helpers of the sample business project."""

-from orders.filters import Order, filter_by_amount, filter_by_status, sum_by_currency
+from orders.filters import Order, filter_by_amount, filter_by_country, filter_by_status, sum_by_currency

-__all__ = ("Order", "filter_by_amount", "filter_by_status", "sum_by_currency")
+__all__ = (
+    "Order",
+    "filter_by_amount",
+    "filter_by_country",
+    "filter_by_status",
+    "sum_by_currency",
+)

diff --git a/src/orders/filters.py b/src/orders/filters.py
--- a/src/orders/filters.py
+++ b/src/orders/filters.py
@@ -21,6 +21,40 @@ class Order:
     currency: str


+def _normalize_country(value: str | None) -> str | None:
+    """Return the comparable form of a country code.
+
+    Textual comparisons ignore case and surrounding whitespace, so ``" de "``
+    and ``"DE"`` normalise to the same value.  ``None`` is not a country and
+    stays ``None`` so that it never matches a requested country.
+    """
+
+    if value is None:
+        return None
+    return value.strip().casefold()
+
+
+def filter_by_country(orders: Iterable[Order], country: str) -> list[Order]:
+    """Return the orders whose country matches ``country``.
+
+    The comparison ignores case and surrounding whitespace on both sides, so
+    ``filter_by_country(orders, " de ")`` keeps the orders stored as ``"DE"``
+    and ``"de"``.  The input is never modified and the result keeps the order
+    of the input.  An unknown country yields an empty list; ``None`` is not
+    accepted as the requested country.
+    """
+
+    if country is None:
+        raise TypeError("country must be a string, not None")
+
+    wanted = _normalize_country(country)
+    return [
+        order
+        for order in orders
+        if _normalize_country(order.country) == wanted
+    ]
+
+
 def filter_by_status(orders: Iterable[Order], status: str) -> list[Order]:
     """Return the orders whose status matches ``status`` exactly."""
```

## 7. 验证

### 修改前

命令：

```bash
cd sample_project && python -m pytest tests -q
```

输出：

```
...FF                                                                    [100%]
FAILED tests\test_filters.py::test_filter_by_country_ignores_case_and_padding
FAILED tests\test_filters.py::test_filter_by_country_does_not_mutate_the_input
E       ImportError: cannot import name 'filter_by_country' from 'orders.filters'
2 failed, 3 passed in 0.79s
```

失败原因是**目标行为未实现**，不是缺少依赖或环境错误。

### 修改后

命令：

```bash
cd sample_project
python -m pytest tests -q
```

输出：

```
.....                                                                    [100%]
5 passed in 0.15s
```

逐用例明细：

```
tests\test_filters.py::test_filter_by_status_keeps_exact_matches PASSED  [ 20%]
tests\test_filters.py::test_filter_by_amount_uses_a_lower_bound PASSED   [ 40%]
tests\test_filters.py::test_sum_by_currency_reports_cents_and_uses_other PASSED [ 60%]
tests\test_filters.py::test_filter_by_country_ignores_case_and_padding PASSED [ 80%]
tests\test_filters.py::test_filter_by_country_does_not_mutate_the_input PASSED [100%]
============================== 5 passed in 0.19s ==============================
```

### 规格边界自检

在独立脚本中逐条核对规格约定（**未改动测试文件**）：

```
case+pad ' de ' -> ['o-1', 'o-2']      # 忽略大小写与首尾空白
upper 'US'     -> ['o-3']              # 仅大小写不同
padded '  us'  -> ['o-3']              # 仅首尾空白不同
unknown 'jp'   -> []                   # 未知国家返回空列表
empty input    -> []                   # 空输入返回空列表而非 None
order kept     -> ['o-1', 'o-2']       # 顺序与输入一致
new list obj   -> True                 # 返回新列表对象
input unmutated-> True                 # 入参集合未被修改
None           -> TypeError: country must be a string, not None
generator input-> ['o-1', 'o-2']       # 支持任意 Iterable
regression     -> ['o-1', 'o-2', 'o-4'] {'EUR': 3500, 'USD': 3000, 'OTHER': 700}
```

### 补丁可复现性

把 `evidence/code-change.patch` 应用到一份原始文件副本上，`git apply --check` 退出码 0、
`git apply` 退出码 0，应用结果与当前源文件逐字节一致。

## 8. 使用的上下文来源汇总

**规格条目**

- `sample_project/specs/order_filtering.md`（SPEC-ORDER-FILTERING —— 目标规格，绑定条目）
- `sample_project/specs/change_request.md`（SPEC-CHANGE-REQUEST —— 变更流程与验证要求）
- `sample_project/specs/currency_rounding.md`（SPEC-CURRENCY-ROUNDING —— 分为单位的整数约定）

**代码文件（仅这两个被修改）**

- `sample_project/src/orders/filters.py`
- `sample_project/src/orders/__init__.py`

**测试文件（只读，未修改）**

- `sample_project/tests/test_filters.py`

**产出物**

- `evidence/code-change.patch`