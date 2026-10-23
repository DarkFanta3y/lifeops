// UI 视觉走查截图：本地 mock 后端 + Playwright，多视口截取主要界面。先 npm run dev。
// 用法：node scripts/ui-shots.mjs [输出目录]，默认 /tmp/lifeops-shots。
import { createServer } from 'node:http';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const BASE = process.env.SHOTS_BASE || 'http://127.0.0.1:5173';
const outDir = process.argv[2] || '/tmp/lifeops-shots';
const API_BASE = process.env.SHOTS_API_BASE || 'http://127.0.0.1:8082';

const sessions = Array.from({ length: 9 }, (_, i) => ({
  conversation_id: `c${i}`, title: `周报整理与资料归档 ${i}`, message_count: 4,
  last_message: '已完成本周内容汇总，资料已归档到知识库。', updated_at: new Date(Date.now() - i * 86400000).toISOString(),
}));
const providers = [
  { provider_id: 'zhipu', name: '智谱开放平台', api_base: 'https://open.bigmodel.cn/api/paas/v4', protocol: 'openai_chat',
    has_api_key: true, api_key_hint: '****f3a9', models: [
      { model_id: 'glm-4.7', name: 'GLM-4.7', context_window: 200000, max_output_tokens: 32000 },
      { model_id: 'glm-4.7-air', name: 'GLM-4.7 Air', context_window: 128000, max_output_tokens: 8000 }] },
  { provider_id: 'deepseek', name: 'DeepSeek 开放平台', api_base: 'https://api.deepseek.com/v1', protocol: 'openai_chat',
    has_api_key: true, api_key_hint: '****91c2', models: [{ model_id: 'deepseek-chat', name: 'DeepSeek Chat', context_window: 64000, max_output_tokens: 8000 }] },
  { provider_id: 'local', name: '本地推理网关', api_base: 'http://127.0.0.1:9988/v1', protocol: 'anthropic_messages',
    has_api_key: false, api_key_hint: '', models: [] },
];
const sources = [
  { source_id: 'work_notes', name: '工作笔记', description: '近两年的工作记录与周报，整理过的会议纪要。', call_when: '查找工作安排或历史结论时', enabled: true, path_prefix: 'notes/' },
  { source_id: 'reading', name: '阅读摘录', description: '文章与书籍的高亮摘录。', call_when: '讨论读书内容时', enabled: true, path_prefix: 'reading/' },
  { source_id: 'archive', name: '归档资料', description: '旧项目文档，仅供追溯。', call_when: '被明确问到旧项目时', enabled: false, path_prefix: 'archive/' },
];
const cats = { system: 4200, tools: 1850, user: 940, inject: 300, skill: 0, assistant: 2100, tool: 1600 };
const usage = { uncachedInputTokens: 4200, cacheReadTokens: 12800, cacheWriteTokens: 900, outputTokens: 1450 };
const json = (res, data) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data)); };

