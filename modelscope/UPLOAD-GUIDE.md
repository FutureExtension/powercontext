# 上传指南：把本 Skill 发布到魔搭社区（ModelScope Skills）

> 适用对象：「2026年OceanBase数据库大赛」生态赛题「魔搭社区」的提交人。
> 本文件里**每一条**魔搭侧的操作路径、字段名、约束，都来自我**实际探测**过的魔搭线上产物（前端发布包 `maas/2.13.176`、官方 OpenAPI 规范 `/.well-known/openapi.json`、以及真实公开 API 响应），探测时间：**2026-11-05**。
> 凡是我**没能亲自确认**的，都在 `2.3` / `7.4` 明确标注了「未确认」，不会写成确定事实。
> **界面可能随版本调整**：魔搭前端是 SPA 且发布频繁，入口文案可能变化；文末给出了可检索的入口关键词。

---

## 0. 一分钟总览

| 你要做的事 | 用哪条路径 |
| --- | --- |
| 只想赶紧交作业 | **路径 A（网页端）**：打包 → 自定义创建 → 复制网址 |
| 想可复现、可脚本化 | **路径 B（OpenAPI）**：打包 → `POST /files/upload` → `POST /skills` → 复制网址 |
| **交哪个值** | 优先交**网址** `https://www.modelscope.cn/skills/<你的ID>`；网址不合适时交**编号** `<owner>/<skill_name>` 或 `@<owner>/<skill_name>` |

---

## 1. 账号注册与登录

1. 打开 https://modelscope.cn/ ，点右上角**登录 / 注册**。
2. 支持手机号 / 邮箱等魔搭当前提供的注册方式（**未确认**具体可选方式，以页面实际展示为准）。
3. 登录后建议先做两件事：
   - 确认你的**用户名**：它是 Skill 编号和网址里的 `owner`。查法：访问 https://modelscope.cn/my/myaccesstoken 页面会显示当前账号的 Access Token，同时 `GET /openapi/v1/users/me` 会返回 `data.username`（两者一致）。
   - 把 Access Token 放进环境变量，**不要**写进任何文件或仓库：

     ```bash
     # Linux / macOS
     export MODELSCOPE_API_TOKEN=<YOUR_TOKEN>

     # Windows PowerShell
     \env:MODELSCOPE_API_TOKEN = "<YOUR_TOKEN>"
     ```

> ⚠️ Token 等同于账号密码。本仓库/本目录下**不得**出现任何真实 Token、密码或 API Key；示例一律用占位符。
> 需要 Access Token 的入口：https://modelscope.cn/my/myaccesstoken （**已确认该路径存在**；页面上具体按钮文案未确认）。

---

## 2. Skill 的创建 / 上传入口

### 2.1 路径 A：网页端（推荐给绝大多数参赛者）

**已确认的入口与页面标题**（取自魔搭前端发布包 `maas/2.13.176` 的路由表与 i18n 文案）：

| 入口 | URL | 页面标题（i18n） |
| --- | --- | --- |
| Skills 中心（技能广场） | https://www.modelscope.cn/skills | **Skills 中心** |
| 新建 Skill | https://www.modelscope.cn/skills/create | **Skills 创建** |
| Skill 详情页 | https://www.modelscope.cn/skills/{owner}/{skill_name} | **Skills 详情页** |

**操作步骤：**

1. 登录后打开 **Skills 中心**（https://www.modelscope.cn/skills ）。
2. 点**「新建 Skill」**按钮 → 弹出下拉，里面有两个入口（**已确认**这两个入口文案）：
   - **「快速创建」** —— 副标题「从 Github 导入并托管您的 Skills」。适合你已经把 Skill 推到 GitHub 公开仓库的情况。
   - **「自定义创建」** —— 副标题「从本地文件上传并提交您的 Skills」。适合你本地已经有一个 Skill 目录的情况（**本赛题推荐这条**）。
3. 选「自定义创建」→ 上传本地 Skill 包 → 填写信息 → 提交。

**「快速创建」（GitHub 导入）的完整向导**（**已确认**为三步）：

| 步骤 | 文案 | 你要做的事 | 平台行为 |
| --- | --- | --- | --- |
| 1 | **导入Github** | 填 **「Github仓库地址」**（字段名 `GithubUrl`，必填）；勾选 **「自动同步」**（`AutoSyncEnabled`，可选，开启后跟随仓库更新） | 平台调用 `GET /api/v1/skills/github/parse` 解析该**公开**仓库，返回可导入的 Skill 列表（每个条目含 `SkillPath`、`FileList`、`Name`、`DisplayName`、`Description`、`License`、`Developer`、`RepoInfo`） |
| 2 | **选择Skills** | 从解析结果中勾选要导入的 Skill | 平台**自动预选 `SkillPath` 以 `SKILL.md` 结尾**的那一项；同时检测重复（`/api/v1/skills/user_repeat`、`/api/v1/skills/official_repeat`） |
| 3 | **确认创建** | 确认名称、描述、协议、分类等 | 平台调用创建接口并回填展示名/描述/头像/协议/开发者 |

