<script setup>
// 照搬 dsh-context components/donut.tsx：stroke-dasharray 环图，相邻扇区之间留一条细缝。
import { computed } from 'vue';

const SEG_GAP = 0.5;
const props = defineProps({
  segments: { type: Array, required: true },
  centerTop: [String, Number],
  centerSub: String,
  size: { type: Number, default: 118 },
  hoverKey: { type: String, default: null },
});
const emit = defineEmits(['hover']);
const arcs = computed(() => {
  let total = 0;
  for (const s of props.segments) if (Number.isFinite(s.value) && s.value > 0) total += s.value;
  const result = [];
  let acc = 0;
  if (total > 0) {
    for (const s of props.segments) {
      const v = Number.isFinite(s.value) && s.value > 0 ? s.value : 0;
      if (v === 0) continue;
      const pct = v / total * 100;
      result.push({ key: s.key, color: s.color, len: pct, offset: 100 - acc + 25 });
      acc += pct;
    }
  }
  if (result.length > 1) {
    for (const a of result) {
      const cut = Math.min(SEG_GAP / 2, a.len / 4);
      a.len -= cut * 2;
      a.offset -= cut;
    }
  }
  return result;
});
const hovering = computed(() => props.hoverKey !== null && arcs.value.some(a => a.key === props.hoverKey));
</script>

<template>
  <div class="lc-donut @max-[240px]/lc-card:mx-auto" :class="{ 'lc-donut-dim': hovering }"
    :style="{ width: `${size}px`, height: `${size}px` }" @mouseleave="emit('hover', null)">
    <svg viewBox="0 0 42 42" :width="size" :height="size" aria-hidden="true">
      <circle v-if="!arcs.length" class="lc-donut-track fill-none stroke-4" cx="21" cy="21" r="15.9155" />
      <circle v-for="(a, i) in arcs" v-else :key="a.key"
        class="lc-donut-seg fill-none stroke-4 animate-lc-donut-in motion-reduce:animate-none"
        :class="{ 'lc-donut-seg-on': hoverKey === a.key }" cx="21" cy="21" r="15.9155"
        :stroke-dasharray="`${a.len} ${100 - a.len}`" :stroke-dashoffset="a.offset"
        :style="{ '--lc-i': i, stroke: a.color }" @mouseenter="emit('hover', a.key)" />
    </svg>
    <div class="lc-donut-center">
      <b :style="{ fontSize: `${Math.max(11, Math.round(size * 0.13))}px` }">{{ centerTop }}</b>
      <span v-if="centerSub" :style="{ fontSize: `${Math.max(9, Math.round(size * 0.105))}px` }">{{ centerSub }}</span>
    </div>
  </div>
</template>
