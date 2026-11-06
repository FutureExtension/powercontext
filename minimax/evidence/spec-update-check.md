# 规格更新验证：输出必须随规格变化

> 题目要求：「更新样例中的规格并重新导入后，模块应使用更新后的内容，不能始终返回固定答案。」
> 本文件记录该验收项的**实测**过程与结果。

## 步骤

1. 基线：python -m sdd.cli plan --task "为订单筛选增加按国家过滤的能力"
   → 见 context-before-spec-change.md
2. 在 sample_project/specs/order_filtering.md 的「- 未知国家返回空列表；」后追加一行：

   `
   - 国家代码按 ISO 3166-1 alpha-2 规范化，例如  de  视为 DE；
   `

3. python -m sdd.cli seed（重新导入）
4. 再次 python -m sdd.cli plan --task "为订单筛选增加按国家过滤的能力"
   → 见 context-after-spec-change.md

## 实测差异

`diff
- 代码检索词（来自规格正文中的标识符）：SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents
+ 代码检索词（来自规格正文中的标识符）：SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country alpha filter_by_status status filter_by_amount min_cents

- [SPEC-ORDER-FILTERING] 订单筛选接口约定  （来源 sample_project/specs/order_filtering.md，相关度 1.0175）
+ [SPEC-ORDER-FILTERING] 订单筛选接口约定  （来源 sample_project/specs/order_filtering.md，相关度 1.0165）
`

两处变化：

1. 新规格里的标识符 \lpha\ 被提取进代码检索词；
2. SPEC-ORDER-FILTERING 的全文相关度由 \1.0175\ 变为 \1.0165\（正文变长、词项分布改变）。

**结论**：模块的输出由数据库中的规格内容决定，不是固定答案。

## 重置

删除追加的那一行，重新执行 \python -m sdd.cli seed\ 即可恢复原状。
（本仓库已恢复，\sample_project/specs/order_filtering.md\ 与初始版本一致。）