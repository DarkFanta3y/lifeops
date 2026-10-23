<script setup>
// 照搬 dsh-context components/browserTreemap.tsx：两级 squarify 矩形树图，悬停提示、点击打开分类或条目。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { t } from '../i18n.js';
import { CAT_COLOR, catLabel, fmt } from '../kit.js';
import { mapOf, squarify } from '../treemap.js';

const FALLBACK_W = 640;
const FALLBACK_H = 240;
const GAP = 2;
const FRAME = 1;
const PAD = 2;
const HEAD = 16;
const HEAD_MIN_W = 56;
const HEAD_MIN_H = 40;
const LABEL_MIN_W = 42;
const LABEL_MIN_H = 22;
const NUM_MIN_H = 36;
const MIN_RECT = 6;
const TIP_FLIP_Y = 64;

const props = defineProps({ elements: { type: Array, required: true }, openCat: String, hoverKey: String });
const emit = defineEmits(['hover', 'pick-cat', 'pick-block']);
const wrapRef = ref(null);
const tipRef = ref(null);
const size = ref({ w: 0, h: 0 });
const tipKey = ref(null);
const tipShift = ref(0);
const cats = computed(() => mapOf(props.elements));
const total = computed(() => cats.value.reduce((s, c) => s + c.tokens, 0));

const tree = computed(() => {
  const w = size.value.w || FALLBACK_W;
  const h = size.value.h || FALLBACK_H;
  const out = [];
  for (const lc of squarify(cats.value, { x: 0, y: 0, w, h })) {
    const rw = lc.rect.w - GAP;
    const rh = lc.rect.h - GAP;
    if (rw < MIN_RECT || rh < MIN_RECT) continue;
    const showHead = rw >= HEAD_MIN_W && rh >= HEAD_MIN_H;
    const headH = showHead ? HEAD : 0;
    const iw = rw - 2 * FRAME - 2 * PAD;
    const ih = rh - 2 * FRAME - headH - 2 * PAD;
    const blocks = [];
    if (iw >= MIN_RECT && ih >= MIN_RECT) {
      for (const lb of squarify(lc.item.blocks, { x: 0, y: 0, w: iw, h: ih })) {
        const bw = lb.rect.w - GAP;
        const bh = lb.rect.h - GAP;
        if (bw < MIN_RECT || bh < MIN_RECT) continue;
        blocks.push({ b: lb.item, sx: PAD + lb.rect.x, sy: headH + PAD + lb.rect.y, sw: bw, sh: bh,
          px: lc.rect.x + GAP / 2 + FRAME + PAD + lb.rect.x, py: lc.rect.y + GAP / 2 + FRAME + headH + PAD + lb.rect.y });
      }
    }
    out.push({ c: lc.item, x: lc.rect.x + GAP / 2, y: lc.rect.y + GAP / 2, w: rw, h: rh, showHead, blocks });
  }
  return out;
});

const tip = computed(() => {
  if (tipKey.value === null) return null;
  const catHit = tree.value.find(lc => 'cat:' + lc.c.cat === tipKey.value);
  if (catHit) {
    return { head: catLabel(catHit.c.cat), fig: `≈${fmt(catHit.c.tokens)}，${Math.round(catHit.c.tokens / total.value * 100)}% ${t('overview.ofUsed')}`,
      note: t('browser.items', { n: catHit.c.blocks.reduce((s, b) => s + b.count, 0) }),
      cx: catHit.x + catHit.w / 2, top: catHit.y, bottom: catHit.y + catHit.h };
  }
  for (const lc of tree.value) {
    const hit = lc.blocks.find(lb => lb.b.key === tipKey.value);
    if (hit) {
      return { head: hit.b.count > 1 ? `${hit.b.label} ×${hit.b.count}` : hit.b.label,
        fig: `≈${fmt(hit.b.tokens)}，${Math.round(hit.b.tokens / total.value * 100)}% ${t('overview.ofUsed')}`,
        cx: hit.px + hit.sw / 2, top: hit.py, bottom: hit.py + hit.sh };
    }
  }
  return null;
});
watch(tip, async (value) => {
  await nextTick();
  const wrapW = wrapRef.value?.getBoundingClientRect().width || 0;
  const tipW = tipRef.value?.getBoundingClientRect().width || 0;
  if (!value || wrapW <= 0 || tipW <= 0) { tipShift.value = 0; return; }
  const leftOver = tipW / 2 - value.cx;
  const rightOver = value.cx + tipW / 2 - wrapW;
  tipShift.value = leftOver > 0 ? Math.ceil(leftOver) : rightOver > 0 ? Math.ceil(-rightOver) : 0;
});
const tipStyle = computed(() => {
  const value = tip.value;
  if (!value) return { left: '0px', top: '0px' };
  const flip = value.top < TIP_FLIP_Y;
  const shiftX = tipShift.value === 0 ? 'translateX(-50%)'
    : `translateX(calc(-50% ${tipShift.value > 0 ? '+' : '-'} ${Math.abs(tipShift.value)}px))`;
  return { left: `${Math.round(value.cx)}px`, top: flip ? `${Math.round(value.bottom + 4)}px` : `${Math.round(value.top - 4)}px`,
    transform: flip ? shiftX : shiftX + ' translateY(-100%)' };
});

