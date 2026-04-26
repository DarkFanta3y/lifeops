# Draft: 修复 surrogate 编码错误

## 错误分析

**错误信息**: `'utf-8' codec can't encode characters in position 1833-1834: surrogates not allowed`

**发生位置**: `await self.llm.chat(all_messages, ...)` 内部 → openai/httpx 序列化请求时

**根本原因**:
- Python 字符串中含有 Unicode 代理字符（U+D800-U+DFFF）
- 这些字符在 UTF-16 中有效，但在 UTF-8 中非法
- openai/httpx 库内部调用 `.encode('utf-8')` 时抛出 `UnicodeEncodeError`

**数据流**:
1. LLM API 返回 JSON 响应，其中包含 `\uDxxx` 转义序列
2. Python 的 JSON 解析器解析后产生含 surrogate 的字符串
3. 字符串存储在 `Message.content` 或 `tool_calls[].arguments` 中
4. 下一轮 ReAct 循环中，这些消息被发送回 LLM API
5. openai 库序列化时调用 `.encode('utf-8')` 失败

**涉及的代码路径**:
- `llm/types.py`: `ChatResponse.from_openai_response()` — 提取 LLM 响应
- `llm/types.py`: `Message.to_dict()` — 序列化消息为 dict
- `agent.py`: 第 118 行 `self.llm.chat()`
- `agent.py`: 第 156-164 行 — 工具结果也可能携带 surrogate

## 受影响文件
- `src/lifeops/llm/types.py` — 需要清理 LLM 响应中的 surrogate
- `src/lifeops/agent.py` — 需要清理工具输出中的 surrogate

## 修复方案
添加 `_clean_surrogates()` 函数，在数据进入系统时清理 surrogate 字符。

### 边界修复点
1. `ChatResponse.from_openai_response()` — 进入系统时清理 content 和 arguments
2. `agent.py` 工具结果处理 — 清理 `tool_output` 中的 surrogate
3. `Message.to_dict()` — 作为兜底清理所有 content
