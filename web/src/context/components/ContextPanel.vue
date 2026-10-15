<script setup>
// 照搬 dsh-context components/contextView.tsx：统计卡 → 当前构成 + 趋势 + 浏览器 → 事件 + 文件活动。
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { fetchContextFiles, fetchContextHead } from '../../api.js';
import '../styles/index.js';
import { t } from '../i18n.js';
import { fmt, headlineOf } from '../kit.js';
import { aggregateByTurn, attachMarkers, turnStepsOf } from '../trend.js';
import { aggregateOps } from '../fileActivity.js';
import ContextBrowser from './ContextBrowser.vue';
import CurrentComposition from './CurrentComposition.vue';
import EventList from './EventList.vue';
import FileCard from './FileCard.vue';
import RequestDetail from './RequestDetail.vue';
import StatsContext from './StatsContext.vue';
import StatsTiming from './StatsTiming.vue';
import StatsTokens from './StatsTokens.vue';
import TrendChart from './TrendChart.vue';
import TrendOverview from './TrendOverview.vue';

const EVENT_KINDS = ['inject', 'compaction', 'prune', 'model', 'mode'];
const POLL_MS = 2000;
const props = defineProps({ conversationId: { type: String, required: true }, running: Boolean });
const emit = defineEmits(['team']);

const data = ref(null);
const files = ref({ root: '', ops: [] });
const error = ref('');
const selectedSeq = ref(null);
const hoveredSeq = ref(null);
const hoverTurn = ref(null);
const granularity = ref('step');
const trendMode = ref('total');
const adaptive = ref(false);
const overview = ref(false);
const durationCurve = ref(true);
const focusTurn = ref(null);
const hoverCat = ref(null);
const focusCat = ref(null);
const pickedKinds = ref([...EVENT_KINDS]);
const browserFocus = ref(null);
let generation = 0;
let timer;

async function refresh() {
  const current = generation;
  const id = props.conversationId;
  try {
    const [head, ops] = await Promise.all([fetchContextHead(id), fetchContextFiles(id)]);
    if (current !== generation) return;
    data.value = head;
    files.value = ops;
    error.value = '';
  } catch (err) {
    if (current === generation) error.value = err.message;
  }
}
watch(() => props.conversationId, () => {
  generation++;
  data.value = null;
  selectedSeq.value = null;
  hoveredSeq.value = null;
  refresh();
}, { immediate: true });
watch(() => props.running, (running) => {
  clearInterval(timer);
  if (running) timer = setInterval(refresh, POLL_MS);
  else refresh();
}, { immediate: true });
onBeforeUnmount(() => clearInterval(timer));
defineExpose({ refresh });

const requests = computed(() => data.value?.requests || []);
const displayRequests = computed(() => (granularity.value === 'turn' ? aggregateByTurn(requests.value) : requests.value));
const markers = computed(() => attachMarkers(displayRequests.value, data.value?.events || []));
const stepsOf = computed(() => turnStepsOf(requests.value));
const pinnedReq = computed(() => displayRequests.value.find(r => r.seq === selectedSeq.value) || null);
const activeReq = computed(() => {
  const hovered = displayRequests.value.find(r => r.seq === hoveredSeq.value);
  return hovered || pinnedReq.value || displayRequests.value[displayRequests.value.length - 1] || null;
});
const activeIdx = computed(() => displayRequests.value.indexOf(activeReq.value));
const activeTurn = computed(() => {
  if (hoverTurn.value !== null) return hoverTurn.value;
  const hovered = displayRequests.value.find(r => r.seq === hoveredSeq.value);
  return hovered ? hovered.turn ?? null : null;
});
const head = computed(() => (data.value ? headlineOf(data.value) : null));
const cacheHit = computed(() => {
  const usage = data.value?.usage;
  const billed = usage ? usage.uncachedInputTokens + usage.cacheReadTokens : 0;
  return billed > 0 ? `${(usage.cacheReadTokens / billed * 100).toFixed(1)}%` : '—';
});
const trendHoverCat = computed(() => (hoverCat.value && hoverCat.value !== 'free' ? hoverCat.value : null));
const kindCounts = computed(() => {
  const counts = {};
  for (const ev of data.value?.events || []) counts[ev.kind] = (counts[ev.kind] || 0) + 1;
  return counts;
});
const shownEvents = computed(() => (data.value?.events || []).filter(ev => pickedKinds.value.includes(ev.kind)));
const fileSummary = computed(() => {
  const totals = aggregateOps(files.value.ops).totals;
  return { reads: totals.read.ops, writes: totals.write.ops, searches: totals.search.ops };
});
const fileBefore = computed(() => (hoveredSeq.value !== null || selectedSeq.value !== null) && activeReq.value ? activeReq.value.time : null);
const fileScope = computed(() => {
  if (fileBefore.value === null) return t('files.scopeLatest');
  const req = activeReq.value;
  return (req.stepCount ?? 1) > 1 ? t('detail.turn', { t: req.turn ?? 0, n: req.stepCount })
    : t('detail.step', { t: req.turn ?? 0, s: req.step ?? 0, n: stepsOf.value(req.turn) });
});

