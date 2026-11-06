# 研记 · Research Desk

> 一个面向学习与科研的资料检索工作台：把讲义与笔记放进 **seekdb**，用自然语言问出**带出处的证据**；
> 复习进度由 **PowerContext** 记住，下次接着用。

## 它解决什么问题

复习时找不到上学期的笔记；读了一堆论文，问"我上次看到的那条数据在哪"却无从下手。
研记把资料变成可检索的笔记，并记住你每个主题读到哪、学到哪：

- **问一句，拿证据**：自然语言提问，返回按相关度排序的笔记，每条都带**出处文件路径**与相关度分数。
- **记得住你的进度**：把一条笔记标记为"已掌握"或"待复习"，下次打开同一主题会直接提醒还剩几条没掌握。
- **看得见的检索**：界面会显示本次问句**实际发出的 SQL**，检索过程不是黑盒。

## 三项技术的分工

| 技术 | 承担的作用 | 在哪里 |
|---|---|---|
| **seekdb** | 存储笔记、构建全文索引、执行检索 | `qoderapp/store.py`：三列宽表 + 一个 IK 全文索引；用 `tokenize(问句,'ik')` 与 `MATCH ... AGAINST` 检索 |
| **PowerContext** | 保存复习状态，并在后续运行中读取复用 | `qoderapp/memory.py`：通过 Memory 应用写入 / 读回主题状态 |
| **Python 标准库** | 提供 HTTP 服务与网页界面，零额外依赖 | `qoderapp/server.py`、`web/` |

## 快速开始

```bash
# 1) 准备一个可用的 seekdb 实例（服务端或嵌入式均可）
export DESK_SEEKDB_HOST=127.0.0.1
export DESK_SEEKDB_PORT=2883

# 2) 把样例笔记导入 seekdb（幂等，可重复执行）
python qoderapp/cli.py seed
# 期望输出：seekdb `research_desk` 已导入 4 条笔记。

# 3) 提问
python qoderapp/cli.py ask --question "分词器不一致会怎样"
# 期望输出：按相关度排序的证据，每条带来源路径。

# 4) 记录复习状态
python qoderapp/cli.py mark --topic "检索基础" --note "NOTE-分词与倒排.md"
python qoderapp/cli.py mark --topic "检索基础" --note "NOTE-检索基础.md" --mastered

# 5) 另起一个进程读回状态（验证"重启后读取并使用"）
python qoderapp/cli.py progress
# 期望输出：检索基础: 已掌握 1，待复习 1，复习次数 2

# 6) 启动网页
python qoderapp/cli.py serve
# 打开 http://127.0.0.1:8848/
```

## 运行环境

| 项 | 值 |
|---|---|
| Python | 3.12 |
| 依赖 | `pymysql`（连 seekdb）；PowerContext 用仓库内的 `src/`；网页只用标准库 |
| seekdb | v1.3.0.0 及以上，MySQL 协议兼容，服务端或 `pylibseekdb` 嵌入式均可 |

## 配置

全部通过环境变量设置，仓库内不含任何凭据：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DESK_SEEKDB_HOST` | `127.0.0.1` | seekdb 主机 |
| `DESK_SEEKDB_PORT` | `2883` | seekdb 端口 |
| `DESK_SEEKDB_USER` | `root` | 用户名 |
| `DESK_SEEKDB_PASSWORD` | 空 | 密码 |
| `DESK_SEEKDB_DATABASE` | `research_desk` | 存放笔记的库名 |
| `DESK_STATE_PATH` | `qoder/state/research-desk.db` | PowerContext 状态库（SQLite） |
| `DESK_SAMPLE_DIR` | `qoder/sample` | 笔记目录 |
| `DESK_HOST` / `DESK_PORT` | `127.0.0.1` / `8848` | 网页服务地址 |
| `DESK_SCOPE` | `research-desk` | PowerContext 作用域 |

## 目录结构

```
qoder/
  qoderapp/
    config.py     环境变量配置
    store.py      seekdb 存储与检索
    memory.py     PowerContext 复习状态
    service.py    业务编排
    server.py     HTTP 服务（标准库）
    cli.py        命令行
  web/            静态网页（可直接发布，无需构建步骤）
  sample/         样例笔记
  docs/           技术说明、验证样例、Qoder 操作清单、已知问题
```

## 文档

- `docs/technical-overview.md` —— 一页技术说明
- `docs/verification-sample.md` —— 验证样例（初始数据、操作步骤、预期结果）
- `docs/qoder-checklist.md` —— 在 Qoder 中完成开发记录与网站发布的操作清单
- `docs/known-issues.md` —— 已知的平台问题与规避方式

## 已知限制

1. **seekdb 1.3.0 在 Windows 上构建全文索引时可能崩溃服务端**（`0xC0000005` 访问冲突，
   后台线程）。本模块因此只在索引确实缺失时才去构建它，并在服务掉线时给出明确提示。
   嵌入式引擎 `pylibseekdb` 不受影响。详见 `docs/known-issues.md`。
2. 检索是纯词法的：中文依赖 IK 分词器，实例未启用 IK 时请去掉建表语句里的 `WITH PARSER ik`。
3. 网页服务是单进程的标准库实现，面向本地与小规模使用，没有鉴权与并发控制。