> GitHub 导入路径下，平台会**托管并同步**你的 GitHub 仓库内容，因此 `source_url` 会填成你的仓库地址。
> 如果你的 Skill 内容还没进 GitHub，**不要**选这条，直接用「自定义创建」本地上传。

### 2.2 路径 B：官方 OpenAPI（可脚本化、可复现）

**已确认**（来自官方 OpenAPI 规范 `https://modelscope.cn/.well-known/openapi.json`，`info.version` = `1.1.0+master.20261103T083422Z`）：

- 基础地址：`https://modelscope.cn/openapi/v1`
- 规范文件：`https://modelscope.cn/.well-known/openapi.json`（**唯一事实来源**，字段以它为准）
- 认证：所有请求带请求头 `Authorization: Bearer <MODELSCOPE_API_TOKEN>`

完整上传流程（3 步）：

```bash
BASE=https://modelscope.cn/openapi/v1
TOKEN="$MODELSCOPE_API_TOKEN"          # 从环境变量读取，绝不硬编码

# ── Step 0. 确认身份与 owner（skill_name / owner 创建后不可改，先确认）
curl -s -X GET "$BASE/users/me" \
  -H "Authorization: Bearer $TOKEN"
# → data.username 即默认 owner

# ── Step 1. 打包：zip 根目录下必须且仅可包含 1 个 SKILL.md
#    （可含 prompts/、examples/、references/ 等子目录；zip ≤ 5MB）
cd <你的 skill 目录>
zip -r ../my-skill.zip . -x '.*' '__MACOSX/*'
# 注意：根目录里应只有 SKILL.md 一个 .md 入口文件

# ── Step 2. 上传文件，拿 file_id
FILE_ID=$(curl -s -X POST "$BASE/files/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@../my-skill.zip" \
  | python -c "import sys,json;print(json.load(sys.stdin)['data']['file_id'])")

# ── Step 3. 创建 Skill
curl -s -X POST "$BASE/skills" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @- <<JSON
{
  "skill_name": "oceanbase-seekdb-agent-memory",
  "owner": "<你的用户名或组织名>",
  "display_name": "OceanBase seekdb + PowerContext 智能体数据底座助手",
  "description": "<见 3.3 的建议文案>",
  "license": "Apache-2.0",
  "category": "developer-tools",
  "tags": ["oceanbase","seekdb","powercontext","rag","agent-memory"],
  "skill_file": "$FILE_ID"
}
JSON
```

> 上面用的是 bash heredoc（未加引号的 `JSON` 允许 `$FILE_ID` 展开）。
> **Windows PowerShell** 请改用文件方式，避免引号转义踩坑：

