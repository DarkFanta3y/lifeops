<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import BubbleList from '@element-plus-x/BubbleList/index.js';
import Sender from '@element-plus-x/Sender/index.js';
import { Document, CopyDocument, Download, Check, Close, Tools, Top } from '@element-plus/icons-vue';
import { approveRequest, sendChatMessage } from '../api.js';
import MarkdownRenderer from '../MarkdownRenderer.vue';
import { updateStreamParts } from './stream.js';

const props = defineProps({ messages: { type: Array, default: () => [] },
  intermediateMessages: { type: Array, default: () => [] }, conversationId: String, disabled: Boolean });
const emit = defineEmits(['update:messages', 'running', 'done', 'error', 'settled-logs']);
const draft = ref('');
const sending = ref(false);
const approval = ref(null);
const approving = ref(false);
const bubbleList = ref(null);
const loggingOpen = ref(false);
const streamLogs = ref([]);
const previewOpen = ref(false);
let controller;
let parts = [];
let assistantId;
const items = computed(() => props.messages.map(message => ({ ...message,
  key: message.message_id, placement: message.role === 'user' ? 'end' : 'start',
  avatar: message.role === 'user' ? undefined : '/lifeops_pixel_logo.svg', avatarSize: '30px',
  noStyle: message.role !== 'user', typing: false,
  loading: Boolean(message.pending && !message.parts?.length),
})));
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
async function send(text = draft.value) {
  text = text.trim();
  if (!text || sending.value || props.disabled) return;
  draft.value = ''; previewOpen.value = false;
  sending.value = true; emit('running', true); emit('error', '');
  parts = [];
  assistantId = crypto.randomUUID();
  const user = { message_id: crypto.randomUUID(), role: 'user', content: text };
  emit('update:messages', [...props.messages, user,
    { message_id: assistantId, role: 'assistant', content: '', parts: [], pending: true }]);
  controller = new AbortController();
  let retractUser = false;
  await nextTick(); bubbleList.value?.scrollToBottom();
  try {
    const payload = await sendChatMessage({ message: text, conversationId: props.conversationId,
      signal: controller.signal, onToken: data => receive('token', data),
      onToolCall: data => receive('tool_call', data), onToolResult: data => receive('tool_result', data),
      onApproval: data => receive('approval_required', data),
      onApprovalResolved: data => receive('approval_resolved', data) });
    emit('done', payload);
  } catch (err) {
    if (err.name !== 'AbortError') emit('error', err.message);
    retractUser = err.name !== 'AbortError' && !parts.length;
    if (!parts.length) draft.value = text;
  } finally {
    const settled = parts.map(part => part.kind === 'tool' && part.result === undefined
      ? { ...part, interrupted: true } : part);
    updateAssistant(message => ({ ...message, pending: false, parts: settled }));
    if (!parts.length) emit('update:messages', props.messages.filter(message => message.message_id !== assistantId
      && (!retractUser || message.message_id !== user.message_id)));
    emit('settled-logs', [...props.intermediateMessages, ...streamLogs.value]);
    streamLogs.value = [];
    controller = null; sending.value = false; approval.value = null; emit('running', false);
  }
}
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
function download(content) {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = 'LifeOps-回答.md'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function print(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
watch(() => props.conversationId, () => { if (!sending.value && !props.messages.some(message => message.message_id === assistantId)) { streamLogs.value = []; draft.value = ''; } });
watch(() => props.messages.length, async () => { await nextTick(); bubbleList.value?.scrollToBottom(); });
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <section class="workspace chat-workspace" :class="{ 'chat-empty': !messages.length }">
    <div class="chat-actions"><span class="muted">{{ messages.length }} 条消息</span>
      <el-button text :icon="Document" @click="loggingOpen = true">Logging</el-button></div>
    <div v-if="!messages.length" class="welcome">
      <img src="/lifeops_pixel_logo.svg" alt="" /><h2>你好，我是 LifeOps</h2>
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
          <div v-if="item.role === 'assistant' && item.content" class="message-actions">
            <el-button text :icon="CopyDocument" aria-label="复制回答" @click="copy(item.content)" />
            <el-button text :icon="Download" aria-label="导出 Markdown" @click="download(item.content)" /></div>
        </template>
      </BubbleList>
    </div>
    <div class="composer" data-slot="lifeops-composer">
      <div v-if="previewOpen" class="composer-preview"><MarkdownRenderer :content="draft || '暂无预览内容'" /></div>
      <Sender v-model="draft" variant="updown" :auto-size="{ minRows: 2, maxRows: 6 }"
        placeholder="发送消息给 LifeOps，Enter 发送，Shift+Enter 换行"
        :loading="sending && !approval" :disabled="disabled || Boolean(approval)" :submit-btn-disabled="!draft.trim()"
        @submit="send" @cancel="controller?.abort()">
        <template #action-list>
          <el-button v-if="sending" circle aria-label="停止生成" @click="controller?.abort()"><el-icon><Close /></el-icon></el-button>
          <el-button v-else circle type="primary" :icon="Top" aria-label="发送消息" :disabled="disabled || !draft.trim()" @click="send()" />
        </template>
        <template #prefix><span class="composer-label">LifeOps 助手</span>
          <el-button text size="small" :aria-expanded="previewOpen" @click="previewOpen = !previewOpen">Markdown 预览</el-button></template>
      </Sender>
      <el-button v-if="approval" size="small" class="stop-approval" @click="controller?.abort()">停止运行</el-button>
      <p class="composer-note">AI 回答可能有误，请核实重要信息。</p>
    </div>
    <div v-if="!messages.length" class="suggestions">
      <button @click="draft = '帮我整理今天的待办，按优先级列出计划'">整理今日待办 <span>↗</span></button>
      <button @click="draft = '从知识库查找与我的问题有关的资料'">查找知识库资料 <span>↗</span></button>
      <button @click="draft = '帮我复盘这一周，整理完成的工作和下周行动'">写一份周复盘 <span>↗</span></button>
    </div>
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
