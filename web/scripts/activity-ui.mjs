// 工具展示的隔离浏览器验收：不连接真实数据库，也不调用模型。
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';
const shots = '/tmp/lifeops-activity-ui';
const text = Array.from({ length: 24 }, (_, i) => `${i + 1}: 这是第 ${i + 1} 行内容`).join('\n');
const historical = {
  messages: [{ message_id: 1, role: 'user', content: '查看文件并修改配置' }, { message_id: 6, role: 'assistant', content: '文件已更新，详细变更可在工作过程中查看。' }],
  intermediate_messages: [
    { message_id: 2, role: 'assistant', intermediate: true, content: '我先检查已有配置。', tool_calls: [
      { id: 'read', function: { name: 'file_read', arguments: '{"path":"README.md"}' } },
      { id: 'edit', function: { name: 'file_replace', arguments: '{"path":"config.py","old_text":"旧值","new_text":"新值"}' } },
    ] },
    { message_id: 3, role: 'tool', tool_call_id: 'read', tool_name: 'file_read', content: text },
    { message_id: 4, role: 'tool', tool_call_id: 'edit', tool_name: 'file_replace', content: '已修改' },
  ],
  tool_executions: [
    { call_id: 'read', tool_name: 'file_read', status: 'completed', success: true, output: text, metadata: { total_lines: 24, shown_lines: 24 }, turn_status: 'completed' },
    { call_id: 'edit', tool_name: 'file_replace', status: 'completed', success: true, output: '已修改', metadata: { diff: '--- a/config.py\n+++ b/config.py\n@@ -1 +1 @@\n-旧值\n+新值' }, turn_status: 'completed' },
  ], has_more: false,
};
let stream, scrolling;
const sse = (res, type, data) => res.write(`data: ${JSON.stringify({ type, data })}\n\n`);
const server = createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*'); res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  if (req.method === 'OPTIONS') { res.end(); return; }
  const json = data => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); };
  if (req.url === '/api/chat') {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const message = JSON.parse(Buffer.concat(chunks).toString()).message;
    stream = res; res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.flushHeaders();
    if (message === '滚动测试') {
      scrolling = res;
      sse(res, 'text_segment', { segment_id: 'scroll:0' });
      sse(res, 'token', Array.from({ length: 100 }, (_, i) => `工作过程第 ${i + 1} 段。\n\n`).join(''));
      return;
    }
    if (message === '失败测试') {
      sse(res, 'tool_call', { call_id: 'bad', tool_name: 'bash', args: { command: 'unavailable' } });
      sse(res, 'tool_result', { call_id: 'bad', tool_name: 'bash', success: false, error: '命令不可用', status: 'failed' });
      sse(res, 'run_finished', { status: 'failed', error: '命令不可用' });
      sse(res, 'done', { conversation_id: 'new', status: 'failed' }); res.end(); return;
    }
    sse(res, 'tool_prepare', { prepare_key: 'r:0:0', tool_name: 'bash' });
    setTimeout(() => {
      sse(res, 'tool_call', { call_id: 'a', prepare_key: 'r:0:0', tool_name: 'bash', args: { command: 'pwd' }, status: 'queued' });
      sse(res, 'approval_required', { call_id: 'a', request_id: 'approval', tool_name: 'bash', params_preview: 'pwd', risk_level: 'high', reason: '请批准测试命令' });
    }, 80); return;
  }
  if (req.url === '/continue-scroll') {
    sse(scrolling, 'token', '后续仍在生成。\n\n'); json({ ok: true }); return;
  }
  if (req.url === '/finish-scroll') {
    sse(scrolling, 'answer_start', { run_id: 'scroll', iteration: 1 });
    sse(scrolling, 'token', '滚动测试完成。');
    sse(scrolling, 'run_finished', { status: 'completed', final_output: '滚动测试完成。' });
    sse(scrolling, 'done', { conversation_id: 'new', status: 'completed' }); scrolling.end(); json({ ok: true }); return;
  }
  if (req.url === '/api/approvals/approval') {
    json({ success: true });
    sse(stream, 'approval_resolved', { call_id: 'a', request_id: 'approval', decision: 'allow_once' });
    sse(stream, 'tool_status', { call_id: 'a', tool_name: 'bash', status: 'running' });
    sse(stream, 'tool_result', { call_id: 'a', tool_name: 'bash', output: '/workspace', success: true, status: 'completed', metadata: { returncode: 0 } });
    sse(stream, 'answer_start', { run_id: 'r', iteration: 1 }); sse(stream, 'token', '授权后执行完成。');
    sse(stream, 'run_finished', { status: 'completed', final_output: '授权后执行完成。' });
    sse(stream, 'done', { status: 'completed', conversation_id: 'new' }); stream.end(); return;
  }
  if (req.url.startsWith('/api/conversations/')) { json(historical); return; }
  if (req.url.startsWith('/api/conversations')) { json({ conversations: [{ conversation_id: 'history', title: '工具展示验收' }], total: 1 }); return; }
  json({ sources: [] });
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const mock = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ channel: process.env.SMOKE_CHROMIUM_CHANNEL || undefined });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['clipboard-read', 'clipboard-write'] });
const page = await context.newPage(), errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.route('**/api/**', route => {
  const url = new URL(route.request().url());
  return route.continue({ url: mock + url.pathname + url.search });
});
try {
  await mkdir(shots, { recursive: true });
  await page.goto(process.env.SMOKE_BASE || 'http://127.0.0.1:5173');
  await page.getByText('工具展示验收', { exact: true }).click();
  await page.getByText('文件已更新，详细变更可在工作过程中查看。', { exact: true }).waitFor();
  assert.equal(await page.locator('[data-slot=lifeops-tool-row]:visible').count(), 0);
  await page.getByRole('button', { name: /^工作过程 ·/ }).click();
  await page.locator('.activity-group-head').click();
  assert.equal(await page.locator('[data-slot=lifeops-tool-row]:visible').count(), 2);
  const read = page.locator('[data-slot=lifeops-tool-row]').first();
  await read.locator('.activity-tool-summary').click();
  assert.equal(await read.locator('.activity-code code').count(), 8);
  await read.getByRole('button', { name: '展开剩余 16 行' }).click();
  assert.equal(await read.locator('.activity-code code').count(), 24);
  await read.getByRole('button', { name: '原始参数与结果' }).click();
  await read.getByRole('button', { name: '复制参数', exact: true }).click();
  assert.match(await page.evaluate(() => navigator.clipboard.readText()), /README.md/);
  await page.getByRole('button', { name: '详细', exact: true }).click();
  assert.equal(await read.locator('.activity-tool-body').isVisible(), true);
  const edit = page.locator('[data-slot=lifeops-tool-row]').nth(1);
  await edit.locator('.activity-tool-summary').click();
  await edit.getByText('-旧值', { exact: true }).waitFor();
  await page.screenshot({ path: `${shots}/detailed.png` });
  await page.reload(); await page.getByText('工具展示验收', { exact: true }).click();
  await page.locator('[data-slot=lifeops-tool-row]:visible').first().waitFor();
  assert.equal(await page.getByRole('button', { name: '详细', exact: true }).getAttribute('aria-pressed'), 'true');
  await page.locator('[data-slot=lifeops-tool-row]').first().locator('.activity-tool-summary').focus();
  await page.keyboard.press('Enter'); assert.equal(await page.locator('.activity-tool-body').count(), 1);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '切换侧栏', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.sidebar').getBoundingClientRect().width <= 64);
  await page.evaluate(() => document.documentElement.classList.add('dark'));
  await page.screenshot({ path: `${shots}/mobile-dark.png` });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.equal(await page.locator('#header-actions').evaluate(el => el.getBoundingClientRect().right <= innerWidth), true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: '切换侧栏', exact: true }).click();
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  const input = page.locator('[data-slot=lifeops-composer] textarea');
  await input.fill('审批演示'); await input.press('Enter');
  await page.locator('[data-slot=lifeops-approval-card]').waitFor();
  assert.equal(await input.isDisabled(), true);
  await page.getByRole('button', { name: '标准', exact: true }).click();
  assert.equal(await page.locator('[data-slot=lifeops-approval-card]').isVisible(), true);
  await page.getByRole('button', { name: '允许一次', exact: true }).click();
  await page.getByText('授权后执行完成。', { exact: true }).waitFor();
  assert.equal(await page.locator('[data-slot=lifeops-approval-card]').count(), 0);
  assert.equal(await page.locator('[data-slot=lifeops-tool-row]:visible').count(), 0);
  await page.screenshot({ path: `${shots}/completed.png` });
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await input.fill('失败测试'); await input.press('Enter');
  await page.getByText('运行失败', { exact: true }).waitFor();
  await page.getByText('命令不可用', { exact: true }).waitFor();
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await input.fill('滚动测试'); await input.press('Enter');
  await page.getByText(/工作过程第 100 段/).first().waitFor();
  const viewport = page.locator('.lifeops-message-list');
  await viewport.hover(); await page.mouse.wheel(0, -600);
  await page.waitForTimeout(100);
  const before = await viewport.evaluate(el => el.scrollTop);
  await fetch(mock + '/continue-scroll'); await page.waitForTimeout(100);
  assert.equal(await viewport.evaluate(el => el.scrollTop), before);
  await fetch(mock + '/finish-scroll');
  await page.getByRole('button', { name: /^工作过程 ·/ }).waitFor();
  assert.equal(await viewport.evaluate(el => el.scrollTop), before);
  assert.equal(await page.getByRole('button', { name: /^工作过程 ·/ }).getAttribute('aria-expanded'), 'true');
  assert.deepEqual(errors, []);
  console.log('通过：三层折叠、8 行预览、完整展开/复制、模式保持、历史 diff、键盘、窄屏/暗色、实时审批、完成折叠、失败原因与阅读位置保持');
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
