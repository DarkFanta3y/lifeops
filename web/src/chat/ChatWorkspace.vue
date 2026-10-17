<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import BubbleList from './ChatMessageList.vue';
import TurnContent from './TurnContent.vue';
import TurnNav from './TurnNav.vue';
import './activity.css';
import Sender from '@element-plus-x/Sender/index.js';
import { Document, CopyDocument, Download, Close, Top, EditPen, RefreshRight, Link, Memo, PieChart, Headset, VideoPause } from '@element-plus/icons-vue';
import { approveRequest, deleteLastTurn, fetchRagSources, reviewPlan, sendChatMessage } from '../api.js';
import { downloadMarkdown } from '../download.js';
import MarkdownRenderer from '../MarkdownRenderer.vue';
import RunStatusBar from './RunStatusBar.vue';
import { collectSources, settleStreamParts, updateStreamParts } from './stream.js';
import { createRunTracker, createSpeedMeter, createUsageMeter, usageStats } from './runMetrics.js';
import { findCommand, matchCommands, parsePlanCommand } from './commands.js';
import { speak, speechSupported, stopSpeaking, toSpeechText } from './speech.js';

const props = defineProps({ messages: { type: Array, default: () => [] },
  intermediateMessages: { type: Array, default: () => [] }, conversationId: String, disabled: Boolean,
  planMode: Boolean });
const emit = defineEmits(['update:messages', 'update:planMode', 'running', 'done', 'error', 'settled-logs', 'context', 'command']);
const draft = ref('');
const sending = ref(false);
const approval = ref(null);
const approving = ref(false);
const review = ref(null);
const reviewing = ref(false);
const reviewFeedback = ref('');
const feedbackOpen = ref(false);
const PLAN_DECISION_TEXT = { approve: '已批准，开始执行', revise: '已要求继续规划', dismiss: '已关闭评审' };
const bubbleList = ref(null);
const composer = ref(null);
const loggingOpen = ref(false);
const streamLogs = ref([]);
const activeStatus = ref('completed');
function savedMode() {
  try { return localStorage.getItem('lifeops.workDetails') === 'detailed' ? 'detailed' : 'standard'; }
  catch { return 'standard'; }
}
const detailMode = ref(savedMode());
function preserveLayout(change) { return bubbleList.value?.preserveLayout(change) || change(); }
function setDetailMode(mode) {
  preserveLayout(() => { detailMode.value = mode; });
  try { localStorage.setItem('lifeops.workDetails', mode); } catch { /* 无持久化权限时保留会话内偏好 */ }
}
const hour = new Date().getHours();
const greeting = hour < 5 ? '夜深了' : hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好';
const editing = ref(false);
const rewinding = ref(false);
const sourceNames = ref(null);
const speakingId = ref(null);
const commandIndex = ref(0);
const commandDismissed = ref(false);
let controller;
let parts = [];
let assistantId;
let turnLogStart = null;
// 运行状态栏：轮次/步骤/速率/Token 从 SSE 流实时累计，结束时用后端真实 usage 校正。
const MAX_ROUNDS = 50; // 与后端 AgentConfig.max_iterations 默认值一致
const runTracker = createRunTracker({ maxRounds: MAX_ROUNDS });
const speedMeter = createSpeedMeter();
const usageMeter = createUsageMeter();
const runStats = ref({ rounds: 1, steps: 0, speed: 0, tokens: 0, cacheHit: null, progress: 2 });
function resetRunStats() {
  runTracker.reset(); speedMeter.reset(); usageMeter.reset();
  runStats.value = { rounds: 1, steps: 0, speed: 0, tokens: 0, cacheHit: null, progress: runTracker.progress() };
}
function trackRunStats() {
  runStats.value = { ...runStats.value, ...usageMeter.snapshot(), rounds: runTracker.rounds, steps: runTracker.steps,
    progress: runTracker.progress(), speed: speedMeter.rate() };
}
const canRewind = computed(() => Boolean(props.conversationId) && !sending.value && !rewinding.value && !props.disabled);
// 命令可用条件；不可用的命令不出现在候选里。
const commandReady = {
  new: () => !sending.value, search: () => !sending.value, context: () => true, logs: () => true,
  regenerate: () => canRewind.value && props.messages.at(-1)?.role === 'assistant',
  rename: () => Boolean(props.conversationId) && !sending.value,
  export: () => props.messages.length > 0 && !sending.value,
  plan: () => !sending.value,
};
const commandMatches = computed(() => commandDismissed.value ? []
  : matchCommands(draft.value).filter(command => commandReady[command.name]()));
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
// 对话快速导航：每轮用户提问一个锚点，当前轮次由消息列表随滚动测量后回传。
const turns = computed(() => props.messages.filter(message => message.role === 'user')
  .map(message => ({ key: String(message.message_id), preview: message.content })));
