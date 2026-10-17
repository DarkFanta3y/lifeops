// 实时和历史共用调用模型；有 ID 时严格匹配，旧服务事件才按同名先入先出兼容。
function matching(parts, data, predicate = () => true) {
  return parts.findIndex(part => part.kind === 'tool' && predicate(part)
    && (data.call_id ? part.callId === data.call_id : part.toolName === data.tool_name));
}
function callFields(data) {
  const fields = {};
  for (const [wire, key] of Object.entries({ call_id: 'callId', run_id: 'runId', iteration: 'iteration',
    canonical_name: 'canonicalName', prepare_key: 'prepareKey', status: 'status', metadata: 'metadata',
    duration_ms: 'durationMs', started_at_ms: 'startedAt', ended_at_ms: 'endedAt',
    approval: 'approval', review: 'review', turn_status: 'turnStatus', turn_error: 'turnError' })) {
    if (data[wire] !== undefined && data[wire] !== null) fields[key] = data[wire];
  }
  return fields;
}
export function updateStreamParts(parts, type, data) {
  if (type === 'token') {
    if (!data) return parts;
    const last = parts.at(-1);
    return last?.kind === 'text'
      ? [...parts.slice(0, -1), { ...last, text: last.text + data }]
      : [...parts, { kind: 'text', text: data }];
  }
  if (type === 'text_segment' || type === 'answer_start') {
    if (type === 'answer_start' && parts.at(-1)?.final) return parts;
    const previous = parts.filter(part => part.status !== 'preparing')
      .map(part => part.final ? { ...part, final: false } : part);
    return [...previous, { kind: 'text', text: '', key: data.segment_id || `answer:${data.run_id}:${data.iteration}`, final: type === 'answer_start' }];
  }
  if (type === 'run_finished') return settleStreamParts(parts, data.status, data.final_output);
  if (type === 'tool_prepare' || type === 'tool_call') {
    const name = data.tool_name || data.name;
    if (name === 'finish_task') return parts;
    const fields = callFields(data);
    const preparing = type === 'tool_prepare';
    const index = parts.findIndex(part => part.kind === 'tool' && (
      data.call_id && part.callId === data.call_id
      || data.prepare_key && part.prepareKey === data.prepare_key));
    const call = { kind: 'tool', toolName: name, args: data.args ?? data.params ?? {}, ...fields,
      status: preparing ? 'preparing' : data.status || 'running' };
    return index < 0 ? [...parts, call] : parts.map((part, i) => i === index ? { ...part, ...call } : part);
  }
  if (type === 'plan_review_required') {
    const index = matching(parts, { ...data, tool_name: 'exit_plan_mode' }, part =>
      (!part.review || part.review.request_id === data.request_id) && part.result === undefined);
    const review = { ...data, decision: null };
    return index < 0 ? [...parts, { kind: 'tool', toolName: 'exit_plan_mode', callId: data.call_id,
      args: { plan: data.plan }, review }] : parts.map((part, i) => i === index ? { ...part, review } : part);
  }
  if (type === 'plan_review_resolved' || type === 'approval_resolved') {
    const key = type === 'approval_resolved' ? 'approval' : 'review';
    return parts.map(part => part[key]?.request_id === data.request_id
      ? { ...part, [key]: { ...part[key], decision: data.decision } } : part);
  }
  if (!['tool_result', 'tool_status', 'approval_required'].includes(type)) return parts;
  const index = matching(parts, data, part => type === 'tool_status' || part.result === undefined
    && (type !== 'approval_required' || !part.approval || part.approval.request_id === data.request_id));
  if (index < 0) return type === 'approval_required'
    ? [...parts, { kind: 'tool', toolName: data.tool_name, callId: data.call_id,
      args: data.params ?? data.args ?? {}, approval: data }] : parts;
  return parts.map((part, i) => {
    if (i !== index) return part;
    if (type === 'approval_required') return { ...part, approval: data, status: 'waiting_approval' };
    if (type === 'tool_status') return { ...part, ...callFields(data) };
    return { ...part, ...callFields(data),
      status: data.status || (data.success === false ? 'failed' : 'completed'),
      result: data.output ?? data.result ?? (data.success === false ? '' : '（无输出）'),
      rawOutput: data.output ?? data.result, error: data.error, isError: data.success === false,
      // 旧服务失败事件只有 error，仍让原有消费者读到错误文本。
      ...(data.success === false && !data.output && !data.result ? { result: data.error || '工具执行失败' } : {}),
      todos: data.metadata?.kind === 'todo' ? data.metadata.todos : undefined };
  });
}

