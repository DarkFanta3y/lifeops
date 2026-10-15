<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import BubbleList from '@element-plus-x/BubbleList/index.js';
import Sender from '@element-plus-x/Sender/index.js';
import { Document, CopyDocument, Download, Check, Close, Tools, Top, Calendar, Search, EditPen, RefreshRight, Link, Memo, PieChart } from '@element-plus/icons-vue';
import { approveRequest, deleteLastTurn, fetchRagSources, sendChatMessage } from '../api.js';
import { downloadMarkdown } from '../download.js';
import MarkdownRenderer from '../MarkdownRenderer.vue';
import { collectSources, updateStreamParts } from './stream.js';

const props = defineProps({ messages: { type: Array, default: () => [] },
  intermediateMessages: { type: Array, default: () => [] }, conversationId: String, disabled: Boolean });
const emit = defineEmits(['update:messages', 'running', 'done', 'error', 'settled-logs', 'context']);
const CONTEXT_COMMAND = '/context';
const draft = ref('');
const sending = ref(false);
const approval = ref(null);
const approving = ref(false);
const bubbleList = ref(null);
const composer = ref(null);
const loggingOpen = ref(false);
const streamLogs = ref([]);
const hour = new Date().getHours();
const greeting = hour < 5 ? '夜深了' : hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好';
const suggestions = [
  { label: '整理今日待办', icon: Calendar, prompt: '帮我整理今天的待办，按优先级列出计划' },
  { label: '查找知识库资料', icon: Search, prompt: '从知识库查找与我的问题有关的资料' },
  { label: '写一份周复盘', icon: EditPen, prompt: '帮我复盘这一周，整理完成的工作和下周行动' },
];
const editing = ref(false);
const rewinding = ref(false);
const sourceNames = ref(null);
let controller;
let parts = [];
let assistantId;
let turnLogStart = null;
const canRewind = computed(() => Boolean(props.conversationId) && !sending.value && !rewinding.value && !props.disabled);
// 历史消息没有 parts，按自增 message_id 取上一条可见消息与本条之间的中间工具调用。
function sourcesOf(message, index) {
  if (message.parts?.length) return collectSources(message.parts.filter(part => part.kind === 'tool')
    .map(part => ({ name: part.toolName, args: part.args })));
  if (typeof message.message_id !== 'number') return [];
  const previous = props.messages[index - 1]?.message_id;
  const from = typeof previous === 'number' ? previous : 0;
  return collectSources(props.intermediateMessages
    .filter(log => log.message_id > from && log.message_id < message.message_id)
    .flatMap(log => log.tool_calls || []).map(call => ({ name: call.function?.name, args: call.function?.arguments })));
}
function memoryText(memory) {
  if (!memory) return '';
  return [['偏好', memory.preferences], ['摘要', memory.summaries], ['实体', memory.entities]]
    .filter(([, count]) => count > 0).map(([label, count]) => `${label} ${count}`).join(' · ');
}
const items = computed(() => {
  const lastIndex = props.messages.length - 1;
  const lastUserIndex = props.messages.findLastIndex(message => message.role === 'user');
  return props.messages.map((message, index) => {
    const sources = message.role === 'assistant' ? sourcesOf(message, index) : [];
    return { ...message, key: message.message_id, placement: message.role === 'user' ? 'end' : 'start',
      noStyle: message.role !== 'user', typing: false,
      loading: Boolean(message.pending && !message.parts?.length),
      isLast: index === lastIndex, isLastUser: index === lastUserIndex, sources,
      sourceText: sources.map(source => source.kind === 'web' ? '联网搜索'
        : sourceNames.value?.[source.id] || source.id || '知识库').join(' · '),
      memoryText: memoryText(message.memory) };
  });
});
const logs = computed(() => [...props.intermediateMessages, ...streamLogs.value]);
const historicalTodos = computed(() => {
  for (const log of [...props.intermediateMessages].reverse()) {
    if (log.tool_name !== 'todo_write') continue;
    try { const value = JSON.parse(log.content); if (Array.isArray(value.todos)) return value.todos; }
    catch {
      const todos = (log.content || '').split('\n').map(line => line.match(/^\[(pending|in_progress|completed)\] (.+)$/)).filter(Boolean)
        .map(match => ({ status: match[1], content: match[2] }));
      if (todos.length) return todos;
    }
  }
  return [];
});
function updateAssistant(updater) {
  emit('update:messages', props.messages.map(message => message.message_id === assistantId ? updater(message) : message));
}
function receive(type, data) {
  parts = updateStreamParts(parts, type, data);
  updateAssistant(message => ({ ...message, parts, pending: false,
    content: parts.filter(part => part.kind === 'text').map(part => part.text).join('') }));
  if (type === 'approval_required' || type === 'approval_resolved') {
    approval.value = parts.find(part => part.approval && !part.approval.decision)?.approval || null;
  }
  if (type === 'tool_call') streamLogs.value = [...streamLogs.value, { role: 'assistant', tool_calls: [
    { function: { name: data.tool_name, arguments: JSON.stringify(data.args ?? data.params ?? {}) } },
  ] }];
  if (type === 'tool_result') streamLogs.value = [...streamLogs.value, { role: 'tool', tool_name: data.tool_name,
    content: `${data.error || ''}${data.output || data.result || ''}`, metadata: data.metadata }];
}
// base / logStart 供重新生成使用：删除末轮后 props 尚未刷新，需显式传入裁剪后的消息与日志长度。
async function send(text = draft.value, { base = props.messages, logStart = props.intermediateMessages.length } = {}) {
  text = text.trim();
  if (!text || sending.value || props.disabled) return;
  // /context 只在前端打开上下文弹窗，不发给模型
  if (text === CONTEXT_COMMAND) { draft.value = ''; emit('context', 'modal'); return; }
  draft.value = ''; editing.value = false;
  sending.value = true; emit('running', true); emit('error', '');
  parts = []; turnLogStart = logStart;
  assistantId = crypto.randomUUID();
  const user = { message_id: crypto.randomUUID(), role: 'user', content: text };
  emit('update:messages', [...base, user,
    { message_id: assistantId, role: 'assistant', content: '', parts: [], pending: true }]);
  controller = new AbortController();
  let retractUser = false, memory;
  await nextTick(); bubbleList.value?.scrollToBottom();
  try {
    const payload = await sendChatMessage({ message: text, conversationId: props.conversationId,
      signal: controller.signal, onToken: data => receive('token', data),
      onToolCall: data => receive('tool_call', data), onToolResult: data => receive('tool_result', data),
      onApproval: data => receive('approval_required', data),
      onApprovalResolved: data => receive('approval_resolved', data) });
    memory = payload?.memory;
    emit('done', payload);
  } catch (err) {
    if (err.name !== 'AbortError') emit('error', err.message);
    retractUser = err.name !== 'AbortError' && !parts.length;
    if (!parts.length) draft.value = text;
  } finally {
    const settled = parts.map(part => part.kind === 'tool' && part.result === undefined
      ? { ...part, interrupted: true } : part);
    updateAssistant(message => ({ ...message, pending: false, parts: settled, memory }));
    if (!parts.length) emit('update:messages', props.messages.filter(message => message.message_id !== assistantId
      && (!retractUser || message.message_id !== user.message_id)));
    emit('settled-logs', [...props.intermediateMessages, ...streamLogs.value]);
    streamLogs.value = [];
    controller = null; sending.value = false; approval.value = null; emit('running', false);
  }
}
// 删除后端末轮消息，返回裁剪后的本地消息、日志长度和被删的用户原文。
async function rewind() {
  const payload = await deleteLastTurn(props.conversationId);
  const index = props.messages.findLastIndex(message => message.role === 'user');
  const base = index < 0 ? props.messages : props.messages.slice(0, index);
  const logs = props.intermediateMessages.filter((log, i) => typeof log.message_id === 'number'
    ? log.message_id < payload.first_deleted_id : turnLogStart === null || i < turnLogStart);
  emit('update:messages', base); emit('settled-logs', logs);
  return { base, logStart: logs.length, text: payload.user_message };
}
async function resend(pickText) {
  if (!canRewind.value) return;
  rewinding.value = true;
  let options, text;
  try { ({ text, ...options } = await rewind()); }
  catch (err) { emit('error', `重新生成失败：${err.message}`); return; }
  finally { rewinding.value = false; }
  await send(pickText(text), options);
}
const regenerate = () => resend(text => text);
function submit(text) {
  if (typeof text !== 'string') text = draft.value;
  if (!editing.value) return send(text);
  if (text.trim()) return resend(() => text);
}
function startEdit(content) { editing.value = true; draft.value = content; }
function cancelEdit() { editing.value = false; draft.value = ''; }
async function decide(requestId, decision) {
  if (approving.value || !approval.value) return;
  approving.value = true;
  try { await approveRequest(requestId, decision); }
  catch (err) { emit('error', `审批提交失败：${err.message}`); }
  finally { approving.value = false; }
}
async function copy(content) {
  try { await navigator.clipboard.writeText(content); ElMessage.success('已复制'); }
  catch { ElMessage.error('复制失败，请检查浏览器剪贴板权限'); }
}
function print(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
watch(() => props.conversationId, () => { if (!sending.value && !props.messages.some(message => message.message_id === assistantId)) { streamLogs.value = []; draft.value = ''; editing.value = false; turnLogStart = null; } });
watch(() => !sourceNames.value && items.value.some(item => item.sources.some(source => source.kind === 'knowledge')), async needed => {
  if (!needed) return;
  sourceNames.value = {};
  try { sourceNames.value = Object.fromEntries(((await fetchRagSources()).sources || []).map(item => [item.source_id, item.name])); }
  catch { /* 拿不到名称时退回显示 source_id */ }
}, { immediate: true });
// 输入框在空状态与对话态之间会重建，切换后把焦点还给它。
watch(() => props.messages.length, async (length, previous) => {
  await nextTick(); bubbleList.value?.scrollToBottom();
  if (!previous !== !length) composer.value?.querySelector('textarea')?.focus();
});
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section class="workspace chat-workspace" :class="{ 'chat-empty': !messages.length }">
    <Teleport defer to="#header-actions">
      <el-button v-if="conversationId" text :icon="PieChart" @click="emit('context', 'drawer')">上下文</el-button>
      <el-button v-if="messages.length" text :icon="Document" @click="loggingOpen = true">运行日志</el-button>
    </Teleport>
    <div v-if="!messages.length" class="welcome">
      <img src="/lifeops_pixel_logo.svg" alt="" /><h2>{{ greeting }}，我是 LifeOps</h2>
      <p>整理思绪、查找资料，把今天的事情做好。</p>
    </div>
    <div v-else class="chat-stream">
      <div v-if="historicalTodos.length" class="history-todos"><strong>任务计划</strong>
        <p v-for="(todo, index) in historicalTodos" :key="index">{{ todo.status === 'completed' ? '✓' : '○' }} {{ todo.content }}</p>
      </div>
      <BubbleList ref="bubbleList" :list="items" max-height="100%" :show-back-button="true">
        <template #content="{ item }">
          <div :data-slot="item.role === 'assistant' ? 'lifeops-assistant-message' : 'lifeops-user-message'">
            <div v-if="item.role === 'user'" class="user-content">{{ item.content }}</div>
            <template v-else-if="item.parts?.length">
              <template v-for="(part, index) in item.parts" :key="index">
                <MarkdownRenderer v-if="part.kind === 'text'" :content="part.text" />
                <div v-else-if="part.approval && !part.approval.decision && !part.interrupted"
                  class="approval-card" role="alertdialog" aria-label="工具审批请求" data-slot="lifeops-approval-card">
                  <strong>工具调用需要授权：{{ part.toolName }}</strong>
                  <el-tag type="warning">风险：{{ part.approval.risk_level }}</el-tag>
                  <pre>{{ part.approval.params_preview || print(part.args) }}</pre><p>{{ part.approval.reason }}</p>
                  <div class="actions"><el-button :disabled="approving" @click="decide(part.approval.request_id, 'deny')">拒绝</el-button>
                    <el-button :disabled="approving" @click="decide(part.approval.request_id, 'allow_always')">总是允许</el-button>
                    <el-button type="primary" :loading="approving" @click="decide(part.approval.request_id, 'allow_once')">允许一次</el-button></div>
                </div>
                <div v-else-if="part.todos" class="todo-card" data-slot="lifeops-todo-card"><strong>任务计划</strong>
                  <p v-for="(todo, i) in part.todos" :key="i" :class="{ completed: todo.status === 'completed' }">
                    {{ todo.status === 'completed' ? '✓' : todo.status === 'in_progress' ? '◷' : '○' }} {{ todo.content }}</p>
                </div>
                <details v-else class="tool-card" :class="{ failed: part.isError }">
                  <summary><el-icon><Close v-if="part.isError" /><Check v-else-if="part.result !== undefined" /><Tools v-else /></el-icon>
                    {{ part.toolName }} <span>{{ part.interrupted ? '已中断' : part.result !== undefined ? (part.isError ? '失败' : '已完成') : '执行中' }}</span></summary>
                  <strong>参数</strong><pre>{{ print(part.args) }}</pre>
                  <template v-if="part.result !== undefined"><strong>结果</strong><pre>{{ print(part.result) }}</pre></template>
                </details>
              </template>
            </template>
            <MarkdownRenderer v-else :content="item.content" />
          </div>
        </template>
        <template #footer="{ item }">
          <div v-if="item.sourceText || item.memoryText" class="message-meta">
            <button v-if="item.sourceText" title="查看运行日志" @click="loggingOpen = true"><el-icon><Link /></el-icon>来源：{{ item.sourceText }}</button>
            <span v-if="item.memoryText"><el-icon><Memo /></el-icon>已载入记忆：{{ item.memoryText }}</span>
          </div>
          <div v-if="item.role === 'assistant' && item.content" class="message-actions" :class="{ pinned: item.isLast }">
            <el-button text :icon="CopyDocument" title="复制" aria-label="复制回答" @click="copy(item.content)" />
            <el-button text :icon="Download" title="导出 Markdown" aria-label="导出 Markdown" @click="downloadMarkdown('LifeOps-回答.md', item.content)" />
            <el-button v-if="item.isLast && canRewind" text :icon="RefreshRight" title="重新生成" aria-label="重新生成" @click="regenerate" /></div>
          <div v-else-if="item.role === 'user'" class="message-actions">
            <el-button text :icon="CopyDocument" title="复制" aria-label="复制消息" @click="copy(item.content)" />
            <el-button v-if="item.isLastUser && canRewind" text :icon="EditPen" title="编辑后重新发送" aria-label="编辑消息" @click="startEdit(item.content)" /></div>
        </template>
      </BubbleList>
    </div>
    <div ref="composer" class="composer" data-slot="lifeops-composer">
      <div v-if="editing" class="composer-editing">正在编辑上一条消息，发送后会替换原来的回答
        <el-button text size="small" @click="cancelEdit">取消</el-button></div>
      <Sender :key="messages.length ? 'chat' : 'empty'" v-model="draft" :variant="messages.length ? 'default' : 'updown'"
        :auto-size="{ minRows: messages.length ? 1 : 2, maxRows: 6 }"
        placeholder="有什么想让我帮忙的？"
        :loading="sending && !approval" :disabled="disabled || Boolean(approval)" :submit-btn-disabled="!draft.trim()"
        @submit="submit" @cancel="controller?.abort()">
        <template #action-list>
          <el-button v-if="sending" circle aria-label="停止生成" @click="controller?.abort()"><el-icon><Close /></el-icon></el-button>
          <el-button v-else circle type="primary" :icon="Top" aria-label="发送消息" :disabled="disabled || !draft.trim()" @click="submit()" />
        </template>
      </Sender>
      <el-button v-if="approval" size="small" class="stop-approval" @click="controller?.abort()">停止运行</el-button>
    </div>
    <div v-if="!messages.length" class="suggestions">
      <button v-for="item in suggestions" :key="item.label" @click="draft = item.prompt">
        <el-icon><component :is="item.icon" /></el-icon>{{ item.label }}</button>
    </div>
    <p class="composer-note">AI 回答可能有误，请核实重要信息。</p>
    <el-dialog v-model="loggingOpen" title="回答中间信息" width="min(1000px, 94vw)" destroy-on-close>
      <el-empty v-if="!logs.length" description="暂无中间信息" />
      <div v-else class="logging-entries"><details v-for="(log, index) in logs" :key="index" :open="index === 0">
        <summary>{{ log.tool_calls?.length ? '工具调用' : log.role === 'tool' ? '工具结果' : '中间信息' }} ·
          {{ log.tool_name || log.tool_calls?.map(call => call.function?.name).join(', ') || log.role }}</summary>
        <div v-for="(call, i) in log.tool_calls || []" :key="i"><strong>{{ call.function?.name }}</strong>
          <p v-if="call.id">调用 ID：{{ call.id }}</p><pre>{{ call.function?.arguments }}</pre></div>
        <MarkdownRenderer :content="log.content || ''" /><pre v-if="log.metadata?.diff">{{ log.metadata.diff }}</pre>
      </details></div>
    </el-dialog>
  </section>
</template>
