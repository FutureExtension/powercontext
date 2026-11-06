---
spec_id: SPEC-ORDER-FILTERING
title: 订单筛选接口约定
tags: ["订单", "筛选", "过滤"]
---

# 订单筛选接口约定

所有筛选函数遵循同一组约定：

1. 输入为 `Iterable[Order]`，输出为**新的** `list[Order]`，**不得修改**入参集合或其中的元素；
2. 返回顺序与输入顺序一致；
3. 文本比较类筛选必须**忽略大小写与首尾空白**；
4. 金额类筛选以**分**为单位的整数比较；
5. 不满足任何条件的输入返回空列表，而不是 `None`。

## 按国家筛选

`filter_by_country(orders, country)` 返回 `country` 与入参匹配（忽略大小写与首尾空白）的订单。

- 未知国家返回空列表；
- 不接受 `None` 作为国家参数。

## 按状态筛选

`filter_by_status(orders, status)` 为**精确匹配**（不忽略大小写）。

## 按金额筛选

`filter_by_amount(orders, min_cents)` 返回金额**大于等于** `min_cents` 的订单。
