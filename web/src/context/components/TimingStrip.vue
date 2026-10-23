<script setup>
// 照搬 dsh-context components/timingStrip.tsx：各段耗时按发生次序紧凑铺排，宽度为耗时占比。
import { computed, ref } from 'vue';
import { t } from '../i18n.js';
import { fmtDuration, fmtTime } from '../kit.js';
import { TIMING_COLOR, TIMING_LABEL } from '../timing.js';

const TICK_FRACS = [0, 0.25, 0.5, 0.75, 1];
const props = defineProps({ spans: { type: Array, required: true }, hoverKey: { type: String, default: null } });
const emit = defineEmits(['hover']);
const tipKey = ref(null);
const valid = computed(() => props.spans.filter(s => Object.hasOwn(TIMING_COLOR, s.kind)
  && Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start));
const total = computed(() => valid.value.reduce((sum, s) => sum + s.end - s.start, 0));
const bands = computed(() => {
  let cursor = 0;
  return valid.value.map((s, i) => {
    const leftPct = cursor / total.value * 100;
    cursor += s.end - s.start;
    return { key: i, kind: s.kind, leftPct, widthPct: (s.end - s.start) / total.value * 100,
      tip: `${t(TIMING_LABEL[s.kind])} ${fmtDuration(s.end - s.start)}，${fmtTime(s.start)}` };
  });
});
const hovering = computed(() => props.hoverKey !== null && bands.value.some(b => b.kind === props.hoverKey));
const tip = computed(() => {
  const band = bands.value.find(b => b.key === tipKey.value);
  return band ? { text: band.tip, leftPct: Math.max(10, Math.min(band.leftPct + band.widthPct / 2, 90)) } : null;
});
function leave() { tipKey.value = null; emit('hover', null); }
function enter(band) { tipKey.value = band.key; emit('hover', band.kind); }
</script>

<template>
  <div v-if="bands.length" class="lc-tstrip" role="img" :aria-label="t('timing.strip')">
    <div class="lc-tstrip-wrap">
      <div class="lc-tstrip-bar" :class="{ 'lc-tstrip-dim': hovering }" @mouseleave="leave">
        <div class="lc-tstrip-fill animate-lc-stacked-in motion-reduce:animate-none">
          <div v-for="b in bands" :key="b.key" class="lc-tstrip-seg" :class="{ 'lc-tstrip-seg-on': hoverKey === b.kind }"
            :style="{ left: `${b.leftPct}%`, width: `${b.widthPct}%`, background: TIMING_COLOR[b.kind] }"
            @mouseenter="enter(b)" />
        </div>
      </div>
      <div class="lc-tip lc-bar-tip" :class="{ 'lc-bar-tip-on': tip }" :style="{ left: `${tip ? tip.leftPct : 50}%` }">
        {{ tip ? tip.text : '' }}
      </div>
    </div>
    <div class="lc-tstrip-axis">
      <span v-for="(frac, i) in TICK_FRACS" :key="frac" class="lc-tstrip-tick"
        :class="{ 'lc-tstrip-tick-first': i === 0, 'lc-tstrip-tick-last': i === TICK_FRACS.length - 1 }"
        :style="{ left: `${frac * 100}%` }">{{ frac === 0 ? '0' : fmtDuration(total * frac) }}</span>
    </div>
  </div>
</template>
