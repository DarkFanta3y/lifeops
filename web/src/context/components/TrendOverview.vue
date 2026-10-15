<script setup>
// 照搬 dsh-context components/trendOverview.tsx：把全部请求压进可视宽度的累积带状图，悬停读数、点击选中。
import { computed, nextTick, ref, watch } from 'vue';
import { CAT_COLOR, fmt, fmtDuration } from '../kit.js';
import { eventAt, eventLabel, flagStepsOf, preprocessTrend, ribbonGeometry, TURN_FILLS, trendTipRows, turnStepsOf, wideQuartiles } from '../trend.js';

const CHART_H = 112;
const Q3_TOP = 41;
const Q1_TOP = 97;
const props = defineProps({
  requests: { type: Array, required: true },
  rawRequests: { type: Array, required: true },
  markers: { type: Array, default: () => [] },
  selectedSeq: { type: Number, default: null },
  hoveredSeq: { type: Number, default: null },
  activeTurn: { type: Number, default: null },
  granularity: { type: String, default: 'step' },
  mode: { type: String, default: 'total' },
  hoverCat: { type: String, default: null },
  focusCat: { type: String, default: null },
  durationCurve: Boolean,
});
const emit = defineEmits(['select', 'hover', 'hover-turn', 'pick-turn']);
const surfaceRef = ref(null);
const tipRef = ref(null);
let lastIdx = null;
const fmtSigned = v => (v > 0 ? '+' : '') + fmt(v);
const delta = computed(() => props.mode === 'delta');
const pre = computed(() => preprocessTrend(props.requests, delta.value, props.focusCat));
const plotted = computed(() => pre.value.requests);
const n = computed(() => plotted.value.length);
const u = computed(() => (n.value > 1 ? n.value - 1 : 1));
const geo = computed(() => ribbonGeometry(plotted.value, delta.value, props.durationCurve));
const groups = computed(() => {
  const result = [];
  plotted.value.forEach((req, i) => {
    let grp = result.length ? result[result.length - 1] : null;
    if (!grp || grp.turn !== (req.turn ?? 0)) { grp = { turn: req.turn ?? 0, count: 0, span: 0, first: i }; result.push(grp); }
    grp.count++;
    grp.span += req.stepCount ?? 1;
  });
  return result;
});
const flagSteps = computed(() => flagStepsOf(n.value, props.granularity));
const flagGroups = computed(() => wideQuartiles(groups.value));
const q3Clear = computed(() => Math.abs(Q3_TOP - 13 - geo.value.upPx) >= 11);
const q1Clear = computed(() => Math.abs(Q1_TOP - 13 - geo.value.upPx) >= 11);
const wash = computed(() => {
  if (props.activeTurn === null) return null;
  const wi = groups.value.findIndex(g => g.turn === props.activeTurn);
  if (wi < 0) return null;
  const grp = groups.value[wi];
  const end = grp.first + grp.count - 1;
  const left = grp.first === 0 ? 0 : (grp.first - 0.5) / u.value * 100;
  const right = end === n.value - 1 ? 100 : (end + 0.5) / u.value * 100;
  return { left: `${left}%`, right: `${100 - right}%` };
});
const hoveredIdx = computed(() => (props.hoveredSeq !== null ? plotted.value.findIndex(r => r.seq === props.hoveredSeq) : -1));
const selectedIdx = computed(() => (props.selectedSeq !== null ? plotted.value.findIndex(r => r.seq === props.selectedSeq) : -1));
const stepsOf = computed(() => turnStepsOf(props.rawRequests));
const tipRows = computed(() => (hoveredIdx.value >= 0
  ? trendTipRows({ granularity: props.granularity, stepsOf: stepsOf.value, delta: delta.value, focus: pre.value.focus,
    durationOn: props.durationCurve }, plotted.value[hoveredIdx.value]) : null));

function pick(e) {
  const rect = e.currentTarget.getBoundingClientRect();
  if (rect.width <= 0) return 0;
  return Math.min(n.value - 1, Math.max(0, Math.round((e.clientX - rect.left) / rect.width * u.value)));
}
function onMove(e) {
  const idx = pick(e);
  if (lastIdx !== idx) { lastIdx = idx; emit('hover', plotted.value[idx].seq); }
}
function onLeave() { lastIdx = null; emit('hover', null); }
function onClick(e) {
  const seq = plotted.value[pick(e)].seq;
  emit('select', props.selectedSeq === seq ? null : seq);
}
watch(hoveredIdx, async () => {
  await nextTick();
  const el = surfaceRef.value;
  const tip = tipRef.value;
  if (!el || !tip) return;
  const cw = el.clientWidth;
  const lw = tip.offsetWidth;
  const half = Math.min(lw / 2, cw / 2);
  const cx = hoveredIdx.value >= 0 ? Math.min(Math.max(hoveredIdx.value / u.value * cw, half), cw - half) : 0;
  tip.style.transform = `translate(${Math.round(cx - lw / 2)}px, 0)`;
});
</script>

