<script setup>
// 照搬 dsh-context components/statsContext.tsx：输入输出 / 事件 → 当前会话 → 工具调用 / Agent 网络 的流向图。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { t } from '../i18n.js';
import { fmt, fmtCost } from '../kit.js';

const FLOW_FOLD_PX = 559;
const TOOL_PILLS_MAX = 4;
const FLOW_LINKS = [
  { from: 'inputs', to: 'session', fromAt: 0.5, toAt: 1 / 3, color: 'var(--color-green-500)' },
  { from: 'events', to: 'session', fromAt: 0.5, toAt: 2 / 3, color: 'var(--color-purple-500)' },
  { from: 'session', to: 'tools', fromAt: 1 / 3, toAt: 0.5, color: 'var(--color-teal-500)' },
  { from: 'session', to: 'cost', fromAt: 2 / 3, toAt: 0.5, color: 'var(--color-pink-500)' },
];
const EVENT_PILLS = [
  { kind: 'inject', cls: 'lc-kind-inject' },
  { kind: 'compaction', cls: 'lc-kind-compaction' },
  { kind: 'prune', cls: 'lc-kind-prune' },
];

const props = defineProps({ data: { type: Object, required: true }, files: { type: Object, required: true } });
const emit = defineEmits(['team']);
const flowRef = ref(null);
const nodes = {};
const links = ref([]);

const counts = computed(() => {
  const requests = props.data.requests || [];
  const events = props.data.events || [];
  const tally = kind => events.filter(e => e.kind === kind).length;
  return {
    turns: new Set(requests.map(r => r.turn)).size,
    steps: requests.length,
    inject: tally('inject'),
    compaction: tally('compaction'),
    prune: tally('prune'),
    skills: new Set(events.filter(e => e.kind === 'inject' && e.sub === 'skill').map(e => e.name)).size,
  };
});
const tools = computed(() => Object.entries(props.data.timing?.tools || {})
  .map(([name, v]) => [name, v.calls]).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)));
const toolTotal = computed(() => tools.value.reduce((sum, [, n]) => sum + n, 0));
const ioTotal = computed(() => (props.data.humanInputs || 0) + props.files.reads + props.files.writes + props.files.searches);
const billed = usage => (usage ? usage.uncachedInputTokens + usage.cacheReadTokens + usage.cacheWriteTokens + usage.outputTokens : 0);
const family = computed(() => billed(props.data.familyUsage));
const own = computed(() => billed(props.data.usage));
const subCount = computed(() => Math.max(0, (props.data.agents || 1) - 1));
const subCost = computed(() => (props.data.familyCost === null || props.data.familyCost === undefined
  ? null : props.data.familyCost - (props.data.cost || 0)));
const prices = computed(() => props.data.prices);

function anchor(box, side, at) {
  if (side === 'left') return { x: box.x, y: box.y + box.h * at, dx: -1, dy: 0 };
  if (side === 'right') return { x: box.x + box.w, y: box.y + box.h * at, dx: 1, dy: 0 };
  if (side === 'top') return { x: box.x + box.w * at, y: box.y, dx: 0, dy: -1 };
  return { x: box.x + box.w * at, y: box.y + box.h, dx: 0, dy: 1 };
}
function curve(a, b) {
  const k = Math.max(18, (a.dx !== 0 ? Math.abs(b.x - a.x) : Math.abs(b.y - a.y)) / 2);
  return `M ${a.x} ${a.y} C ${a.x + a.dx * k} ${a.y + a.dy * k} ${b.x + b.dx * k} ${b.y + b.dy * k} ${b.x} ${b.y}`;
}
function measure() {
  const root = flowRef.value;
  if (!root) return;
  const rootBox = root.getBoundingClientRect();
  const boxes = {};
  for (const key of ['inputs', 'events', 'session', 'tools', 'cost']) {
    const el = nodes[key];
    if (!el) return;
    const r = el.getBoundingClientRect();
    boxes[key] = { x: r.left - rootBox.left, y: r.top - rootBox.top, w: r.width, h: r.height };
  }
  const horizontal = root.clientWidth > FLOW_FOLD_PX;
  links.value = FLOW_LINKS.map(link => ({
    d: curve(anchor(boxes[link.from], horizontal ? 'right' : 'bottom', link.fromAt),
      anchor(boxes[link.to], horizontal ? 'left' : 'top', link.toAt)),
    color: link.color,
  }));
}
let observer;
onMounted(() => {
  nextTick(measure);
  if (typeof ResizeObserver === 'function') {
    observer = new ResizeObserver(measure);
    observer.observe(flowRef.value);
  }
});
onBeforeUnmount(() => observer?.disconnect());
watch(() => [props.data, props.files], () => nextTick(measure));
</script>

