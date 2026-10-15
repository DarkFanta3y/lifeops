// 输入框“/”命令：只在前端执行，不发给模型。
export const COMMANDS = [
  { name: 'new', label: '新建对话', description: '清空当前页，开始一段新对话' },
  { name: 'search', label: '搜索对话', description: '按标题搜索历史对话' },
  { name: 'context', label: '上下文构成', description: '查看当前对话的上下文用量弹窗' },
  { name: 'logs', label: '运行日志', description: '查看本对话的工具调用与中间信息' },
  { name: 'regenerate', label: '重新生成', description: '删除上一轮回答并重新生成' },
  { name: 'rename', label: '重命名对话', description: '修改当前对话标题' },
  { name: 'export', label: '导出对话', description: '把当前对话导出为 Markdown' },
];

// 草稿以“/”开头且仍在输入命令名（无空白）时返回候选；按命令名前缀或中文名包含匹配。
export function matchCommands(draft, commands = COMMANDS) {
  if (typeof draft !== 'string' || !draft.startsWith('/') || /\s/.test(draft)) return [];
  const query = draft.slice(1).toLowerCase();
  return commands.filter(command => command.name.startsWith(query) || (query && command.label.includes(query)));
}

// 整条输入恰好是某个命令（如“/context”）时返回该命令。
export function findCommand(text, commands = COMMANDS) {
  if (typeof text !== 'string') return null;
  const value = text.trim().toLowerCase();
  return commands.find(command => `/${command.name}` === value) || null;
}
