<script setup>
// 照搬 dsh-context fleetView.tsx / agentGraph.tsx / memberBoard.tsx / taskBoard.tsx：
// 汇总条 + Agent 网络图 + 编队成员卡片 + 任务计划（LifeOps 用 todo_write 计划代替团队任务）。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { fetchContextFleet } from '../../api.js';
import '../styles/index.js';
import { t } from '../i18n.js';
import { CATS, catLabel, fmt, fmtCost } from '../kit.js';
import { barSegments, familyHue, fmtDurationCompact, forestOf, layoutForest, lineageOf, pressureColorOf } from '../agentTree.js';

const STAGGER_CAP = 8;
const POLL_MS = 2000;
const TASK_GROUPS = ['in_progress', 'pending', 'completed'];
const props = defineProps({ conversationId: { type: String, required: true }, running: Boolean });
const fleet = ref(null);
const error = ref('');
const hoverId = ref(null);
const pinnedId = ref(null);
const expanded = ref(new Set());
const stageRef = ref(null);
const stageWidth = ref(0);
let timer;
let observer;

async function refresh() {
  try { fleet.value = await fetchContextFleet(props.conversationId); error.value = ''; } catch (err) { error.value = err.message; }
}
watch(() => props.conversationId, () => { fleet.value = null; refresh(); }, { immediate: true });
watch(() => props.running, (running) => {
  clearInterval(timer);
  if (running) timer = setInterval(refresh, POLL_MS); else refresh();
}, { immediate: true });
onMounted(() => {
  if (typeof ResizeObserver !== 'function') return;
  observer = new ResizeObserver(([entry]) => { stageWidth.value = entry.contentRect.width; });
  watch(stageRef, (el) => { if (el) observer.observe(el); }, { immediate: true });
});
onBeforeUnmount(() => { clearInterval(timer); observer?.disconnect(); });

const forest = computed(() => (fleet.value ? forestOf(fleet.value) : null));
const layout = computed(() => (forest.value ? layoutForest(forest.value, stageWidth.value) : null));
const lit = computed(() => (forest.value ? lineageOf(forest.value, hoverId.value ?? pinnedId.value) : null));
const subs = computed(() => forest.value?.nodes.filter(n => !n.isCurrent) || []);
const runningCount = computed(() => forest.value?.nodes.filter(n => n.running).length || 0);
const totalTokens = computed(() => forest.value?.nodes.reduce((sum, n) => sum + (n.head?.tokens || 0), 0) || 0);
const familyCost = computed(() => {
  const costs = forest.value?.nodes.map(n => n.cost).filter(c => c !== null && c !== undefined) || [];
  return costs.length ? costs.reduce((a, b) => a + b, 0) : null;
});
const todos = computed(() => fleet.value?.todos || []);
const todoDone = computed(() => todos.value.filter(todo => todo.status === 'completed').length);
const subsDone = computed(() => subs.value.filter(n => n.completed).length);

function linkPath(x1, y1, x2, y2) {
  const k = Math.min(96, Math.max(24, (y2 - y1) * 0.5));
  return `M ${x1} ${y1} C ${x1} ${y1 + k}, ${x2} ${y2 - k}, ${x2} ${y2}`;
}
function pointOf(id) { return layout.value.points.find(p => p.id === id); }
function segsOf(node) { return node.head ? barSegments(node.head.parts, node.head.pct, pressureColorOf(node.head.pct)).filter(s => !s.free) : []; }
function metaOf(node) {
  const bits = [];
  if (node.durationMs !== null && node.durationMs !== undefined) bits.push(fmtDurationCompact(node.durationMs));
  if (node.requests > 0) bits.push(t('agents.steps', { n: node.requests }));
  return bits.join(' · ');
}
function metricOf(node) {
  const bits = [];
  if (node.billed > 0) bits.push(fmt(node.billed));
  if (node.cost !== null && node.cost !== undefined) bits.push(fmtCost(node.cost));
  return bits.join(' · ') || '—';
}
function pin(id) { pinnedId.value = pinnedId.value === id ? null : id; }
function toggleExpand(id) {
  const next = new Set(expanded.value);
  if (next.has(id)) next.delete(id); else next.add(id);
  expanded.value = next;
}
</script>

