// SSE 事件到页面消息的纯转换，工具同名时关联最早尚未完成的调用（后端按调用顺序发布结果）。
export function updateStreamParts(parts, type, data) {
  if (type === 'token') {
    if (!data) return parts;
    const last = parts.at(-1);
    return last?.kind === 'text'
      ? [...parts.slice(0, -1), { ...last, text: last.text + data }]
      : [...parts, { kind: 'text', text: data }];
  }
  if (type === 'tool_call') {
    return [...parts, { kind: 'tool', toolName: data.tool_name || data.name,
      args: data.args ?? data.params ?? {} }];
  }
  if (type === 'approval_resolved') {
    return parts.map(part => part.approval?.request_id === data.request_id
      ? { ...part, approval: { ...part.approval, decision: data.decision } } : part);
  }
  if (!['tool_result', 'approval_required'].includes(type)) return parts;
  const index = parts.findIndex(part => part.kind === 'tool'
    && part.toolName === data.tool_name && part.result === undefined
    && (type !== 'approval_required' || !part.approval));
  if (index < 0) {
    return type === 'approval_required'
      ? [...parts, { kind: 'tool', toolName: data.tool_name, args: data.params ?? data.args ?? {}, approval: data }]
      : parts;
  }
  return parts.map((part, i) => i !== index ? part : type === 'approval_required'
    ? { ...part, approval: data }
    : { ...part, result: data.success === false ? data.error || data.output || data.result || '工具执行失败'
      : data.output ?? data.result ?? '（无输出）',
      isError: data.success === false,
      todos: data.metadata?.kind === 'todo' ? data.metadata.todos : undefined });
}
