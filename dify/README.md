# 雾隐镇 · 夜班档案室

> **Dify × seekdb** —— 一个会记住你的 AI 侦探搭档。
> 卷宗、物证、镇民口供、你排除过谁，全都存在 seekdb 里；换个会话，阿灯还记得。

---

## 0. 提交物清单、用途与导入顺序

| # | 文件 | 用途 | 谁来导入 / 怎么用 |
|---|------|------|-------------------|
| 1 | `service/app.py` | **自定义工具后端**。一个 FastAPI 服务，把 Dify 的工具调用翻译成对 seekdb 的真实 SQL 读写。 | 评审在本机启动它（见 `6） |
| 2 | `service/requirements.txt` | 工具服务依赖（fastapi / uvicorn / pymysql） | `pip install -r requirements.txt` |
| 3 | `service/.env.example` | 工具服务配置示例，**全部是占位值**，复制成 `.env` 再改 | 复制为 `.env` 后修改 |
| 4 | `service/init_data.sql` | seekdb 建表 + 初始数据（4 个案子 / 21 条物证 / 8 位镇民 / 8 条镇志 / 1 条初始记忆 / 2 条历史问答） | `mysql < init_data.sql` 或 `python smoke_test.py --init` |
| 5 | `service/smoke_test.py` | 一键冒烟测试：真实 seekdb 端到端 / 离线 mock 两种模式 | `python smoke_test.py` |
| 6 | `custom_tool.yml` | **Dify 自定义工具的 OpenAPI 规范**。导入后得到 3 个工具：`search_archive` / `get_player_progress` / `record_progress` | Dify → 工作室 → 工具 → 自定义 → 创建工具 → 导入 `custom_tool.yml`（**必须先做这一步**） |
| 7 | `app.yml` | **Dify 应用 DSL**（Chatflow，14 个节点）。必须等第 6 步完成后再导入 | Dify → 工作室 → 工作室资源 → 导入 DSL → `app.yml` |
| 8 | `README.md` | 本文件：运行说明 | — |
| 9 | `验证样例.md` | 验证样例与运行证据 | — |
| 10 | `NOTES.md` | 设计说明：创意、分工、可核对点、来源声明 | — |

**导入顺序很重要**：`custom_tool.yml` 必须先导入，因为 `app.yml` 里的 4 个「工具」节点引用的是这个自定义工具。
详细步骤见 `6。

### 适用 Dify 版本与部署方式

| 项目 | 说明 |
|------|------|
| DSL 格式版本 | `version: 0.4.0`（Dify 官方的 DSL 格式版本号，不是 Dify 应用版本） |
| 实测 / 推荐 Dify 版本 | **Dify ≥ 1.0**（当前主线 DSL 版本为 0.7.0；导入 0.4.0 的 DSL 会自动升级并提示 *completed-with-warnings*，属正常现象） |
| 更老的 Dify | 若你的 Dify 使用 DSL ≤ 0.3.x，把 `app.yml` 里的 `version: 0.4.0` 改成 `version: 0.1.5` 再导入即可 |
| 部署方式 | 官方 `docker compose up -d`（推荐，Dify 跑在 Docker 里）；源码部署亦可 |
| Dify 侧外部依赖 | 1 个模型提供商（任意 chat 模型即可）、1 个自定义工具、1 个可选的 API Key 鉴权头 |

---

## 1. 作品创意、玩法与体验方式

### 1.1 一句话

**你是雾隐镇新上任的夜班档案员，AI 搭档「阿灯」是档案室里那盏会说话的老灯。**
你用大白话问案，阿灯去镇上的数据库（seekdb）里翻卷宗、找物证、盘镇民，然后把结论念给你听，
并把你这一轮的追问、已排除的嫌疑人、已掌握的物证**写回数据库**——所以下次你开新会话，它还记得你上次问过谁。

### 1.2 设定

