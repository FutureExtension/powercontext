# 验证样例

> 评审可从干净环境开始，按本文件逐步执行。所有预期输出都是**实测**得到的。

## 0. 前置

- Python 3.12，依赖 `pymysql`；PowerContext 用仓库内的 `src/`。
- 一个可用的 seekdb 实例（服务端或嵌入式均可）。

```bash
export DESK_SEEKDB_HOST=127.0.0.1
export DESK_SEEKDB_PORT=2883
export PYTHONPATH=<repo>/src:<repo>/qoder
```

## 1. 初始数据

`qoder/sample/` 随作品提交，**无需另行准备**：

| 文件 | 主题 | 标题 |
|---|---|---|
| `检索基础.md` | 检索基础 | 向量检索中的召回与精度 |
| `分词与倒排.md` | 检索基础 | 倒排索引与分词器 |
| `事务与隔离.md` | 数据库基础 | 事务隔离级别与幻读 |
| `索引设计.md` | 数据库基础 | 索引设计与回表 |

数据库侧初始为空，由第 2 步导入。

## 2. 操作步骤与预期结果

### 步骤 1 · 导入笔记

```bash
python qoderapp/cli.py seed
```

**预期输出**

```
seekdb `research_desk` 已导入 4 条笔记。
```

**核对数据库**（可选，验证资料真的进了 seekdb）

```sql
USE research_desk;
SELECT topic, COUNT(*) FROM desk_note GROUP BY topic;   -- 检索基础 2 / 数据库基础 2
SHOW INDEX FROM desk_note;                                -- 含 idx_desk_note_body (FULLTEXT)
```

### 步骤 2 · 提问，拿到带出处的证据

```bash
python qoderapp/cli.py ask --question "分词器不一致会怎样"
```

**预期输出**（节选）

```
# 分词器不一致会怎样

## 证据
- **倒排索引与分词器**（主题 检索基础，来源 `sample/分词与倒排.md`，相关度 0.7691）
  > ...**索引侧和查询侧必须用同一个分词器**，否则查询词和索引词对不上，检索会静默地少召回。
- **向量检索中的召回与精度**（主题 检索基础，来源 `sample/检索基础.md`，相关度 0.0406）
```

**必须核对的三件事**

1. 来源路径 `sample/分词与倒排.md` **真实存在**，打开后确实包含被引用的那段话；
2. 相关度分数由 **seekdb** 计算，不是本地算的；
3. `--json` 输出里的 `statements` 是本次实际发出的 SQL：

```bash
python qoderapp/cli.py ask --question "分词器不一致会怎样" --json
```

```json
{
  "statements": [
    "SELECT note_id, topic, title, source_path, MATCH(body) AGAINST ('分词器 不一致 怎样' IN BOOLEAN MODE) AS score, SUBSTRING(body, 1, 400) FROM desk_note WHERE MATCH(body) AGAINST ('分词器 不一致 怎样' IN BOOLEAN MODE) ORDER BY score DESC LIMIT 8"
  ]
}
```

### 步骤 3 · 记录复习状态

```bash
python qoderapp/cli.py mark --topic "检索基础" --note "NOTE-分词与倒排.md"
python qoderapp/cli.py mark --topic "检索基础" --note "NOTE-检索基础.md" --mastered
```

**预期输出**

```
主题 检索基础：已掌握 0 条，待复习 1 条。
主题 检索基础：已掌握 1 条，待复习 1 条。
```

### 步骤 4 · 另起一个进程读回状态（验证"状态能够复用"）

```bash
python qoderapp/cli.py progress
```

**预期输出**

```
检索基础: 已掌握 1，待复习 1，复习次数 2
```

这一步是**另一个进程**：状态不是本地变量，而是经 PowerContext 的 Memory 应用落库后读回来的。

### 步骤 5 · 状态被真正用起来

```bash
python qoderapp/cli.py ask --question "分词器不一致会怎样" --topic "检索基础"
```

**预期输出**（顶部多出一行）

```
> 复习提醒：本主题还有 1 条笔记没有标记为已掌握。
```

这行提醒来自 PowerContext 读回的复习状态。

### 步骤 6 · 网页界面

```bash
python qoderapp/cli.py serve
```

打开 <http://127.0.0.1:8848/>：

- 主题下拉里能看到 seekdb 里真实的两个主题及其笔记数；
- 输入问题点"检索"，下方出现证据卡片，带来源路径与相关度；
- 点"标记已掌握"，**刷新页面后**进度条仍然在（状态在 PowerContext 里）；
- 页面底部显示本次发出的 SQL 条数。

## 3. 重置方法

| 要重置的东西 | 怎么做 |
|---|---|
| 数据库中的笔记 | `python qoderapp/cli.py seed`（幂等覆盖） |
| 复习状态 | 删除 `DESK_STATE_PATH` 指向的 SQLite 文件 |
| 样例笔记 | `qoder/sample/` 随仓库提交，改动后重新 `seed` |

## 4. 一次跑完全部步骤

```bash
python scripts/verify.py
```

脚本按上面的顺序执行每一步并打印实际输出与结论。
