// 串行浏览器契约检查；先 npm run dev。用隔离 SSE/HTTP 桩，避免写真实资料或调用模型。
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';
const BASE = process.env.SMOKE_BASE || 'http://127.0.0.1:5173';
const screenshots = process.env.SMOKE_SCREENSHOTS || '/tmp/lifeops-ui';
let sessions = Array.from({ length: 35 }, (_, i) => ({ conversation_id: `c${i}`, title: `历史对话 ${i}`, message_count: 2, last_message: `历史内容 ${i}` }));
let skills = Array.from({ length: 10 }, (_, i) => ({ name: `skill-${i}`, description: `能力 ${i}`, source: 'project', license: 'MIT', path: `/skills/skill-${i}` }));
let sources = [{ source_id: 'notes', name: '工作笔记', description: '本地资料', call_when: '查找资料时', enabled: true, path_prefix: 'notes/' }];
const requests = [], decisions = [];
let stream, polls = 0, chat, failImport = false;
const dualDecisions = new Map();
const sse = (res, type, data) => res.write(`data: ${JSON.stringify({ type, data })}\n\n`);
const server = createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PATCH,DELETE,OPTIONS');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }
  const url = new URL(req.url, 'http://localhost'), buffers = [];
  for await (const chunk of req) buffers.push(chunk);
  const raw = Buffer.concat(buffers).toString(); let body = {};
  try { body = JSON.parse(raw || '{}'); } catch { /* ZIP 上传为 multipart */ }
  requests.push({ method: req.method, path: url.pathname, query: url.search, body, raw });
  const json = data => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); };
  const path = url.pathname;
  if (path === '/api/chat') {
    chat = body; res.writeHead(200, { 'Content-Type': 'text/event-stream' }); res.flushHeaders();
    if (body.message === '失败测试') { sse(res, 'error', '连接暂时失败'); res.end(); return; }
    if (body.message === '停止测试') {
      sse(res, 'token', '部分回复'); const timer = setTimeout(() => { sse(res, 'token', '不应继续显示'); res.end(); }, 5000);
      res.on('close', () => clearTimeout(timer)); return;
    }
    if (body.message === '双审批测试') {
      dualDecisions.clear(); stream = res;
      for (const id of ['a', 'b']) {
        sse(res, 'tool_call', { tool_name: 'read_doc', args: { path: id } });
        sse(res, 'approval_required', { request_id: id, tool_name: 'read_doc', params_preview: id, risk_level: 'high' });
      }
      return;
    }
    sse(res, 'tool_call', { tool_name: 'bash', args: { command: 'pwd' } });
    sse(res, 'approval_required', { request_id: 'r1', tool_name: 'bash', params_preview: '{"command":"pwd"}', risk_level: 'high', reason: '需要执行命令' });
    stream = res; return;
  }
  if (['/api/approvals/a', '/api/approvals/b'].includes(path)) {
    const id = path.split('/').at(-1); dualDecisions.set(id, body.decision); json({ success: true });
    sse(stream, 'approval_resolved', { request_id: id, decision: body.decision });
    if (dualDecisions.size === 2) {
      for (const key of ['a', 'b']) sse(stream, 'tool_result', { tool_name: 'read_doc', output: key, success: true });
      sse(stream, 'token', '双审批完成'); sse(stream, 'done', { conversation_id: 'new' }); stream.end();
    }
    return;
  }
  if (path === '/api/approvals/r1') {
    decisions.push(body.decision); json({ success: true });
    sse(stream, 'approval_resolved', { request_id: 'r1', decision: body.decision });
    sse(stream, 'tool_result', { tool_name: 'bash', output: '/workspace', success: true });
    sse(stream, 'tool_call', { tool_name: 'todo_write', args: {} });
    sse(stream, 'tool_result', { tool_name: 'todo_write', success: true, output: '[completed] 验收完成', metadata: { kind: 'todo', todos: [{ content: '验收完成', status: 'completed' }] } });
    sse(stream, 'token', '# 回复\n\n你好，');
    setTimeout(() => {
      sse(stream, 'token', '已完成。\n\n|列|值|\n|---|---|\n|A|1|\n\n<script>window.hacked=1</script>');
      sessions = [{ conversation_id: 'new', title: '新测试会话', message_count: 2 }, ...sessions.filter(item => item.conversation_id !== 'new')];
      sse(stream, 'done', { conversation_id: chat.conversation_id || 'new', title: '新测试会话' }); stream.end();
    }, 100); return;
  }
  if (path === '/api/conversations') {
    const query = url.searchParams.get('query') || '', rows = sessions.filter(item => item.title.includes(query));
    const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 30);
    if (query === '慢') await new Promise(resolve => setTimeout(resolve, 500));
    json({ conversations: rows.slice(offset, offset + limit), total: rows.length }); return;
  }
  if (path.startsWith('/api/conversations/')) {
    if (req.method === 'DELETE') { sessions = sessions.filter(item => item.conversation_id !== path.split('/').at(-1)); json({ success: true }); return; }
    const older = url.searchParams.has('before_id');
    json({ messages: [{ message_id: older ? 'old' : 'latest', role: older ? 'user' : 'assistant', content: older ? '更早消息' : '历史回答' }],
      intermediate_messages: older ? [] : [{ role: 'tool', tool_name: 'todo_write', content: '[completed] 历史任务\n[pending] 后续任务' }], has_more: !older, next_before_id: older ? null : 'older' }); return;
  }
  if (path === '/api/skills') { if (req.method === 'POST') skills = [...skills, { ...body, source: 'project' }]; json({ skills }); return; }
  if (path === '/api/tools') { json({ tools: [{ name: 'bash', description: '命令执行', category: 'builtin', parameters: { properties: { command: {} } } }], mcp_servers: [{ name: 'docs', tools: [{ name: 'search_docs', description: '文档检索', parameters: { properties: { query: {} } } }] }] }); return; }
  if (path === '/api/rag/sources') { json({ sources }); return; }
  if (path.startsWith('/api/rag/sources/')) {
    const id = path.split('/').at(-1);
    sources = req.method === 'DELETE' ? sources.filter(item => item.source_id !== id) : sources.map(item => item.source_id === id ? { ...item, ...body } : item);
    json({ success: true }); return;
  }
  if (path === '/api/rag/imports/conflict') { json({ conflict: false }); return; }
  if (path === '/api/rag/imports') { json({ import_id: 'import1', markdown_files: ['guide.md'], tree: [{ path: 'guide.md', name: 'guide.md', type: 'file' }] }); return; }
  if (path.endsWith('/preview')) { json({ content: '# 示例文档', chunks: [{ heading_breadcrumb: '示例文档', content: '切片内容' }] }); return; }
  if (path.endsWith('/start')) { polls = 0; json({ status: 'processing' }); return; }
  if (path === '/api/rag/imports/import1') {
    if (req.method === 'DELETE') { json({ success: true }); return; }
    const completed = ++polls > 1;
    if (failImport) { json({ status: completed ? 'failed' : 'processing', error: '模拟入库失败' }); return; }
    if (completed && !sources.some(item => item.source_id === 'imported')) sources = [...sources, { source_id: 'imported', name: '导入资料', description: '说明', call_when: '资料问题', enabled: true }];
    json({ status: completed ? 'completed' : 'processing' }); return;
  }
  res.statusCode = 404; json({ detail: `未实现桩 ${path}` });
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const mockBase = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] });
const page = await context.newPage(), errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
await page.route('http://127.0.0.1:8081/**', route => route.continue({ url: route.request().url().replace('http://127.0.0.1:8081', mockBase) }));
const waitText = text => page.getByText(text, { exact: true }).first().waitFor();
const click = name => page.getByRole('button', { name, exact: true }).click();
try {
  await mkdir(screenshots, { recursive: true }); await page.goto(BASE);
  await page.locator('[data-slot=lifeops-composer] textarea').waitFor(); await waitText('你好，我是 LifeOps');
  assert.equal(requests.filter(item => /^\/api\/conversations\//.test(item.path)).length, 0);
  await page.screenshot({ path: `${screenshots}/desktop.png` });
  await page.locator('.sidebar-history .el-scrollbar__wrap').evaluate(el => { el.scrollTop = el.scrollHeight; });
  await page.waitForFunction(() => document.querySelectorAll('.conversation-item').length === 35);
  console.log('OK 空态、侧栏分页');
  await click('搜索对话'); await page.getByRole('textbox', { name: '标题关键词' }).fill('慢'); await page.waitForTimeout(300);
  await page.getByRole('textbox', { name: '标题关键词' }).fill('历史对话 3'); await page.locator('.search-result').first().waitFor(); await page.waitForTimeout(550);
  assert.equal(await page.locator('.search-result').count(), 6);
  await page.locator('.search-result').first().click(); await waitText('历史回答'); await waitText('更早消息'); await waitText('✓ 历史任务');
  console.log('OK 搜索、游标历史、计划恢复');
  await click('新对话'); await page.locator('[data-slot=lifeops-composer] textarea').fill('失败测试');
  await page.locator('[data-slot=lifeops-composer] textarea').press('Enter'); await waitText('连接暂时失败');
  assert.equal(await page.locator('[data-slot=lifeops-user-message]').count(), 0);
  assert.equal(await page.locator('[data-slot=lifeops-composer] textarea').inputValue(), '失败测试');
  console.log('OK 零输出失败撤回消息并恢复草稿');
  await click('新对话'); await page.locator('[data-slot=lifeops-composer] textarea').fill('审批测试'); await page.locator('[data-slot=lifeops-composer] textarea').press('Enter');
  await page.locator('[data-slot=lifeops-approval-card]').waitFor();
  assert.equal(await page.getByRole('button', { name: 'Skills', exact: true }).isDisabled(), true);
  await click('允许一次'); await waitText('你好，已完成。'); await page.waitForFunction(() => !document.querySelector('[data-slot=lifeops-approval-card]')); await waitText('✓ 验收完成');
  assert.deepEqual(decisions, ['allow_once']); assert.equal(await page.evaluate(() => window.hacked), undefined);
  assert.equal(await page.locator('[data-slot=lifeops-assistant-message] table').count(), 1);
  await click('复制回答'); assert.match(await page.evaluate(() => navigator.clipboard.readText()), /你好/);
  const download = page.waitForEvent('download'); await click('导出 Markdown'); assert.equal((await download).suggestedFilename(), 'LifeOps-回答.md');
  await click('Logging'); await waitText('工具调用 · bash'); await page.waitForTimeout(300);
  await page.screenshot({ path: `${screenshots}/logging.png` });
  await page.getByRole('dialog').getByRole('button', { name: '关闭此对话框' }).click(); await page.getByRole('dialog').waitFor({ state: 'hidden' });
  await page.screenshot({ path: `${screenshots}/chat.png` }); console.log('OK SSE、审批、工具、计划、Markdown、复制导出、Logging');
  await page.locator('[data-slot=lifeops-composer] textarea').fill('双审批测试');
  await page.locator('[data-slot=lifeops-composer] textarea').press('Enter');
  await page.waitForFunction(() => document.querySelectorAll('[data-slot=lifeops-approval-card]').length === 2);
  await page.locator('[data-slot=lifeops-approval-card]').first().getByRole('button', { name: '拒绝', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('[data-slot=lifeops-approval-card]').length === 1);
  assert.equal(dualDecisions.get('a'), 'deny');
  assert.equal(await page.locator('[data-slot=lifeops-composer] textarea').isDisabled(), true);
  await click('总是允许'); await waitText('双审批完成');
  assert.equal(dualDecisions.get('b'), 'allow_always');
  console.log('OK 各审批卡片分别提交正确请求');
  await page.locator('[data-slot=lifeops-composer] textarea').fill('停止测试'); await page.locator('[data-slot=lifeops-composer] textarea').press('Enter'); await waitText('部分回复');
  await click('停止生成'); await page.getByRole('button', { name: '停止生成', exact: true }).waitFor({ state: 'hidden' }); assert.equal(await page.getByText('不应继续显示').count(), 0);
  await click('Skills'); await waitText('skill-0'); await page.locator('.el-pagination .btn-next').click(); await waitText('skill-8');
  await click('新增 Skill'); await page.getByRole('textbox', { name: 'Skill 名称' }).fill('weekly-review'); await page.getByRole('textbox', { name: 'Skill 描述' }).fill('周复盘'); await page.getByRole('textbox', { name: 'SKILL 内容' }).fill('# 周复盘\n整理工作');
  await click('保存'); await page.getByRole('dialog').waitFor({ state: 'hidden' }); assert.equal(skills.at(-1).name, 'weekly-review');
  await click('工具与 MCP'); await waitText('bash'); await page.getByText('MCP', { exact: true }).click(); await waitText('docs'); await page.locator('.el-table__expand-icon').click(); await waitText('search_docs');
  console.log('OK 停止、Skills 创建分页、工具与 MCP');
  await click('知识库'); await waitText('工作笔记'); await page.getByRole('button', { name: '查看 工作笔记 详情' }).press('Enter'); await waitText('notes/'); await click('编辑数据源');
  await page.locator('#source-name').fill('工作记录'); await click('保存'); await waitText('工作记录'); assert.equal(sources[0].name, '工作记录');
  await click('新增本地知识库'); await page.locator('#import-id').fill('imported'); await page.locator('#import-name').fill('导入资料'); await page.locator('#import-description').fill('说明'); await page.locator('#import-condition').fill('资料问题');
  await page.locator('input[type=file]').setInputFiles({ name: 'notes.zip', mimeType: 'application/zip', buffer: Buffer.from('PK mock') }); await waitText('guide.md'); await click('下一步'); await waitText('切片内容');
  await page.getByText('固定大小', { exact: true }).click(); await page.locator('.el-input-number input').fill('300'); await page.locator('.el-input-number input').press('Tab'); await page.waitForTimeout(200);
  await click('开始入库'); await waitText('处理完成'); await page.screenshot({ path: `${screenshots}/import.png` });
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click(); await page.getByRole('dialog').waitFor({ state: 'hidden' }); await waitText('导入资料');
  const started = requests.find(item => item.path.endsWith('/start')); assert.equal(started.body.strategy, 'fixed'); assert.equal(started.body.chunk_size, 300); assert.equal(started.body.name, '导入资料');
  await page.screenshot({ path: `${screenshots}/knowledge.png` });
  failImport = true; await click('新增本地知识库');
  await page.locator('#import-id').fill('failed_source'); await page.locator('#import-name').fill('失败资料');
  await page.locator('#import-description').fill('说明'); await page.locator('#import-condition').fill('资料问题');
  await page.locator('input[type=file]').setInputFiles({ name: 'notes.zip', mimeType: 'application/zip', buffer: Buffer.from('PK mock') });
  await waitText('guide.md'); await click('下一步'); await waitText('切片内容'); await click('开始入库');
  await waitText('正在处理知识库'); await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('dialog').waitFor({ state: 'hidden' }); await waitText('模拟入库失败');
  await click('查看入库进度'); await waitText('处理失败');
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click(); await page.getByRole('dialog').waitFor({ state: 'hidden' });
  assert.equal(requests.some(item => item.method === 'DELETE' && item.path === '/api/rag/imports/import1'), true);
  console.log('OK 后台入库失败提示、重开详情与清理暂存');
  await page.setViewportSize({ width: 390, height: 844 }); await page.reload(); await page.locator('[data-slot=lifeops-composer] textarea').waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); await page.screenshot({ path: `${screenshots}/mobile.png` });
  assert.deepEqual(errors, []); console.log(`OK 知识库编辑、三步导入、移动布局；截图：${screenshots}`);
} catch (error) {
  console.error('页面错误', errors); console.error('最近请求', requests.slice(-4));
  await page.screenshot({ path: `${screenshots}/failure.png` }); throw error;
} finally { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