雾隐镇是个海边小镇，海雾一年到头不散。最近半个月镇上出了四桩怪事：

| 案件 | 标题 | 地点 | 性质 |
|------|------|------|------|
| CASE-2401 | 灯塔下的第三盏灯 | 灯塔 | 灯油与备用灯失窃 |
| CASE-2402 | 咸鱼仓的红盐账本 | 咸鱼仓 | 账本被撕走三页 |
| CASE-2403 | 雾钟停摆的那一夜 | 钟楼 | 雾钟被砸停，整条海岸线失去预警 |
| CASE-2404 | 纸鸢街的第十三个风筝 | 纸鸢街 | 连续出现无主风筝与匿名信 |

镇上有 8 位有名有姓的镇民：盐婆陈阿婆、账房周掌柜、老灯林海、三爷秦三、砚师傅温砚、鸢娘苏小鸢、苗姑苗娘、巡夜的丁叔。
每个人的动机、常去的地方、自称的不在场证明，都写在 seekdb 的 `suspects` 表里。

### 1.3 玩法（体验方式）

1. **开局**：在 Dify 应用页面顶部的表单里填 **侦探代号**（默认 `detective_001`）和 **要接手的卷宗**（4 选 1）。
2. **自由提问**：用大白话问，例如
   - 「钟楼的雾钟到底是怎么坏的？」
   - 「谁把那袋灯油换掉了？」
   - 「查一下咸鱼仓的红盐账本」
   - 「温砚那晚在哪？」

   阿灯会先把问题拆成 **关键词 / 地点 / 人物**，再去 seekdb 里查，最后用它的口吻讲给你听。
3. **引用即归档**：阿灯在回答里用 `【EV-0301】` `【SUS-05】` 标注它引用的物证与镇民编号，
   系统会把这些编号**自动写回** `player_progress` 表，成为你的"已掌握物证 / 已排除镇民"。
4. **结案**：线索够了（**本轮翻到关键物证 ≥ 2 条**且**仍有未被排除的镇民**）时说一声「结案」，
   阿灯会做结案陈词，并把 `case_files.status` 从 `open` 改成 `closed` 写回 seekdb。
5. **跨会话记忆**：关掉页面、重新开一个会话，阿灯会主动提起"你上次已经排除了丁叔""铜屑那条线你还没查清"——
   因为这些都存在 `player_progress` 表里，按你的侦探代号关联。

### 1.4 为什么这个玩法适合展示数据库

- **问题模糊**：玩家说"雾钟怎么坏的"，不是 SQL。→ 需要「自然语言 → 结构化检索词」的转换。
- **答案有依据**：阿灯不能瞎编。→ 所有结论都必须来自数据库里的卷宗/物证。
- **记忆要跨会话**：Dify 的会话记忆存在它自己的库里，出会话就没了。→ 所以进度必须落到 seekdb。
- **状态会变化**：排除一个嫌疑人、结一个案子。→ seekdb 要能被写。

---

## 2. Dify 与 seekdb 的分工

| 环节 | 由谁负责 | 说明 |
|------|---------|------|
| 输入处理（拆解意图、抽关键词） | **Dify** | 「解析提问」Code 节点：判定 `close` / `ask` 意图，抽出引号里的显式关键词和英文编号 |
| 条件判断（能不能结案） | **Dify** | 「判定结案条件」Code 节点 + 「可以结案吗」If/Else 节点 |
| 模型调用（推理与叙事） | **Dify** | 「阿灯·推理」LLM 节点：只允许依据检索到的卷宗作答，并标注引用编号 |
| 工具调用 | **Dify** | 4 个「工具」节点调用自定义工具 |
| 检索词的"词典" | **seekdb** | 地点词典来自 `case_files.location` / `evidence.location`，人名词典来自 `suspects.name/alias`；中文按 2/3-gram 切分后**只保留在数据库语料里真实出现过的字串** |
| 结构化数据存储 | **seekdb** | 6 张表：`case_files` / `evidence` / `suspects` / `town_lore` / `player_progress` / `investigation_log` |
| 混合检索 | **seekdb** | 一条 SQL 里同时做「结构化过滤（案件编号/地点/状态）」+「关键词匹配（FULLTEXT MATCH，失败自动退回 LIKE）」 |
| 跨会话记忆 | **seekdb** | `player_progress` 表，按 `player_id` 关联；`investigation_log` 保存每一轮问答 |
| 状态变更 | **seekdb** | 结案时 `UPDATE case_files SET status='closed'` |