const server = createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PATCH,DELETE,PUT,OPTIONS');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }
  const url = new URL(req.url, 'http://localhost');
  const path = url.pathname;
  if (path === '/api/conversations') {
    const query = url.searchParams.get('query') || '';
    const rows = sessions.filter(item => item.title.includes(query));
    const offset = Number(url.searchParams.get('offset') || 0), limit = Number(url.searchParams.get('limit') || 30);
    return json(res, { conversations: rows.slice(offset, offset + limit), total: rows.length });
  }
  if (path === '/api/conversations/c1') {
    return json(res, {
      messages: [
        { message_id: 1, role: 'user', content: '帮我把上周的周报整理成要点，并对比一下两周的进度。' },
        { message_id: 2, role: 'assistant', content: `已经整理好了，上周进展可以概括为三部分：

## 核心进展
- **上下文洞察页** 完成了 KPI 卡片与热力图联动
- 知识库导入支持断点续传
- 修复了会话分页的重复项

## 与前一周对比
| 方向 | 上周 | 前一周 |
| --- | --- | --- |
| 完成事项 | 6 | 3 |
| 遗留问题 | 1 | 4 |

## 建议
本周优先收敛遗留问题，再开始新的开发。` },
      ],
      intermediate_messages: [
        { message_id: 1, role: 'tool', tool_name: 'todo_write', content: '[completed] 读取周报文档\n[completed] 汇总要点' },
      ],
      tool_executions: [], has_more: false, plan_mode: false,
    });
  }
  if (path === '/api/models') {
    return json(res, { providers, active: { provider_id: 'zhipu', provider_name: '智谱开放平台', model_id: 'glm-4.7', model_name: 'GLM-4.7' },
      fallback: { model: 'glm-4.7', api_base: 'https://open.bigmodel.cn/api/paas/v4', has_api_key: true }, protocols: [] });
  }
  if (path === '/api/rag/sources') return json(res, { sources });
  if (path === '/api/context/overview') {
    const days = Array.from({ length: 30 }, (_, i) => {
      const day = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
      return { day, tokens: 12000 + i * 800, requests: 8 + (i % 5), sessions: 2 + (i % 3), cost: i % 2 ? 0.42 : null };
    });
    const day = days[0].day;
    return json(res, { range: url.searchParams.get('range') || '7d',
      kpi: { sessions: 26, requests: 143, billed: 386400, cost: 12.08, cacheHit: 0.734, usage },
      usage7: days.slice(0, 7), heatmap: days, composition: { ...cats, total: 11000 }, prices: { input: 0.02, cache: 0.004, output: 0.06 },
      sessions: sessions.slice(0, 8).map((item, i) => ({ conversationId: item.conversation_id, title: item.title, updatedAt: Date.now() - i * 3600000,
        runs: 2 + i, requests: 6 + i * 2, days: [day], current: { ...cats, total: 11000 }, window: 200000, billed: 48300 - i * 2100,
        cost: 1.4 - i * 0.1, lastActive: Date.now() - i * 3600000 })) });
  }
  if (path.endsWith('/context/fleet')) {
    return json(res, { agents: [{ id: 'main', parent: null, title: '主智能体', kind: 'main', status: 'done', steps: 6,
      current: { ...cats, total: 11000 }, window: 200000, billed: 38640, cost: 1.2, durationMs: 42000, prompt: '整理周报' }],
      todos: [{ content: '汇总要点', status: 'completed' }, { content: '对比两周进度', status: 'in_progress' }] });
  }
  if (path.endsWith('/context/files')) return json(res, { root: '/Users/cxy/Projects/lifeops', ops: [] });
  if (path.endsWith('/context')) {
    return json(res, { ok: true, hasSnapshots: true, model: 'glm-4.7', contextWindow: 200000, reserveRatio: 0.1,
      current: { ...cats, total: 11000 }, estimated: 11000, toolCalls: 12, humanInputs: 4, answers: 4, lastUser: '帮我把上周的周报整理成要点',
      running: false, requests: [{ id: 1, seq: 1, runId: 'r1', turn: 1, step: 1, iteration: 0, time: Date.now(), model: 'glm-4.7',
        ...cats, total: 11000, estimated: 11000, budget: 200000, prompt: 17000, cacheRead: 12800, output: 1450, activeMs: 4200, ttftMs: 320,
        brief: { opener: '整理周报', inputs: [] }, response: { text: '已经整理好了' } }],
      events: [], usage, familyUsage: usage, agents: 1, cost: 1.24, familyCost: 1.24, prices: { input: 0.02, cache: 0.004, output: 0.06 },
      timing: { wallMs: 42000, ttftMs: 320, genMs: 38000, calls: 6, toolsMs: 2100, toolCalls: 12, speedTokens: 38, speedMs: 1000, tools: {} },
      spans: [] });
  }
  if (path === '/api/chat') {
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    res.flushHeaders();
    const sse = (type, data) => res.write(`data: ${JSON.stringify({ type, data })}\n\n`);
    const s = (type, data) => { sse(type, data); return new Promise(r => setTimeout(r, 60)); };
    await s('tool_call', { tool_name: 'retrieve_knowledge', args: { query: '上周周报', source: 'work_notes' } });
    await s('tool_result', { tool_name: 'retrieve_knowledge', output: '上周完成上下文洞察页与知识库导入。', success: true });
    await s('usage', { prompt_tokens: 15200, completion_tokens: 210, cached_tokens: 11800, total_tokens: 15410 });
    await s('token', '已读取知识库中的周报，正在整理要点……');
    await s('done', { conversation_id: 'c9', title: '周报整理', usage: { prompt_tokens: 15200, completion_tokens: 210, cached_tokens: 11800, total_tokens: 15410 } });
    return res.end();
  }
  res.statusCode = 404; json(res, { detail: `未实现桩 ${path}` });
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const mockBase = `http://127.0.0.1:${server.address().port}`;

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch();
for (const [width, height, tag] of [[1440, 900, 'desktop'], [768, 1024, 'tablet'], [390, 844, 'mobile']]) {
  const context = await browser.newContext({ viewport: { width, height } });
  const page = await context.newPage();
  await page.route(`${API_BASE}/**`, route => route.continue({ url: route.request().url().replace(API_BASE, mockBase) }));
  await page.goto(BASE);
  await page.locator('[data-slot=lifeops-composer] textarea').waitFor();
  await page.screenshot({ path: `${outDir}/${tag}-welcome.png` });
  // 对话态（首个条目是组件的"新对话"占位，需按标题选真实会话；窄视口默认折叠侧栏，先展开）
  if (width < 760) await page.getByRole('button', { name: '切换侧栏' }).click();
  await page.locator('.conversation-item', { hasText: '周报整理与资料归档 1' }).click();
  await page.getByText('核心进展').waitFor({ timeout: 15000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${outDir}/${tag}-chat.png` });
  // 知识库
  await page.getByRole('button', { name: '知识库' }).click();
  await page.getByText('工作笔记').first().waitFor();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${outDir}/${tag}-knowledge.png` });
  // 模型管理
  await page.getByRole('button', { name: '模型管理' }).click();
  await page.getByText('智谱开放平台').first().waitFor();
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${outDir}/${tag}-models.png` });
  // 上下文洞察
  await page.getByRole('button', { name: '上下文洞察' }).click();
  await page.getByText('活跃会话').waitFor();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${outDir}/${tag}-insights.png` });
  await context.close();
}
// 1440 宽度下的对话运行态与审批卡（视觉走查需要交互态）
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
await page.route(`${API_BASE}/**`, route => route.continue({ url: route.request().url().replace(API_BASE, mockBase) }));
await page.goto(BASE);
await page.locator('[data-slot=lifeops-composer] textarea').fill('整理周报');
await page.locator('[data-slot=lifeops-composer] textarea').press('Enter');
await page.waitForTimeout(900);
await page.screenshot({ path: `${outDir}/desktop-chat-running.png` });
await context.close();
await browser.close();
server.closeAllConnections();
await new Promise(resolve => server.close(resolve));
console.log(`截图完成：${outDir}`);
