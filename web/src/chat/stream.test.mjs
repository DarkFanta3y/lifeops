import { test } from 'node:test';
import assert from 'node:assert/strict';
import { collectSources, updateStreamParts } from './stream.js';

test('文本、同名工具结果与审批按事件顺序关联，保留原对象', () => {
  const original = [];
  let parts = updateStreamParts(original, 'token', '你好');
  parts = updateStreamParts(parts, 'tool_call', { tool_name: 'bash', args: { command: 'pwd' } });
  parts = updateStreamParts(parts, 'approval_required', {
    request_id: 'r1', tool_name: 'bash', risk_level: 'high', reason: '执行命令',
  });
  assert.equal(parts[1].approval.request_id, 'r1');
  parts = updateStreamParts(parts, 'approval_resolved', { request_id: 'r1', decision: 'deny' });
  assert.equal(parts[1].approval.decision, 'deny');
  parts = updateStreamParts(parts, 'tool_result', { tool_name: 'bash', success: false, error: '拒绝' });
  parts = updateStreamParts(parts, 'tool_call', { tool_name: 'bash', args: {} });
  parts = updateStreamParts(parts, 'tool_result', { tool_name: 'bash', output: 'ok', success: true });
  parts = updateStreamParts(parts, 'token', '完成');
  assert.equal(parts[1].result, '拒绝');
  assert.equal(parts[2].result, 'ok');
  assert.equal(parts[3].text, '完成');
  assert.deepEqual(original, []);
});

test('计划结果保留结构、连续 token 合并、孤立审批仍可操作', () => {
  let parts = updateStreamParts([], 'token', 'a');
  parts = updateStreamParts(parts, 'token', 'b');
  assert.deepEqual(parts, [{ kind: 'text', text: 'ab' }]);
  parts = updateStreamParts(parts, 'approval_required', {
    request_id: 'r2', tool_name: 'todo_write', args: { todos: [] },
  });
  parts = updateStreamParts(parts, 'tool_result', {
    tool_name: 'todo_write', metadata: { kind: 'todo', todos: [{ content: '验收', status: 'completed' }] },
  });
  assert.equal(parts[1].todos[0].content, '验收');
  assert.deepEqual(updateStreamParts(parts, 'unknown', {}), parts);
});

test('同轮先发布两次同名调用时，审批和结果按后端执行顺序对应参数', () => {
  let parts = updateStreamParts([], 'tool_call', { tool_name: 'bash', args: { command: 'A' } });
  parts = updateStreamParts(parts, 'tool_call', { tool_name: 'bash', args: { command: 'B' } });
  parts = updateStreamParts(parts, 'approval_required', { request_id: 'A', tool_name: 'bash' });
  assert.equal(parts[0].approval?.request_id, 'A');
  assert.equal(parts[1].approval, undefined);
  parts = updateStreamParts(parts, 'approval_resolved', { request_id: 'A', decision: 'deny' });
  parts = updateStreamParts(parts, 'tool_result', { tool_name: 'bash', success: false, output: '', error: 'A 被拒绝' });
  parts = updateStreamParts(parts, 'approval_required', { request_id: 'B', tool_name: 'bash' });
  parts = updateStreamParts(parts, 'tool_result', { tool_name: 'bash', success: true, output: 'B 完成' });
  assert.equal(parts[0].result, 'A 被拒绝');
  assert.equal(parts[1].approval.request_id, 'B');
  assert.equal(parts[1].result, 'B 完成');
});

test('来源提取：识别知识库与联网搜索，解析字符串参数并去重', () => {
  const sources = collectSources([
    { name: 'retrieve_knowledge', args: '{"query":"a","source":"notes"}' },
    { name: 'retrieve_knowledge', args: { query: 'b', source: 'notes' } },
    { name: 'web_search', args: { query: 'x' } },
    { name: 'web_search', args: 'not json' },
    { name: 'bash', args: { command: 'pwd' } },
  ]);
  assert.deepEqual(sources, [{ kind: 'knowledge', id: 'notes' }, { kind: 'web', id: '' }]);
});

test('finish_task 不生成工具卡片，其结果事件被忽略', () => {
  let parts = updateStreamParts([], 'tool_call', { tool_name: 'finish_task', args: { answer: 'hi' } });
  parts = updateStreamParts(parts, 'tool_result', { tool_name: 'finish_task', success: true, output: 'hi' });
  parts = updateStreamParts(parts, 'token', 'hi');
  assert.deepEqual(parts, [{ kind: 'text', text: 'hi' }]);
});