const activeTurnKey = ref(null);
function goTurn(key) { bubbleList.value?.scrollToKey(key); }
const historicalTodos = computed(() => {
  if (props.messages.some(message => message.parts?.some(part => part.toolName === 'todo_write'))) return [];
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
  // usage 只是指标，不参与正文渲染：累加后立即刷新状态栏。
  if (type === 'usage') { usageMeter.addUsage(data); trackRunStats(); return; }
  if (type === 'run_finished') activeStatus.value = data.status;
  const update = () => {
    parts = updateStreamParts(parts, type, data);
    const final = parts.filter(part => part.kind === 'text' && part.final);
    updateAssistant(message => ({ ...message, parts, pending: false, turnStatus: activeStatus.value,
      keepProcessOpen: type === 'run_finished' ? !bubbleList.value?.isFollowing() : message.keepProcessOpen,
      turnError: type === 'run_finished' ? data.error : message.turnError,
      content: (final.length ? final : parts.filter(part => part.kind === 'text')).map(part => part.text).join('') }));
  };
  if (type === 'run_finished') preserveLayout(update); else update();
  if (type === 'token') { speedMeter.add(data); usageMeter.addText(data); runTracker.onToken(); trackRunStats(); }
  if (type === 'tool_call') { runTracker.onToolCall(data.tool_name || data.name); trackRunStats(); }
  if (type === 'tool_result') runTracker.onToolResult();
  if (type === 'approval_required' || type === 'approval_resolved') {
    approval.value = parts.find(part => part.approval && !part.approval.decision)?.approval || null;
  }
  if (type === 'plan_review_required' || type === 'plan_review_resolved') {
    review.value = parts.find(part => part.review && !part.review.decision)?.review || null;
    reviewFeedback.value = ''; feedbackOpen.value = false;
  }
  if (type === 'tool_call') streamLogs.value = [...streamLogs.value, { role: 'assistant', tool_calls: [
    { id: data.call_id, function: { name: data.tool_name, arguments: JSON.stringify(data.args ?? data.params ?? {}) } },
  ] }];
  if (type === 'tool_result') streamLogs.value = [...streamLogs.value, { role: 'tool', tool_name: data.tool_name,
    tool_call_id: data.call_id, content: `${data.error || ''}${data.output || data.result || ''}`, metadata: data.metadata }];
}
// base / logStart 供重新生成使用：删除末轮后 props 尚未刷新，需显式传入裁剪后的消息与日志长度。
async function send(text = draft.value, { base = props.messages, logStart = props.intermediateMessages.length } = {}) {
  text = text.trim();
  if (!text || sending.value || props.disabled) return;
  draft.value = ''; editing.value = false; stopSpeech();
  sending.value = true; emit('running', true); emit('error', '');
  resetRunStats(); activeStatus.value = 'running';
  parts = []; turnLogStart = logStart;
  assistantId = crypto.randomUUID();
  const user = { message_id: crypto.randomUUID(), role: 'user', content: text };
  emit('update:messages', [...base, user,
    { message_id: assistantId, role: 'assistant', content: '', parts: [], pending: true, turnStatus: 'running' }]);
  controller = new AbortController();
  let retractUser = false, memory;
  await nextTick(); bubbleList.value?.scrollToBottom();
  try {
    const payload = await sendChatMessage({ message: text, conversationId: props.conversationId,
      planMode: props.planMode, signal: controller.signal, onToken: data => receive('token', data),
      onUsage: data => receive('usage', data),
      onToolCall: data => receive('tool_call', data), onToolResult: data => receive('tool_result', data),
      onActivity: (type, data) => receive(type, data),
      onApproval: data => receive('approval_required', data),
      onApprovalResolved: data => receive('approval_resolved', data),
      onPlanReview: data => receive('plan_review_required', data),
      onPlanReviewResolved: data => receive('plan_review_resolved', data),
      onPlanModeChanged: data => emit('update:planMode', Boolean(data.active)) });
    memory = payload?.memory;
    activeStatus.value = payload?.status || (activeStatus.value === 'running' ? 'completed' : activeStatus.value);
    const usage = usageStats(payload?.usage);
    if (usage) runStats.value = { ...runStats.value, tokens: usage.tokens, cacheHit: usage.cacheHit };
    emit('done', payload);
  } catch (err) {
    activeStatus.value = err.name === 'AbortError' ? 'cancelled' : 'failed';
    updateAssistant(message => ({ ...message, turnError: err.name === 'AbortError' ? '运行已停止' : err.message }));
    if (err.name !== 'AbortError') emit('error', err.message);
    retractUser = err.name !== 'AbortError' && !parts.length;
    if (!parts.length) draft.value = text;
  } finally {
    parts = settleStreamParts(parts, activeStatus.value);
    updateAssistant(message => ({ ...message, pending: false, parts, memory, turnStatus: activeStatus.value,
      content: parts.filter(part => part.kind === 'text' && part.final).map(part => part.text).join('') }));
    if (!parts.length) emit('update:messages', props.messages.filter(message => message.message_id !== assistantId
      && (!retractUser || message.message_id !== user.message_id)));
    emit('settled-logs', [...props.intermediateMessages, ...streamLogs.value]);
    streamLogs.value = [];
    controller = null; sending.value = false; approval.value = null; review.value = null; emit('running', false);
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
  const plan = parsePlanCommand(text);
  if (plan) return runPlanCommand(plan);
  const command = findCommand(text);
  if (command) return runCommand(command);
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
// 计划模式随下一条消息提交给后端；带消息时直接发送。
function runPlanCommand({ active, message }) {
  if (sending.value) { ElMessage.warning('运行中无法切换计划模式'); return; }
  draft.value = ''; editing.value = false;
  emit('update:planMode', active);
  if (message) return send(message);
  ElMessage.info(active ? '已进入计划模式：先规划，批准后再执行' : '已退出计划模式');
}
async function decidePlan(decision) {
  if (reviewing.value || !review.value) return;
  reviewing.value = true;
  try { await reviewPlan(review.value.request_id, decision, decision === 'revise' ? reviewFeedback.value.trim() : ''); }
  catch (err) { emit('error', `计划评审提交失败：${err.message}`); }
  finally { reviewing.value = false; }
}
async function copy(content) {
  try { await navigator.clipboard.writeText(content); ElMessage.success('已复制'); }
  catch { ElMessage.error('复制失败，请检查浏览器剪贴板权限'); }
}
function stopSpeech() { stopSpeaking(); speakingId.value = null; }
function toggleSpeak(item) {
  if (speakingId.value === item.key) return stopSpeech();
  speakingId.value = item.key;
  speak(toSpeechText(item.content), { onEnd: () => { speakingId.value = null; } });
}
// “/”命令只在前端执行，不发给模型；new/search/rename/export 交给 App 处理。
function runCommand(command) {
  if (!commandReady[command.name]()) { ElMessage.warning(`当前无法使用 /${command.name}`); return; }
  draft.value = ''; editing.value = false;
  if (command.name === 'context') emit('context', 'modal');
  else if (command.name === 'logs') loggingOpen.value = true;
  else if (command.name === 'regenerate') regenerate();
  else if (command.name === 'plan') runPlanCommand({ active: true, message: '' });
  else emit('command', command.name);
}
// 捕获阶段拦截按键，避免回车被 Sender 当作发送。
function commandKeydown(event) {
  const count = commandMatches.value.length;
  if (!count || event.isComposing) return;
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    commandIndex.value = (commandIndex.value + (event.key === 'ArrowDown' ? 1 : count - 1)) % count;
  } else if ((event.key === 'Enter' && !event.shiftKey) || event.key === 'Tab') {
    runCommand(commandMatches.value[Math.min(commandIndex.value, count - 1)]);
  } else if (event.key === 'Escape') commandDismissed.value = true;
  else return;
  event.preventDefault(); event.stopPropagation();
}
watch(draft, () => { commandIndex.value = 0; commandDismissed.value = false; });
function print(value) { return typeof value === 'string' ? value : JSON.stringify(value, null, 2); }
// 新会话首轮结束后 conversationId 才落地，此时消息里仍带着本次回答，不能重置运行指标。
watch(() => props.conversationId, () => { stopSpeech(); if (!sending.value && !props.messages.some(message => message.message_id === assistantId)) { resetRunStats(); streamLogs.value = []; draft.value = ''; editing.value = false; turnLogStart = null; } });
watch(() => !sourceNames.value && items.value.some(item => item.sources.some(source => source.kind === 'knowledge')), async needed => {
  if (!needed) return;
  sourceNames.value = {};
  try { sourceNames.value = Object.fromEntries(((await fetchRagSources()).sources || []).map(item => [item.source_id, item.name])); }
  catch { /* 拿不到名称时退回显示 source_id */ }
}, { immediate: true });
// 输入框在空状态与对话态之间会重建，切换后把焦点还给它。
watch(() => props.messages.length, async (length, previous) => {
  await nextTick();
  if (!previous !== !length) composer.value?.querySelector('textarea')?.focus();
});
onBeforeUnmount(() => { controller?.abort(); stopSpeech(); });
</script>

<template>
  <section class="workspace chat-workspace" :class="{ 'chat-empty': !messages.length }">
    <Teleport defer to="#header-actions">
      <div v-if="messages.length" class="activity-mode" role="group" aria-label="工作过程显示模式">
        <button v-for="mode in ['standard', 'detailed']" :key="mode" type="button" :aria-pressed="detailMode === mode"
          @click="setDetailMode(mode)">{{ mode === 'standard' ? '标准' : '详细' }}</button>
      </div>
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
      <BubbleList ref="bubbleList" :list="items" max-height="100%" :show-back-button="true"
        @turn-change="activeTurnKey = $event">
        <template #content="{ item }">
          <div :data-slot="item.role === 'assistant' ? 'lifeops-assistant-message' : 'lifeops-user-message'">
            <div v-if="item.role === 'user'" class="user-content">{{ item.content }}</div>
            <TurnContent v-else-if="item.parts?.length" :parts="item.parts" :mode="detailMode"
              :status="item.turnStatus" :error="item.turnError" :keep-process-open="item.keepProcessOpen"
              :running="sending && item.isLast" @layout="preserveLayout">
              <template #control="{ part }">
                <div v-if="part.toolName === 'exit_plan_mode' && (part.review || part.args?.plan)"
                  class="plan-card" :role="part.review && !part.review.decision && !part.interrupted ? 'alertdialog' : undefined"
                  aria-label="计划评审" data-slot="lifeops-plan-review-card">
                  <div class="plan-head"><strong>{{ part.review?.title || '计划' }}</strong>
                    <el-tag v-if="part.review?.decision" size="small" :type="part.review.decision === 'approve' ? 'success' : 'info'">
                      {{ PLAN_DECISION_TEXT[part.review.decision] }}</el-tag>
                    <el-tag v-else-if="part.interrupted" size="small" type="info">已中断</el-tag>
                    <el-tag v-else-if="part.isError && !part.review" size="small" type="danger">提交失败</el-tag></div>
                  <div class="plan-body"><MarkdownRenderer :content="part.review?.plan || part.args.plan" /></div>
                  <p v-if="part.isError && !part.review" class="plan-error">{{ part.result }}</p>
                  <template v-if="part.review && !part.review.decision && !part.interrupted">
                    <el-input v-if="feedbackOpen" v-model="reviewFeedback" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }"
                      placeholder="说明需要调整的地方（可选）" />
                    <div class="actions">
                      <el-button :disabled="reviewing" @click="decidePlan('dismiss')">关闭</el-button>
                      <el-button v-if="!feedbackOpen" :disabled="reviewing" @click="feedbackOpen = true">继续规划</el-button>
                      <el-button v-else :loading="reviewing" @click="decidePlan('revise')">提交反馈</el-button>
                      <el-button type="primary" :loading="reviewing" @click="decidePlan('approve')">批准并执行</el-button></div>
                  </template>
                </div>
                <div v-else-if="part.approval && !part.approval.decision && !part.interrupted"
                  class="approval-card" role="alertdialog" aria-label="工具审批请求" data-slot="lifeops-approval-card">
                  <strong>工具调用需要授权：{{ part.toolName }}</strong>
                  <el-tag type="warning">风险：{{ part.approval.risk_level }}</el-tag>
                  <pre>{{ part.approval.params_preview || print(part.args) }}</pre><p>{{ part.approval.reason }}</p>
                  <div class="actions"><el-button :disabled="approving" @click="decide(part.approval.request_id, 'deny')">拒绝</el-button>
                    <el-button :disabled="approving" @click="decide(part.approval.request_id, 'allow_always')">总是允许</el-button>
                    <el-button type="primary" :loading="approving" @click="decide(part.approval.request_id, 'allow_once')">允许一次</el-button></div>
                </div>
              </template>
            </TurnContent>
            <MarkdownRenderer v-else :content="item.content" />
          </div>
        </template>
        <template #footer="{ item }">
          <div v-if="item.sourceText || item.memoryText" class="message-meta">
            <button v-if="item.sourceText" title="查看运行日志" @click="loggingOpen = true"><el-icon><Link /></el-icon>来源：{{ item.sourceText }}</button>
            <span v-if="item.memoryText"><el-icon><Memo /></el-icon>已载入记忆：{{ item.memoryText }}</span>
          </div>
          <div v-if="item.role === 'assistant' && item.content" class="message-actions" :class="{ pinned: item.isLast || speakingId === item.key }">
            <el-button text :icon="CopyDocument" title="复制" aria-label="复制回答" @click="copy(item.content)" />
            <el-button v-if="speechSupported && !(sending && item.isLast)" text :icon="speakingId === item.key ? VideoPause : Headset"
              :title="speakingId === item.key ? '停止朗读' : '朗读'" :aria-label="speakingId === item.key ? '停止朗读' : '朗读回答'" @click="toggleSpeak(item)" />
            <el-button text :icon="Download" title="导出 Markdown" aria-label="导出 Markdown" @click="downloadMarkdown('LifeOps-回答.md', item.content)" />
            <el-button v-if="item.isLast && canRewind" text :icon="RefreshRight" title="重新生成" aria-label="重新生成" @click="regenerate" /></div>
          <div v-else-if="item.role === 'user'" class="message-actions">
            <el-button text :icon="CopyDocument" title="复制" aria-label="复制消息" @click="copy(item.content)" />
            <el-button v-if="item.isLastUser && canRewind" text :icon="EditPen" title="编辑后重新发送" aria-label="编辑消息" @click="startEdit(item.content)" /></div>
        </template>
      </BubbleList>
      <TurnNav v-if="turns.length > 1" :turns="turns" :active-key="activeTurnKey" @select="goTurn" />
    </div>
    <div ref="composer" class="composer" data-slot="lifeops-composer" @keydown.capture="commandKeydown">
      <ul v-if="commandMatches.length" class="command-menu" role="listbox" aria-label="命令">
        <li v-for="(command, index) in commandMatches" :key="command.name" role="option"
          :aria-selected="index === commandIndex" :class="{ active: index === commandIndex }"
          @mouseenter="commandIndex = index" @mousedown.prevent="runCommand(command)">
          <code>/{{ command.name }}</code><strong>{{ command.label }}</strong><span>{{ command.description }}</span>
        </li>
      </ul>
      <div v-if="planMode" class="composer-plan" data-slot="lifeops-plan-mode">
        <el-tag size="small" type="warning" effect="dark">计划模式</el-tag>
        <span>只读探索并提交计划，批准后才执行</span>
        <el-button text size="small" :disabled="sending" @click="runPlanCommand({ active: false, message: '' })">退出</el-button></div>
      <div v-if="editing" class="composer-editing">正在编辑上一条消息，发送后会替换原来的回答
        <el-button text size="small" @click="cancelEdit">取消</el-button></div>
      <Sender :key="messages.length ? 'chat' : 'empty'" v-model="draft" :variant="messages.length ? 'default' : 'updown'"
        :auto-size="{ minRows: messages.length ? 1 : 2, maxRows: 6 }"
        placeholder="有什么想让我帮忙的？输入 / 查看命令"
        :loading="sending && !approval && !review" :disabled="disabled || Boolean(approval) || Boolean(review)" :submit-btn-disabled="!draft.trim()"
        @submit="submit" @cancel="controller?.abort()">
        <template #action-list>
          <el-button v-if="sending" circle aria-label="停止生成" @click="controller?.abort()"><el-icon><Close /></el-icon></el-button>
          <el-button v-else circle type="primary" :icon="Top" aria-label="发送消息" :disabled="disabled || !draft.trim()" @click="submit()" />
        </template>
      </Sender>
      <el-button v-if="approval || review" size="small" class="stop-approval" @click="controller?.abort()">停止运行</el-button>
    </div>
    <RunStatusBar v-if="messages.length" :rounds="runStats.rounds" :steps="runStats.steps"
      :speed="runStats.speed" :tokens="runStats.tokens" :cache-hit="runStats.cacheHit"
      :progress="runStats.progress" :running="sending" />
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