function measure() {
  const el = wrapRef.value;
  if (!el) return;
  const r = el.getBoundingClientRect();
  size.value = { w: Math.round(r.width), h: Math.round(r.height) };
}
function enter(key, cat) { tipKey.value = key; emit('hover', cat); }
function leave() { tipKey.value = null; emit('hover', null); }
let observer;
onMounted(() => {
  measure();
  if (typeof ResizeObserver === 'function' && wrapRef.value) {
    observer = new ResizeObserver(measure);
    observer.observe(wrapRef.value);
  }
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div v-if="!cats.length" class="lc-map-empty">{{ t('browser.mapEmpty') }}</div>
  <div v-else ref="wrapRef" class="lc-map" :class="{ 'lc-map-dim': tip }" @mouseleave="leave">
    <div v-for="lc in tree" :key="lc.c.cat" class="lc-map-cat"
      :class="{ 'lc-map-cat-open': openCat === lc.c.cat, 'lc-map-cat-on': hoverKey === lc.c.cat }"
      :style="{ left: `${lc.x}px`, top: `${lc.y}px`, width: `${lc.w}px`, height: `${lc.h}px`, '--lc-map-c': CAT_COLOR[lc.c.cat] }">
      <button v-if="lc.showHead" type="button" class="lc-map-cat-head" @mouseenter="enter('cat:' + lc.c.cat, lc.c.cat)"
        @click="emit('pick-cat', lc.c.cat)">
        <span class="lc-map-cat-label">{{ catLabel(lc.c.cat) }}</span><b>≈{{ fmt(lc.c.tokens) }}</b>
      </button>
      <button v-for="lb in lc.blocks" :key="lb.b.key" type="button" class="lc-map-block" :class="{ 'lc-map-block-on': tipKey === lb.b.key }"
        :style="{ left: `${lb.sx}px`, top: `${lb.sy}px`, width: `${lb.sw}px`, height: `${lb.sh}px`,
          '--lc-map-a': `${Math.round(14 + 30 * Math.sqrt(lb.b.tokens / lc.c.tokens))}%` }"
        @mouseenter="enter(lb.b.key, lc.c.cat)" @click="emit('pick-block', lc.c.cat, lb.b)">
        <span v-if="lb.sw >= LABEL_MIN_W && lb.sh >= LABEL_MIN_H" class="lc-map-label">
          {{ lb.b.label }}<em v-if="lb.b.count > 1">×{{ lb.b.count }}</em>
        </span>
        <span v-if="lb.sw >= LABEL_MIN_W && lb.sh >= NUM_MIN_H" class="lc-map-num">≈{{ fmt(lb.b.tokens) }}</span>
      </button>
    </div>
    <div ref="tipRef" class="lc-tip lc-map-tip" :class="{ 'lc-map-tip-on': tip }" :role="tip ? 'tooltip' : undefined" :style="tipStyle">
      <template v-if="tip">
        <b class="lc-bar-tip-head">{{ tip.head }}</b>
        <span class="lc-bar-tip-fig">{{ tip.fig }}</span>
        <span v-if="tip.note" class="lc-bar-tip-note">{{ tip.note }}</span>
      </template>
    </div>
  </div>
</template>
