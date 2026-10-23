<script setup>
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue';
import zhCn from 'element-plus/es/locale/lang/zh-cn';
import { Coin, Cpu, DataAnalysis, Search, Plus, Fold, Expand, ArrowDown, EditPen, Download, Delete } from '@element-plus/icons-vue';
import Conversations from '@element-plus-x/Conversations/index.js';
import { fetchConversations, fetchConversationCursor, deleteConversation, renameConversation,
  fetchModels, setActiveModel, clearActiveModel } from './api.js';
import { downloadMarkdown } from './download.js';
import { restoreConversation } from './chat/stream.js';
import { mergeUniqueById } from './pagination.js';

const ChatWorkspace = defineAsyncComponent(() => import('./chat/ChatWorkspace.vue'));
const DatabaseWorkspace = defineAsyncComponent(() => import('./workspaces/DatabaseWorkspace.vue'));
const InsightsWorkspace = defineAsyncComponent(() => import('./workspaces/InsightsWorkspace.vue'));
const ModelsWorkspace = defineAsyncComponent(() => import('./workspaces/ModelsWorkspace.vue'));
const ContextDrawer = defineAsyncComponent(() => import('./context/components/ContextDrawer.vue'));
const ContextModal = defineAsyncComponent(() => import('./context/components/ContextModal.vue'));
const contextDrawer = ref(false);
const contextModal = ref(false);
const view = ref('chat');
const collapsed = ref(window.innerWidth < 760);
const running = ref(false);
const conversations = ref([]);
const total = ref(0);
const listLoading = ref(false);
const listMoreLoading = ref(false);
const selectedId = ref(null);
const selectedTitle = ref('');
const messages = ref([]);
const intermediate = ref([]);
const planMode = ref(false);
const historyLoading = ref(false);
const error = ref('');
const searchOpen = ref(false);
const query = ref('');
const results = ref([]);
const searchTotal = ref(0);
const searchLoading = ref(false);
const searchError = ref('');
let listGeneration = 0;
let historyGeneration = 0;
let searchGeneration = 0;
const nav = [
  { key: 'insights', label: '上下文洞察', icon: DataAnalysis },
  { key: 'database', label: '知识库', icon: Coin },
  { key: 'models', label: '模型管理', icon: Cpu },
];
const title = computed(() => view.value === 'chat' ? selectedTitle.value
  : nav.find(item => item.key === view.value)?.label);
const modelProviders = ref([]);
const activeModel = ref(null);
const modelFallback = ref(null);
const modelReady = ref(false);
const activeModelKey = computed(() => activeModel.value
  ? `${activeModel.value.provider_id}::${activeModel.value.model_id}` : '');
const activeModelLabel = computed(() => activeModel.value
  ? `${activeModel.value.provider_name} ${activeModel.value.model_name || activeModel.value.model_id}`
  : `默认 ${modelFallback.value?.model || '环境变量'}`);
const modelOptions = computed(() => modelProviders.value.flatMap(provider => (provider.models || [])
  .map(model => ({ value: `${provider.provider_id}::${model.model_id}`,
    provider: provider.name, model: model.name || model.model_id }))));
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const keys = isMac ? { search: '⌘K', newChat: '⌘⇧O' } : { search: 'Ctrl K', newChat: 'Ctrl Shift O' };
const groupOrder = ['今天', '昨天', '7 天内', '更早'];
const grouping = { sort: (a, b) => groupOrder.indexOf(a) - groupOrder.indexOf(b) };
function groupOf(updatedAt) {
  const time = Date.parse(updatedAt);
  if (Number.isNaN(time)) return '更早';
  const days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(time).setHours(0, 0, 0, 0)) / 86400000);
  return days <= 0 ? '今天' : days === 1 ? '昨天' : days <= 7 ? '7 天内' : '更早';
}
const sessionItems = computed(() => conversations.value.map(item => ({ ...item,
  label: item.title || '未命名对话', disabled: running.value, group: groupOf(item.updated_at),
})));

