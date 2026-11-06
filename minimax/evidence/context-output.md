# 任务上下文

- 任务：为订单筛选增加按国家过滤的能力
- 作用域：sdd-task
- 检索词（由数据库 IK 分词器切分）：为 增 筛选 能力 加按 过滤 的 订单 国家
- 代码检索词（来自规格正文中的标识符）：SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents

## 实际执行的数据库查询
- `SELECT spec_id, title, file_path, MATCH(body) AGAINST (为 增 筛选 能力 加按 过滤 的 订单 国家 IN BOOLEAN MODE) AS score FROM sdd_spec WHERE MATCH(body) AGAINST (为 增 筛选 能力 加按 过滤 的 订单 国家 IN BOOLEAN MODE) ORDER BY score DESC LIMIT 5`
- `SELECT symbol_id, symbol, file_path, kind, spec_id, related_test, MATCH(body) AGAINST (SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents IN BOOLEAN MODE) AS score FROM sdd_symbol WHERE MATCH(body) AGAINST (SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents IN BOOLEAN MODE) ORDER BY score DESC LIMIT 10`
- `SELECT test_id, name, file_path, MATCH(body) AGAINST (SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents IN BOOLEAN MODE) AS score FROM sdd_test WHERE MATCH(body) AGAINST (SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents IN BOOLEAN MODE) ORDER BY score DESC LIMIT 10`

## 适用的规格条目
- [SPEC-ORDER-FILTERING] 订单筛选接口约定  （来源 sample_project/specs/order_filtering.md，相关度 1.0175）
- [SPEC-CURRENCY-ROUNDING] 币种汇总与精度  （来源 sample_project/specs/currency_rounding.md，相关度 0.4588）
- [SPEC-CHANGE-REQUEST] 变更请求流程  （来源 sample_project/specs/change_request.md，相关度 0.1031）

## 需要修改的代码文件或符号
- filter_by_status  （src/orders/filters.py，相关度 1.7293）
- filter_by_amount  （src/orders/filters.py，相关度 1.1595）
- filter_by_country  （src/orders/filters.py，相关度 1.0465）
- sum_by_currency  （src/orders/filters.py，相关度 0.6399）
- _normalize_country  （src/orders/filters.py，相关度 0.1499）

## 用于验证功能及兼容性的测试
- test_filter_by_status_keeps_exact_matches  （tests/test_filters.py，相关度 1.4591）
- test_filter_by_amount_uses_a_lower_bound  （tests/test_filters.py，相关度 1.4591）
- test_sum_by_currency_reports_cents_and_uses_other  （tests/test_filters.py，相关度 1.1321）
- test_filter_by_country_ignores_case_and_padding  （tests/test_filters.py，相关度 0.6807）
- test_filter_by_country_does_not_mutate_the_input  （tests/test_filters.py，相关度 0.6666）

## 已完成事项 / 待办事项 / 已有验证结果
- 已完成事项：（无）
- 待办事项：按规格实现修改；运行目标功能测试；运行回归测试
- 已有验证结果：（无）
