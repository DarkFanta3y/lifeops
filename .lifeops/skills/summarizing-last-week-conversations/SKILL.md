---
name: summarizing-last-week-conversations
description: 根据触发 Skill 时的时间戳，总结过去一周的对话内容。Use when the user asks to summarize, review, recap, or extract action items from conversations in the last week.
metadata:
  short-description: 总结过去一周对话
---

# Summarize Last Week Conversation

## 目标

以用户触发本 Skill 的时间戳为结束时间，回顾过去 7 天内的对话内容，输出一份可执行、可追溯的中文摘要。

## 时间窗口

1. 将“触发时间”作为窗口结束时间。
2. 窗口开始时间 = 触发时间向前推 7 天。
3. 如果系统上下文提供了当前日期、时区或消息时间戳，优先使用这些信息。
4. 如果没有精确时间戳，明确说明使用了可见上下文中的当前日期/时间作为近似触发时间。

## 工作流

1. 收集过去 7 天的可见对话、短期记忆、长期记忆或可用检索结果。
2. 只纳入落在时间窗口内、且能从上下文或检索结果中找到依据的内容。
3. 按主题合并重复讨论，保留关键决策、已完成事项、待办事项、阻塞点和未关闭问题。
4. 对无法确认时间或来源的内容，不要编造；放入“未确认/缺口”。
5. 输出前检查是否遗漏了用户明确要求的范围、格式或关注点。

## 输出格式

使用以下结构：

```markdown
## 过去一周对话总结

- 时间范围：YYYY-MM-DD HH:mm 至 YYYY-MM-DD HH:mm（时区）

### 主题概览
- ...

### 关键决策
- ...

### 已完成事项
- ...

### 待办事项
- [ ] ...

### 阻塞点与风险
- ...

### 未确认/缺口
- ...
```

如果某一节没有内容，写“无明确记录”，不要删除该节。
