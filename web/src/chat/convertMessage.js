/**
 * 把 LifeOps 本地消息结构转换为 assistant-ui 的 ThreadMessageLike。
 *
 * 消息分两类：
 * - 历史消息（服务端拉取）：只有 role + content 文本。
 * - 流式消息（本轮 run 产生）：带 parts 数组，文本与工具调用按到达顺序交错。
 *
 * 工具 part 不传显式 status：assistant-ui 会根据 result/approval 字段自动派生
 * （无 result 且 approval.approved 未定 → requires-action，见 auto-status 机制）。
 */
export function convertMessage(message) {
  if (message.role !== "assistant") {
    return {
      id: message.message_id,
      role: "user",
      content: [{ type: "text", text: message.content || "" }],
    };
  }

  if (!Array.isArray(message.parts) || message.parts.length === 0) {
    return {
      id: message.message_id,
      role: "assistant",
      content: [{ type: "text", text: message.content || "" }],
    };
  }

  const content = message.parts.map((part) => {
    if (part.kind === "tool") {
      return {
        type: "tool-call",
        toolCallId: part.toolCallId,
        toolName: part.toolName,
        args: part.args ?? {},
        argsText: part.argsText ?? JSON.stringify(part.args ?? {}, null, 2),
        result: part.result,
        isError: part.isError || undefined,
        approval: part.approval,
      };
    }
    return { type: "text", text: part.text || "" };
  });

  return { id: message.message_id, role: "assistant", content };
}
