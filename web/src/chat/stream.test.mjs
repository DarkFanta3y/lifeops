import { test } from 'node:test';
import assert from 'node:assert/strict';
import { updateStreamParts } from './stream.js';

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
