<script setup>
// 照搬 dsh-context components/trendChart.tsx（不含 DNA 模式）：每次请求一根柱子，支持全量/增量、自适应、耗时曲线与轮次条。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { CATS, fmt, fmtDuration } from '../kit.js';
import { eventAt, eventLabel, preprocessTrend, TURN_FILLS, trendMaxima, trendTipRows, turnStepsOf } from '../trend.js';

const CHART_H = 112;
const Q3_TOP = 41;
const Q1_TOP = 97;
const BAR_W = 14;
const BAR_GAP = 2;
const STAGGER_CAP = 20;
const STEP_FLAG_EVERY = 5;
const RISE_CAP = 200;
const LABEL_OVERHANG = 48;
const LABEL_GAP = 2;
const LABEL_FONT = 10;
const LABEL_FONT_MIN = 6;

const props = defineProps({
  requests: { type: Array, required: true },
  rawRequests: { type: Array, required: true },
  markers: { type: Array, default: () => [] },
  selectedSeq: { type: Number, default: null },
  hoveredSeq: { type: Number, default: null },
  activeTurn: { type: Number, default: null },
  granularity: { type: String, default: 'step' },
  mode: { type: String, default: 'total' },
  focusTurn: { type: Number, default: null },
  hoverCat: { type: String, default: null },
  focusCat: { type: String, default: null },
  adaptive: Boolean,
  durationCurve: Boolean,
});
const emit = defineEmits(['select', 'hover', 'hover-turn', 'pick-turn', 'focus-turn-handled']);
const scrollRef = ref(null);
const tipRef = ref(null);
const visMax = ref(null);
const fmtSigned = v => (v > 0 ? '+' : '') + fmt(v);
const delta = computed(() => props.mode === 'delta');
const pre = computed(() => preprocessTrend(props.requests, delta.value, props.focusCat));
const plotted = computed(() => pre.value.requests);
const stepsOf = computed(() => turnStepsOf(props.rawRequests));

const maxima = computed(() => {
  let { maxTotal, maxUp, maxDown } = trendMaxima(plotted.value, delta.value);
  if (props.adaptive && visMax.value) {
    if (delta.value) {
      if (visMax.value.up + visMax.value.down > 0) { maxUp = visMax.value.up; maxDown = visMax.value.down; }
    } else {
      maxTotal = Math.max(1, visMax.value.total);
    }
  }
  return { maxTotal, maxUp, maxDown };
});
const span = computed(() => Math.max(1, maxima.value.maxUp + maxima.value.maxDown));
const deltaScale = computed(() => CHART_H / span.value);
const upPx = computed(() => Math.round(maxima.value.maxUp * deltaScale.value));
const downPx = computed(() => CHART_H - upPx.value);
const q3Clear = computed(() => Math.abs(Q3_TOP - 13 - upPx.value) >= 11);
const q1Clear = computed(() => Math.abs(Q1_TOP - 13 - upPx.value) >= 11);
const riseFrom = computed(() => Math.max(0, plotted.value.length - RISE_CAP));

const maxActiveMs = computed(() => {
  if (!props.durationCurve) return 0;
  if (props.adaptive && visMax.value) return visMax.value.activeMs;
  return plotted.value.reduce((max, req) => Math.max(max, req.activeMs ?? 0), 0);
});
const duration = computed(() => {
  const runs = [];
  const dots = [];
  if (!props.durationCurve) return { runs, dots };
  const scale = CHART_H / Math.max(1, maxActiveMs.value);
  let run = [];
  const flush = () => {
    if (run.length >= 2) runs.push(run.map(p => `${p[0]},${p[1]}`).join(' '));
    else if (run.length === 1) dots.push(run[0]);
    run = [];
  };
  plotted.value.forEach((req, i) => {
    if (req.activeMs === undefined) { flush(); return; }
    run.push([i * (BAR_W + BAR_GAP) + BAR_W / 2, Math.round((CHART_H - req.activeMs * scale) * 100) / 100]);
  });
  flush();
  return { runs, dots };
});

