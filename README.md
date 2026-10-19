<div align="center">

<img src="assets/lifeops_pixel_logo.svg" alt="logo" width="10%"> <img src="assets/lifeops_logo.svg" alt="logo" width="40%">

**AI 驱动的生活助手智能体**

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://python.org)
[![Ruff](https://img.shields.io/badge/linter-ruff-FCC624.svg)](https://docs.astral.sh/ruff/)

[功能亮点](#功能亮点) · [智能体](#智能体) · [Web 控制台](#web-控制台) · [快速开始](#快速开始) · [项目结构](#项目结构)

</div>

---

LifeOps 是一个本地优先的 AI 生活助手智能体，把流式对话、工具调用、Skill 编排、长期记忆、本地 Markdown RAG 和 MCP 工具整合进一个 Web 控制台。

## 功能亮点

- **流式对话**：SSE 逐 token 渲染，支持生成中停止；工具参数到齐前只做安全预热，兼容需要回传 `reasoning_content` 的思考模式模型。
- **Web 控制台**：Vue 3 + Element Plus X，提供聊天、历史、上下文洞察、知识库、模型管理与运行日志；对话流右侧按提问生成快速导航横条，悬停预览、点击定位。
- **模型管理**：在 Web 控制台维护多家模型提供商，支持 OpenAI Chat Completions / OpenAI Responses / Anthropic Messages 协议、密钥脱敏、拉取模型目录与一键切换当前模型；未配置时回退 `.env` 的 `LLM_*`。
- **会话历史**：保存消息与中文短标题，按「今天 / 昨天 / 7 天内 / 更早」分组，支持搜索、重命名、导出与删除。
- **「/」命令**：输入 `/` 打开菜单，支持过滤、↑↓ 选择、回车 / Tab 执行、Esc 关闭：`/new`、`/search`、`/context`、`/logs`、`/regenerate`、`/rename`、`/export`、`/plan`；除 `/plan` 外均在前端执行。
- **工具过程展示**：参考 DeepSeek Harness，以紧凑中文动作行展示调用，支持整轮 / 连续分组 / 单次调用三层折叠，标准与详细两档，参数、结果与 diff 内联查看。
- **运行状态栏**：输入框下方常驻显示轮次与步骤、tok/s、Token 总量、缓存命中率与环形进度，按每次调用的 `usage` 事件累计，并以 `done` 的真实 usage 校正。
- **Skill 与工具**：自动发现项目级、用户级 Skill，按 `$skill-name` 或语义匹配激活；内置工具与 MCP 工具统一注册，每轮按相关性裁剪暴露给模型的工具。
- **长期记忆**：持续学习会话摘要、用户偏好与知识图谱，支持记忆搜索、偏好 / 实体删除与低价值记忆清理。
- **本地 RAG**：索引本地 Markdown，混合向量检索、BM25、RRF 与 reranker，回答可引用本地资料。
- **上下文洞察**：记录每次 LLM 请求的上下文构成与厂商 usage，提供对话页抽屉、`/context` 弹窗与统计页。
- **生产级运行时**：每次请求生成 `run_id`，记录结构化 trace、工具策略决策、失败分类与离线 eval。

## 智能体

![Agent 架构](assets/agent.png)

### ReAct 推理与工具执行

每次输入由 Agent 调度器处理：加载上下文与相关 Skill，再按「LLM 推理 → 执行工具 → 观察结果 → 继续或完成」迭代，默认最多 50 轮（`LIFEOPS_AGENT_MAX_ITERATIONS`）。执行过工具后必须继续调用工具或内部 `finish_task`，普通文本不会被当作完成。只读工具（`file_read`、`grep`、`glob` 等）可并行，写入类工具每轮至多一个并串行执行。

流式工具调用会先做无副作用预热，参数为合法 JSON 后才进入策略网关执行；参数非法且本轮未输出正文时，仅降级调用一次非流式 LLM，不猜测或空参执行。需要回传 `reasoning_content` 的模型会在历史中保留该字段，但思考内容不会展示在消息、搜索结果或运行日志中。

### 计划模式与计划闸门

内嵌式 Plan-Execute：复杂度分类器（低温单问调用，失败降级为简单任务）判定为多步骤任务时开启**计划闸门**，在 `todo_write` 列出计划前拒绝 `bash`、`file_create`、`file_replace`、`file_append`，只读探索不受限；计划会持续注入每轮上下文，完成一步更新一步，允许就地修订。开关为 `LIFEOPS_AGENT_PLAN_GATE_ENABLED`，trace 记录 `task_complexity_decided` 与 `plan_gate_denied`。

计划模式用于「先出方案、确认后动手」：`/plan` 进入、`/plan off` 退出、`/plan <消息>` 进入并发送，按会话持久化在 `conversations.plan_mode`。规划阶段只读探索并写出完整计划，写入类工具与子智能体均受限；模型调用 `exit_plan_mode` 提交计划后，前端出现评审卡片，可「批准并执行」「继续规划（附反馈）」或关闭，超时（`LIFEOPS_AGENT_PLAN_REVIEW_TIMEOUT_SECONDS`，默认 900 秒）结束本次运行。开关为 `LIFEOPS_AGENT_PLAN_MODE_ENABLED`，决策通过 `POST /api/plan-reviews/{request_id}` 提交。

### Runtime Trace 与工具策略

每次 `/api/chat` 创建独立 `run_id`，记录模型调用、检索路由、工具请求、策略决策、上下文压缩与完成 / 失败等 trace event；可通过 `GET /api/runs/{run_id}`、`GET /api/conversations/{conversation_id}/runs` 查询。

工具执行前经过 `ToolPolicyEngine`：只读工具默认允许，`bash`、文件写入和 MCP 工具保守处理，危险命令始终拒绝。策略给出 `ask` 时通过 SSE `approval_required` 请求人工审批（允许一次 / 总是允许 / 拒绝），超时默认拒绝；「总是允许」持久化到 `.lifeops/tool-policy.json`。`LIFEOPS_TOOL_POLICY_PERMISSION_MODE` 支持 `default` / `accept_edits` / `yolo`。解析失败、工具失败、策略拒绝、RAG 失败与迭代上限都会分类写入 trace，离线 eval 覆盖普通问答与危险工具拒绝等路径。

```bash
curl http://127.0.0.1:8081/api/runs/<run_id>
curl http://127.0.0.1:8081/api/conversations/<conversation_id>/runs
curl http://127.0.0.1:8081/api/tools/policy
```

其余 `LIFEOPS_RUNTIME_*`、`LIFEOPS_TOOL_POLICY_*` 保持默认即可，完整参数见 `src/lifeops/core/config.py` 与 `.env.example`。

### 分层上下文

- `L1`：系统提示、Skill 目录和近期对话，始终保留
- `L2`：已激活 Skill 正文、RAG 命中结果和高相关长期记忆
- `L3`：工具执行结果和其他中间产物，压力升高时卸载、修剪或摘要压缩

这样长会话中既能保留稳定身份、近期任务、个人偏好和必要证据，又能控制工具结果带来的上下文膨胀。

### RAG

![本地 Markdown RAG](assets/rag.png)

RAG 把本地 Markdown 知识库索引到 ChromaDB 与 BM25。DATABASE 页面上传 ZIP 后可浏览目录树并预览切片：固定大小支持 150–900 字符，按标题切块时超长章节自动拆分。索引完成后写入完成标识，重启时清理未完成导入并加载已完成知识库；覆盖前需二次确认，失败恢复旧目录，删除只删除配置。主 LLM 调用唯一公开工具 `retrieve_knowledge`，按 `source="recipes"`（`dishes/`）或 `source="islamic_culture"`（`伊斯兰文化知识库/`）检索，内部由 `RAGRouter` 分发。返回结果按父 Markdown 聚合并保留证据片段，本地图片通过只读资源接口展示。

![手动添加本地数据源](assets/本地知识库添加.png)

### 记忆管理

跨会话信息写入 Docker 管理的 MySQL，包括会话摘要、用户偏好、知识图谱实体与关系、工具 / Skill 使用统计和上下文压缩事件。

![长期记忆](assets/memory.png)

## Web 控制台

LifeOps 以本地 Web 控制台为主要入口：FastAPI 提供会话、聊天、Skill、工具、记忆、RAG、模型与数据源接口，前端通过 SSE 接收流式回答与工具事件。

![LifeOps Web 控制台](assets/web.png)

### 对话与历史

- 聊天界面固定在视口内，侧栏用于新建、搜索和切换历史会话；新会话先返回即时标题，中文短标题在后台生成并补齐。
- 前端以 [ruoyi-element-ai](https://github.com/element-plus-x/ruoyi-element-ai) 为基础重构，采用 Vue 3、Element Plus 与 Element Plus X；聊天、知识库页面均接入 FastAPI/SSE。
- 工具过程以「图标 / 中文动作 / 目标摘要 / 状态」紧凑行展示，标准 / 详细模式保存在本地；文件变更内联 diff，结果可展开、滚动、复制，刷新和历史分页后可恢复。
- 高风险工具触发内联审批卡片（允许一次 / 总是允许 / 拒绝），审批期间输入区禁用；生成中可随时停止，完整记录仍归档到运行日志弹窗。
- 最后一轮支持重新生成与编辑后重发（`DELETE /api/conversations/{id}/last-turn`）；回答下方标注知识库 / 联网来源与本轮载入的记忆条数，并可用浏览器语音朗读。
- 侧栏按时间分组，标题菜单支持重命名（`PATCH /api/conversations/{id}`）、导出和删除；快捷键 `⌘/Ctrl + K` 搜索、`⌘/Ctrl + Shift + O` 新建。
- Markdown 禁用原始 HTML 并经 DOMPurify 清洗；代码块带语言标签、复制按钮和 highlight.js 高亮；本地图片通过后端资源接口展示。
- 对话流右侧的快速导航横条悬停预览提问、点击平滑定位并高亮当前轮次，容器宽度不足时自动隐藏。

SSE 保留 `token`、`tool_call`、`tool_result`、`done`，调用事件补充 `call_id`、`run_id`、迭代序号与时间，新增 `tool_status`、`run_started`、`run_finished`、`text_segment`、`answer_start`、`usage` 等生命周期事件；`done` 同时携带本次运行累计的真实 usage。并行工具按实际完成顺序通知界面，模型历史仍按调用顺序写入。模板与参考实现的 MIT 许可见 `web/public/licenses/ruoyi-element-ai.txt`、`web/public/licenses/deepseek-harness.txt` 和 `web/src/chat/NOTICE.md`。

![工具调用 Logging](assets/logging.png)

以上截图使用浏览器验收的隔离示例数据。

### 模型管理

导航栏「模型管理」集中维护推理提供商。配置保存在 `.lifeops/models.json`（可用 `LIFEOPS_MODELS_PATH` 覆盖，文件权限为 `0600`），不写入数据库，也不覆盖 `.env`：

- **添加提供商**：填写 Provider ID、显示名称、API 地址、API 协议和 API 密钥；「模型目录」支持手动添加模型 ID，或从提供商的 `/models` 接口拉取后批量勾选。API 密钥只在保存与运行时使用，列表接口只返回是否已保存和末四位提示。
- **三种协议**：OpenAI Chat Completions 复用现有 `LLMClient`；OpenAI Responses 与 Anthropic Messages 由 `src/lifeops/llm/` 下的适配器转换为同一套流式事件，支持工具调用、usage 与思考内容回传。
- **当前模型**：在提供商详情抽屉中把任一模型设为当前模型，运行时即时重建 LLM 客户端并同步到记忆服务与已创建的会话 Agent；对话页顶栏的模型下拉可直接切换，或「恢复环境变量默认」回到 `.env` 的 `LLM_*` 配置。未设置当前模型时行为与旧版一致。
- **接口**：`GET /api/models`、`POST /api/models/providers`、`PATCH/DELETE /api/models/providers/{id}`、`POST /api/models/available`、`PUT/DELETE /api/models/active`。

### 上下文洞察

上下文洞察移植自 [dsh-context](https://github.com/bowenliang123/dsh-context)（Apache-2.0），是 LifeOps 的原生能力。

- **记录**：每次 LLM 请求把系统提示各分段、工具 schema 和消息按七类估算 token，写入 `context_snapshots`，内容按哈希去重存入 `context_blobs`；响应后补写厂商 usage、首 token 时间与耗时，子智能体请求同样记录。流式 usage 依赖 `stream_options.include_usage`，厂商不支持时可设 `LLM_STREAM_USAGE=false`。
- **对话页抽屉**：顶栏「上下文」打开，分「上下文 / 编队」两页，包含流向统计、Token 与耗时环图、构成、趋势图、步骤简报、上下文浏览器、事件与文件活动；编队页展示子智能体网络、成员卡片与 `todo_write` 计划，运行中每 2 秒刷新。
- **`/context`**：仅在前端打开构成弹窗，不发给模型。
- **统计页**：按 7 天 / 30 天 / 全部统计活跃会话、Token、预估费用、缓存命中、构成与活跃热力图。
- **费用**：配置 `LIFEOPS_CONTEXT_PRICE_INPUT_PER_M` / `_OUTPUT_PER_M` / `_CACHE_PER_M`（元/百万 token）后估算。
- **接口**：`GET /api/conversations/{id}/context`、`/context/files`、`/context/fleet`、`GET /api/context/snapshots/{snapshot_id}`、`GET /api/context/overview?range=7d|30d|all`；旧会话不回填。

![对话页上下文抽屉](assets/context-drawer.png)

![编队：主智能体与子智能体](assets/context-fleet.png)

![上下文洞察页](assets/context-insights.png)

### Skills 与 Tools

LifeOps 按 Agent Skills 标准扫描项目级 `.agents/skills/` 与用户级 `~/.agents/skills/`，每个 Skill 是包含 `SKILL.md` 的独立目录。启用时额外暴露只读工具 `activate_skill`：流式阶段只预读取并校验，执行成功后才把正文注入 L2 上下文并写入使用 trace。

内置工具包括命令执行（`run_in_background` / `bash_output` / `bash_kill`，超时自动终止，输出超限保留头尾）、文件读写（创建 / 替换 / 追加）、`grep` 与 `glob`、网页搜索和本地知识库检索。修改已有文件前必须先用 `file_read` 读过（会话级 `FileEditGuard`），`old_text` 必须唯一，结果以 unified diff 写入 metadata。工具参数 schema 保留 `minLength`、`enum`、`pattern`、`additionalProperties: false` 等约束。

内置工具、MCP 工具与 Skill 伪工具注册到统一工具表，执行层保留完整 registry；发送给 LLM 的 `tools` 每轮最多 20 个，按「核心工具 → Skill 的 `allowed-tools` 指定 MCP 工具 → 本轮已调用 MCP 工具 → 其余候选」排序。指定和已调用组内按相关性降序排列；其余候选保留原有类别 / 风险优先级，同优先级再比较相关性，同分按注册顺序排列。所有组统一受数量上限约束，`allowed-tools` 仅影响筛选，不授予执行权限。

MCP 相关性仍按当前提问、已激活 Skill、工具名称 / 描述和领域词做本地确定性匹配：英文匹配完整词或短语，兼容大小写与点、下划线、短横线分隔，避免 `price` 误命中 `pr`；中文用 jieba 分词匹配共同词并过滤通用词、标点和纯数字。用户与 Skill 文本每次筛选各分词一次，不增加模型调用；分词不提供跨语言翻译或同义词推理。模型协议适配器保留已选工具的顺序。MCP 的 function name 只使用合法 wire name（如 `mcp_github_search_repositories`），策略与日志保留 canonical name（`mcp.github.search_repositories`）。

每轮请求还会估算 system、历史与工具 schema 的 token 预算，超限时裁剪最旧历史并压缩当前运行的工具输出；无法安全压缩时返回 `context_error`。除手写 `LIFEOPS_MCP_SERVERS` 外，`LIFEOPS_MCP_PRESETS` 支持无需 API Key 的基础 MCP，推荐 `context7,playwright,memory,sequential_thinking,filesystem`；同名手写 Server 优先于预设。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env   # 填写 LLM_API_KEY，核对模型与端点；其他常用项按需取消注释
lifeops-web
```

Linux 上如需避免 CUDA 版 PyTorch，先安装 CPU wheel，再安装项目依赖：

```bash
python -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
```

需要 Google Workspace MCP 时额外安装：`python -m pip install -e ".[workspace]"`。

另开终端启动前端：

```bash
cd web
npm install
npm run dev
```

默认后端为 `http://127.0.0.1:8081`，前端为 `http://127.0.0.1:5173`。后端监听地址可用 `LIFEOPS_WEB_HOST` / `LIFEOPS_WEB_PORT` 覆盖，修改后须同步 `web/.env.local` 的 `VITE_API_URL`，否则请求会报 `Failed to fetch`。本机 `.env` 使用 `8082`，因为 `8081` 已被其他项目的 dev server 占用。

### Docker Compose

在 Docker Desktop 已启动、`.env` 填写 LLM 配置与两个独立的 MySQL 随机密码后运行：

```bash
docker compose build
# 已有 SQLite 数据时先执行下方迁移步骤，再启动新版后端。
docker compose up -d
docker compose ps
docker compose logs -f backend
```

- 后端固定为 `http://127.0.0.1:8082`，前端继续用 `npm run dev`；Compose 将容器监听地址覆盖为 `0.0.0.0`，宿主机仅开放本机端口，进程退出后自动重启。
- 会话、记忆、知识库配置、运行轨迹与上下文快照保存在 MySQL 8.4 的 `mysql-data` 卷，仅开放 `127.0.0.1:3307`；连接失败时直接报错，不回退 SQLite。
- 向量由独立 Chroma 1.5.7 服务管理，保存在 `chroma-data` 卷，宿主机仅开放 `127.0.0.1:8004`；后端等待两个数据库健康后启动。
- 知识库原文、BM25 / 父文档 / 切片缓存与审批文件仍在宿主机 `.lifeops/`；`models/` 只读挂载复用，不在运行中下载。
- 项目目录挂载到 `/workspace`，项目 Skill、Filesystem MCP 与文件工具可访问；其他 Mac 目录（如 Obsidian vault）需通过本地 Compose 覆盖文件挂载。
- Agent 的 shell 命令在 Linux 容器内执行，修改源码后需重建镜像；镜像预装 Node.js、Chromium、现有 MCP 程序与 GitHub MCP，`docker/entrypoint.py` 启动时适配 `.env` 中的 MCP 命令。
- Google 凭据默认存放在 `google-credentials` 卷；迁移已有凭据时可通过忽略提交的 `compose.override.yaml` 把宿主机目录挂载到 `/var/lib/lifeops/google-mcp`。
- MCP 参数适配支持 `type: ["boolean", "null"]` 等联合类型，避免 Sequential Thinking 等工具因可空字段注册失败。

```bash
docker compose restart backend    # 重启后端
docker compose up -d --build      # 更新源码后重建并启动
docker compose down              # 停止，保留数据与命名卷
```

容器日志最多保留 3 个 10 MB 文件；`healthcheck` 检查知识库 API。本机直接运行后端时，`LIFEOPS_DATABASE_URL` 指向本机 MySQL 端口，Chroma 参数为 `LIFEOPS_RAG_CHROMA_HOST=127.0.0.1`、`LIFEOPS_RAG_CHROMA_PORT=8004`；`LIFEOPS_RAG_CHROMA_PATH` 在服务模式下只保存 BM25 等本地缓存。消息搜索使用 MySQL 字面子串查询，支持中文、单字和标点。

已有 SQLite 数据可在停止后端后迁移（目标必须为空库）：

```bash
docker compose up -d mysql --wait
docker compose stop backend
docker compose run --rm --no-deps backend python -m lifeops.storage.mysql_migration \
  --sqlite /app/.lifeops/conversations.db \
  --report /workspace/.codex/mysql-migration-report.json
docker compose up -d --wait
```

迁移工具检查全部 22 张表的行数与字段 SHA-256（含二进制向量），提交后重新连接复核；目标已有不同数据时拒绝覆盖。旧库应在接口读写、MySQL 导出与恢复校验通过后再删除；SQLite 仅保留为兼容测试与旧数据迁移的实现。

导出 MySQL 备份（备份含个人数据，请保存到受限目录）：

```bash
umask 077
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -u root --single-transaction --hex-blob --no-tablespaces --set-gtid-purged=OFF "$MYSQL_DATABASE"' > lifeops-mysql.sql
```

已有嵌入式 Chroma 可在停止后端后直接迁移向量：

```bash
docker compose stop backend
docker compose up -d chroma --wait
docker compose run --rm --no-deps backend python -m lifeops.rag.chroma_migration \
  --source /app/.lifeops/chroma --backup-dir /workspace/.codex/chroma-export
docker compose up -d --wait
```

迁移要求目标 Chroma 为空；工具先生成 `collection-*.jsonl.gz` 受限备份，再逐条比较 ID、正文、元数据、URI 与 float32 向量 SHA-256，并保留集合索引参数。恢复到空服务时用 `--restore` 代替 `--source` 和 `--backup-dir`。验证后可归档旧 `chroma.sqlite3` 与 UUID 目录，但须保留三个 `.pkl` 缓存及 `index_state.json`。部署方式见 [Chroma 官方 Docker 文档](https://docs.trychroma.com/guides/deploy/docker)。

索引重建只删除当前集合，保留其他集合与本地文件；向量按批次写入，增量删除失败会报错。同步发现集合缺失或向量数量与切片缓存不符时会重新生成索引。

常用开发命令：

```bash
python -m pytest tests/ -v
python -m pytest tests/evals -v
python -m ruff check src/ tests/

cd web
npm run build
npm test                 # 消息事件和分页定向测试
npm run test:ui          # 启动前端后串行浏览器检查（隔离 HTTP/SSE 桩）
```

重建本地 Markdown RAG 索引：

```bash
python -m lifeops.rag.index --rebuild
```

## 项目结构

```text
lifeops/
├── src/lifeops/
│   ├── agent.py                 # Agent 核心调度器
│   ├── context_insight/         # 上下文快照记录与洞察查询
│   ├── history.py               # 本地会话历史
│   ├── model_registry.py        # 模型提供商与当前模型注册表
│   ├── core/                    # 配置与分层上下文
│   ├── llm/                     # LLM 客户端与 OpenAI / Anthropic 协议适配
│   ├── memory/                  # 长期记忆、偏好和知识图谱
│   ├── rag/                     # Markdown RAG 索引与检索
│   ├── runtime/                 # run/trace、工具策略和失败分类
│   ├── skills/                  # Skill 发现、匹配和加载
│   ├── tools/                   # 内置工具与 MCP 适配
│   └── web/                     # FastAPI 本地 Web API
├── web/                         # Vue 3 + Vite Web 控制台（web/src/context 为上下文洞察）
├── tests/                       # pytest 测试套件
├── assets/                      # README Logo 与截图素材
├── .agents/skills/              # Agent Skills 标准 Skill 目录
└── .lifeops/                    # 本地知识库、历史和索引数据
```

## Star History

<a href="https://www.star-history.com/?repos=DarkFanta3y%2Flifeops&type=date&logscale=&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=DarkFanta3y/lifeops&type=date&theme=dark&logscale&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=DarkFanta3y/lifeops&type=date&logscale&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=DarkFanta3y/lifeops&type=date&logscale&legend=top-left" />
 </picture>
</a>

## License

MIT
