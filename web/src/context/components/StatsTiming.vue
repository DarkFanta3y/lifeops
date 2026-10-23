<script setup>
// 照搬 dsh-context components/statsTiming.tsx：活跃时长拆成模型等待 / 模型回复 / 工具执行 / 其他开销。
import { computed, ref } from 'vue';
import { t } from '../i18n.js';
import { fmt, fmtDuration, fmtShare } from '../kit.js';
import { TIMING_COLOR, formatTokensPerSecond } from '../timing.js';
import Donut from './Donut.vue';
import SliceList from './SliceList.vue';
import TimingStrip from './TimingStrip.vue';

const props = defineProps({ timing: Object, spans: Array });
const hoverKey = ref(null);
const wall = computed(() => (props.timing?.wallMs > 0 ? props.timing.wallMs : 0));
const tps = computed(() => {
  const timing = props.timing;
  return timing?.speedMs > 0 && timing.speedTokens >= 0
    ? formatTokensPerSecond(timing.speedTokens / (timing.speedMs / 1000)) : null;
});
const view = computed(() => {
  const timing = props.timing;
  if (!timing || !(wall.value > 0 || timing.calls > 0 || timing.toolCalls > 0)) return { segments: [], rows: [] };
  const w = wall.value;
  const ttftRing = Math.min(timing.ttftMs, w);
  const genRing = Math.max(0, Math.min(timing.genMs, w - ttftRing));
  const toolRing = Math.max(0, Math.min(timing.toolsMs, w - ttftRing - genRing));
  const other = Math.max(0, w - ttftRing - genRing - toolRing);
  const share = ms => (w > 0 ? ms / w : 0);
  const callTimes = t('timing.callTimes', { n: fmt(timing.calls) });
  const slices = [
    { key: 'ttft', label: t('timing.ttft'), ms: timing.ttftMs, ring: ttftRing, times: callTimes },
    { key: 'text', label: t('timing.gen'), ms: timing.genMs, ring: genRing },
    { key: 'tools', label: t('timing.tools'), ms: timing.toolsMs, ring: toolRing,
      times: t('timing.toolTimes', { n: fmt(timing.toolCalls) }) },
    { key: 'other', label: t('timing.other'), ms: other, ring: other },
  ];
  const countOf = (ms, times) => {
    const dur = fmtDuration(ms);
    if (!times) return dur;
    return ms > 0 ? `${dur}，${times}` : times;
  };
  return {
    segments: slices.map(s => ({ key: s.key, color: TIMING_COLOR[s.key], value: share(s.ring) })),
    rows: slices.filter(s => s.ms > 0).map(s => ({ key: s.key, color: TIMING_COLOR[s.key], label: s.label,
      pct: fmtShare(s.ms, w), count: countOf(s.ms, s.times) })),
  };
});
</script>

<template>
  <div class="lc-card lc-col-donut flex-1 min-w-[min(360px,100%)]">
    <div class="lc-card-title">
      <span class="lc-card-title-text">{{ t('timing.title') }}</span>
      <span v-if="tps !== null" class="lc-card-rate" :title="t('timing.tpsTip')">{{ t('timing.tps', { tps }) }}</span>
    </div>
    <div v-if="!view.rows.length" class="lc-empty">{{ t('timing.empty') }}</div>
    <template v-else>
      <div class="lc-donut-row flex items-center justify-start gap-3 min-w-0 @max-[320px]/lc-card:gap-2 @max-[240px]/lc-card:flex-wrap">
        <Donut :segments="view.segments" :size="96" :center-top="wall > 0 ? fmtDuration(wall) : '—'"
          :center-sub="t('timing.total')" :hover-key="hoverKey" @hover="hoverKey = $event" />
        <SliceList :rows="view.rows" :hover-key="hoverKey" @hover="hoverKey = $event" />
      </div>
      <TimingStrip v-if="spans?.length" :spans="spans" :hover-key="hoverKey" @hover="hoverKey = $event" />
    </template>
  </div>
</template>