const groups = computed(() => {
  const result = [];
  for (const req of plotted.value) {
    let grp = result.length ? result[result.length - 1] : null;
    if (!grp || grp.turn !== (req.turn ?? 0)) {
      grp = { turn: req.turn ?? 0, count: 0, span: 0, agg: req.stepCount !== undefined };
      result.push(grp);
    }
    grp.count++;
    grp.span += req.stepCount ?? 1;
  }
  let x = 0;
  for (const grp of result) {
    grp.width = grp.agg ? BAR_W : grp.span * (BAR_W + BAR_GAP) - BAR_GAP;
    grp.offset = x;
    x += grp.width + BAR_GAP;
  }
  return result;
});
const labelFont = computed(() => {
  const est = turn => 6.5 * String(turn).length;
  let scale = 1;
  const list = groups.value;
  for (let i = 0; i + 1 < list.length; i++) {
    const avail = (list[i].width + list[i + 1].width) / 2 + BAR_GAP;
    const need = (est(list[i].turn) + est(list[i + 1].turn)) / 2 + LABEL_GAP;
    if (need > avail) scale = Math.min(scale, avail / need);
  }
  return scale < 1 ? `${Math.max(LABEL_FONT_MIN, Math.floor(LABEL_FONT * scale))}px` : '';
});

const hoveredIdx = computed(() => (props.hoveredSeq !== null ? plotted.value.findIndex(r => r.seq === props.hoveredSeq) : -1));
const tipRows = computed(() => {
  const req = hoveredIdx.value >= 0 ? plotted.value[hoveredIdx.value] : null;
  return req ? trendTipRows({ granularity: props.granularity, stepsOf: stepsOf.value, delta: delta.value,
    focus: pre.value.focus, durationOn: props.durationCurve }, req) : null;
});

function segHeight(v) { return `${Math.max(1, Math.round(v / maxima.value.maxTotal * CHART_H))}px`; }
function deltaHeight(v) { return `${Math.max(1, Math.round(Math.abs(v) * deltaScale.value))}px`; }

function measureVisible(el) {
  if (!props.adaptive) return;
  const n = plotted.value.length;
  if (n === 0 || el.clientWidth <= 0) return;
  const pitch = BAR_W + BAR_GAP;
  const sl = el.scrollLeft;
  const vr = sl + el.clientWidth;
  let total = 0; let up = 0; let down = 0; let activeMs = 0;
  const from = Math.max(0, Math.floor(sl / pitch));
  const to = Math.min(n - 1, Math.max(from, Math.floor((vr - 1) / pitch)));
  for (let i = from; i <= to; i++) {
    const req = plotted.value[i];
    activeMs = Math.max(activeMs, req.activeMs ?? 0);
    if (delta.value) {
      let bu = 0; let bd = 0;
      for (const c of CATS) { const d = req[c.key] || 0; if (d > 0) bu += d; else bd -= d; }
      up = Math.max(up, bu); down = Math.max(down, bd);
    } else {
      total = Math.max(total, req.total);
    }
  }
  const prev = visMax.value;
  if (!prev || prev.total !== total || prev.up !== up || prev.down !== down || prev.activeMs !== activeMs) {
    visMax.value = { total, up, down, activeMs };
  }
}

// 每个轮次标签在其可见区间内居中，碰撞时隐藏后者。
function updateTurnLabels(el) {
  const labels = el.querySelectorAll('.lc-turn-label');
  const list = groups.value;
  const n = Math.min(labels.length, list.length);
  const sl = el.scrollLeft;
  const vr = sl + el.clientWidth;
  let chainR = -Infinity;
  for (let i = 0; i < n; i++) {
    const { offset: off, width: w } = list[i];
    let dx = 0;
    let vis = '';
    if (off + w + LABEL_OVERHANG > sl && off - LABEL_OVERHANG < vr) {
      const lw = labels[i].offsetWidth;
      const visL = Math.max(off, sl);
      const visR = Math.min(off + w, vr);
      if (visR > visL && lw < w) dx = Math.min(Math.max((visL + visR) / 2 - off, lw / 2), w - lw / 2) - w / 2;
      const left = off + w / 2 + dx - lw / 2;
      if (left < chainR) vis = 'hidden'; else chainR = left + lw + LABEL_GAP;
    }
    labels[i].style.transform = dx !== 0 ? `translateX(${dx}px)` : '';
    labels[i].style.visibility = vis;
  }
}

// 提示框放在滚动容器外，按柱子可见位置平移。
function syncTip() {
  const el = scrollRef.value;
  const tip = tipRef.value;
  if (!el || !tip) return;
  const col = hoveredIdx.value >= 0 ? hoveredIdx.value * (BAR_W + BAR_GAP) + BAR_W / 2 : 0;
  const lw = tip.offsetWidth;
  const cw = el.clientWidth;
  const half = Math.min(lw / 2, cw / 2);
  const cx = Math.min(Math.max(col - el.scrollLeft, half), cw - half);
  tip.style.transform = `translate(${Math.round(cx - lw / 2)}px, 0)`;
}

