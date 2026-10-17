// 参考 DeepSeek Harness ui-tool 的“纯展示模型 + 工具映射 + 通用回退”。
const TOOLS = {
  file_read: ['read', '读取文件'], file_create: ['diff', '创建文件'],
  file_replace: ['diff', '替换文件内容'], file_append: ['diff', '追加文件内容'],
  bash: ['terminal', '执行命令'], bash_output: ['terminal', '读取后台输出'], bash_kill: ['terminal', '停止后台任务'],
  grep: ['search', '搜索内容'], glob: ['search', '查找文件'],
  web_search: ['web', '联网搜索'], retrieve_knowledge: ['knowledge', '检索知识库'],
  todo_write: ['todo', '更新任务计划'], activate_skill: ['skill', '加载技能'], spawn_agent: ['agent', '委派子智能体'],
  exit_plan_mode: ['plan', '提交计划'],
};
export const STATUS_TEXT = { preparing: '准备调用', queued: '等待执行', running: '执行中',
  waiting_approval: '等待授权', completed: '已完成', failed: '失败', interrupted: '已中断', incomplete: '未完成' };
export const print = value => typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2);
export function toolPresentation(part) {
  const key = part.canonicalName?.replace(/^(builtin|internal)\./, '') || part.toolName;
  const [kind, title] = TOOLS[key] || ['generic', '调用工具'];
  const args = part.args || {}, metadata = part.metadata || {};
  const state = part.interrupted ? (part.status === 'incomplete' ? 'incomplete' : 'interrupted')
    : part.isError ? 'failed' : part.status || (part.result !== undefined ? 'completed' : 'running');
  let summary = args.description || '';
  if (['read', 'diff'].includes(kind)) summary = args.path || args.file_path || summary;
  else if (kind === 'terminal') summary = args.description || args.command || metadata.command || args.task_id || summary;
  else if (['search', 'web', 'knowledge'].includes(kind)) summary = args.query || args.pattern || summary;
  else if (kind === 'skill') summary = args.name || summary;
  else if (kind === 'agent') summary = args.description || args.prompt || summary;
  else if (kind === 'generic') summary = [part.toolName, summary].filter(Boolean).join(' · ');
  let suffix = '';
  if (kind === 'read' && Number.isFinite(metadata.shown_lines)) suffix = `${metadata.shown_lines} 行`;
  if (kind === 'search' && Number.isFinite(metadata.total_matches ?? metadata.count)) suffix = `${metadata.total_matches ?? metadata.count} 条`;
  if (kind === 'knowledge' && args.source) suffix = args.source;
  const diff = kind === 'diff' && !part.isError && typeof metadata.diff === 'string' ? metadata.diff : null;
  const counts = diff ? diff.split('\n').reduce((sum, line) => ({
    added: sum.added + Number(line.startsWith('+') && !line.startsWith('+++')),
    removed: sum.removed + Number(line.startsWith('-') && !line.startsWith('---')),
  }), { added: 0, removed: 0 }) : null;
  const todos = kind === 'todo' && !part.isError && Array.isArray(metadata.todos) && metadata.todos.every(todo => todo
    && typeof todo.content === 'string' && ['pending', 'in_progress', 'completed'].includes(todo.status)) ? metadata.todos : null;
  if (todos && kind === 'todo') {
    const completed = todos.filter(todo => todo.status === 'completed').length;
    summary = todos.find(todo => todo.status === 'in_progress')?.content || '任务清单';
    suffix = `${completed}/${todos.length}`;
  }
  const sourceLinks = ['web', 'knowledge'].includes(kind) && !part.isError && Array.isArray(metadata.results)
    ? metadata.results.filter(item => item && typeof item.title === 'string' && /^https?:\/\//i.test(item.url || '')
      && !/[\s\x00-\x1f]/.test(item.url)) : [];
  return { kind, title, summary: print(summary || '查看调用详情').replace(/\s+/g, ' ').trim(), suffix,
    state, statusText: !part.isError && metadata.running === true ? '后台运行中' : STATUS_TEXT[state] || '状态不可用', diff, counts, todos, sourceLinks,
    workdir: metadata.workdir || args.workdir, exitCode: metadata.returncode, taskId: metadata.task_id || args.task_id,
    output: part.result === undefined ? null : print(part.result), error: part.error,
    previewLines: kind === 'diff' ? 9 : 8 };
}
export function pendingControl(part) {
  return !part.interrupted && (part.approval && !part.approval.decision || part.review && !part.review.decision);
}
export function processEntries(parts) {
  const entries = [];
  for (const [index, part] of parts.entries()) {
    const key = part.callId || part.prepareKey || part.key || `part:${index}`;
    if (part.kind === 'text' || pendingControl(part) || part.toolName === 'exit_plan_mode' && part.args?.plan) {
      entries.push({ key, kind: part.kind === 'text' ? 'text' : 'control', part });
    } else {
      const previous = entries.at(-1);
      if (previous?.kind === 'group') previous.parts.push(part);
      else entries.push({ key: `group:${key}`, kind: 'group', parts: [part] });
    }
  }
  return entries;
}
export function activitySummary(parts, running = false) {
  const unique = [...new Map(parts.map((part, i) => [part.callId || part.prepareKey || i, part])).values()];
  const live = unique.findLast(part => ['preparing', 'running', 'waiting_approval', 'queued'].includes(part.status));
  if (running && live) { const model = toolPresentation(live); return `${model.title} · ${model.summary}`; }
  const counts = new Map();
  for (const part of unique) {
    const title = toolPresentation(part).title;
    counts.set(title, (counts.get(title) || 0) + 1);
  }
  return [...counts].sort((a, b) => b[1] - a[1]).slice(0, 3)
    .map(([title, count]) => `${title} ${count} 次`).join('、') || '工作过程';
}