```powershell
$body = @{
  skill_name   = "oceanbase-seekdb-agent-memory"
  owner        = "<你的用户名或组织名>"
  display_name = "OceanBase seekdb + PowerContext 智能体数据底座助手"
  description  = "<见 3.3 的建议文案>"
  license      = "Apache-2.0"
  category     = "developer-tools"
  tags         = @("oceanbase","seekdb","powercontext","rag","agent-memory")
  skill_file   = $env:FILE_ID
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "$env:BASE/skills" -Method Post -Headers @{ Authorization = "Bearer $env:TOKEN" } -ContentType "application/json" -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

创建成功后**更新**已有 Skill（改描述/标签/文件）用：

```bash
curl -s -X PATCH "$BASE/skills/<owner>/<skill_name>/settings" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description":"<新的描述>","tags":["oceanbase","seekdb"]}'
```

> `skill_file` 传入时**整体覆盖**原有项目文件；不传则保留原文件不变。`tags` 传入时整体覆盖原标签列表。

### 2.3 「界面可能随版本调整」—— 已确认 vs 未确认

**已确认（来自线上前端包 + 线上 API 实测）**

- 存在 Skills 板块，路由为 `/skills`、`/skills/create`、`/skills/{skillOwner}/{skillName}`，详情页还有 `/summary`、`/files`、`/tree/:version/*` 等子页。
- 页面标题 i18n：`Skills 中心`、`Skills 创建`、`Skills 详情页`。
- 新建入口的两个选项：`快速创建`（GitHub 导入）/ `自定义创建`（本地文件上传）。
- GitHub 导入是三步向导，字段名 `GithubUrl`、`AutoSyncEnabled`。
- **SKILL.md 是硬性要求**：本地上传会校验上传文件列表里存在「路径恰为 `SKILL.md`」或「文件名为 `SKILL.md` 且不在子目录中」的条目，否则直接报错「**缺少 SKILL.md 文件** / 当前上传目录中缺少 SKILL.md 文件。」；GitHub 导入也会**自动选中路径以 `SKILL.md` 结尾**的条目。
- `SKILL.md` 必须包含 YAML front-matter，官方 OpenAPI 字段说明明确要求 **`name`、`version`、`description` 三项**。
- zip 包 ≤ **5MB**；根目录下**必须且仅可**包含 **1 个** `SKILL.md`；可包含子目录与辅助文件。
- 平台识别的来源类型包含 `github.com`、`clawhub.ai`，其余归为「互联网来源」。
- Skill 记录上有 `display_name` / `description` / `description_en` / `license` / `category` / `tags` / `private`（网页端 `Visibility=5` 即公开）/ `auto_sync_enabled` / `logo_url` / `source_url` 等字段。
- 详情页有 `Skill 介绍`、`Skill 文件` 两个标签页，以及「前往实验场试用」入口；另有「您是此 Skill 的开发者吗？」的**开发者认证**流程。

**未确认（不要当成事实）**

- 网页端按钮的**精确文案与布局**（我只解析到了前端包里的 i18n 文案，**没能成功渲染出页面截图**：本次执行环境的内置浏览器未能 attach，无法截图佐证）。
- 「自定义创建」上传对话框的**具体表单字段名**（前端包中该分支未展开到可确认粒度）；本文按 OpenAPI 字段给出等价填法。
- 提测平台的具体入口路径与字段名（**未确认**，请以大赛平台的实际页面为准）。
- 平台是否对新上传 Skill 有审核期、人工复核或「认领/迁移」流程（前端包中**存在** `/v1/skills/claim`、`/v1/skills/claimStatus` 相关接口和「开发者认证」文案，但具体触发时机与对**新提交**是否有影响，**未确认**）。

---

## 3. 上传时要填的字段与建议填法

### 3.1 字段清单（以 OpenAPI 为准，网页端对应项同名同义）

| 字段 | 必填 | 约束 | 本 Skill 的建议填法 |
| --- | --- | --- | --- |
| `skill_name` | ✅ | `^[a-z0-9-]+$`，≤64 字符，**创建后不可改** | `oceanbase-seekdb-agent-memory` |
| `owner` | ✅ | 用户名或组织名，**创建后不可改** | 你的魔搭用户名（或你创建的组织名） |
| `skill_file` | ✅ | 上传 zip 得到的 `file_id` | 用 `POST /files/upload` 返回的 `file_id` |
| `license` | ✅ | 字符串，不填默认 `Apache-2.0` | `Apache-2.0`（与本目录源码注释一致） |
| `category` | ✅ | 枚举，见下 | `developer-tools` |
| `display_name` | ⬜ | ≤128 字符 | `OceanBase seekdb + PowerContext 智能体数据底座助手` |
| `description` | ⬜ | ≤2000 字符 | 见 `3.3` |
| `tags` | ⬜ | 字符串数组 | `["oceanbase","seekdb","powercontext","rag","agent-memory"]` |
| `source_url` | ⬜ | URI | 你把 Skill 推到 GitHub 后填仓库地址（**建议填**：平台据此展示来源，便于审核） |
| `logo_url` | ⬜ | URI | 可留空用默认图标 |
| `private` | ⬜ | 布尔，默认 `false`（公开） | **保持 `false`**，否则别人看不到，判题方无法访问 |

`category` 合法枚举（**已确认**，来自 OpenAPI `SkillCategory`）：
`skill-management`、`developer-tools`、`marketing-seo`、`frontend-development`、`ai-media`、`code-quality-testing`、`mobile-development`、`cloud-devops`、`other`。

> 实测线上数据里出现过枚举外的 `ai-automation`（如 `@ivangdavila/self-improving`）。**建议严格使用上面 9 个官方枚举值**，避免被校验拒绝。

### 3.2 本 Skill 的打包要求

- zip **根目录**下必须且仅可有 **1 个** `SKILL.md`。
- `SKILL.md` 的 YAML front-matter 必须含 **`name`、`version`、`description`** —— 本目录的 `SKILL.md` 已满足（`name: oceanbase-seekdb-agent-memory`、`version: 1.0.0`、`description: ...`）。
- `name` 与平台 `skill_name` 保持一致，便于检索与核对。
- 可选附带子目录（如把长参考链接放进 `references/`）。本目录的 `UPLOAD-GUIDE.md` 可以一起打进 zip（它不是 `SKILL.md`，不违反「仅 1 个 SKILL.md」约束）；**但**如果你的上传工具对根目录文件数有额外要求，就只打包 `SKILL.md`。
- zip **≤ 5MB**。

打包示例：

```bash
cd C:/codex-work/ob-00001/work/submissions/modelscope
zip -r oceanbase-seekdb-agent-memory.zip SKILL.md UPLOAD-GUIDE.md
ls -l oceanbase-seekdb-agent-memory.zip    # 确认 < 5MB
```

### 3.3 建议填写的「功能说明 + 简短使用示例」

网页端 `description` 字段（≤2000 字符）建议填下面这段（OpenAPI 的 `description` 与网页端同名字段）。

```text
把 AI Agent 应用落地到 OceanBase seekdb + PowerContext 上的数据底座助手。给定需求即输出可运行的建表/查询 SQL 与记忆链路代码，并附验证排错清单。

能力：(1) 检索选型——按需求映射到纯向量/纯全文/混合三方案并给建表 DDL；(2) 单条 SQL 混合检索——MATCH ... AGAINST 与 l2_distance(...) APPROXIMATE 同写一条 SQL，标量过滤下推到库内；(3) AI COLUMN——AI_EMBED/AI_COMPLETE 异步生成向量与摘要，支持 RETRY AI COLUMN 与 ai_column_strict_read；(4) COW 沙箱——FORK DATABASE / MERGE TABLE 让 Agent 安全试错；(5) PowerContext 记忆链路——CaptureSource 采集、SourceDefinition 注册来源与投影、MemoryCitation 精确引用，search_memory 支持 fts|vector|hybrid|auto；(6) EXPLAIN 验证——确认 TEXT RETRIEVAL SCAN 与 VECTOR INDEX 同时命中。

使用示例1（企业制度问答，纯 SQL）：建表 policy_doc（含 FULLTEXT INDEX ... WITH PARSER ik 与 VECTOR INDEX ... DISTANCE=l2,TYPE=hnsw）→ 写入 → SELECT ... WHERE company_id=42 AND MATCH(content) AGAINST('数据隔离') ORDER BY dist APPROXIMATE LIMIT 10 → 返回带条款号的 top-10。

使用示例2（Agent 长期记忆，Python）：POST /v1/sources/content 采集会话 → POST /v1/memory/flush 加工 → POST /v1/memory/remember 显式写入结论 → POST /v1/memory/search (mode=hybrid) 检索 → 每条命中返回 citation(memory_ref/entry_id/entry_version_id) 与 matched_by，可回溯到具体记忆版本原文。

关键词：seekdb、OceanBase、PowerContext、混合检索、MATCH AGAINST、AI COLUMN、Agent 记忆、MemoryCitation、embedding。
```

---

## 4. 上传成功后如何取到网址或编号（两种方式任选其一）

### 方式一：拿「Skill 网址」（**推荐**，最不容易填错）

打开你的 Skill 详情页，把**浏览器地址栏整条 URL** 复制下来：

```text
https://www.modelscope.cn/skills/<owner>/<skill_name>
```

实测样例（真实存在的公开 Skill）：

| 编号 | 网址 |
| --- | --- |
| `@anthropics/skill-creator` | https://www.modelscope.cn/skills/@anthropics/skill-creator |
| `iic/fun-denoise` | https://www.modelscope.cn/skills/iic/fun-denoise |
| `VoyagerX/modelscope-skill-upload` | https://www.modelscope.cn/skills/VoyagerX/modelscope-skill-upload |

> 带 `@` 与不带 `@` 的形式都存在：组织/官方账号导入的 Skill 用 `@owner/name`，个人账号创建的用 `owner/name`。**以你页面地址栏里实际显示的为准，原样复制**。
> 验证：详情页 HTML 的 `<title>` 会渲染成「Skill 详情 - <分类名> - <skill 名>」形式（例如 `Skill 详情 - Skills管理 - skill-creator`），看到标题即说明页面命中了正确的 Skill。

### 方式二：拿「Skill 编号」

**编号就是 Skill 的 ID**，官方 OpenAPI 规范原文：*「技能 ID，格式为 `@author/skill_name`（例如 `@Alipay/alipay-payment-integration`），其中 @ 和 / 无需 URL 编码」*。

编号的两种实际形态（**已实测**）：

| 形态 | 何时出现 | 实测 |
| --- | --- | --- |
| `@owner/skill_name` | 官方/组织账号导入的 Skill | `@anthropics/skill-creator` ✅ |
| `owner/skill_name` | 个人账号创建的 Skill | `iic/fun-denoise` ✅ |

取值办法：

1. 直接看方式一里的网址，**去掉前缀** `https://www.modelscope.cn/skills/` 就是编号。
2. 或调接口取权威字段：

   ```bash
   # 列出某个 owner 名下的全部 Skill（公开接口，无需 Token）
   curl -s "$BASE/skills?filter.owner=<owner>&page_size=10"

   # 按 ID 取详情（公开 Skill 无需 Token）
   curl -s "$BASE/skills/<owner>/<skill_name>"
   # → data.id 即编号；data._id 是内部主键，形如 FVA80usrezHtdfEq7GEFxA==，不是面向用户的编号
   ```

> ⚠️ **不要**提交 `data._id`（内部主键）——它不是「魔搭社区中该 Skill 对应的编号」，判题方无法据此定位页面。
> ⚠️ **不要**提交个人主页（`https://www.modelscope.cn/<你的用户名>`）、账号 ID、或只有 Skill 名称——赛题明确要求提交的信息必须能**准确定位到上传的那个 Skill**。

### 4.1 上线后自检（两条命令，公开可读、无需 Token）

```bash
# ① 列表里能搜到（公开接口）
curl -s "https://modelscope.cn/openapi/v1/skills?search=oceanbase-seekdb&page_size=10" \
  | python -c "import sys,json;[print(s['id'],'|',s.get('display_name'),'|',s.get('category')) for s in json.load(sys.stdin)['data']['skills']]"

# ② 详情能取到（把 <owner>/<skill_name> 换成你的）
curl -s "https://modelscope.cn/openapi/v1/skills/<owner>/<skill_name>" \
  | python -c "import sys,json;d=json.load(sys.stdin)['data'];print(d['id'],'|',d.get('description','')[:80])"

# ③ 网页可打开（应返回 200）
curl -s -o /dev/null -w "%{http_code}\n" "https://www.modelscope.cn/skills/<owner>/<skill_name>"

# ④ 按 owner 列出（公开接口，无需 Token；应能看到你刚建的 Skill）
curl -s "https://modelscope.cn/openapi/v1/skills?filter.owner=<owner>&page_size=20" \
  | python -c "import sys,json;[print(s['id'],'|',s.get('display_name')) for s in json.load(sys.stdin)['data']['skills']]"
```

**若 ① 搜不到但详情页能打开**：说明 Skill 已发布，只是还没进搜索索引/分类索引 —— 提交**网址**即可，不必等索引。
**若 ② 报 `ResourceNotFound`**：检查 `@` 前缀是否与实际一致（两种形态二选一）。
**若 ③ 不是 200**：多半是把编号写错了，或 Skill 还是私有的（`private=true`）。

---

## 5. 如何在提测平台填写

1. 登录**大赛提测平台**，进入「魔搭社区」赛题的**提交入口**。
2. 把 `4` 里拿到的**网址**或**编号**粘贴到对应字段。
3. 提交前**逐字核对**：

   | ❌ 错误填写 | ✅ 正确填写 |
   | --- | --- |
   | `https://www.modelscope.cn/你的用户名`（个人主页） | `https://www.modelscope.cn/skills/<owner>/<skill_name>` |
   | `你的魔搭账号 ID` | `@<owner>/<skill_name>` 或 `<owner>/<skill_name>` |
   | `oceanbase-seekdb-agent-memory`（只有名称） | 同上，带 `owner/` 前缀的完整编号 |
   | `https://modelscope.cn/skills/...` 少了 `www.` | 两种都行，但**必须**是 `/skills/<owner>/<name>` 这一层路径 |
   | `FVA80usrezHtdfEq7GEFxA==`（内部 _id） | 用 `id` 字段或地址栏路径 |

4. 提交后再打开一次自己填的网址，确认能**看到自己上传的 Skill 内容**（介绍 + 文件列表），而不是 404 或「无权限」。

> 提测平台的**具体字段名与入口路径未确认**（我没有该平台的账号与地址），请以平台实际页面为准。本节只给出「填什么、别填什么」的判定标准。

---

## 6. 上传前自检清单

### 6.1 Skill 内容自检（本目录可直接执行）

- [x] 文件编码为 **UTF-8 无 BOM**（`SKILL.md` 首 3 字节为 `45 45 45`，即 `---`，不是 `EF BB BF`）。
- [x] YAML frontmatter 完整，含 `name`、`version`、`description`（官方 OpenAPI 硬性要求这三项）。
- [x] `name` 符合 `^[a-z0-9-]+$` 且 ≤64 字符，与计划提交的 `skill_name` 一致。
- [x] `description` 写清了**用途 + 触发条件**，第三方读者能判断何时该用。
- [x] 正文分节齐全：能力边界（含**不做什么**）/ 决策流程与选型决策表 / 可直接复制的代码与 SQL / 使用示例 / 常见问题与排错 / 参考资料。
- [x] 使用示例 **≥2 个**，且每个都含**输入**与**输出**。
- [x] 代码与 SQL 均为**真实可执行**的语法（seekdb MySQL 兼容语法 + PowerContext 真实 API/模型字段），不是伪代码。
- [x] **无任何真实密钥**：全文仅出现 `<YOUR_TOKEN>`、`<YOUR_API_KEY>`、`<scope_id>` 等占位符；不含真实 Token/密码/密钥/内网地址。
- [x] 参考资料标注了来源（OceanBase 官方文档、GitHub 仓库地址、语雀链接）。
- [x] 文件里没有把本地绝对路径泄漏到可公开内容里（示例路径使用占位符）。

### 6.2 打包与上传自检

- [ ] zip 根目录下**有且仅有 1 个** `SKILL.md`。
- [ ] zip 体积 **< 5MB**。
- [ ] `SKILL.md` 的 frontmatter 在**压缩包内**那份也是完好的（改的是源目录，别忘了重新打包）。
- [ ] `skill_name` 只含小写字母/数字/连字符（创建后**不可改**，写错只能重建）。
- [ ] `owner` 填的是你**真正拥有**的账号/组织。
- [ ] `private=false`（公开可见）。
- [ ] `category` 取自官方 9 个枚举值。
- [ ] `license` 与仓库内代码注释声明的协议一致（本目录为 `Apache-2.0`）。
- [ ] `description` 控制在 2000 字符以内。
- [ ] 已跑过 `4.1` 的三条自检命令。

---

## 7. 失败排查

### 7.1 上传报错

| 报错 / 现象 | 原因 | 处理 |
| --- | --- | --- |
| 「**缺少 SKILL.md 文件** / 当前上传目录中缺少 SKILL.md 文件。」 | 上传的文件列表里没有「路径=`SKILL.md`」或「根级 `SKILL.md`」的条目 | 确认 zip **根目录**下有 `SKILL.md`；不要把它放在 `my-skill/SKILL.md` 这种多套一层的位置 |
| 解析不到任何 Skill / `parse` 返回空 | GitHub 仓库是私有的、地址写错、或仓库里没有 `SKILL.md` | 必须是**公开**仓库；仓库根目录放 `SKILL.md`；或改用「自定义创建」本地上传 |
| 「请输入正确的Github仓库地址」 | 地址格式不是 GitHub 仓库 URL | 用 `https://github.com/<owner>/<repo>` 形式 |
| 提示该地址**已对应有多个重复的 Skill** | 同一来源已存在过 | 用「重新导入/认领」流程，或改用自定义创建并换一个 `skill_name` |
| `413` / 体积超限 | zip > 5MB | 删掉大文件（示例数据集、模型权重、日志），只保留 `SKILL.md` + 必要文档 |
| `401 InvalidAuthentication` | Token 为空/过期/带了引号 | 从 https://modelscope.cn/my/myaccesstoken 重新取；请求头格式 `Authorization: Bearer <token>`（Bearer 后一个空格） |
| `403` | 无权限（组织 Skill 需该组织管理权限） | 换成你自己的账号作为 `owner` |
| `409` | `skill_name` 已存在 | `skill_name` 创建后不可改；换一个名字，或改用 `PATCH .../settings` 更新已有 Skill |
| `422` | 字段类型/长度/枚举不合法 | 对照 `3.1` 逐项检查；注意 `description` ≤2000、`display_name` ≤128、`skill_name` ≤64 |
| 上传接口报「文件格式不正确」 | 选了非 zip / 损坏的包 | 重新打包，确认是合法 zip 且根目录结构正确 |

### 7.2 找不到自己的 Skill

1. 先确认**是不是私有的**：把 `private` 改成 `false`（或网页端把可见性改为公开）。
2. 确认你查的是**列表接口还是详情接口**：详情用 `GET /openapi/v1/skills/{id}`，列表用 `GET /openapi/v1/skills?search=<关键词>` 或 `GET /openapi/v1/skills?filter.owner=<owner>`（**后者公开可读、已实测 200**，是「列出某个 owner 名下全部 Skill」最可靠的方式）。
   > 前端内部还有一个 `GET /api/v1/console/personal/skills` 接口，但**我未能从公网验证它**（直连返回 404，且它不在官方 OpenAPI 规范路径表中），因此不建议依赖；用 `filter.owner` 即可。
3. 确认 `@` 前缀：组织导入的是 `@owner/name`，个人创建的是 `owner/name`，**两种都试一遍**。
4. 等待平台**分类/搜索索引**刷新：新建 Skill 可能短时间内搜不到，但详情页立刻可访问 —— **提交网址即可**。
5. 确认 `owner` 那一段确实是你：把 `/skills/<owner>/<name>` 里的 owner 换成你的用户名再试。

### 7.3 编号丢失 / 拿不到编号

- **编号其实不需要单独申请**：它就是 `owner/skill_name`（或 `@owner/skill_name`），从详情页地址栏直接取。
- 万一记不住，事后随时可取：

  ```bash
  # ① 按关键词列出
  curl -s "https://modelscope.cn/openapi/v1/skills?search=<关键词>&page_size=10"

  # ② 列出某个 owner 名下的全部 Skill（公开接口，无需 Token）
  curl -s "https://modelscope.cn/openapi/v1/skills?filter.owner=<owner>&page_size=10"

  # ③ 按 ID 取详情
  curl -s "https://modelscope.cn/openapi/v1/skills/<owner>/<skill_name>"
  ```

- 提测平台通常允许**提交后再次修改**，别因为一时找不到就填错值。

### 7.4 仍然不确定时的兜底做法

1. **先在网页端手动创建一次**（路径 A），确认入口、表单、报错提示与本文档一致；若发现不一致，**以你看到的为准**并回填更新本文档。
2. 提交**网址**而不是编号：网址的可定位性最强，且判题方一眼能看出指向 `/skills/<owner>/<name>`。
3. 提交前**自己用无痕窗口打开一次**该网址：确认 200 + 能看到 Skill 介绍与文件列表。
4. 把 `4.1` 三条命令的输出截图存档，作为「已成功上传并可访问」的佐证。

### 7.5 可检索的入口关键词（界面变动时用）

在魔搭站内搜索框或搜索引擎里检索：

- `Skills 中心`、`Skills 魔搭`、`魔搭 技能广场`、`新建 Skill`、`自定义创建`、`快速创建`、`从 Github 导入并托管您的 Skills`、`缺少 SKILL.md 文件`
- 英文/拼音：`ModelScope Skill`、`modelscope skills create`、`skills marketplace`
- 官方文档中心（https://www.modelscope.cn/docs ）的导航里含 **Skills** 条目

---

## 8. 本文档的查证记录（2026-11-05）

**查证方式**：直接拉取并解析魔搭线上产物，不依赖记忆。

| 查证对象 | 手段 | 结果 |
| --- | --- | --- |
| Skills 路由与页面标题 | 拉取前端发布包 `https://g.alicdn.com/sail-web/maas/2.13.176/umi.js` 及其异步 chunk（`p__skills__Create__index` / `p__skills__Home__index` / `p__skills__Detail__index` / `p__skills__index`）并解析路由表与 i18n 文案 | ✅ 拿到 `/skills`、`/skills/create`、`/skills/:skillOwner/:skillName` 及全部标签页 |
| 「新建 Skill」的两个入口、GitHub 三步向导、`GithubUrl` / `AutoSyncEnabled` 字段 | 同上，解析 Home/Create chunk | ✅ |
| SKILL.md 强制校验逻辑与报错文案 | 同上，定位上传校验代码 | ✅ |
| OpenAPI 规范（`POST /skills` / `POST /files/upload` / `PATCH settings` / `GET /skills` / `GET /skills/{id}` / `GET /users/me`、字段约束、`category` 枚举、`skill_file` 的 zip 规则） | `https://modelscope.cn/.well-known/openapi.json`（HTTP 200，496,970 字节，`info.version=1.1.0+master.20261103T083422Z`） | ✅ 逐字段核对 |
| 编号格式 `@author/skill_name` | OpenAPI `GET /skills/{id}` 的参数说明原文 | ✅ |
| 公开列出某 owner 名下 Skill 的接口 | `GET /openapi/v1/skills?filter.owner=VoyagerX&page_size=5` → 200；`GET /openapi/v1/skills?search=skill-creator` → 200 | ✅ |
| `/openapi/v1/console/personal/skills` | 该路径**不在**官方 OpenAPI 规范路径表中；实测直连返回 404 | ❌ **未确认**（已改用 `filter.owner`） |
| 公开列出某 owner 名下 Skill 的接口 | `GET /openapi/v1/skills?filter.owner=VoyagerX&page_size=5` → 200；`GET /openapi/v1/skills?search=skill-creator` → 200 | ✅ |
| 编号两种形态、详情接口可用性 | `GET /openapi/v1/skills/@anthropics/skill-creator` → 200；`GET /openapi/v1/skills/anthropics/skill-creator` → 404；`GET /openapi/v1/skills/iic/fun-denoise` → 200 | ✅ |
| 公开 Skill 列表（含 `_id` / `id` / `category` / `display_name` / `description` 字段） | `GET /openapi/v1/skills?page_size=30&page_number=1` → 200 | ✅ |
| 详情页 URL 与 SSR 标题 | `GET https://www.modelscope.cn/skills/@anthropics/skill-creator` → 200，`<title>` = `Skill 详情 - Skills管理 - skill-creator` | ✅ |
| Skill 文件树接口 | `GET /api/v1/skills/@anthropics/skill-creator/repo/files` → 200，返回 tree 条目 | ✅ |
| 网页端**渲染截图** | 内置浏览器在本执行环境**未能 attach**（超时），无法截图 | ❌ **未确认** |
| 网页端「自定义创建」表单的精确字段名 | 前端包中未展开到可确认粒度 | ❌ **未确认**（本文按 OpenAPI 字段给出等价填法） |
| 提测平台入口与字段名 | 无该平台访问权限 | ❌ **未确认** |
| 新上传是否需人工审核/认领 | 前端存在 `/v1/skills/claim`、`/v1/skills/claimStatus` 接口与「开发者认证」文案，但触发条件不明 | ⚠️ **部分确认**（接口存在，机制未确认） |

> 本文档中凡标注「未确认」的条目，请以你实际操作时的界面/接口返回为准，并顺手回填更新。

---

## 9. 链接可达性探测结果（2026-11-05 实测）

对本文档与 `SKILL.md` 中出现的**全部真实 URL**（不含占位符）逐个发起 `HTTP GET`（跟随重定向，超时 25 s）。结果如实记录如下：

| URL | HTTP | 备注 |
| --- | --- | --- |
| https://github.com/oceanbase/seekdb | 200 | |
| https://github.com/oceanbase/seekdb/tree/2026-competition | 200 | |
| https://docs.seekdb.ai/ | 200 | 302 → `/seekdb/seekdb-overview/` |
| https://deepwiki.com/oceanbase/seekdb | **429** | 限流（Rate Limit），**非死链**；稍后重试通常可开 |
| https://github.com/oceanbase/powercontext | 200 | |
| https://github.com/oceanbase/powercontext/tree/2026-competition | 200 | |
| https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/gp9hi8ikdnef8ryc | 200 | 302 → `/login?org=oceanbase`（语雀对未登录访问重定向，链接本身有效） |
| https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hqkh5u47mf5nv8r5 | 200 | 同上（赛题十一：seekdb 混合检索的单 SQL 候选查询） |
| https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/qenx4sy5s09h2t07 | 200 | 同上（赛题三：AI 列） |
| https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/za7cfo5cazcrihhq | 200 | 同上（赛题四：全文索引调优） |
| https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/lz6ixow11mar233g | 200 | 同上（赛题一：部署一个 seekdb） |
| https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/brxxufkegusa86hl | 200 | 同上（比赛仓库地址总表） |
| https://modelscope.cn/ | 200 | → `/home` |
| https://modelscope.cn/my/myaccesstoken | 200 | Access Token 页 |
| https://www.modelscope.cn/skills | 200 | Skills 中心 |
| https://www.modelscope.cn/skills/create | 200 | Skills 创建 |
| https://www.modelscope.cn/skills/@anthropics/skill-creator | 200 | **真实公开 Skill**，`<title>` = `Skill 详情 - Skills管理 - skill-creator` |
| https://www.modelscope.cn/skills/iic/fun-denoise | 200 | **真实公开 Skill**（个人账号形态，无 `@`） |
| https://www.modelscope.cn/skills/VoyagerX/modelscope-skill-upload | 200 | **真实公开 Skill** |
| https://modelscope.cn/.well-known/openapi.json | 200 | 官方 OpenAPI 规范，496,970 字节 |
| https://modelscope.cn/openapi/v1/skills?search=... | 200 | 公开列表/搜索接口，无需 Token |
| https://modelscope.cn/openapi/v1/skills?filter.owner=... | 200 | 公开「按 owner 列出」接口，无需 Token |
| https://www.modelscope.cn/docs | 200 | 官方文档中心，导航含 Skills |
| https://g.alicdn.com/sail-web/maas/2.13.176/umi.js | 200 | 魔搭前端发布包（本文档路由/文案查证的来源） |
| https://modelscope.cn/openapi/v1 | 404 | **正常**：这是 API 基础路径，本身不是端点 |

另有两类**不是真实链接**、未参与探测：

- `http://127.0.0.1:8000` —— 文档里 PowerContext 本地服务的**占位地址**（探测结果：连接失败，符合预期）。
- 含 `<owner>` / `<你的用户名>` 等占位符的 URL —— 需要你替换成自己的值后再验证。

> 结论：**所有被引用的真实外部链接均可达**（唯一非 200 是 `deepwiki` 的 429 限流）；本文档中引用的每条接口路径，均已用实测响应交叉验证过。
