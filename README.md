# 2026 大赛生态方向交付物

本分支基于 `2026-competition-ecosystem`，按赛题要求把五份生态作品分别放在对应目录。
每个目录都带运行说明、验证样例和证据；提交时用本分支的 commit SHA。

| 赛题 | 目录 | 交付物 | 本机验证 |
|---|---|---|---|
| 高德开放平台 · 周边去哪儿 | `gaode/` | `SKILL.md`（Skill 文件）+ `README-notes.md`（提测备注） | 按题面逐条自检：需求理解→地点搜索→步行路线→筛选→回答格式→异常处理 |
| 魔搭社区 · 上传并分享自己的 Skill | `modelscope/` | `SKILL.md` + `UPLOAD-GUIDE.md` | **提交物是上传后的网址或编号**（需个人账号）；本目录提供待上传的 Skill 原文与上传步骤 |
| Dify · 雾隐镇夜班档案室 | `dify/` | Dify DSL（`app.yml`、`custom_tool.yml`）+ 配套工具服务 + 初始化数据 + 验证样例 + 部署说明 | `dify/service/smoke_test.py` 端到端自检；README §2 写明 Dify 与 seekdb 的分工 |
| MiniMax · 规有所依（SDD 上下文管理） | `minimax/` | 上下文模块源码、运行说明、验证样例、代码差异、测试日志、MiniMax 开发记录、一页技术说明 | `python minimax/scripts/run_verification.py` 端到端验证 |
| 阶跃星辰 · 浏览器端向量化 + seekdb 混合检索 | `stepfun/` | 可运行 Web 应用、完整源码、一页技术说明、性能与验证数据 | `npm run verify`（21/21）、`npm run verify:browser`（16/16，真实无头 Edge） |
| Qoder · 研记 Research Desk | `qoder/` | 应用源码、运行说明、验证样例、开发记录 | `python qoder/scripts/verify.py`（7 项） |

## 依赖说明

`minimax/` 与 `qoder/` 用 **PowerContext** 保存并复用任务状态（`from powercontext...`），
因此本分支同时带上 SDK 源码 `src/`：运行时把 `src/` 放进 `PYTHONPATH` 即可，
不需要额外安装其它包（seekdb 客户端用 `pymysql`）。

## 统一验证顺序

```bash
# 1) MiniMax：上下文检索 → 改前测试 → 改后测试 → 状态落库
PYTHONPATH=src python minimax/scripts/run_verification.py

# 2) Qoder：写入 → 检索 → 状态复用
PYTHONPATH=src python qoder/scripts/verify.py

# 3) 阶跃星辰：Node 端 21 条断言
cd stepfun && npm install && npm run verify

# 4) 阶跃星辰：浏览器端 16 条断言（需要本机 Edge/Chrome）
cd stepfun && npm run verify:browser

# 5) Dify：配套工具服务自检（需要本机 seekdb）
python dify/service/smoke_test.py
```

## 已知限制

- 魔搭与 Qoder 需要个人账号（上传网址 / Sites 发布），本机无法代做。
- 阶跃星辰的浏览器端在本机拿到的是 Chromium 的 **SwiftShader 软件 WebGPU 适配器**，
  反映 CPU 软件渲染，不代表真实显卡性能；README §10 已如实标注。
- 全部配置示例只含占位值，仓库内没有任何真实凭据。