<template>
  <div v-if="n" class="lc-chartrow">
    <div class="lc-axis">
      <template v-if="delta">
        <span class="lc-axis-top">{{ fmtSigned(geo.maxUp) }}</span>
        <span v-if="q3Clear" class="lc-axis-q3">{{ fmtSigned(Math.round(geo.maxUp - geo.span / 4)) }}</span>
        <span class="lc-axis-mid" :style="{ top: `${13 + geo.upPx}px` }">0</span>
        <span v-if="q1Clear" class="lc-axis-q1">{{ fmtSigned(Math.round(geo.maxUp - 3 * geo.span / 4)) }}</span>
        <span class="lc-axis-bot">{{ fmtSigned(-geo.maxDown) }}</span>
      </template>
      <template v-else>
        <span class="lc-axis-top">{{ fmt(geo.maxTotal) }}</span>
        <span class="lc-axis-q3">{{ fmt(Math.round(geo.maxTotal * 3 / 4)) }}</span>
        <span class="lc-axis-mid">{{ fmt(Math.round(geo.maxTotal / 2)) }}</span>
        <span class="lc-axis-q1">{{ fmt(Math.round(geo.maxTotal / 4)) }}</span>
        <span class="lc-axis-bot">0</span>
      </template>
    </div>
    <div class="lc-chart-wrap">
      <div class="lc-chart-scroll lc-chart-fit" :class="{ 'lc-chart-dim': activeTurn !== null }">
        <div ref="surfaceRef" class="lc-chart" :data-catdim="hoverCat || undefined"
          @mousemove="onMove" @mouseleave="onLeave" @click="onClick">
          <div class="lc-grid lc-grid-top" />
          <div v-if="!delta || q3Clear" class="lc-grid lc-grid-q3" />
          <div v-if="!delta || q1Clear" class="lc-grid lc-grid-q1" />
          <div v-if="!delta" class="lc-grid lc-grid-mid" />
          <div class="lc-grid lc-grid-zero" :style="delta ? { top: `${18 + geo.upPx}px` } : undefined" />
          <svg v-if="geo.polys.length || geo.durationRuns.length || geo.durationDots.length"
            class="lc-duration lc-fit-svg animate-lc-bar-in motion-reduce:animate-none"
            :viewBox="`0 0 ${u} ${CHART_H}`" preserveAspectRatio="none" aria-hidden="true">
            <polygon v-for="(p, i) in geo.polys" :key="i" :data-cat="p.cat" class="lc-cat-seg"
              :style="{ fill: CAT_COLOR[p.cat], stroke: CAT_COLOR[p.cat] }" :points="p.points" />
            <template v-for="(pts, i) in geo.durationRuns" :key="'r' + i">
              <polyline class="lc-dur-halo" :points="pts" /><polyline :points="pts" />
            </template>
            <template v-for="(p, i) in geo.durationDots" :key="'d' + i">
              <circle class="lc-dur-halo" :cx="p[0]" :cy="p[1]" r="2" /><circle :cx="p[0]" :cy="p[1]" r="1.2" />
            </template>
          </svg>
          <template v-if="wash">
            <div class="lc-fit-wash" :style="{ left: 0, width: wash.left, right: 'auto' }" />
            <div class="lc-fit-wash" :style="{ left: 'auto', width: wash.right, right: 0 }" />
          </template>
          <div v-if="hoveredIdx >= 0" class="lc-fit-cursor" :style="{ left: `${hoveredIdx / u * 100}%` }" />
          <div v-if="selectedIdx >= 0" class="lc-fit-cursor lc-fit-pin" :style="{ left: `${selectedIdx / u * 100}%` }" />
          <div class="lc-fit-layer">
            <template v-for="(ev, i) in markers" :key="`marker-${i}`">
              <span v-if="ev" class="lc-bar-marker" :style="{ left: `${i / u * 100}%` }"
                :title="'✂ ' + (eventAt(ev) ? eventAt(ev) + ' — ' : '') + eventLabel(ev)">✂</span>
            </template>
            <span v-for="idx in flagSteps" :key="`flag-${idx}`" class="lc-step-flag"
              :style="{ left: idx === n - 1 ? 'calc(100% - 1px)' : `${idx / u * 100}%` }" aria-hidden="true">
              <span class="lc-step-flag-label">{{ idx + 1 }}</span>
            </span>
          </div>
        </div>
        <div class="lc-turns" @mouseleave="emit('hover-turn', null)">
          <span v-for="(grp, gi) in groups" :key="`turn-${gi}`" class="lc-turn" :class="{ 'lc-turn-on': activeTurn === grp.turn }"
            :style="{ flexGrow: grp.span, flexBasis: 0, background: TURN_FILLS[gi % TURN_FILLS.length] }" :title="`T${grp.turn}`"
            @mouseenter="emit('hover-turn', grp.turn)" @click="emit('pick-turn', grp.turn)">
            <span v-if="flagGroups.includes(gi)" class="lc-turn-label">{{ grp.turn }}</span>
          </span>
        </div>
      </div>
      <div v-if="tipRows" ref="tipRef" class="lc-chart-tip"><span v-for="(row, i) in tipRows" :key="i">{{ row }}</span></div>
    </div>
    <div v-if="durationCurve" class="lc-axis lc-axis-r">
      <span class="lc-axis-top">{{ fmtDuration(geo.maxActiveMs) }}</span>
      <span class="lc-axis-q3">{{ fmtDuration(Math.round(geo.maxActiveMs * 3 / 4)) }}</span>
      <span class="lc-axis-mid">{{ fmtDuration(Math.round(geo.maxActiveMs / 2)) }}</span>
      <span class="lc-axis-q1">{{ fmtDuration(Math.round(geo.maxActiveMs / 4)) }}</span>
      <span class="lc-axis-bot">0</span>
    </div>
  </div>
</template>