test('计划评审挂到 exit_plan_mode 调用并记录决策', () => {
  let parts = updateStreamParts([], 'tool_call', { tool_name: 'exit_plan_mode', args: { plan: '# 计划' } });
  parts = updateStreamParts(parts, 'plan_review_required', { request_id: 'p1', title: '计划', plan: '# 计划' });
  assert.equal(parts.length, 1);
  assert.equal(parts[0].review.decision, null);
  parts = updateStreamParts(parts, 'plan_review_resolved', { request_id: 'p1', decision: 'approve' });
  assert.equal(parts[0].review.decision, 'approve');
  parts = updateStreamParts(parts, 'tool_result', { tool_name: 'exit_plan_mode', success: true, output: '已批准' });
  assert.equal(parts[0].result, '已批准');
});

test('找不到 exit_plan_mode 调用时单独追加计划卡片', () => {
  const parts = updateStreamParts([], 'plan_review_required', { request_id: 'p2', title: 'T', plan: '# T' });
  assert.equal(parts[0].toolName, 'exit_plan_mode');
  assert.equal(parts[0].args.plan, '# T');
});

test('调用 ID 关联乱序结果与审批，不回退到同名的另一调用', () => {
  let parts = updateStreamParts([], 'tool_call', { call_id: 'a', tool_name: 'bash', args: { command: 'A' } });
  parts = updateStreamParts(parts, 'tool_call', { call_id: 'b', tool_name: 'bash', args: { command: 'B' } });
  parts = updateStreamParts(parts, 'tool_result', { call_id: 'b', tool_name: 'bash', success: false, output: 'stdout', error: 'stderr' });
  parts = updateStreamParts(parts, 'approval_required', { call_id: 'a', tool_name: 'bash', request_id: 'r' });
  assert.equal(parts[0].result, undefined);
  assert.equal(parts[0].approval.request_id, 'r');
  assert.equal(parts[1].result, 'stdout');
  assert.equal(parts[1].error, 'stderr');
  assert.deepEqual(updateStreamParts(parts, 'tool_result', { call_id: 'missing', tool_name: 'bash', output: '错误关联' }), parts);
});

test('预热原地变为正式调用，结束时清理未派发节点并保留最终回答', async () => {
  const { settleStreamParts } = await import('./stream.js');
  let parts = updateStreamParts([], 'tool_prepare', { prepare_key: 'r:0:0', tool_name: 'file_read' });
  parts = updateStreamParts(parts, 'tool_call', { prepare_key: 'r:0:0', call_id: 'a', tool_name: 'file_read', args: { path: 'a.md' } });
  assert.equal(parts.length, 1); assert.equal(parts[0].callId, 'a');
  parts = updateStreamParts(parts, 'tool_prepare', { prepare_key: 'r:1:0', tool_name: 'bash' });
  parts = updateStreamParts(parts, 'answer_start', { run_id: 'r', iteration: 1 });
  parts = updateStreamParts(parts, 'token', '答案');
  parts = settleStreamParts(parts, 'completed', '最终答案');
  assert.equal(parts.length, 2); assert.equal(parts[0].interrupted, true);
  assert.equal(parts[1].final, true); assert.equal(parts[1].text, '最终答案');
});

test('历史恢复保留消息顺序、diff、审批与最终回答，不重复追加原始结果', async () => {
  const { restoreConversation } = await import('./stream.js');
  const restored = restoreConversation([
    { message_id: 1, role: 'user', content: '修改文件' }, { message_id: 5, role: 'assistant', content: '完成' },
  ], [
    { message_id: 4, role: 'tool', tool_call_id: 'a', tool_name: 'file_replace', content: '旧原文' },
    { message_id: 3, role: 'assistant', intermediate: true, tool_calls: [{ id: 'a', function: { name: 'file_replace', arguments: '{"path":"a.md"}' } }] },
    { message_id: 2, role: 'assistant', intermediate: true, content: '先查看文件' },
  ], [{ call_id: 'a', tool_name: 'file_replace', status: 'completed', success: true, output: '新结果',
    metadata: { diff: '-旧\n+新' }, approval: { request_id: 'r', decision: 'allow_once' }, turn_status: 'completed' }]);
  assert.equal(restored.length, 2);
  assert.deepEqual(restored[1].parts.map(part => part.kind), ['text', 'tool', 'text']);
  assert.equal(restored[1].parts[1].result, '新结果');
  assert.equal(restored[1].parts[1].metadata.diff, '-旧\n+新');
  assert.equal(restored[1].parts[1].approval.decision, 'allow_once');
  assert.equal(restored[1].parts[2].final, true);
});