<template>
  <div class="lc-card flex-[3] min-w-[min(360px,100%)]">
    <div class="lc-card-title"><span class="lc-card-title-text">{{ t('stats.title') }}</span></div>
    <div ref="flowRef" class="lc-stats lc-flow">
      <svg class="lc-flow-svg" aria-hidden="true">
        <g v-for="(l, i) in links" :key="i">
          <path class="lc-flow-ribbon" :d="l.d" :stroke="l.color" />
          <path class="lc-flow-dash animate-lc-agent-flow motion-reduce:animate-none" :d="l.d" :stroke="l.color" />
        </g>
      </svg>
      <div class="lc-flow-col">
        <div :ref="el => (nodes.inputs = el)" class="lc-flow-node">
          <div class="lc-flow-head"><span class="lc-flow-label">{{ t('stats.io') }}</span><b class="lc-flow-total">{{ fmt(ioTotal) }}</b></div>
          <div class="lc-flow-pills">
            <span class="lc-flow-pill lc-stat-tipped group/tip" :class="{ 'lc-flow-pill-dim': !data.humanInputs }">
              <span class="lc-flow-pill-label">{{ t('stats.humanInputs') }}<i class="lc-stat-q" aria-hidden="true">?</i></span>
              <b>{{ fmt(data.humanInputs || 0) }}</b>
              <span class="lc-tip lc-stat-tip group-hover/tip:opacity-100" role="tooltip">{{ t('stats.humanInputsTip') }}</span>
            </span>
            <span class="lc-flow-pill" :class="{ 'lc-flow-pill-dim': !files.reads }">
              <span class="lc-flow-pill-label">{{ t('files.kind.read') }}</span><b>{{ fmt(files.reads) }}</b>
            </span>
            <span class="lc-flow-pill" :class="{ 'lc-flow-pill-dim': !files.writes }">
              <span class="lc-flow-pill-label">{{ t('files.kind.write') }}</span><b>{{ fmt(files.writes) }}</b>
            </span>
            <span v-if="files.searches" class="lc-flow-pill">
              <span class="lc-flow-pill-label">{{ t('files.kind.search') }}</span><b>{{ fmt(files.searches) }}</b>
            </span>
          </div>
        </div>
        <div :ref="el => (nodes.events = el)" class="lc-flow-node">
          <div class="lc-flow-head">
            <span class="lc-flow-label">{{ t('stats.events') }}</span>
            <b class="lc-flow-total">{{ fmt(counts.inject + counts.compaction + counts.prune) }}</b>
          </div>
          <div class="lc-flow-pills">
            <span v-for="p in EVENT_PILLS" :key="p.kind" class="lc-flow-pill lc-flow-pill-tint" :class="[p.cls, { 'lc-flow-pill-dim': !counts[p.kind] }]">
              <span class="lc-flow-pill-label">{{ t('kind.' + p.kind) }}</span><b>{{ fmt(counts[p.kind]) }}</b>
            </span>
          </div>
        </div>
      </div>
      <div class="lc-flow-mid">
        <div :ref="el => (nodes.session = el)" class="lc-flow-node lc-flow-self">
          <span class="lc-flow-label">{{ t('stats.session') }}</span>
          <span class="lc-flow-self-stats">
            <span class="lc-flow-kv"><b>{{ fmt(counts.turns) }}</b><i>{{ t('stats.turns') }}</i></span>
            <span class="lc-flow-kv"><b>{{ fmt(counts.steps) }}</b><i>{{ t('stats.steps') }}</i></span>
          </span>
          <span class="lc-flow-self-stats">
            <span class="lc-flow-kv"><b>{{ fmt(counts.skills) }}</b><i>{{ t('stats.skills') }}</i></span>
            <span class="lc-flow-kv"><b>{{ fmt(data.answers || 0) }}</b><i>{{ t('stats.answers') }}</i></span>
          </span>
        </div>
      </div>
      <div class="lc-flow-col lc-flow-col-r">
        <div :ref="el => (nodes.tools = el)" class="lc-flow-node">
          <div class="lc-flow-head"><span class="lc-flow-label">{{ t('stats.toolCalls') }}</span><b class="lc-flow-total">{{ fmt(toolTotal) }}</b></div>
          <div class="lc-flow-pills lc-flow-pills-tools">
            <span v-for="[name, n] in tools.slice(0, TOOL_PILLS_MAX)" :key="name" class="lc-flow-pill" :title="name">
              <span class="lc-flow-pill-label">{{ name }}</span><b>{{ fmt(n) }}</b>
            </span>
            <span class="lc-flow-pill lc-flow-pill-dim">
              <span class="lc-flow-pill-label">{{ t('stats.toolsMore', { n: Math.max(0, tools.length - TOOL_PILLS_MAX) }) }}</span>
            </span>
          </div>
        </div>
        <div :ref="el => (nodes.cost = el)" class="lc-flow-node lc-flow-team" role="button" tabindex="0"
          @click="emit('team')" @keydown.enter.prevent="emit('team')">
          <div class="lc-flow-head lc-stat-tipped group/tip">
            <span class="lc-flow-label">{{ t('agents.title') }}<i class="lc-stat-q" aria-hidden="true">?</i></span>
            <b class="lc-flow-total"><span class="lc-flow-pair"><b>{{ fmt(family) }}</b><i>/</i><b>{{ fmtCost(data.familyCost) }}</b></span></b>
            <span class="lc-tip lc-stat-tip group-hover/tip:opacity-100" role="tooltip">
              {{ prices ? t('stats.costTip') : t('stats.costUnset') }}
              <span class="lc-stat-tip-row">{{ t('stats.billedTip') }}</span>
              <span v-if="prices" class="lc-stat-tip-row">
                {{ t('stats.costPriceHead') }}{{ t('stats.costMiss') }} ¥{{ prices.input }}，{{ t('stats.costHit') }} ¥{{ prices.cache ?? prices.input }}，{{ t('stats.costOut') }} ¥{{ prices.output ?? prices.input }}
              </span>
            </span>
          </div>
          <div class="lc-flow-rows">
            <div class="lc-flow-row">
              <span class="lc-flow-row-label">{{ t('stats.currentAgent') }}</span>
              <span class="lc-flow-pair"><b>{{ fmt(own) }}</b><i>/</i><b>{{ fmtCost(data.cost) }}</b></span>
            </div>
            <div class="lc-flow-row">
              <span class="lc-flow-row-label">{{ t('stats.teamSubs', { n: subCount }) }}</span>
              <span class="lc-flow-pair"><b>{{ fmt(family - own) }}</b><i>/</i><b>{{ fmtCost(subCost) }}</b></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