async function refreshConversations() {
  const generation = ++listGeneration;
  listLoading.value = true;
  listMoreLoading.value = false;
  try {
    const payload = await fetchConversations('', 30, 0);
    if (generation !== listGeneration) return;
    conversations.value = payload.conversations || [];
    total.value = payload.total ?? conversations.value.length;
    const selected = conversations.value.find(item => item.conversation_id === selectedId.value);
    if (selected) selectedTitle.value = selected.title;
  } catch (err) { if (generation === listGeneration) error.value = err.message; }
  finally { if (generation === listGeneration) listLoading.value = false; }
}
async function loadMore() {
  if (listLoading.value || listMoreLoading.value || conversations.value.length >= total.value) return;
  const generation = listGeneration;
  listMoreLoading.value = true;
  try {
    const payload = await fetchConversations('', 30, conversations.value.length);
    if (generation !== listGeneration) return;
    conversations.value = mergeUniqueById(conversations.value, payload.conversations || [], 'conversation_id');
    total.value = payload.total ?? total.value;
  } catch (err) { error.value = err.message; }
  finally { if (generation === listGeneration) listMoreLoading.value = false; }
}
function newChat() {
  if (running.value) return;
  ++historyGeneration;
  view.value = 'chat'; selectedId.value = null; selectedTitle.value = '';
  messages.value = []; intermediate.value = []; error.value = ''; historyLoading.value = false;
  planMode.value = false;
  collapseSidebarOnNarrow();
}
// 窄屏下侧栏常驻会挤压内容区，选中目标后收起。
function collapseSidebarOnNarrow() {
  if (window.innerWidth < 760) collapsed.value = true;
}
async function selectConversation(item) {
  if (running.value) return;
  const id = item.conversation_id;
  const generation = ++historyGeneration;
  view.value = 'chat'; selectedId.value = id; selectedTitle.value = item.title || '';
  messages.value = []; intermediate.value = []; error.value = ''; historyLoading.value = true;
  searchOpen.value = false; planMode.value = false;
  collapseSidebarOnNarrow();
  try {
    let before = null;
    const cursors = new Set();
    let history = [], logs = [], executions = [];
    while (true) {
      const payload = await fetchConversationCursor(id, 50, before);
      if (generation !== historyGeneration) return;
      if (before === null) planMode.value = Boolean(payload.plan_mode);
      history = [...(payload.messages || []), ...history];
      logs = [...(payload.intermediate_messages || []), ...logs];
      executions = [...(payload.tool_executions || []), ...executions];
      if (!payload.has_more) break;
      if (!payload.next_before_id || cursors.has(payload.next_before_id)) throw new Error('历史分页游标无效，请重试');
      before = payload.next_before_id; cursors.add(before);
    }
    messages.value = restoreConversation(history, logs, executions);
    const snapshots = new Map(executions.map(item => [item.call_id, item]));
    intermediate.value = logs.map(log => ({ ...log, metadata: snapshots.get(log.tool_call_id)?.metadata || log.metadata }));
  } catch (err) { if (generation === historyGeneration) error.value = err.message; }
  finally { if (generation === historyGeneration) historyLoading.value = false; }
}
async function removeConversation(command, item) {
  if (command !== 'delete' || running.value) return;
  try {
    await ElMessageBox.confirm('该对话的历史消息会从本地记录中移除。', '删除对话？',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' });
  } catch { return; }
  try {
    await deleteConversation(item.conversation_id);
    if (selectedId.value === item.conversation_id) newChat();
    results.value = results.value.filter(row => row.conversation_id !== item.conversation_id);
    await refreshConversations();
    ElMessage.success('对话已删除');
  } catch (err) { error.value = err.message; }
}
async function titleCommand(command) {
  if (running.value) return;
  const id = selectedId.value, name = selectedTitle.value || '未命名对话';
  if (command === 'delete') return removeConversation('delete', { conversation_id: id });
  if (command === 'export') {
    const body = messages.value.map(message => `## ${message.role === 'user' ? '我' : 'LifeOps'}\n\n${message.content}`);
    return downloadMarkdown(`${name}.md`, [`# ${name}`, ...body].join('\n\n') + '\n');
  }
  let value;
  try {
    ({ value } = await ElMessageBox.prompt('', '重命名对话', { inputValue: name, inputPattern: /\S/,
      inputErrorMessage: '标题不能为空', confirmButtonText: '保存', cancelButtonText: '取消' }));
  } catch { return; }
  try {
    const payload = await renameConversation(id, value.trim());
    if (selectedId.value === id) selectedTitle.value = payload.title;
    await refreshConversations();
  } catch (err) { error.value = err.message; }
}
function openContext(kind) {
  if (kind === 'modal') contextModal.value = true; else contextDrawer.value = true;
}
function chatCommand(name) {
  if (name === 'new') newChat();
  else if (name === 'search') openSearch();
  else titleCommand(name);
}
async function openInsightSession(id) {
  const item = conversations.value.find(row => row.conversation_id === id) || { conversation_id: id };
  await selectConversation(item);
  contextDrawer.value = true;
}
async function chatDone(payload) {
  if (payload?.conversation_id) selectedId.value = payload.conversation_id;
  if (payload?.title) selectedTitle.value = payload.title;
  await refreshConversations();
}
async function loadModelState() {
  try {
    const payload = await fetchModels();
    modelProviders.value = payload.providers || [];
    activeModel.value = payload.active || null;
    modelFallback.value = payload.fallback || null;
    modelReady.value = true;
  } catch {
    // 后端尚未升级或不支持模型接口时隐藏选择器，不打断对话。
    if (!modelReady.value) modelReady.value = false;
  }
}
async function switchModel(command) {
  if (running.value || !command || command === activeModelKey.value) return;
  try {
    if (command === '__env__') {
      await clearActiveModel();
    } else {
      const separator = command.indexOf('::');
      await setActiveModel(command.slice(0, separator), command.slice(separator + 2));
    }
    await loadModelState();
    ElMessage.success(`当前模型：${activeModelLabel.value}`);
  } catch (err) {
    error.value = err.message;
  }
}
async function searchPage(offset = 0, generation = searchGeneration) {
  if (!query.value.trim()) return;
  if (offset && searchLoading.value) return;
  searchLoading.value = true;
  try {
    const payload = await fetchConversations(query.value.trim(), 20, offset);
    if (generation !== searchGeneration) return;
    results.value = offset ? mergeUniqueById(results.value, payload.conversations || [], 'conversation_id')
      : payload.conversations || [];
    searchTotal.value = payload.total ?? results.value.length;
  } catch (err) { if (generation === searchGeneration) searchError.value = err.message; }
  finally { if (generation === searchGeneration) searchLoading.value = false; }
}
watch([query, searchOpen], (_, __, cleanup) => {
  const generation = ++searchGeneration;
  results.value = []; searchTotal.value = 0; searchError.value = ''; searchLoading.value = false;
  if (!searchOpen.value || !query.value.trim()) return;
  const timer = setTimeout(() => searchPage(0, generation), 250);
  cleanup(() => clearTimeout(timer));
});
function openSearch() {
  if (running.value) return;
  searchOpen.value = true; query.value = '';
}
function shortcut(event) {
  if (!(event.ctrlKey || event.metaKey)) return;
  const key = event.key.toLowerCase();
  if (key === 'k' && !event.shiftKey) { event.preventDefault(); openSearch(); }
  else if (key === 'o' && event.shiftKey) { event.preventDefault(); newChat(); }
}
onMounted(() => { refreshConversations(); loadModelState(); window.addEventListener('keydown', shortcut); });
onUnmounted(() => window.removeEventListener('keydown', shortcut));
watch(view, value => { if (value === 'chat') loadModelState(); });
</script>

<template>
  <el-config-provider :locale="zhCn">
    <div class="app-shell" :class="{ collapsed }">
      <aside class="sidebar" aria-label="主导航">
        <div class="brand">
          <img v-if="!collapsed" src="/lifeops_pixel_logo.svg" alt="" />
          <strong v-if="!collapsed">LifeOps</strong>
          <el-button text :icon="collapsed ? Expand : Fold" aria-label="切换侧栏" @click="collapsed = !collapsed" />
        </div>
        <button class="new-chat" :disabled="running" aria-label="新对话" @click="newChat">
          <el-icon><Plus /></el-icon><span v-if="!collapsed">新对话</span><kbd v-if="!collapsed">{{ keys.newChat }}</kbd>
        </button>
        <nav class="navigation">
          <button :disabled="running" :title="collapsed ? '搜索对话' : undefined" aria-label="搜索对话"
            @click="openSearch">
            <el-icon><Search /></el-icon><span v-if="!collapsed">搜索对话</span><kbd v-if="!collapsed">{{ keys.search }}</kbd>
          </button>
          <button v-for="item in nav" :key="item.key" :disabled="running" :aria-label="item.label"
            :class="{ active: view === item.key }" :title="collapsed ? item.label : undefined"
            @click="view = item.key; collapseSidebarOnNarrow()">
            <el-icon><component :is="item.icon" /></el-icon><span v-if="!collapsed">{{ item.label }}</span>
          </button>
        </nav>
        <div v-if="!collapsed" class="sidebar-history" v-loading="listLoading">
          <div v-if="!conversations.length" class="section-label">最近对话</div>
          <Conversations v-if="conversations.length" :groupable="grouping" :active="selectedId || undefined" :items="sessionItems"
            row-key="conversation_id" label-key="label" :label-max-width="175" :show-tooltip="true"
            :menu="[{ key: 'delete', label: '删除对话', disabled: running }]"
            :style="{ width: '100%', height: '100%', padding: '0', backgroundColor: 'transparent' }"
            :load-more="loadMore" :load-more-loading="listMoreLoading"
            :items-style="{ borderRadius: '10px', margin: '3px 8px', padding: '10px 12px' }"
            :items-active-style="{ backgroundColor: '#fff', color: '#0057ff' }"
            :items-hover-style="{ backgroundColor: '#00000009' }"
            @change="selectConversation" @menu-command="removeConversation" />
          <p v-else-if="!listLoading" class="muted empty-history">暂无对话记录</p>
        </div>
        <div class="sidebar-footer" title="本地工作空间"><i class="status-dot" /><span v-if="!collapsed">本地工作空间</span></div>
      </aside>
      <main class="main-layout">
        <header class="app-header">
          <el-dropdown v-if="view === 'chat' && selectedId" trigger="click" :disabled="running" @command="titleCommand">
            <button class="title-trigger" aria-label="对话菜单"><span>{{ title || '未命名对话' }}</span><el-icon><ArrowDown /></el-icon></button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item command="rename" :icon="EditPen">重命名</el-dropdown-item>
              <el-dropdown-item command="export" :icon="Download">导出对话</el-dropdown-item>
              <el-dropdown-item command="delete" :icon="Delete" divided>删除对话</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
          <h1 v-else>{{ title }}</h1>
          <div id="header-actions">
            <el-dropdown v-if="view === 'chat' && modelReady" trigger="click" :disabled="running" @command="switchModel">
              <button class="model-trigger" aria-label="切换当前模型" :disabled="running">
                <el-icon><Cpu /></el-icon>
                <span>{{ activeModel?.provider_name || '默认' }}</span>
                <span class="model-name">{{ activeModel?.model_name || activeModel?.model_id || modelFallback?.model || '环境变量' }}</span>
                <el-icon><ArrowDown /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="__env__" :disabled="!activeModel">
                    环境变量默认 {{ modelFallback?.model || 'LLM_MODEL' }}
                  </el-dropdown-item>
                  <el-dropdown-item v-for="option in modelOptions" :key="option.value" :command="option.value"
                    :disabled="option.value === activeModelKey">{{ option.provider }} {{ option.model }}</el-dropdown-item>
                  <el-dropdown-item v-if="!modelOptions.length" disabled>还没有配置模型提供商</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </header>
        <el-alert v-if="error" :title="error" type="error" show-icon closable @close="error = ''" />
        <div class="content" v-loading="historyLoading">
          <ChatWorkspace v-if="view === 'chat'" v-model:messages="messages" v-model:plan-mode="planMode" :conversation-id="selectedId"
            :intermediate-messages="intermediate" :disabled="historyLoading" @running="running = $event"
            @done="chatDone" @settled-logs="intermediate = $event" @error="error = $event" @context="openContext" @command="chatCommand" />
          <InsightsWorkspace v-else-if="view === 'insights'" @open="openInsightSession" />
          <ModelsWorkspace v-else-if="view === 'models'" />
          <DatabaseWorkspace v-else />
        </div>
      </main>
      <ContextDrawer v-if="contextDrawer" v-model="contextDrawer" :conversation-id="selectedId" :running="running"
        :title="selectedTitle || '未命名对话'" />
      <ContextModal v-if="contextModal" v-model="contextModal" :conversation-id="selectedId" />
      <el-dialog v-model="searchOpen" title="搜索对话标题" width="min(600px, 94vw)" destroy-on-close>
        <el-input v-model="query" placeholder="输入标题关键词" :prefix-icon="Search" clearable aria-label="标题关键词" />
        <el-alert v-if="searchError" :title="searchError" type="error" show-icon />
        <div class="search-results" v-loading="searchLoading">
          <button v-for="item in results" :key="item.conversation_id" class="search-result" @click="selectConversation(item)">
            <strong>{{ item.title || '未命名对话' }}</strong><span>{{ item.last_message }}</span>
          </button>
          <el-empty v-if="!results.length && !searchLoading" :description="query.trim() ? '无匹配标题' : '输入标题关键词后搜索'" />
          <el-button v-if="results.length < searchTotal" :loading="searchLoading" @click="searchPage(results.length)">加载更多</el-button>
        </div>
      </el-dialog>
    </div>
  </el-config-provider>
</template>
