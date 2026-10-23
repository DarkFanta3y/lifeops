<script setup>
import { computed, ref } from 'vue';
import { Document, EditPen, Monitor, Search, Connection, List, MagicStick, UserFilled, Tools, ArrowRight, ArrowDown } from '@element-plus/icons-vue';
import { toolPresentation, print } from './toolPresentation.js';
const props = defineProps({ part: { type: Object, required: true } });
const model = computed(() => toolPresentation(props.part));
const icons = { read: Document, diff: EditPen, terminal: Monitor, search: Search, web: Connection,
  knowledge: Search, todo: List, skill: MagicStick, agent: UserFilled, generic: Tools };
const emit = defineEmits(['layout']);
function changeLayout(change) { emit('layout', change); }
const expanded = ref(false), all = ref(false), rawOpen = ref(false), copied = ref('');
const body = computed(() => model.value.diff || model.value.output || '');
const lines = computed(() => body.value.split('\n'));
const visibleLines = computed(() => all.value ? lines.value : lines.value.slice(0, model.value.previewLines));
async function copy(value, label) {
  try { await navigator.clipboard.writeText(print(value)); copied.value = label; }
  catch { copied.value = '复制失败'; }
}
</script>
<template>
  <div class="activity-tool" :data-state="model.state" data-slot="lifeops-tool-row" data-reading-anchor>
    <button type="button" class="activity-tool-summary" :aria-expanded="expanded" :disabled="model.state === 'preparing'"
      :title="`${model.title}，${model.summary}，${model.statusText}`" @click="changeLayout(() => { expanded = !expanded; })">
      <el-icon class="activity-tool-icon"><component :is="icons[model.kind] || Tools" /></el-icon>
      <span class="activity-tool-title">{{ model.title }}</span>
      <span class="activity-tool-target">{{ model.summary }}</span>
      <span v-if="model.suffix" class="activity-suffix">{{ model.suffix }}</span>
      <span v-if="model.counts && !part.isError" class="activity-diff-totals"><b>+{{ model.counts.added }}</b> <i>−{{ model.counts.removed }}</i></span>
      <span class="activity-state">{{ model.statusText }}</span>
      <el-icon v-if="model.state !== 'preparing'" class="activity-chevron"><ArrowDown v-if="expanded" /><ArrowRight v-else /></el-icon>
    </button>
    <div v-if="expanded" class="activity-tool-body">
      <div v-if="model.workdir || model.taskId || model.exitCode !== undefined" class="activity-facts">
        <span v-if="model.workdir">目录：{{ model.workdir }}</span><span v-if="model.taskId">任务：{{ model.taskId }}</span>
        <span v-if="model.exitCode !== undefined">退出码：{{ model.exitCode }}</span>
      </div>
      <div v-if="part.approval?.decision" class="activity-receipt">授权结果：{{ part.approval.timed_out ? '等待超时，未执行' : { allow_once: '允许一次', allow_always: '总是允许', deny: '已拒绝' }[part.approval.decision] || part.approval.decision }}</div>
      <template v-if="model.kind === 'terminal' && part.args?.command">
        <div class="activity-section-head"><span>命令</span><button type="button" @click="copy(part.args.command, '命令')">复制命令</button></div>
        <pre class="activity-code">{{ part.args.command }}</pre>
      </template>
      <ul v-if="model.todos" class="activity-todos" data-slot="lifeops-todo-card">
        <li v-for="(todo, index) in model.todos" :key="index" :class="{ completed: todo.status === 'completed' }">
          <span>{{ todo.status === 'completed' ? '✓' : todo.status === 'in_progress' ? '◷' : '○' }}</span>{{ todo.content }}</li>
      </ul>
      <ul v-else-if="model.sourceLinks.length" class="activity-links"><li v-for="(item, i) in model.sourceLinks" :key="i">
        <a :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }}</a><p v-if="item.snippet">{{ item.snippet }}</p></li></ul>
      <template v-else-if="model.output !== null || model.diff">
        <div class="activity-section-head"><span>{{ model.diff ? '文件变更' : '结果' }}</span><button type="button" @click="copy(body, '结果')">复制结果</button></div>
        <pre class="activity-code" :class="{ 'activity-terminal': model.kind === 'terminal' }"><code v-for="(line, index) in visibleLines" :key="index" :class="{ added: model.diff && line.startsWith('+'), removed: model.diff && line.startsWith('-') }">{{ line || ' ' }}{{ '\n' }}</code></pre>
        <button v-if="lines.length > model.previewLines" type="button" class="activity-expand" @click="changeLayout(() => { all = !all; })">{{ all ? '收起长结果' : `展开剩余 ${lines.length - model.previewLines} 行` }}</button>
      </template>
      <p v-if="model.error && model.error !== model.output" class="activity-error">{{ model.error }}</p>
      <p v-if="model.state === 'incomplete'" class="activity-facts">这条历史调用没有完整的结果记录。</p>
      <div class="activity-raw"><button type="button" class="activity-expand" :aria-expanded="rawOpen" @click="changeLayout(() => { rawOpen = !rawOpen; })">{{ rawOpen ? '收起原始记录' : '原始参数与结果' }}</button><template v-if="rawOpen">
        <div class="activity-section-head"><span>参数</span><button type="button" @click="copy(part.args, '参数')">复制参数</button></div><pre>{{ print(part.args) }}</pre>
        <template v-if="model.output !== null"><div class="activity-section-head"><span>原始结果</span><button type="button" @click="copy(part.rawOutput ?? part.result, '原始结果')">复制原始结果</button></div><pre>{{ print(part.rawOutput ?? part.result) }}</pre></template>
        <template v-if="part.metadata"><div class="activity-section-head">结果元数据</div><pre>{{ print(part.metadata) }}</pre></template>
      </template></div>
      <span v-if="part.durationMs !== undefined" class="activity-facts">调用耗时 {{ (part.durationMs / 1000).toFixed(2) }} 秒</span>
      <span class="activity-copy-status" role="status">{{ copied ? `${copied}${copied === '复制失败' ? '' : '已复制'}` : '' }}</span>
    </div>
  </div>
</template>