function toggleKind(kind) {
  pickedKinds.value = pickedKinds.value.includes(kind) ? pickedKinds.value.filter(k => k !== kind) : [...pickedKinds.value, kind];
}
function toggleOverview() {
  overview.value = !overview.value;
  if (overview.value) adaptive.value = false;
}
function toggleAdaptive() {
  adaptive.value = !adaptive.value;
  if (adaptive.value) overview.value = false;
}
function pickTurn(turn) {
  granularity.value = 'turn';
  if (overview.value) {
    const last = requests.value.filter(r => (r.turn ?? 0) === turn).pop();
    if (last) selectedSeq.value = last.seq;
  } else {
    focusTurn.value = turn;
  }
}
function locateBrief({ seq, cat, isResponse }) {
  if (isResponse) {
    const index = requests.value.findIndex(r => r.seq === seq);
    const next = requests.value[index + 1];
    if (next) browserFocus.value = { seq: next.seq, cat: 'assistant' };
    return;
  }
  browserFocus.value = { seq, cat };
}
function focusInject(ev) {
  const req = requests.value.find(r => r.turn === ev.turn && r.step === ev.step);
  if (req) browserFocus.value = { seq: req.seq, cat: ev.sub === 'skill' ? 'skill' : 'inject', name: ev.sub === 'skill' ? 'skill:' + ev.name : undefined };
}
function locateFile(op) { browserFocus.value = { seq: op.snapshot, cat: 'tool', call: op.callId }; }
</script>

