# SQLite 迁移指南

## 概述

LifeOps 已从 JSONL 文件存储迁移到 SQLite 数据库，为对话历史提供了更可靠、更高效的存储方案。本次迁移带来以下核心改进：

- **分页查询**：会话列表和消息列表支持 `limit` / `offset` 参数，避免一次性返回大量数据
- **全文搜索**：新增 `/api/search/messages` 端点，支持对消息内容进行关键词搜索
- **结构化存储**：SQLite 提供事务保障、索引加速和原子写入，告别 JSONL 追加写的不稳定问题

## 新功能说明

### 分页查询

会话列表和消息详情端点新增分页参数：

| 端点 | 参数 | 类型 | 说明 |
|------|------|------|------|
| `GET /api/conversations` | `query` | string (可选) | 搜索关键词 |
| | `limit` | int (可选) | 返回数量上限 |
| | `offset` | int (可选) | 偏移量，用于翻页 |
| `GET /api/conversations/{id}` | `limit` | int (可选) | 消息数量上限 |
| | `offset` | int (可选) | 消息偏移量 |

**向后兼容**：不传分页参数时，API 返回格式与迁移前完全一致（数组格式）。

传入分页参数后，响应将包含分页元信息：

```json
{
  "conversations": [...],
  "total": 100,
  "limit": 20,
  "offset": 0
}
```

### 全文搜索

新增消息搜索端点：

```
GET /api/search/messages?q=<关键词>&limit=20&offset=0
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `q` | string | 是 | 搜索关键词，最少 1 个字符 |
| `limit` | int | 否 | 返回数量上限，默认 20 |
| `offset` | int | 否 | 偏移量，默认 0 |

响应示例：

```json
{
  "results": [
    {
      "conversation_id": "abc123",
      "role": "user",
      "content": "包含关键词的消息内容...",
      "created_at": "2025-01-01T00:00:00"
    }
  ],
  "total": 5,
  "limit": 20,
  "offset": 0
}
```

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LIFEOPS_DB_PATH` | SQLite 数据库文件路径 | `.lifeops/conversations.db` |

在 `.env` 文件中配置：

```bash
# SQLite 数据库路径（替代 JSONL 历史文件）
LIFEOPS_DB_PATH=.lifeops/conversations.db
```

旧变量 `LIFEOPS_HISTORY_PATH`（JSONL 路径）已弃用，保留但不再推荐使用。

## 自动迁移

启动 Web API（`uv run lifeops-web`）时，系统会自动检测迁移需求：

1. **检测 JSONL 文件**：如果 `LIFEOPS_HISTORY_PATH` 指向的 JSONL 文件存在，且 SQLite 数据库不存在或为空，自动触发迁移
2. **逐行解析**：读取 JSONL 文件中的每一行对话记录，解析后写入 SQLite
3. **原有文件保留**：迁移完成后 JSONL 文件不会被删除，可手动确认后清理

### 迁移流程

```
启动 lifeops-web
   │
   ├── 检查 LIFEOPS_DB_PATH 指向的数据库是否存在
   │      │
   │      ├── 存在且有数据 → 直接使用，跳过迁移
   │      │
   │      └── 不存在或为空
   │             │
   │             ├── 检查 LIFEOPS_HISTORY_PATH 指向的 JSONL 文件
   │             │      │
   │             │      ├── 存在 → 自动迁移 JSONL → SQLite
   │             │      │
   │             │      └── 不存在 → 创建新的空数据库
   │
   └── 启动完成，使用 SQLite 存储
```

### 手动迁移

如需重新触发迁移，删除 SQLite 数据库文件后重启 `lifeops-web` 即可：

```bash
rm .lifeops/conversations.db
uv run lifeops-web
```

## 前端 API 客户端更新

`web/src/api.js` 已更新，新增分页和搜索支持：

```javascript
// 分页获取会话列表
import { fetchConversations, fetchConversation, searchMessages } from "./api";

// 获取前 20 条会话
const result = await fetchConversations("", 20, 0);

// 获取会话详情，只加载最近 50 条消息
const detail = await fetchConversation("conv-id", 50, 0);

// 翻页：获取第 21-40 条会话
const page2 = await fetchConversations("", 20, 20);

// 全文搜索消息
const searchResult = await searchMessages("关键词", 20, 0);
```

所有函数保持向后兼容——不传分页参数时行为与之前一致。

## 故障排除

### 迁移后数据丢失

- 检查 JSONL 文件是否完整：`wc -l .lifeops/conversations.jsonl`
- 确认迁移日志中是否有错误：`LIFEOPS_LOG_LEVEL=DEBUG uv run lifeops-web`
- 可删除 `.lifeops/conversations.db` 后重启以重新触发迁移

### 数据库文件锁

SQLite 在并发写入时可能出现锁冲突。LifeOps 为单用户本地场景设计，正常使用不应遇到此问题。如出现 `database is locked` 错误：

1. 确认没有其他进程同时访问数据库
2. 检查是否有僵死的 `lifeops-web` 进程：`ps aux | grep lifeops`
3. 重启服务即可恢复

### 分页参数不生效

- 确认后端已迁移到 SQLite（JSONL 存储不支持分页）
- 检查请求参数是否正确传递：`GET /api/conversations?limit=20&offset=0`

### 搜索无结果

- 确认 `q` 参数不为空
- 搜索基于 SQLite LIKE 查询，需要消息内容中包含精确的搜索关键词
- 检查数据库中是否有数据：直接用 SQLite 客户端查看 `sqlite3 .lifeops/conversations.db "SELECT COUNT(*) FROM messages;"`

## API 变更对照

| 端点 | 变更 | 说明 |
|------|------|------|
| `GET /api/conversations` | 新增 query / limit / offset 参数 | 传入分页参数后返回含 `total` 的对象；不传则保持数组格式 |
| `GET /api/conversations/{id}` | 新增 limit / offset 参数 | 传入后返回含分页元信息的对象；不传则保持原格式 |
| `GET /api/search/messages` | **新增端点** | 全文搜索消息内容 |