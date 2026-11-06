# 已知问题

## 1. seekdb 1.3.0 在 Windows 上构建全文索引会崩溃服务端

**现象**

执行 `CREATE FULLTEXT INDEX ...` 时，服务端进程直接退出，客户端报：

```
pymysql.err.OperationalError: (2013, 'Lost connection to MySQL server during query
([WinError 10054] 远程主机强迫关闭了一个现有的连接。'))
```

服务端 stderr 里有访问冲突栈：

```
[WIN32-TRACE] Vectored exception #1: code=0xC0000005 addr=0x... tid=... (bg-thread)
  AccessViolation: READ at 0x0000000000000400
  Module: ...\seekdb.exe + 0x175D520
[WIN32-TRACE] Background thread crash #1, terminating process to avoid corruption.
```

**复现情况（本机实测）**

- 用 `WITH PARSER ik` 和用默认分词器**都会崩**；
- **偶发**：同样的语句有时成功、有时把服务端带走；
- 崩溃点在**后台线程**的索引构建里，不是查询路径；
- 崩溃后该实例上**只建了一半的表会留下来**（本机实测：三个表只剩第一个）。

**规避方式（本模块已实现）**

1. `qoderapp/store.py` 在建索引前先查 `information_schema.STATISTICS`，
   **索引已经存在就不再执行 `CREATE FULLTEXT INDEX`**；
2. 真的需要建索引时，如果连接因此断开，模块抛出明确的 `RuntimeError`，
   指出是索引构建把服务端带走了，而不是让人去猜一个协议错误；
3. **嵌入式引擎不受影响**：用 `pylibseekdb` 连续 8 次建 IK 全文索引并写入、
   全文检索，全部成功。

**给平台的一条反馈**

这个问题落在「全文索引」这一族里，而赛题四正是全文索引性能优化。
如果官方能复现，值得提一个 issue：Windows 上 `CREATE FULLTEXT INDEX`
的后台线程会访问越界（读 0x400）并终止进程。

## 2. 实例未启用 IK 分词器

检索依赖 IK 分词器。若实例不支持 `WITH PARSER ik`，把
`qoderapp/store.py` 里 `INDEXES` 的建索引语句去掉 `WITH PARSER ik` 即可，
代价是中文只能按字串切分。

## 3. 网页服务是单进程实现

`qoderapp/server.py` 用标准库的 `ThreadingHTTPServer`，面向本地与小规模使用：
没有鉴权、没有并发控制、不适合直接暴露到公网。