let scrolledOnce = false;
let lastGran = props.granularity;
let lastSeq = 0;
let prevScrollWidth = 0;
async function layout() {
  await nextTick();
  const el = scrollRef.value;
  if (!el) return;
  const list = plotted.value;
  const newestSeq = list.length ? list[list.length - 1].seq : 0;
  const grew = newestSeq !== lastSeq;
  if (props.granularity !== lastGran) { lastGran = props.granularity; scrolledOnce = false; }
  if (props.focusTurn !== null) {
    const gi = groups.value.findIndex(g => g.turn === props.focusTurn);
    if (gi >= 0) {
      scrolledOnce = true;
      el.scrollLeft = Math.max(0, groups.value[gi].offset + BAR_W / 2 - el.clientWidth / 2);
    }
    emit('focus-turn-handled');
  } else if (!scrolledOnce) {
    scrolledOnce = true;
    el.scrollLeft = el.scrollWidth;
  } else if (grew && el.scrollLeft + el.clientWidth >= prevScrollWidth - 24) {
    el.scrollLeft = el.scrollWidth;
  }
  lastSeq = newestSeq;
  prevScrollWidth = el.scrollWidth;
  updateTurnLabels(el);
  syncTip();
  measureVisible(el);
}
watch(() => [props.granularity, props.focusTurn, plotted.value, props.adaptive], layout);
watch(hoveredIdx, () => nextTick(syncTip));
function onScroll(e) {
  updateTurnLabels(e.currentTarget);
  syncTip();
  measureVisible(e.currentTarget);
}
function onWheel(e) {
  // 横向滚动到边界时不把滚动传给页面（照搬 overscroll.ts 的意图）
  const el = e.currentTarget;
  if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
  const atStart = el.scrollLeft <= 0 && e.deltaX < 0;
  const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 1 && e.deltaX > 0;
  if (atStart || atEnd) e.preventDefault();
}
let observer;
onMounted(() => {
  layout();
  if (typeof ResizeObserver === 'function') {
    observer = new ResizeObserver(() => measureVisible(scrollRef.value));
    observer.observe(scrollRef.value);
  }
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div class="lc-chartrow">
    <div class="lc-axis">
      <template v-if="delta">
        <span class="lc-axis-top">{{ fmtSigned(maxima.maxUp) }}</span>
        <span v-if="q3Clear" class="lc-axis-q3">{{ fmtSigned(Math.round(maxima.maxUp - span / 4)) }}</span>
        <span class="lc-axis-mid" :style="{ top: `${13 + upPx}px` }">0</span>
        <span v-if="q1Clear" class="lc-axis-q1">{{ fmtSigned(Math.round(maxima.maxUp - 3 * span / 4)) }}</span>
        <span class="lc-axis-bot">{{ fmtSigned(-maxima.maxDown) }}</span>
      </template>
      <template v-else>
        <span class="lc-axis-top">{{ fmt(maxima.maxTotal) }}</span>
        <span class="lc-axis-q3">{{ fmt(Math.round(maxima.maxTotal * 3 / 4)) }}</span>
        <span class="lc-axis-mid">{{ fmt(Math.round(maxima.maxTotal / 2)) }}</span>
        <span class="lc-axis-q1">{{ fmt(Math.round(maxima.maxTotal / 4)) }}</span>
        <span class="lc-axis-bot">0</span>
      </template>
    </div>
    <div class="lc-chart-wrap">
      <div ref="scrollRef" class="lc-chart-scroll" :class="{ 'lc-chart-dim': activeTurn !== null }" @scroll="onScroll" @wheel="onWheel">
        <div class="lc-chart" :data-catdim="hoverCat || undefined" @mouseleave="emit('hover', null)">
          <div class="lc-grid lc-grid-top" />
          <div v-if="!delta || q3Clear" class="lc-grid lc-grid-q3" />
          <div v-if="!delta || q1Clear" class="lc-grid lc-grid-q1" />
          <div v-if="!delta" class="lc-grid lc-grid-mid" />
          <div class="lc-grid lc-grid-zero" :style="delta ? { top: `${18 + upPx}px` } : undefined" />
          <div v-for="(req, i) in plotted" :key="`${req.seq}:${granularity}`"
            class="lc-bar hover:bg-(--dsw-alias-bg-layer-2)"
            :class="{ 'lc-bar-selected': selectedSeq === req.seq, 'lc-bar-hovered': hoveredSeq === req.seq,
              'lc-bar-in-turn': activeTurn !== null && (req.turn ?? 0) === activeTurn }"
            :data-seq="req.seq" :style="{ width: `${BAR_W}px` }"
            @click="emit('select', selectedSeq === req.seq ? null : req.seq)" @mouseenter="emit('hover', req.seq)">
            <span v-if="granularity === 'step' && (i + 1) % STEP_FLAG_EVERY === 0" class="lc-step-flag" aria-hidden="true">
              <span class="lc-step-flag-label">{{ i + 1 }}</span>
            </span>
            <span v-if="markers[i]" class="lc-bar-marker"
              :title="'✂ ' + (eventAt(markers[i]) ? eventAt(markers[i]) + ' — ' : '') + eventLabel(markers[i])">✂</span>
            <template v-if="delta">
              <div class="lc-bar-up" :class="{ 'animate-lc-bar-in motion-reduce:animate-none': i >= riseFrom }"
                :style="{ bottom: `${downPx}px`, '--lc-i': Math.min(Math.max(0, i - riseFrom), STAGGER_CAP) }">
                <template v-for="c in CATS" :key="c.key">
                  <div v-if="(req[c.key] || 0) > 0" :data-cat="c.key" class="lc-cat-seg"
                    :style="{ height: deltaHeight(req[c.key]), background: c.color }" />
                </template>
              </div>
              <div class="lc-bar-down" :class="{ 'animate-lc-bar-in motion-reduce:animate-none': i >= riseFrom }"
                :style="{ top: `${upPx}px`, '--lc-i': Math.min(Math.max(0, i - riseFrom), STAGGER_CAP) }">
                <template v-for="c in CATS" :key="c.key">
                  <div v-if="(req[c.key] || 0) < 0" :data-cat="c.key" class="lc-cat-seg"
                    :style="{ height: deltaHeight(req[c.key]), background: c.color }" />
                </template>
              </div>
            </template>
            <div v-else class="lc-bar-stack" :class="{ 'animate-lc-bar-in motion-reduce:animate-none': i >= riseFrom }"
              :style="{ '--lc-i': Math.min(Math.max(0, i - riseFrom), STAGGER_CAP) }">
              <template v-for="c in CATS" :key="c.key">
                <div v-if="req[c.key]" :data-cat="c.key" class="lc-cat-seg" :style="{ height: segHeight(req[c.key]), background: c.color }" />
              </template>
            </div>
          </div>
          <svg v-if="durationCurve && (duration.runs.length || duration.dots.length)" class="lc-duration"
            :width="plotted.length * (BAR_W + BAR_GAP) - BAR_GAP" :height="CHART_H" aria-hidden="true">
            <template v-for="(pts, i) in duration.runs" :key="'r' + i">
              <polyline class="lc-dur-halo" :points="pts" /><polyline :points="pts" />
            </template>
            <template v-for="(p, i) in duration.dots" :key="'d' + i">
              <circle class="lc-dur-halo" :cx="p[0]" :cy="p[1]" r="2" /><circle :cx="p[0]" :cy="p[1]" r="1.2" />
            </template>
          </svg>
        </div>
        <div class="lc-turns" :style="labelFont ? { fontSize: labelFont } : undefined" @mouseleave="emit('hover-turn', null)">
          <span v-for="(grp, gi) in groups" :key="`turn-${gi}`" class="lc-turn" :class="{ 'lc-turn-on': activeTurn === grp.turn }"
            :style="{ width: `${grp.width}px`, background: TURN_FILLS[gi % TURN_FILLS.length] }" :title="`T${grp.turn}`"
            @mouseenter="emit('hover-turn', grp.turn)" @click="emit('pick-turn', grp.turn)">
            <span class="lc-turn-label">{{ grp.turn }}</span>
          </span>
        </div>
      </div>
      <div v-if="tipRows" ref="tipRef" class="lc-chart-tip"><span v-for="(row, i) in tipRows" :key="i">{{ row }}</span></div>
    </div>
    <div v-if="durationCurve" class="lc-axis lc-axis-r">
      <span class="lc-axis-top">{{ fmtDuration(maxActiveMs) }}</span>
      <span class="lc-axis-q3">{{ fmtDuration(Math.round(maxActiveMs * 3 / 4)) }}</span>
      <span class="lc-axis-mid">{{ fmtDuration(Math.round(maxActiveMs / 2)) }}</span>
      <span class="lc-axis-q1">{{ fmtDuration(Math.round(maxActiveMs / 4)) }}</span>
      <span class="lc-axis-bot">0</span>
    </div>
  </div>
</template>
