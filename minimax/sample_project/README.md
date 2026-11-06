# sample_project — 待改造的业务工程

这个工程是 MiniMax 赛题的**被修改对象**：赛题要求「选择一项能够运行、具有测试的业务工程，
定义并完成一项局部修改」。这里选定的局部修改是：

> **为订单筛选增加按国家过滤的能力 `filter_by_country`。**

工程刻意保持很小，但它是真实可运行的 Python 包，带单元测试：

```
sample_project/
  src/orders/__init__.py
  src/orders/filters.py      # 被修改的文件
  tests/test_filters.py       # 目标功能测试 + 相关回归测试
  specs/                     # 规格条目（会被导入 seekdb 供上下文检索）
```

## 运行

```bash
cd sample_project
python -m pytest tests -q
```

`tests/test_filters.py::test_filter_by_country` 是**目标功能测试**：在改造前因为
`filter_by_country` 尚未实现而失败，改造后通过；其余用例是**相关回归测试**，改造前后都通过。