**一句话**：**Dify 负责"理解、编排、叙事"，seekdb 负责"存储、检索、记账"。**
Dify 本身不直接连数据库，它只通过一个 OpenAPI 自定义工具去调一个 Python 服务；这个服务用 `pymysql`（MySQL 协议）连 seekdb。

### 技术结合的可核对点（评审可以逐条查）

| # | 核对点 | 在哪看 |
|---|--------|--------|
| 1 | Dify 的工具节点确实发出了 HTTP 请求到本工具服务 | 工具服务日志 / `/health` 的调用计数 |
| 2 | 工具服务确实用 MySQL 协议连了 seekdb | `service/app.py` 的 `pymysql.connect(host=127.0.0.1, port=2881)`；`/health` 返回 seekdb 版本号 |
| 3 | 每次工具调用执行的**具体 SQL** | 工具返回的 `sql_trace` 字段（会原样出现在 Dify 节点执行记录的"输出"里） |
| 4 | 读写涉及哪些表 | `sql_trace` 里的 SQL 文本；`init_data.sql` 的建表语句 |
| 5 | 写回确实落库 | `SELECT * FROM player_progress / investigation_log / case_files` |
| 6 | 跨会话记忆 | 新会话里 `get_player_progress` 返回 `player_progress` 里上一轮的 `cleared_evidence` / `eliminated_suspects` |
| 7 | 结案确实改了状态 | `case_files.status` 由 `open` 变 `closed`，并带 `closed_at` / `closed_by` |

---

## 3. 目录结构

```
dify/
├── app.yml                    # Dify 应用 DSL（Chatflow，14 节点 / 13 连线）
├── custom_tool.yml            # Dify 自定义工具 OpenAPI 规范（3 个 operation）
├── README.md                  # 本文件
├── 验证样例.md                 # 验证样例 + 证据
├── NOTES.md                   # 设计说明
└── service/
    ├── app.py                 # 自定义工具服务（FastAPI + pymysql）
    ├── requirements.txt
    ├── .env.example
    ├── init_data.sql
    └── smoke_test.py
```

---

## 4. 运行环境、软件与插件版本

| 组件 | 版本 | 说明 |
|------|------|------|
| Dify | ≥ 1.0（建议用当前主线/最新稳定版） | 提供 Chatflow 运行时、自定义工具、模型接入 |
| seekdb | **1.3.0**（本作品验证于 Windows 版 seekdb 1.3.0.0） | MySQL 协议，**默认端口 2881**；也可用官方 Docker 镜像 `oceanbase/seekdb` |
| Python | ≥ 3.10（推荐 3.11/3.12） | 工具服务与冒烟测试 |
| fastapi | ≥ 0.110, < 1.0 | `service/requirements.txt` |
| uvicorn | ≥ 0.27, < 1.0 | 同上 |
| PyMySQL | ≥ 1.1, < 2.0 | 同上；**用 MySQL 协议连 seekdb** |
| Dify 插件 | `langgenius/openai`（仅当你的模型是 OpenAI 兼容时需要） | 也可以用 DeepSeek、通义、智谱、Ollama 等任意 chat 模型插件；见 `5 |
| 自定义工具 | 无插件 | 由 `custom_tool.yml` 创建的 **API 型自定义工具**（不是插件） |

> **关于 Embedding / Rerank**：本作品**刻意不使用**向量检索，因此 **不需要任何 Embedding 或 Rerank 服务**。
> 理由见 `NOTES.md` `4（可复现性优先）。seekdb 的 `MATCH ... AGAINST` 全文索引能力仍然启用，且服务会自动探测。

