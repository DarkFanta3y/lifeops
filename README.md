<div align="center">

<img src="lifeops_logo.svg" alt="logo" width="40%">

**AI 驱动的生活助手智能体**

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://python.org)
[![uv](https://img.shields.io/badge/uv-package_manager-6E39C6.svg)](https://github.com/astral-sh/uv)
[![pytest](https://img.shields.io/badge/local_tests-271%20passed-green.svg)](https://docs.pytest.org)
[![Ruff](https://img.shields.io/badge/linter-ruff-FCC624.svg)](https://docs.astral.sh/ruff/)

[快速开始](#快速开始) · [架构](#架构) · [配置](#配置) · [开发](#开发)

</div>

---


## 快速开始

```bash
# 安装依赖
uv sync

# 设置 API Key
export LLM_API_KEY=your-key-here
```

终端 1：启动本地 API

```bash
uv run lifeops-web
```

终端 2：启动前端开发服务器

```bash
cd web
npm install
npm run dev
```

默认 API 地址为 `http://127.0.0.1:8081`，前端地址为 `http://127.0.0.1:5173`。如需修改前端调用的 API 地址，可设置 `VITE_API_URL`。

### Web 控制台

Web 控制台包含三个主要区域：
- 左侧侧边栏 — 顶部提供 `新聊天` 与 `搜索标题`；`新聊天` 只清空当前输入与消息流，第一条消息发送后才创建历史记录，并在首条消息发送时自动生成中文短标题；`搜索标题` 通过弹窗按会话标题检索本地历史
- `SKILLS` — 查看当前发现的 Skill 元数据，并可通过刷新旁的加号手动新增项目级 Skill，保存到 `.lifeops/skills/<name>/SKILL.md`
- `TOOLS` — 顶栏提供 `TOOL` / `MCP` 分段切换，默认显示内置工具；切到 `MCP` 后以可展开行展示已连接 MCP Server，展开后显示该 Server 提供的工具和参数

聊天历史位于侧边栏 `对话` 分组中，可折叠。悬浮单条历史会显示删除按钮，确认后会从本地 JSONL 历史中移除该会话，并刷新侧边栏与搜索结果。

Web 控制台固定在浏览器视口内：历史对话很多时只滚动侧边栏对话列表，聊天消息很多时只滚动主消息流，输入框保持在底部可见，发送按钮内嵌在输入框末尾。聊天消息支持 Markdown/GFM 实时渲染，聊天输入区可展开 Markdown 预览，Skill 描述预览也会随输入实时渲染；侧边栏摘要与表格单元格保持纯文本以维持紧凑布局。`SKILLS` / `TOOLS` 主工作区与侧边栏贴合，数据较少时不额外保留底部空白；数据超过分页阈值或 MCP 展开内容变高时由表格内容区滚动，外置分页固定在主区域右下角，底部半透明模糊层仅在分页出现时做视觉过渡、不拦截点击。

本地 Web API 的会话端点：
- `GET /api/conversations` — 获取会话列表
- `GET /api/conversations?query=关键词` — 只按会话标题搜索
- `GET /api/conversations/{conversation_id}` — 获取会话消息
- `DELETE /api/conversations/{conversation_id}` — 删除会话历史并清理 Web agent 缓存
- `POST /api/chat` — 发送聊天消息，返回 `conversation_id`、`reply`，新 Web 会话额外返回 `title`
- `POST /api/skills` — 创建项目级 Skill，名称仅支持小写字母、数字和短横线，metadata 使用 YAML mapping 片段
- `GET /api/tools` — 返回内置工具列表，并在 `mcp_servers` 中返回已连接 MCP Server 的工具分组

## 架构

```
                  ┌──────────────┐
    用户输入 ───► │   Agent      │
                  │  (ReAct 循环) │
                  └──────┬───────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
     ┌──────────┐ ┌──────────┐ ┌──────────┐
     │   LLM    │ │  Tools   │ │ Context  │
     │  Client  │ │ Registry │ │ Manager  │
     └──────────┘ └──────────┘ └──────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
               ┌──────┐      ┌──────────┐    ┌──────────┐
               │  L1  │      │   L2     │    │   L3     │
               │ 常驻  │      │  按需加载 │    │ 溢出压缩 │
               └──────┘      └──────────┘    └──────────┘
```

**核心流程**: 用户输入 → LLM 推理 → 工具调用 → 迭代 → 最终响应

**上下文分层**:
- **L1** — 系统提示、Skill 目录、近期对话，始终在上下文中
- **L2** — Skill 完整文档、RAG 检索结果，按需加载
- **L3** — 工具执行结果，容量不足时自动压缩

## 配置

优先级: 环境变量 > `.env` 文件 > 默认值

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_API_KEY` | LLM API 密钥（**必填**） | — |
| `LLM_MODEL` | 模型名称 | `glm-4-flash` |
| `LLM_API_BASE` | API 地址 | `https://open.bigmodel.cn/api/paas/v4` |
| `LIFEOPS_HISTORY_PATH` | Web / 本地 API JSONL 历史缓存路径 | `.lifeops/conversations.jsonl` |
| `LIFEOPS_DEBUG` | 调试模式 | `false` |
| `LIFEOPS_LOG_LEVEL` | 日志级别 | `INFO` |

### 上下文调优

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LIFEOPS_CONTEXT_MAX_CONTEXT_TOKENS` | 上下文窗口大小 | `200000` |
| `LIFEOPS_CONTEXT_L1_BUDGET_RATIO` | L1 预算占比 | `0.10` |
| `LIFEOPS_CONTEXT_L2_BUDGET_RATIO` | L2 预算占比 | `0.60` |
| `LIFEOPS_CONTEXT_L3_BUDGET_RATIO` | L3 预算占比 | `0.20` |

### Skill 配置

LifeOps 会扫描项目级 `.lifeops/skills/` 和用户级 `~/.lifeops/skills/`。启动时日志只显示已预加载的 Skill 数量，L1 只包含 Skill 名称和描述；用户显式输入 `$skill-name`，或隐式匹配命中后，完整 `SKILL.md` 才会进入 L2。项目 Skill 优先于用户 Skill。

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LIFEOPS_SKILLS_ENABLED` | 启用 Skill 系统 | `true` |
| `LIFEOPS_SKILLS_PROJECT_DIR` | 项目级 Skill 目录 | `.lifeops/skills` |
| `LIFEOPS_SKILLS_USER_DIR` | 用户级 Skill 目录 | `~/.lifeops/skills` |
| `LIFEOPS_SKILLS_IMPLICIT_MATCH_ENABLED` | 启用 LLM 隐式匹配 | `true` |
| `LIFEOPS_SKILLS_MAX_ACTIVE` | 单轮最多激活 Skill 数 | `3` |

最小 Skill 示例：

```markdown
---
name: weekly-review
description: 整理本周记录、总结进展、生成下周行动计划。Use when the user asks for weekly review, planning, or reflection.
---

# Weekly Review

1. 读取相关笔记或历史记录。
2. 汇总完成事项、阻塞项和下周重点。
3. 必要时调用文件读取、搜索或日历工具。
```

项目内置 Skill：

- `summarizing-last-week-conversations`：以触发 Skill 的时间戳为结束时间，总结过去 7 天内的对话主题、决策、完成事项、待办、风险与信息缺口。

### MCP 配置

启动时日志只显示已连接的 MCP 数量；具体 Server 连接过程与 MCP 工具注册明细降为 debug 日志。

Agent 会在首次调用 LLM 前连接已配置的 MCP Server 并注册工具，因此用户可以直接提出“我的 github profile 信息是什么”这类请求，LLM 可选择 `mcp.github.get_me` 获取当前 token 对应的 GitHub profile。

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LIFEOPS_MCP_ENABLED` | 启用 MCP 工具 | `true` |
| `LIFEOPS_MCP_SERVERS` | MCP Server JSON 配置 | — |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub MCP Server 所需 | — |
| `GOOGLE_OAUTH_CLIENT_ID` | Google Workspace MCP Server 所需 OAuth Client ID | — |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google Workspace MCP Server 可选 OAuth Client Secret | — |
| `OAUTHLIB_INSECURE_TRANSPORT` | Google Workspace MCP 本地 HTTP OAuth 回调开关 | — |
| `GOOGLE_MCP_CREDENTIALS_DIR` | Google Workspace MCP OAuth 凭据缓存目录 | — |
| `LIFEOPS_GOOGLE_WORKSPACE_MCP_PERMISSIONS` | Google Workspace MCP 权限范围，默认只允许 Gmail 草稿 | `gmail:drafts` |
| `LIFEOPS_GOOGLE_WORKSPACE_MCP_TOOL_TIER` | Google Workspace MCP 工具层级 | `core` |

#### MCP 凭据获取

GitHub MCP 使用 `GITHUB_PERSONAL_ACCESS_TOKEN`。推荐创建 fine-grained personal access token，并按需要限制仓库和权限范围。申请入口：
- GitHub token 页面: https://github.com/settings/personal-access-tokens
- GitHub 官方说明: https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token

Docker stdio 配置中只应使用 `-e GITHUB_PERSONAL_ACCESS_TOKEN` 传递环境变量名，token 值放在 MCP server 的 `env` 配置或进程环境中，不要写入 Docker args。

Google Workspace MCP 不使用类似 GitHub 的固定 access token。它使用 Google Cloud OAuth 客户端凭据：
- `GOOGLE_OAUTH_CLIENT_ID`：必填，来自 Google Cloud OAuth Client
- `GOOGLE_OAUTH_CLIENT_SECRET`：可选，本地 confidential client 可配置；public PKCE client 可不配置
- 第一次运行时由 MCP 服务触发 Google OAuth 授权，同意后令牌会缓存在 `GOOGLE_MCP_CREDENTIALS_DIR` 指定目录或上游默认目录

Google OAuth 申请入口：
- Google Cloud Credentials: https://console.cloud.google.com/apis/credentials
- Google Workspace 凭据官方说明: https://developers.google.com/workspace/guides/create-credentials
- Google Workspace MCP 上游说明: https://github.com/taylorwilsdon/google_workspace_mcp

配置步骤：
1. 在 Google Cloud 创建或选择项目。
2. 在 APIs & Services / Credentials 中创建 OAuth Client ID；本地单用户运行优先选 Desktop Application。
3. 在 APIs & Services / Library 中启用要使用的 API，例如 Gmail API、Google Calendar API、Google Drive API。
4. 将 Client ID 写入 `GOOGLE_OAUTH_CLIENT_ID`，如有 Client Secret 则写入 `GOOGLE_OAUTH_CLIENT_SECRET`。

Google Workspace 预设不会自动启用，避免用户未完成 OAuth 授权时启动失败。需要动态注册时可在代码中使用：

```python
from lifeops.tools.mcp.servers import (
    create_google_workspace_mcp_config,
    get_google_workspace_mcp_server_name,
)

agent.add_mcp_server(
    get_google_workspace_mcp_server_name(),
    create_google_workspace_mcp_config(),
)
```

Google Workspace MCP 权限通过 `LIFEOPS_GOOGLE_WORKSPACE_MCP_PERMISSIONS` 传给上游 `workspace-mcp --permissions` 参数。默认权限为 `gmail:drafts`，适合 SKILLS 编排先生成 Gmail 草稿；如需真实发送邮件，请显式设置 `LIFEOPS_GOOGLE_WORKSPACE_MCP_PERMISSIONS=gmail:send`。也可以扩展为 `gmail:send calendar:full drive:readonly` 等组合权限。

## 项目结构

```
src/lifeops/
├── agent.py                # Agent 核心类
├── history.py              # JSONL 对话历史缓存
├── core/
│   ├── config.py           # 配置管理 (pydantic-settings)
│   └── context_manager.py  # 三层上下文管理器
├── llm/
│   ├── client.py           # OpenAI 兼容 LLM 客户端
│   └── types.py             # Message, ToolCallResult 等类型
├── skills/
│   ├── loader.py            # Skill 发现与 frontmatter 解析
│   ├── manager.py           # Skill 清单与 L2 注入管理
│   ├── matcher.py           # 显式 / 隐式触发匹配
│   └── types.py             # Skill 类型定义
├── tools/
│   ├── base.py              # Tool 基类与 ToolDefinition
│   ├── registry.py          # 工具注册中心
│   ├── builtin/             # 内置工具
│   │   ├── bash.py
│   │   ├── file_read.py
│   │   ├── file_edit.py
│   │   └── web_search.py
│   └── mcp/
│       ├── manager.py       # MCP Server 注册与状态管理
│       └── servers/         # MCP Server 预设
│           ├── github.py
│           └── google_workspace.py
├── web/
│   ├── api.py              # FastAPI 本地 Web API
│   └── title_summary.py    # Web 新会话中文短标题生成
└── utils/
    └── logging.py           # 日志工具
```
## Star History

<a href="https://www.star-history.com/?type=date&repos=DarkFanta3y%2Flifeops">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=DarkFanta3y/lifeops&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=DarkFanta3y/lifeops&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=DarkFanta3y/lifeops&type=date&legend=top-left" />
 </picture>
</a>

## License

MIT