test('中断历史和旧版缺失结果不会恢复为执行中或可操作审批', async () => {
  const { restoreConversation } = await import('./stream.js');
  const messages = [{ message_id: 1, role: 'user', content: '读取' }];
  const logs = [{ message_id: 2, role: 'assistant', intermediate: true,
    tool_calls: [{ id: 'a', function: { name: 'file_read', arguments: '{}' } }] }];
  const old = restoreConversation(messages, logs)[1];
  assert.equal(old.parts[0].status, 'incomplete');
  const stopped = restoreConversation(messages, logs, [{ call_id: 'a', status: 'interrupted',
    turn_status: 'cancelled', review: { decision: null } }])[1];
  assert.equal(stopped.turnStatus, 'cancelled');
  assert.equal(stopped.parts[0].interrupted, true);
});

test('工具摘要和过程分组按调用身份计数，正文拆组，空迭代不拆组', async () => {
  const { activitySummary, processEntries, toolPresentation } = await import('./toolPresentation.js');
  const a = { kind: 'tool', callId: 'a', toolName: 'file_read', args: { path: 'README.md' }, result: '1: 内容', metadata: { shown_lines: 1 } };
  const b = { kind: 'tool', callId: 'b', toolName: 'bash', args: { command: 'pwd' }, isError: true, error: 'Exit code 8' };
  const entries = processEntries([a, b, { kind: 'text', text: '进度' }, { ...a, callId: 'c' }]);
  assert.deepEqual(entries.map(item => item.kind), ['group', 'text', 'group']);
  assert.equal(activitySummary([a, a, b]), '读取文件 1 次、执行命令 1 次');
  assert.equal(toolPresentation(a).suffix, '1 行');
  assert.equal(toolPresentation(b).exitCode, undefined);
  assert.equal(toolPresentation({ ...b, metadata: { returncode: 8 } }).exitCode, 8);
});

test('状态快照之后到达的计划评审不重复创建卡片', () => {
  let parts = updateStreamParts([], 'tool_call', { call_id: 'a', tool_name: 'exit_plan_mode', args: { plan: '# 计划' } });
  parts = updateStreamParts(parts, 'tool_status', { call_id: 'a', tool_name: 'exit_plan_mode', review: { request_id: 'p', decision: null } });
  parts = updateStreamParts(parts, 'plan_review_required', { call_id: 'a', request_id: 'p', plan: '# 计划' });
  assert.equal(parts.length, 1);
  assert.equal(parts[0].review.plan, '# 计划');
});

test('失败的 finish_task 候选答案在重试后成为过程，不冒充最终回答', () => {
  let parts = updateStreamParts([], 'answer_start', { run_id: 'r', iteration: 0 });
  parts = updateStreamParts(parts, 'token', '尚未完成');
  parts = updateStreamParts(parts, 'text_segment', { segment_id: 'r:1' });
  assert.equal(parts[0].final, false);
  parts = updateStreamParts(parts, 'answer_start', { run_id: 'r', iteration: 1 });
  parts = updateStreamParts(parts, 'token', '最终答复');
  parts = updateStreamParts(parts, 'run_finished', { status: 'completed', final_output: '最终答复' });
  assert.equal(parts.filter(part => part.final).length, 1);
});

test('未知或损坏的结构化结果回退原文，旧结果明确结束状态', async () => {
  const { toolPresentation } = await import('./toolPresentation.js');
  const unknown = toolPresentation({ toolName: 'mcp_custom', result: '原文', metadata: {
    todos: [null], diff: '+未授权修改', results: [null],
  } });
  assert.equal(unknown.todos, null); assert.equal(unknown.diff, null);
  assert.deepEqual(unknown.sourceLinks, []); assert.equal(unknown.output, '原文');
  let parts = updateStreamParts([], 'tool_call', { tool_name: 'bash', args: {} });
  parts = updateStreamParts(parts, 'tool_result', { tool_name: 'bash', success: true, output: 'ok' });
  assert.equal(parts[0].status, 'completed');
});