<template>
  <div class="lc-root">
    <div v-if="error && !fleet" class="lc-error">
      <span class="lc-error-msg">{{ t('error') }}{{ error }}</span>
      <button type="button" class="lc-error-retry" @click="refresh">{{ t('error.retry') }}</button>
    </div>
    <div v-else-if="!forest" class="lc-empty">{{ t('loading') }}</div>
    <template v-else>
      <div class="lc-card lc-summary">
        <div class="lc-summary-chips">
          <span class="lc-agents-chip">{{ t('agents.chip.count', { n: forest.nodes.length }) }}</span>
          <span class="lc-agents-chip" :class="{ 'lc-agents-chip-on': runningCount > 0 }">{{ t('agents.chip.running', { n: runningCount }) }}</span>
          <span v-if="subs.length" class="lc-agents-chip">{{ t('fleet.summary.done', { n: subsDone }) }}</span>
          <span v-if="totalTokens" class="lc-agents-chip">{{ t('agents.chip.tokens', { n: fmt(totalTokens) }) }}</span>
          <span v-if="familyCost !== null" class="lc-agents-chip">{{ t('fleet.summary.cost', { n: fmtCost(familyCost) }) }}</span>
        </div>
        <div v-if="todos.length" class="lc-summary-progress">
          <span class="lc-summary-progress-label">{{ t('fleet.tasks.title') }}</span>
          <span class="lc-tasks-progress-track"><i :style="{ width: `${todoDone / todos.length * 100}%` }" /></span>
          <span class="lc-summary-progress-n">{{ todoDone }}/{{ todos.length }}</span>
        </div>
      </div>
      <div class="lc-cols">
        <div class="lc-col lc-col-graph flex-1 min-w-[min(420px,100%)]">
          <div class="lc-card lc-agents">
            <div class="lc-card-title">
              <span class="lc-card-title-text">{{ t('agents.title') }}</span>
              <span class="lc-card-sub">{{ t('agents.sub') }}</span>
            </div>
            <div class="lc-agents-legend">
              <span v-for="c in CATS" :key="c.key" class="lc-agents-legend-item"><i :style="{ background: c.color }" />{{ catLabel(c.key) }}</span>
              <span class="lc-agents-legend-item"><i class="lc-agents-legend-free" />{{ t('agents.legend.free') }}</span>
              <span class="lc-agents-legend-item"><i class="lc-agents-legend-edge" />{{ t('agents.running') }}</span>
            </div>
            <div class="lc-agents-split">
              <div class="lc-agents-main">
                <div ref="stageRef" class="lc-agents-stage">
                  <div class="lc-agents-canvas" :class="{ 'lc-agents-focus': lit }"
                    :style="{ width: `${layout.width}px`, height: `${layout.height}px` }">
                    <svg class="lc-agents-links" :width="layout.width" :height="layout.height" :viewBox="`0 0 ${layout.width} ${layout.height}`">
                      <g v-for="link in layout.links" :key="link.to" :class="{ 'lc-agents-on': lit && lit.has(link.to) }">
                        <path class="lc-agents-link stroke-[1.5px]" :class="{ 'lc-agents-link-live': link.running }"
                          :d="linkPath(link.x1, link.y1, link.x2, link.y2)" :stroke="link.color" fill="none" />
                        <path v-if="link.running" class="lc-agents-flow animate-lc-agent-flow fill-none stroke-2"
                          :d="linkPath(link.x1, link.y1, link.x2, link.y2)" :stroke="link.color" />
                        <circle class="lc-agents-joint" :cx="link.x1" :cy="link.y1" r="2" :fill="link.color" />
                        <circle class="lc-agents-joint" :cx="link.x2" :cy="link.y2" r="3" :fill="link.color" />
                      </g>
                    </svg>
                    <template v-for="(node, index) in forest.nodes" :key="node.id">
                      <div v-if="pointOf(node.id)" class="lc-agent-card animate-lc-agent-in motion-reduce:animate-none lc-agent-clickable"
                        :class="{ 'lc-agent-self': node.isCurrent, 'lc-agent-hover': hoverId === node.id,
                          'lc-agent-on': lit && lit.has(node.id), 'lc-agent-pinned': pinnedId === node.id }"
                        :style="{ left: `${pointOf(node.id).x - layout.cardW / 2}px`, top: `${pointOf(node.id).y}px`,
                          width: `${layout.cardW}px`, '--lc-i': Math.min(index, STAGGER_CAP) }"
                        :data-agent="node.id" role="button" tabindex="0" @click="pin(node.id)"
                        @mouseenter="hoverId = node.id" @mouseleave="hoverId = null">
                        <div class="lc-agent-card-head">
                          <span v-if="node.running || node.completed" class="lc-agent-state lc-state-dot"
                            :class="node.running ? 'lc-state-ongoing' : 'lc-state-done'" />
                          <div class="lc-agent-label">{{ node.label }}</div>
                          <span v-if="node.isCurrent" class="lc-agents-badge lc-agent-self-badge">{{ t('agents.self') }}</span>
                        </div>
                        <div class="lc-agent-metric"><span class="lc-agent-tokens">{{ metricOf(node) }}</span></div>
                        <div class="lc-agent-bar">
                          <i v-for="(seg, i) in segsOf(node)" :key="seg.key" class="lc-agent-bar-seg animate-lc-stacked-in motion-reduce:animate-none"
                            :style="{ width: `${seg.share * 100}%`, background: seg.color, '--lc-i': Math.min(i, STAGGER_CAP) }" />
                        </div>
                        <div v-if="metaOf(node) || node.head?.pct != null" class="lc-agent-meta">
                          <span class="lc-agent-meta-text">{{ metaOf(node) }}</span>
                          <span v-if="node.head?.pct != null" class="lc-agent-pct" :style="{ color: pressureColorOf(node.head.pct) }">{{ node.head.pct }}%</span>
                        </div>
                      </div>
                    </template>
                  </div>
                </div>
                <div v-if="forest.solo" class="lc-empty lc-agents-solo">{{ t('agents.solo') }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="lc-col flex-1 min-w-[min(360px,100%)]">
          <div class="lc-card lc-members">
            <div class="lc-card-title"><span class="lc-card-title-text">{{ t('fleet.board.title') }}</span></div>
            <div v-if="!subs.length" class="lc-empty">{{ t('fleet.board.solo') }}</div>
            <div v-else class="lc-members-grid">
              <div v-for="node in subs" :key="node.id" class="lc-member-card"
                :class="{ 'lc-member-pinned': pinnedId === node.id, 'lc-member-hover': hoverId === node.id }"
                :style="{ '--lc-member-hue': familyHue(node.family) }" role="button" tabindex="0"
                @click="pin(node.id)" @mouseenter="hoverId = node.id" @mouseleave="hoverId = null">
                <div class="lc-member-head">
                  <span class="lc-member-icon">◎</span>
                  <b class="lc-member-name lc-member-name-wrap" :title="node.label">{{ node.label }}</b>
                  <span class="lc-member-dot lc-state-dot" :class="node.running ? 'lc-state-ongoing' : node.completed ? 'lc-state-done' : ''" />
                </div>
                <div class="lc-member-status">
                  {{ node.running ? t('agents.running') : node.completed ? t('fleet.task.completed') : '—' }}
                  <span v-if="node.model" class="lc-member-model">{{ node.model }}</span>
                </div>
                <div v-if="node.agent.prompt" class="lc-member-desc" :title="node.agent.prompt">
                  {{ t('fleet.prompt') }}：{{ expanded.has(node.id) ? node.agent.prompt : node.agent.prompt.slice(0, 120) }}
                </div>
                <div v-if="node.agent.output" class="lc-member-reply" :title="node.agent.output">
                  {{ t('fleet.reply') }}：{{ expanded.has(node.id) ? node.agent.output : node.agent.output.slice(0, 120) }}
                </div>
                <div v-if="metaOf(node)" class="lc-member-meta"><span class="lc-member-meta-text">{{ metaOf(node) }}</span></div>
                <div class="lc-member-foot">
                  <span class="lc-member-tasks-none">{{ t('fleet.tools') }}：{{ (node.agent.tools || []).join('、') || '—' }}</span>
                  <button v-if="(node.agent.prompt || '').length > 120 || (node.agent.output || '').length > 120" type="button"
                    class="lc-member-tasks" @click.stop="toggleExpand(node.id)">
                    {{ expanded.has(node.id) ? t('fleet.collapse') : t('fleet.expand') }}
                  </button>
                </div>
              </div>
            </div>
          </div>
          <div class="lc-card lc-tasks flex-1 min-w-[min(360px,100%)]">
            <div class="lc-card-title">
              <span class="lc-card-title-text">{{ t('fleet.tasks.title') }}</span>
              <span class="lc-card-sub">{{ t('fleet.tasks.sub') }}</span>
            </div>
            <div v-if="!todos.length" class="lc-empty">{{ t('fleet.tasks.noTeam') }}</div>
            <template v-else>
              <template v-for="status in TASK_GROUPS" :key="status">
                <div v-if="todos.some(todo => todo.status === status)" :class="`lc-tasks-group lc-tasks-group-${status}`">
                  <div class="lc-tasks-group-head">
                    {{ t('fleet.task.' + status) }}
                    <span class="lc-kind-n">{{ todos.filter(todo => todo.status === status).length }}</span>
                  </div>
                  <ul class="lc-tasks-rows">
                    <li v-for="(todo, i) in todos.filter(item => item.status === status)" :key="i" class="lc-team-task">
                      <div class="lc-team-task-head">
                        <b class="lc-team-task-subject">{{ todo.content }}</b>
                        <span class="lc-agents-badge">{{ t('fleet.task.' + status) }}</span>
                      </div>
                    </li>
                  </ul>
                </div>
              </template>
            </template>
          </div>
        </div>
      </div>
      <div class="lc-foot">{{ t('footer') }}</div>
    </template>
  </div>
</template>
