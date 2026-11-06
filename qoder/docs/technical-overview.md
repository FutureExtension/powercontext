# 一页技术说明：研记 · Research Desk

> 赛题：Qoder × OceanBase —— Build with Qoder，用 Qoder 做一个让学习、科研和工作更高效的项目。

## 1. 问题

学习与科研里最常见的低效是"资料在，但找不回来"：讲义散在十几个文件夹里，
论文读了一半记不清读到哪，问"我上次看到的那条数据在哪"只能靠翻。

## 2. 解法

```
  自然语言提问
        │
        ├─► seekdb：notes 表 + IK 全文索引
        │       · 问句交给数据库自己的分词器 tokenize(q,'ik')
        │       · MATCH(body) AGAINST(... IN BOOLEAN MODE) 一次命中
        │       · 结果带 note_id / title / source_path / score
        │
        ├─► PowerContext：复习状态
        │       · 每个主题一条状态记录：已掌握 / 待复习 / 复习次数
        │       · 通过 Memory 应用写入，另一进程读回
        │
        └─► 网页界面：证据卡片 + 出处 + 复习进度条
                · 界面上直接显示本次问句实际发出的 SQL
```

## 3. 模块结构

| 文件 | 职责 |
|---|---|
| `qoderapp/config.py` | 环境变量配置，仓库内无凭据 |
| `qoderapp/store.py` | seekdb 存储层：建表、全文索引、IK 分词、全文检索 |
| `qoderapp/memory.py` | PowerContext 状态层：复习状态的写入与读回 |
| `qoderapp/service.py` | 业务编排：提问、标记、进度汇总 |
| `qoderapp/server.py` | HTTP 服务与静态文件（仅标准库） |
| `qoderapp/cli.py` | 命令行入口 |
| `web/` | 静态单页应用，无构建步骤，可直接发布 |

## 4. 上下文是怎么选出来的

1. **问句切词交给数据库**：`tokenize(问句, 'ik')` 用的是建索引时同一个分词器，
   索引侧与查询侧的词边界因此永远一致；模块不自己猜分词。
2. **一条 SQL 命中**：`MATCH(body) AGAINST (词1 词2 ... IN BOOLEAN MODE)`，
   正文用 IK 全文索引，相关度由数据库给出。
3. **出处可核对**：每条命中都带 `source_path`，指向 `sample/` 下真实存在的文件。

## 5. 指定技术是否真的在起作用

| 技术 | 可核对的证据 |
|---|---|
| **seekdb** | `seed` 把 4 条笔记写进 seekdb 的 `desk_note` 表并建索引；`ask` 每次发出真实的 `MATCH ... AGAINST` 语句，语句原文可在界面和 `--json` 输出里看到；检索结果里的相关度分数由数据库计算 |
| **PowerContext** | `mark` 把状态写进 Memory；**另起一个进程**执行 `progress` 能读回同一主题的已掌握 / 待复习 / 复习次数；再次 `ask` 时，回答顶部会带出"本主题还有 N 条待复习"的提醒，这段提醒来自 PowerContext 而不是本地文件 |
| **Qoder** | 项目的主要开发在 Qoder 中完成，记录见 `docs/qoder-checklist.md`；网站通过 Qoder Sites 发布 |

## 6. 界面

`web/index.html` + `web/app.js` + `web/styles.css`，无构建步骤：

- 提问框 + 主题下拉（主题来自 seekdb 的真实分组统计）
- 证据卡片：标题、主题、来源路径、相关度、原文片段，每条可一键"标记已掌握 / 标记待复习"
- 复习进度条：每个主题的掌握比例
- 检索状态行：本次发出的 SQL 条数

## 7. 验收方式

见 `docs/verification-sample.md`：四条命令即可从零跑通，
并逐条核对"数据库实际参与"与"状态能够复用"两个关键项。