---

## 5. 所需模型服务及配置项

Dify 侧只需要 **一个 chat 模型**（能中文对话即可）。

| 配置项 | 位置 | 占位值 / 说明 |
|--------|------|--------------|
| 模型提供商 API Key | Dify → 工作室 → 设置 → 模型供应商 → OpenAI 兼容 → API Key | `sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`（**占位值，不要提交真实 Key**） |
| 模型名 | Dify → 设置 → 模型供应商 | `gpt-4o-mini` 或任意可用的 chat 模型 |
| `app.yml` 里的模型 | LLM 节点「阿灯·推理」 | `provider: langgenius/openai/openai`，`name: gpt-4o-mini`，`temperature: 0.4` |
| Embedding 服务 | — | **不需要**（本作品不做向量检索） |
| Rerank 服务 | — | **不需要** |
| 工具服务地址 | `custom_tool.yml` 的 `servers[0].url` | `http://host.docker.internal:8100`（Dify 在 Docker 中）/ `http://127.0.0.1:8100`（同机直跑） |
| 工具服务 API Key（可选） | `custom_tool.yml` → 创建工具时填 Credentials（请求头 `X-Api-Key`），同时设 `TOOL_API_KEY` 环境变量 | `replace-with-a-random-token`（**占位值**） |

**如果你的 Dify 工作区里没有 OpenAI 插件**：导入 `app.yml` 后打开「阿灯·推理」节点，
在下拉框里改成你自己已配置的模型即可；或者把 `app.yml` 中 LLM 节点的 `provider` / `name` 改成你的模型，
再删掉顶部的 `dependencies` 段。

---

## 6. 完整部署步骤（从零到能玩）

### 6.1 启动 seekdb

**方式 A：Docker（推荐，与评审环境一致）**

```bash
docker run -d --name seekdb -p 2881:2881 \
  -e OB_ROOT_PASSWORD=your-root-password \
  oceanbase/seekdb:latest
```

**方式 B：官方安装包 / 本机二进制**

Windows（官方 MSI 安装后）：

```powershell
cd <seekdb 安装目录>\bin
.\seekdb_manage.ps1 install     # 初始化 + 注册服务（需要管理员权限）
.\seekdb_manage.ps1 start
.```

Linux / macOS：用官方 Docker 镜像（方式 A）最省事。

启动后自检：

```bash
mysql -h 127.0.0.1 -P 2881 -u root -p -e "SELECT VERSION();"
```

### 6.2 安装工具服务依赖

```bash
cd dify/service
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 6.3 配置工具服务

```bash
cp .env.example .env      # Windows: copy .env.example .env
# 编辑 .env：至少确认 SEEKDB_HOST / SEEKDB_PORT / SEEKDB_USER / SEEKDB_PASSWORD / SEEKDB_DATABASE
```

```ini
# .env（全部是占位值）
SEEKDB_HOST=127.0.0.1
SEEKDB_PORT=2881
SEEKDB_USER=root
SEEKDB_PASSWORD=your-seekdb-password
SEEKDB_DATABASE=wuyin_archive
SEEKDB_CHARSET=utf8mb4
TOOL_HOST=0.0.0.0
TOOL_PORT=8100
TOOL_API_KEY=
```

### 6.4 初始化数据

```bash
# 方式 A：用 mysql 客户端
mysql -h 127.0.0.1 -P 2881 -u root -p < init_data.sql