<template>
  <div class="lc-root">
    <div v-if="error && !data" class="lc-error">
      <span class="lc-error-msg">{{ t('error') }}{{ error }}</span>
      <button type="button" class="lc-error-retry" @click="refresh">{{ t('error.retry') }}</button>
    </div>
    <div v-else-if="!data" class="lc-empty">{{ t('loading') }}</div>
    <template v-else>
      <div v-if="!data.hasSnapshots" class="lc-card"><div class="lc-empty">{{ t('nosnap') }}</div></div>
      <div class="lc-cols lc-head">
        <StatsContext :data="data" :files="fileSummary" @team="emit('team')" />
        <div class="lc-card flex-1 min-w-[min(240px,100%)]">
          <div class="lc-card-title"><span class="lc-card-title-text">{{ t('stats.info') }}</span></div>
          <div class="lc-info">
            <div class="lc-info-row"><span>{{ t('stats.model') }}</span><b :title="data.model">{{ data.model || '—' }}</b></div>
            <div class="lc-info-row"><span>{{ t('stats.window') }}</span><b>{{ fmt(data.contextWindow) }}</b></div>
            <div class="lc-info-row"><span>{{ t('overview.reserveHeadroom') }}</span>
              <b>{{ data.reserveRatio !== null ? Math.round(data.reserveRatio * 100) + '%' : '—' }}</b></div>
            <div class="lc-info-row"><span>{{ t('stats.steps') }}</span><b>{{ fmt(requests.length) }}</b></div>
            <div class="lc-info-row"><span>{{ t('stats.cacheHit') }}</span><b>{{ cacheHit }}</b></div>
          </div>
        </div>
      </div>
      <div class="lc-cols lc-head">
        <StatsTokens :usage="data.usage" :current="data.current" />
        <StatsTiming :timing="data.timing" :spans="data.spans" />
      </div>
      <div class="lc-cols lc-cols-main">
        <div class="lc-col flex-1 min-w-[min(360px,100%)]">
          <CurrentComposition v-if="head" :head="head" :subtitle="data.model || ''" :hover-key="hoverCat" @hover="hoverCat = $event" />
          <div class="lc-card">
            <div class="lc-card-title">
              <span class="lc-card-title-text">{{ t('trend.title') }}</span>
              <span class="lc-gran lc-trend-mods" role="group">
                <button type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': adaptive }" :title="t('trend.adaptiveHint')"
                  @click="toggleAdaptive">{{ t('trend.adaptive') }}</button>
                <button type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': durationCurve }" :title="t('trend.durationTip')"
                  @click="durationCurve = !durationCurve">{{ t('trend.duration') }}</button>
                <button type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': overview }" :title="t('trend.overviewTip')"
                  @click="toggleOverview">{{ t('trend.overview') }}</button>
              </span>
              <div class="lc-trend-ctl">
                <div class="lc-gran">
                  <button class="lc-gran-btn" :class="{ 'lc-gran-on': granularity === 'step' }" @click="granularity = 'step'">{{ t('gran.step') }}</button>
                  <button class="lc-gran-btn" :class="{ 'lc-gran-on': granularity === 'turn' }" @click="granularity = 'turn'">{{ t('gran.turn') }}</button>
                </div>
                <div class="lc-gran" :title="t('gran.modeHint')">
                  <button class="lc-gran-btn" :class="{ 'lc-gran-on': trendMode === 'total' }" @click="trendMode = 'total'">{{ t('gran.total') }}</button>
                  <button class="lc-gran-btn" :class="{ 'lc-gran-on': trendMode === 'delta' }" @click="trendMode = 'delta'">{{ t('gran.delta') }}</button>
                </div>
              </div>
            </div>
            <div v-if="!displayRequests.length" class="lc-empty">{{ t('trend.empty') }}</div>
            <div v-else>
              <TrendOverview v-if="overview" :key="'o' + conversationId" :requests="displayRequests" :raw-requests="requests"
                :markers="markers" :selected-seq="pinnedReq ? pinnedReq.seq : null" :hovered-seq="hoveredSeq"
                :active-turn="activeTurn" :granularity="granularity" :mode="trendMode" :hover-cat="trendHoverCat"
                :focus-cat="focusCat" :duration-curve="durationCurve"
                @select="selectedSeq = $event" @hover="hoveredSeq = $event" @hover-turn="hoverTurn = $event" @pick-turn="pickTurn" />
              <TrendChart v-else :key="'c' + conversationId" :requests="displayRequests" :raw-requests="requests" :markers="markers"
                :selected-seq="pinnedReq ? pinnedReq.seq : null" :hovered-seq="hoveredSeq" :active-turn="activeTurn"
                :granularity="granularity" :mode="trendMode" :focus-turn="focusTurn" :hover-cat="trendHoverCat"
                :focus-cat="focusCat" :adaptive="adaptive" :duration-curve="durationCurve"
                @select="selectedSeq = $event" @hover="hoveredSeq = $event" @hover-turn="hoverTurn = $event"
                @pick-turn="pickTurn" @focus-turn-handled="focusTurn = null" />
              <RequestDetail :request="activeReq" :delta="trendMode === 'delta'"
                :prev="trendMode === 'delta' && activeIdx > 0 ? displayRequests[activeIdx - 1] : null"
                :marker="activeIdx >= 0 ? markers[activeIdx] : null" :steps-of="stepsOf" :hover-key="trendHoverCat" locatable
                @hover="hoverCat = $event" @locate="locateBrief" />
            </div>
          </div>
        </div>
        <div class="lc-col lc-col-browser flex-1 min-w-[min(360px,100%)]">
          <ContextBrowser :requests="requests" :steps-of="stepsOf" :preview-seq="hoveredSeq"
            :pin-seq="pinnedReq ? pinnedReq.seq : null" :focus="browserFocus" :hover-key="hoverCat"
            @hover="hoverCat = $event" @open-cat="focusCat = $event" @focus-handled="browserFocus = null" />
        </div>
      </div>
      <div class="lc-cols">
        <div class="lc-card lc-col flex-1 min-w-[min(360px,100%)]">
          <div class="lc-card-title">
            <span class="lc-card-title-text">{{ t('events.title') }}</span>
            <div class="lc-kinds @max-[380px]/lc-card:flex-wrap">
              <button v-for="k in EVENT_KINDS" :key="k" :data-kind="k" class="lc-gran-btn"
                :class="pickedKinds.includes(k) ? 'lc-gran-on lc-kind-' + k : ''" @click="toggleKind(k)">
                {{ t('kind.' + k) }}<span v-if="kindCounts[k] !== undefined" class="lc-kind-n">{{ fmt(kindCounts[k]) }}</span>
              </button>
            </div>
          </div>
          <EventList :events="shownEvents" @focus="focusInject" />
        </div>
        <FileCard :ops="files.ops" :before="fileBefore" :scope="fileScope" :workspace="files.root" @locate="locateFile" />
      </div>
      <div class="lc-foot">{{ t('footer') }}</div>
    </template>
  </div>
</template>
