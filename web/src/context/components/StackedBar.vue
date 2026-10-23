<script setup>
// 照搬 dsh-context components/stackedBar.tsx：构成条 + 悬停联动提示 + 预留遮罩。
import { computed, nextTick, ref, watch } from 'vue';
import { t } from '../i18n.js';
import { catLabel, fmt } from '../kit.js';

const STAGGER_CAP = 8;
const props = defineProps({
  parts: { type: Array, required: true },
  max: Number,
  height: { type: Number, default: 14 },
  hoverKey: { type: String, default: null },
  pickable: Boolean,
  showTip: { type: Boolean, default: true },
  reserve: Object,
});
const emit = defineEmits(['hover', 'pick']);
const reserveOn = ref(null);
const wrapRef = ref(null);
const tipRef = ref(null);
const tipShift = ref(0);

const total = computed(() => props.parts.reduce((sum, p) => sum + p.value, 0));
const scale = computed(() => (props.max !== undefined && props.max > total.value ? props.max : total.value));
const free = computed(() => (props.max !== undefined && props.max > total.value ? props.max - total.value : 0));
const usedPct = computed(() => (scale.value > 0 ? total.value / scale.value * 100 : 0));
const hovering = computed(() => props.hoverKey !== null && props.hoverKey !== undefined);
const visible = computed(() => (total.value > 0 ? props.parts.filter(p => p.value > 0) : []));
const widths = computed(() => visible.value.map(p => p.value / scale.value * 100));

function trackPct(tokens) {
  return Math.round(Math.max(0, Math.min(100, tokens / scale.value * 100)) * 10) / 10;
}
const win = computed(() => (props.max !== undefined && props.max > 0 ? props.max : undefined));
const masks = computed(() => {
  const reserve = win.value === undefined ? undefined : props.reserve;
  if (!reserve) return [];
  const start = win.value - reserve.output - reserve.headroom;
  const left = trackPct(start);
  const width = trackPct(start + reserve.headroom) - left;
  return width > 0 ? [{ key: 'headroom', label: t('overview.reserveHeadroom'), tokens: reserve.headroom, left, width }] : [];
});

const tip = computed(() => {
  const mask = reserveOn.value === null ? undefined : masks.value.find(m => m.key === reserveOn.value);
  if (mask) {
    return {
      head: mask.label,
      figure: fmt(mask.tokens),
      note: t('overview.reserveHeadroomTip', { p: Math.round(mask.width) }) + '；' + t('overview.reserveHeadroomBuffer'),
      leftPct: mask.left + mask.width / 2,
    };
  }
  if (!hovering.value) return null;
  if (props.hoverKey === 'free' && free.value > 0) {
    const pct = free.value / scale.value * 100;
    return { head: t('overview.free'), figure: `${fmt(free.value)}，${Math.round(pct)}% ${t('overview.ofWindow')}`,
      leftPct: (total.value / scale.value * 100) + pct / 2 };
  }
  let acc = 0;
  const rawTotal = props.parts.reduce((sum, p) => sum + (p.raw ?? p.value), 0);
  for (let i = 0; i < visible.value.length; i++) {
    const p = visible.value[i];
    if (p.key === props.hoverKey) {
      const count = p.raw ?? p.value;
      return {
        head: p.label ?? catLabel(p.key),
        figure: `≈${fmt(count)}，${rawTotal > 0 ? Math.round(count / rawTotal * 100) : 0}% ${t('overview.ofUsed')}`,
        leftPct: acc + widths.value[i] / 2,
      };
    }
    acc += widths.value[i];
  }
  return null;
});

// 提示超出条宽时按像素回拉，保持完整可见。
watch(tip, async (value) => {
  await nextTick();
  const wrapW = wrapRef.value?.getBoundingClientRect().width || 0;
  const tipW = tipRef.value?.getBoundingClientRect().width || 0;
  if (!value || wrapW <= 0 || tipW <= 0) { tipShift.value = 0; return; }
  const center = value.leftPct / 100 * wrapW;
  const leftOver = tipW / 2 - center;
  const rightOver = center + tipW / 2 - wrapW;
  tipShift.value = leftOver > 0 ? Math.ceil(leftOver) : rightOver > 0 ? Math.ceil(-rightOver) : 0;
});
const tipStyle = computed(() => {
  if (!tip.value) return { left: '50%' };
  const shift = tipShift.value === 0 ? {}
    : { transform: `translateX(calc(-50% ${tipShift.value > 0 ? '+' : '-'} ${Math.abs(tipShift.value)}px))` };
  return { left: `${tip.value.leftPct}%`, ...shift };
});

function hover(key) { emit('hover', key); }
function enterReserve(key) { reserveOn.value = key; emit('hover', null); }
function leave() { emit('hover', null); reserveOn.value = null; }
</script>

<template>
  <div ref="wrapRef" class="lc-stacked-wrap">
    <div class="lc-stacked" :class="{ 'lc-stacked-dim': hovering }" :style="{ height: `${height}px` }" @mouseleave="leave">
      <div v-for="(p, i) in visible" :key="p.key"
        class="lc-stacked-seg animate-lc-stacked-in motion-reduce:animate-none"
        :class="{ 'lc-stacked-seg-on': hoverKey === p.key || (p.group && hoverKey === p.group), 'lc-stacked-seg-pick': pickable }"
        :style="{ width: `${widths[i]}%`, backgroundColor: p.color, '--lc-i': Math.min(i, STAGGER_CAP) }"
        @mouseenter="hover(p.key)" @click="pickable && emit('pick', p.key)" />
      <div v-if="free > 0" class="lc-stacked-free animate-lc-stacked-in motion-reduce:animate-none"
        :class="{ 'lc-stacked-free-on': hoverKey === 'free' }"
        :style="{ width: `${free / scale * 100}%`, '--lc-i': Math.min(visible.length, STAGGER_CAP + 1) }"
        @mouseenter="hover('free')" />
      <div v-for="m in masks" :key="m.key" :class="`lc-reserve lc-reserve-${m.key}`"
        :style="{ left: `${m.left}%`, width: `${m.width}%` }"
        @mouseenter="enterReserve(m.key)" @mouseleave="reserveOn = null" />
      <div class="lc-occupied-box" :class="{ 'lc-occupied-box-on': free > 0 && hovering }" :style="{ width: `${usedPct}%` }" />
    </div>
    <div v-if="showTip" ref="tipRef" class="lc-tip lc-bar-tip" :class="{ 'lc-bar-tip-on': tip }"
      :role="tip ? 'tooltip' : undefined" :style="tipStyle">
      <template v-if="tip">
        <b class="lc-bar-tip-head">{{ tip.head }}</b>
        <span class="lc-bar-tip-fig">{{ tip.figure }}</span>
        <span v-if="tip.note" class="lc-bar-tip-note">{{ tip.note }}</span>
      </template>
    </div>
  </div>
</template>