# 方式 B：不需要 mysql 客户端（脚本会自己切分并逐条执行）
python smoke_test.py --init
```

会建库 `wuyin_archive` 与 6 张表，并灌入初始数据。
脚本最后一段是**可选的全文索引**（`ALTER TABLE ... ADD FULLTEXT KEY ...`）；
如果你的 seekdb 版本不支持，这几条会报错但**不影响前面的数据**，工具服务会自动退回 LIKE 检索。

> **Windows 上务必用 `--no-fulltext`（或 `DIFY_FULLTEXT=off`）**：
> seekdb 1.3.0 在 Windows 上执行 `ADD FULLTEXT KEY` **可能让服务端进程崩溃**（本机复现两次，
> 现象是连接被断开、实例退出）。这不是本作品的代码问题。跳过全文索引后，检索全部走 LIKE，
> 功能完全一致：
>
> ```bash
> # 方式 A'：不创建全文索引（Windows 推荐）
> python smoke_test.py --init --no-fulltext
>
> # 方式 B'：等价的写法
> DIFY_FULLTEXT=off python smoke_test.py --init
> ```
>
> `DIFY_FULLTEXT` 三档：`auto`（默认，缺索引就建、失败退回 LIKE）、`on`（只用全文索引）、
> `off`（一次都不建，直接用 LIKE）。`/health` 会返回 `fulltext_mode` 与 `fulltext_enabled`。

### 6.5 启动工具服务

```bash
python app.py          # 或： uvicorn app:app --host 0.0.0.0 --port 8100
```

自检：

```bash
curl http://127.0.0.1:8100/health
```

期望看到：

```json
{
  "service": "wuyin-archive-tool",
  "version": "1.0.0",
  "seekdb": { "ok": true, "version": "5.7.25-...-seekdb", "database": "wuyin_archive", "missing_tables": [] },
  "fulltext_enabled": true,
  "auth_required": false
}
```

### 6.6 外部服务的获取与配置：在 Dify 里创建自定义工具（**先做这一步**）

1. Dify → **工作室 → 工具 → 自定义 → 创建工具**
2. 方式一：把 `custom_tool.yml` 的内容粘贴进"Schema"文本框。
   方式二：点"导入"上传 `custom_tool.yml` 文件。
3. **确认服务器地址**：Schema 里的 `servers[0].url` 必须是 Dify 能访问到的工具服务地址
   - Dify 跑在 Docker 里 → `http://host.docker.internal:8100`
     （Linux 上需要在 `docker-compose.yaml` 的 `api` 服务下加
     `extra_hosts:
  - "host.docker.internal:host-gateway"`）
   - Dify 直接跑在本机 → `http://127.0.0.1:8100`
4. 保存。工具列表里应出现 **3 个工具**：
   `search_archive`、`get_player_progress`、`record_progress`。
5. 如果你给 `TOOL_API_KEY` 填了值，在这里点「鉴权」→ 类型选 **Header** → 键名 `X-Api-Key` → 值填同一个 token。

### 6.7 导入 Dify 应用 DSL

1. Dify → **工作室 → 工作室资源 → 导入 DSL** → 上传 `app.yml`。
2. 导入后打开应用《雾隐镇 · 夜班档案室》。

