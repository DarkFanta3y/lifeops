# Draft: 中文提示词改造

## 需求 (confirmed)
- 系统中所有文字提示词应为中文，因为调用的模型也是中文模型
- 工具调用、function calling 等部分采用标准格式（保持英文/标准格式）

## 发现的英文文本 (分类梳理)

### 1. 系统提示词 (System Prompt) — HIGH PRIORITY
- **文件**: `src/lifeops/agent.py:17-26`
- **内容**: `DEFAULT_SYSTEM_PROMPT` 全部为英文
- **类型**: 传给 LLM 的核心系统提示词，**必须中文**

### 2. 工具描述 (Tool Definitions) — HIGH PRIORITY
这些是 function calling 的 `description` 字段，传给 LLM 的工具说明：

- **bash.py:43**: `description="Execute a bash command and return the output"`
- **bash.py:45**: `description="The bash command to execute"`
- **bash.py:46**: `description="Timeout in seconds"`
- **bash.py:47**: `description="Working directory"`
- **file_read.py:47**: `description="Read a file or list a directory"`
- **file_read.py:49-52**: 参数描述全英文
- **file_edit.py:53**: `description="Create, replace text, or append to files"`
- **file_edit.py:57-61**: 参数描述全英文
- **web_search.py:20**: `description="Search the web for information (requires MCP search server)"`
- **web_search.py:23**: `description="Search query"`

### 3. 用户界面消息 (CLI Messages) — MEDIUM PRIORITY
- **agent.py:140**: `"I couldn't generate a response. Please try again."`
- **agent.py:143**: `"I reached the maximum number of iterations. Please rephrase your request or break it into smaller steps."`
- **agent.py:192**: `"Error: LLM_API_KEY not set."` (错误提示)
- **agent.py:193-196**: API Key 设置指引消息（英文）
- **agent.py:202-205**: 启动横幅和帮助文本
- **agent.py:211**: `"Goodbye!"`
- **agent.py:218**: `"Goodbye!"`
- **agent.py:223**: `"Conversation reset."`
- **agent.py:241**: `"Thinking..."`
- **agent.py:245**: Panel title `"Agent"`
- **agent.py:247**: Panel title `"Error"`

### 4. 工具执行结果消息 (Tool Output) — MEDIUM PRIORITY
- **agent.py:118**: `f"Unknown tool: {tc.name}"`
- **agent.py:123**: `f"Error: {result.error}"` (前缀 Error)
- **bash.py:27**: `"(no output)"`
- **bash.py:32**: `f"Exit code {process.returncode}: {error_output}"`
- **bash.py:35**: `f"Command timed out after {timeout}s"`
- **file_read.py:18**: `f"File not found: {file_path}"`
- **file_read.py:34**: `f"... ({len(all_lines) - end} more lines)"`
- **file_edit.py:21**: `f"Created {file_path}"`
- **file_edit.py:25**: `f"File not found: {file_path}"`
- **file_edit.py:30**: `"Text not found in file"`
- **file_edit.py:33**: `f"Replaced in {file_path}"`
- **file_edit.py:44**: `f"Appended to {file_path}"`
- **file_edit.py:47**: `f"Unknown operation: {operation}"`
- **web_search.py:14**: `"Web search not yet implemented. Install a search provider MCP server."`

### 5. 日志消息 (Logger) — LOW PRIORITY (调试用，可保持英文)
- 多处 `logger.info`, `logger.debug`, `logger.warning`, `logger.error`
- 这些是开发者日志，通常保持英文是惯例

## 不需要改的部分 (保持标准格式)
- Tool name: `bash`, `file_read`, `file_edit`, `web_search` — 标准标识符
- Parameter name: `command`, `path`, `offset` 等 — API 参数名
- Tool function type: `"function"` — OpenAI 标准字段
- MessageRole 枚举值: `system`, `user`, `assistant`, `tool` — OpenAI 标准字段
- JSON Schema 结构: `"type": "object"`, `"properties"` 等 — 标准格式

## 范围边界
- INCLUDE: 系统提示词、工具描述、CLI 用户消息、工具执行结果消息
- EXCLUDE: 工具名称、参数名称、JSON Schema 结构关键字、日志消息(开发者用)

## 开放问题
- 日志消息是否也需中文化？(倾向: 不需要，这是开发者调试日志)

## 测试策略决策
- 基础设施: 已有 pytest 设置
- 自动测试: YES (tests-after) — 修改后验证中文字符串存在
- Agent QA: 手动启动 REPL 验证界面中文