export function settleStreamParts(parts, status = 'completed', finalOutput) {
  let settled = parts.filter(part => part.status !== 'preparing').map(part => {
    if (part.kind !== 'tool' || part.result !== undefined) return part;
    return { ...part, interrupted: true, status: 'interrupted' };
  });
  if (typeof finalOutput === 'string' && finalOutput) {
    const index = settled.findLastIndex(part => part.kind === 'text' && part.final);
    const tail = settled.at(-1);
    if (index >= 0) settled = settled.map((part, i) => i === index ? { ...part, text: finalOutput } : part);
    else if (tail?.kind === 'text' && tail.text === finalOutput) settled = [...settled.slice(0, -1), { ...tail, final: true }];
    else settled.push({ kind: 'text', text: finalOutput, final: true, key: 'final' });
  } else if (status === 'completed' && settled.at(-1)?.kind === 'text') {
    settled = [...settled.slice(0, -1), { ...settled.at(-1), final: true }];
  }
  return settled.filter(part => part.kind !== 'text' || part.text);
}

function argsOf(value) {
  if (typeof value !== 'string') return value || {};
  try { return JSON.parse(value); } catch { return { 原始参数: value }; }
}

// 历史消息按数据库身份恢复顺序，调用和结果跨分页也只生成一个工具节点。
export function restoreConversation(messages, intermediate, executions = []) {
  const records = [...messages, ...intermediate].filter(record => typeof record.message_id === 'number')
    .sort((a, b) => a.message_id - b.message_id);
  if (!records.length) return messages;
  const snapshots = new Map(executions.map(snapshot => [snapshot.call_id, snapshot]));
  const output = [];
  let turn = [], user;
  function flush() {
    if (!turn.length) return;
    let parts = [], final, turnStatus, turnError;
    for (const record of turn) {
      if (record.role === 'assistant') {
        if (record.content) {
          const isFinal = !record.intermediate && !record.tool_calls;
          parts.push({ kind: 'text', text: record.content, key: `message:${record.message_id}`, final: isFinal });
          if (isFinal) final = record;
        }
        for (const call of record.tool_calls || []) {
          const name = call.function?.name;
          parts = updateStreamParts(parts, 'tool_call', { call_id: call.id, tool_name: name, args: argsOf(call.function?.arguments) });
          const snapshot = snapshots.get(call.id);
          if (snapshot) {
            parts = updateStreamParts(parts, 'tool_status', snapshot);
            if (snapshot.output !== undefined || snapshot.success !== undefined) parts = updateStreamParts(parts, 'tool_result', snapshot);
            if (snapshot.turn_status) turnStatus = snapshot.turn_status;
            if (snapshot.turn_error) turnError = snapshot.turn_error;
          }
        }
      } else if (record.role === 'tool' && !snapshots.has(record.tool_call_id)) {
        const failed = record.content?.startsWith('Error: ');
        parts = updateStreamParts(parts, 'tool_result', { call_id: record.tool_call_id,
          tool_name: record.tool_name, success: !failed, output: record.content,
          ...(failed ? { error: record.content.slice(7) } : {}) });
      }
    }
    // 没有结束快照的旧记录不捏造执行状态和耗时。
    parts = parts.map(part => part.kind === 'tool' && part.result === undefined
      ? { ...part, interrupted: true, status: part.status === 'interrupted' ? 'interrupted' : 'incomplete' } : part);
    if (parts.length) output.push({ ...(final || {}), role: 'assistant',
      message_id: final?.message_id || `history:${user?.message_id || turn[0].message_id}`,
      content: final?.content || '', parts, turnError, turnStatus: turnStatus || (final ? 'completed' : 'incomplete') });
    turn = [];
  }
  for (const record of records) {
    if (record.role === 'user') { flush(); user = record; output.push(record); }
    else turn.push(record);
  }
  flush();
  return output;
}

export function collectSources(calls) {
  const sources = [];
  for (const call of calls) {
    const name = call.name || '';
    const kind = name.endsWith('retrieve_knowledge') ? 'knowledge' : name.endsWith('web_search') ? 'web' : null;
    if (!kind) continue;
    const args = argsOf(call.args);
    const id = kind === 'knowledge' ? String(args?.source || '').trim() : '';
    if (!sources.some(item => item.kind === kind && item.id === id)) sources.push({ kind, id });
  }
  return sources;
}