> ⚠️ **必须做一步手动绑定**：Dify 的自定义工具用 **provider_id（工作区内部 UUID）** 标识，
> 而这个 UUID 在每个工作区都不一样，所以导入 DSL 后 4 个「工具」节点会显示为"未绑定/失效"。
> 逐个点开工具节点，在下拉框里选中你刚创建的那个工具（`search_archive` / `get_player_progress` / `record_progress`），
> 参数绑定会**自动按名字填好**（因为 DSL 里参数名与 OpenAPI 的 property 名一致），确认后保存即可。
> 详细说明见 `验证样例.md` `5。

### 6.8 配置模型

打开「阿灯·推理」节点 → 模型下拉框 → 选择你工作区里已配置好的 chat 模型 → 保存。

### 6.9 应用入口

| 入口 | 地址 |
|------|------|
| Web 应用（主要入口） | Dify 控制台 → 工作室 → 应用《雾隐镇 · 夜班档案室》 → 右上角「运行」/「预览」→ `http://<你的Dify地址>/app/<app-id>` |
| API（可选） | `POST http://<你的Dify地址>/v1/chat-messages`，Header `Authorization: Bearer <app-api-key>`，Body 见 `验证样例.md` `6 |

**进入应用后**：顶部表单填「侦探代号」和「接手案件」，然后直接在对话框里提问即可。

---

本作品需要的**外部服务只有一个**：§6.6 的这个自定义工具后端（`service/app.py`）。
它不需要从任何第三方获取——源码就在本仓库里，`pip install -r requirements.txt` 即可运行，不需要账号、密钥或付费资源。
唯一需要向外部获取的是**模型服务**（§5）：任意一个你能访问的 chat 模型 API。

## 7. Dify 访问服务所需的网络条件

| 方向 | 要求 |
|------|------|
| Dify（api 容器） → 工具服务 | 工具服务端口（默认 8100）可达。Docker 场景用 `host.docker.internal`；Linux 需 `extra_hosts` 映射 |
| 工具服务 → seekdb | seekdb 的 2881 端口可达（同机或同内网）。Docker 场景若 seekdb 也是容器，工具服务用容器名/服务名连 |
| Dify → 模型服务 | Dify 能访问你配置的模型供应商 API（公网或内网代理） |

**不需要**对外暴露 seekdb，也不需要把 2881 开放到公网。

---

## 8. 必要的资源条件

| 项目 | 最低要求 |
|------|---------|
| CPU / 内存 | seekdb 建议 ≥ 2 核 / 4 GB；工具服务 < 200 MB；Dify 本身 ≥ 2 核 / 4 GB |
| 磁盘 | seekdb 数据目录 ≥ 5 GB（含 redo 日志）；Dify ≥ 10 GB |
| 端口 | 2881（seekdb）、8100（工具服务）、80/443（Dify） |
| 网络 | 工具服务与 seekdb、Dify 与工具服务之间互通即可 |
| 其他 | 无需 GPU；不需要 Embedding / Rerank 服务 |

---

## 9. 已知功能限制

1. **中文分词是"语料反查"式的**：服务端把问句切成 2/3-gram，再只保留**在 seekdb 语料里真实出现过**的字串。
   这对"雾钟""铜锤"这类词很准，但对**库里完全没有的词**（比如你问"外星人"）会检索不到——这是刻意的，
   目的是让阿灯"查不到就说查不到"，不编造。
2. **全文检索受 seekdb 分词器影响**：`MATCH(...) AGAINST(...)` 使用 seekdb 自带的分词器，
   对中文的召回不一定比 LIKE 好。因此服务把 **LIKE 作为兜底**，FULLTEXT 只作为"命中则加分"的附加条件；
   `/health` 与每次检索的 `strategy` 字段会告诉你当前用的是 `fulltext+like` 还是 `like`。
3. **检索是"全表扫描 + 内存打分"**：当前数据量（4 案 / 21 物证 / 8 镇民 / 8 镇志）下毫秒级返回。
   数据量很大时应改为带索引的分页检索。
4. **单案绑定**：一次只查一个案件（`case_id`）。想跨案搜，把 `case_id` 传空串。
5. **自定义工具需要手动重新绑定**：Dify 的 DSL 不携带工作区内部 UUID，导入后必须手动选一次工具（`6.7）。这是 Dify 的机制限制，不是本作品的设计。
6. **结案条件是硬编码的**：关键物证 ≥ 2 条且仍有未排除的嫌疑人。改规则要改 `app.yml` 里「判定结案条件」节点的 Python。
7. **模型依赖**：必须配置一个 chat 模型，否则「阿灯·推理」节点会失败。检索与写回本身不依赖模型（可用 `smoke_test.py` 单独验证）。
8. **写回是"最终一致"的**：阿灯的回答里如果没写 `【EV-xxxx】` 编号，系统会退回用检索阶段的默认物证列表——因此提示词里明确要求了标注格式。
9. **只读用户不行**：`root` 或对 `wuyin_archive` 有 SELECT/INSERT/UPDATE 权限的账号即可，不需要 DBA。
10. **Windows + seekdb 1.3.0 建全文索引会崩服务端**（平台问题，本机复现两次）：
    初始化与启动都用 `DIFY_FULLTEXT=off`（或 `smoke_test.py --init --no-fulltext`）走 LIKE 路径。
    本机实测：`DIFY_FULLTEXT=off` 下初始化 **20/20 条语句**成功，真实 seekdb 端到端冒烟 **19/19 通过**
    （真实 SELECT、跨会话进度读取、写回与结案 UPSERT、直连数据库复核落库）；
    `--offline` mock 模式同样 **19/19 通过**。

