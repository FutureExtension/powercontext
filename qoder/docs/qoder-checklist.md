# 在 Qoder 中完成开发记录与网站发布

> 赛题要求：**项目的主要开发工作必须在 Qoder 中完成**，并且**必须通过 Qoder Sites 发布**、
> 可见范围设为「任何人都可访问」，提交时还要填 **Qoder 账号 UID**。
>
> 本机已完成的部分：项目代码、样例、运行说明、验证样例、一页技术说明、全部本地验证。
> 剩下的是**必须在 Qoder 账号里完成**的部分，本文件是逐条操作清单。

## 0. 一次性准备

### 0.1 注册个人账号并领取额度

1. 注册 **Qoder 个人账号**（企业版账号无法把站点设为公开访问，题面明确要求用个人账号）。
2. 到 <https://ask.oceanbase.com/t/topic/35653137> 领取 2000 Qoder CN Credits（约等于一个月 Pro）。
3. 在 Qoder 里生成 **Personal Access Token**，设置为环境变量 `QODER_PERSONAL_ACCESS_TOKEN`。

### 0.2 安装 Qoder CLI（可选，只在需要命令行时）

本机已下载过 Windows 版 CLI，可直接复用：

```
https://qoder-ide.oss-accelerate.aliyuncs.com/qodercli/releases/1.1.83/qodercli-windows-x64.zip
sha256 ed505cfac74b3a5077cf3ad85f99a7fa294557b6ecf491a0c482ae986bd6cc34
```

免登录可用的命令：`--version`、`--help`、`status`、`sites operations`、
`sites describe prepare_site`、`mcp list`、`skills list`。
需要登录的：`qoder -p "..."`（非交互式对话）、`sites list_sites`、任何站点读写动作。

## 1. 在 Qoder 里完成开发（这是题目的硬要求）

把本仓库的 `qoder/` 目录交给 Qoder，让它**做真实的开发工作**并留下对话记录。
建议按下面的顺序，每一步都保留截图或录屏：

| 步骤 | 交给 Qoder 的任务 | 要保留的证据 |
|---|---|---|
| 1 | 阅读 `qoder/README.md` 与 `qoder/docs/technical-overview.md`，解释这个项目解决什么问题 | 对话截图 |
| 2 | 让 Qoder 实现"按主题筛选笔记"的功能：在 `qoderapp/store.py` 的 `search()` 上加 `topic` 参数并接入 `qoderapp/service.py` 与 `web/app.js` 的主题下拉 | **代码差异截图** |
| 3 | 让 Qoder 为新功能补测试，并运行 `python scripts/verify.py` | 测试输出截图 |
| 4 | 让 Qoder 检查 `qoder/docs/known-issues.md` 里记录的 seekdb 全文索引崩溃，给出规避方案并落到代码里 | 对话截图 |
| 5 | 让 Qoder 把网页界面按你的审美改一版（配色、排版、卡片样式） | 改版后的页面截图 |

> 第 2 步产出的代码差异必须**留在提交的仓库里**，
> 这样"Qoder 开发记录"与"提交的代码"才对得上，评审才认。

## 2. 在 Qoder Sites 发布网站

`qoder/web/` 是**纯静态**页面，没有构建步骤，可以直接发布。
在 Qoder 里（或用 CLI）执行 `prepare_site`，参数与 schema 对齐如下：

| 参数 | 取值 | 说明 |
|---|---|---|
| `actionId` | 一个新的 UUID | 重试时必须复用同一个 UUID |
| `projectRoot` | `qoder/` | 项目根目录 |
| `webDirectory` | `web` | **构建产物目录**，不是源码根目录 |
| `displayName` | `研记 Research Desk` | 站点显示名 |
| `slug` | `research-desk` | 只允许小写字母、数字和连字符 |
| `spa` | `true` | 单页应用 |
| `createNewSite` | 仅在你明确要新建站点时传 `true` | 其余情况省略 |

CLI 参考：

```powershell
$env:QODER_PERSONAL_ACCESS_TOKEN = '<你的 token>'
& C:\codex-work\ob-00001\work\probe-qoder\cli\bin\qodercli.exe sites describe prepare_site
```

流程是 `prepare_site` → 检查 `descriptorStatus`（`pending` 就用同样的 `actionId` 和完全相同的输入重试）→
`publish_site` → `get_publish_status`，取回 `site.url`。

发布后把可见范围设为「任何人都可访问」，然后**用无痕窗口打开该网址确认能访问**。

## 3. 提交材料清单

| 材料 | 位置 |
|---|---|
| 项目网站网址 | Sites 发布后回填 |
| 代码仓库 | 本仓库（`qoder/` 目录），填 HTTPS URL + 40 位 commit SHA |
| 运行说明 | `qoder/README.md` |
| 验证样例 | `qoder/docs/verification-sample.md` |
| Qoder 开发记录 | 第 1 步的截图 / 录屏 + Qoder 账号 UID |
| 一页技术说明 | `qoder/docs/technical-overview.md` |
| 使用效果（鼓励） | 第 3 步之后统计：提问次数、命中的笔记数、标记已掌握的条数；`qoderapp/cli.py progress` 的输出可以直接作为记录 |

## 4. 提交前的自检

```bash
python qoder/scripts/verify.py     # 跑完整验证样例
python qoderapp/cli.py seed        # 幂等
```

- [ ] 网站无痕可访问
- [ ] 第 2 步的代码差异在仓库里
- [ ] `verify.py` 全绿
- [ ] 运行说明里的命令在干净环境跑得通