---

## 10. 配置示例（占位值汇总）

本仓库**不包含任何真实密钥**。所有需要替换的位置：

| 位置 | 占位值 |
|------|--------|
| `service/.env.example` → `SEEKDB_PASSWORD` | `replace-with-your-seekdb-password` |
| `service/.env.example` → `TOOL_API_KEY` | 留空 = 不鉴权；或 `replace-with-a-random-token` |
| `custom_tool.yml` → `servers[0].url` | `http://host.docker.internal:8100` |
| Dify 模型供应商 API Key | `sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| Dify 自定义工具 Credentials（若启用鉴权） | 头 `X-Api-Key`，值与 `TOOL_API_KEY` 一致 |

---

## 11. 来源与改动声明

| 内容 | 来源 | 改动 |
|------|------|------|
| Dify 应用 DSL 结构（`version/kind/app/workflow.graph` 骨架、节点与边的字段格式） | 参考 Dify 官方仓库 `langgenius/dify` 的公开示例文件：`api/tests/fixtures/workflow/http_request_with_json_tool_workflow.yml`、`basic_chatflow.yml`、`conditional_hello_branching_workflow.yml`、`conditional_parallel_code_execution_workflow.yml`、`scripts/stress-test/setup/dsl/workflow_llm.yml` | **仅参考字段格式**；节点、提示词、连线、业务逻辑全部为本作品原创 |
| 自定义工具 OpenAPI 解析规则 | Dify 源码 `api/core/tools/utils/parser.py`（`ApiBasedToolSchemaParser`） | 仅据此确保 `custom_tool.yml` 能被 Dify 正确解析；schema 内容为本作品原创 |
| 模型插件依赖标识 `langgenius/openai:0.2.5@373362a......` | Dify 仓库 `scripts/stress-test/setup/dsl/workflow_llm.yml` 中公开的 marketplace 标识 | 原样引用，评审可在 Dify 中改成自己的模型 |
| 雾隐镇人物、案件、物证、镇志、对话文本 | **本作品原创**（虚构） | — |
| `service/app.py`、`service/smoke_test.py`、`service/init_data.sql` | **本作品原创** | — |
| 第三方代码 | 未复制任何第三方源码 | 仅依赖 fastapi / uvicorn / pymysql 三个公开包 |

---

## 12. 一键验证（评审最快路径）

```bash
cd dify/service

# 0) 起一个不依赖数据库的离线自检（验证 HTTP 契约与编排逻辑）
python smoke_test.py --offline

# 1) 初始化 seekdb
python smoke_test.py --init

# 2) 起服务 + 真实端到端（会自动拉起 app.py，跑完自动关闭）
python smoke_test.py

# 3) 把测试数据清干净、案件状态复原
python smoke_test.py --reset
```

`python smoke_test.py` 的真实模式会依次验证：`/health` 连通性 → `/search_archive` 检索 →
`/get_player_progress` 跨会话记忆 → `/record_progress` 写回 → **直连 seekdb 复核行是否真的落库** → 复原案件状态。
完整样例与证据见 `验证样例.md`。
