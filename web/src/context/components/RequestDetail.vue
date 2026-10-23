<script setup>
// 照搬 dsh-context components/requestDetail.tsx：选中请求的标题行、实际用量指标、三行步骤简报与构成条。
import { computed } from 'vue';
import { t } from '../i18n.js';
import { CATS, cacheHitPercent, catLabel, fmt, fmtTime, partsOf } from '../kit.js';
import { eventAt, eventLabel } from '../trend.js';
import CatLegend from './CatLegend.vue';
import StackedBar from './StackedBar.vue';

const MAX_CHIPS = 3;
const props = defineProps({
  request: Object,
  prev: { type: Object, default: undefined },
  delta: Boolean,
  marker: Object,
  stepsOf: Function,
  hoverKey: { type: String, default: null },
  locatable: Boolean,
});
const emit = defineEmits(['hover', 'locate']);
const req = computed(() => props.request);
const isTurn = computed(() => (req.value?.stepCount ?? 0) > 1);
const head = computed(() => (isTurn.value
  ? t('detail.turn', { t: req.value.turn ?? 0, n: req.value.stepCount })
  : t('detail.step', { t: req.value.turn ?? 0, s: req.value.step ?? 0, n: props.stepsOf?.(req.value.turn) ?? 1 })));
const deltas = computed(() => CATS.map(c => (props.delta ? (req.value[c.key] || 0) - (props.prev ? props.prev[c.key] || 0 : 0) : 0)));
const net = computed(() => deltas.value.reduce((sum, d) => sum + d, 0));
const parts = computed(() => (props.delta
  ? CATS.map((c, i) => ({ key: c.key, color: c.color, value: Math.abs(deltas.value[i]) }))
  : partsOf(req.value)));
const legendParts = computed(() => (props.delta ? parts.value.map((p, i) => ({ ...p, raw: deltas.value[i] })) : parts.value));
const hint = computed(() => (props.locatable ? ' — ' + t('brief.locate') : ''));
const inputs = computed(() => req.value?.brief?.inputs || []);

function chipParts(node) {
  if (node.cat === 'tool') return { tag: node.tool || t('node.toolResult'), text: '' };
  if (node.cat === 'assistant') {
    const names = node.calls || [];
    const text = node.name && !node.name.startsWith('调用 ') ? node.name : '';
    return { tag: names.length ? names.join(' › ') : null, text: text || (names.length ? '' : t('node.empty')) };
  }
  if (node.cat === 'skill') return { tag: catLabel('skill'), text: node.name.replace(/^skill:/, '') };
  if (node.cat === 'inject') return { tag: catLabel('inject'), text: node.name };
  return { tag: null, text: node.name };
}
const response = computed(() => {
  const r = req.value?.response;
  if (!r) return null;
  return { tag: r.calls?.length ? r.calls.join(' › ') : null, text: r.text || '' };
});
function factTitle(tag, text) { return tag !== null ? (text ? tag + '：' + text : tag) : text; }
function locate(cat, isResponse) { if (props.locatable) emit('locate', { seq: req.value.seq, cat, isResponse }); }
</script>

<template>
  <div v-if="req" class="lc-detail">
    <div class="lc-detail-head">
      <b>{{ head }}</b>
      <span v-if="marker && eventAt(marker)" class="lc-detail-marker" :title="eventLabel(marker)">✂ {{ eventAt(marker) }}</span>
      <span v-if="isTurn" class="lc-detail-tag">{{ t('detail.lastStep') }}</span>
      <span v-if="delta" class="lc-detail-tag">{{ t('gran.delta') }}</span>
      <span class="lc-detail-time">{{ fmtTime(req.time) }}</span>
      <span class="lc-detail-metrics">
        <span v-if="delta" class="lc-detail-metric" :class="{ 'lc-detail-metric-up': net > 0, 'lc-detail-metric-down': net < 0 }">
          {{ t('tip.delta', { n: (net > 0 ? '+' : '') + fmt(net) }) }}
        </span>
        <template v-else>
          <span v-if="req.prompt !== undefined" class="lc-detail-metric">{{ t('detail.actual', { n: fmt(req.prompt) }) }}</span>
          <span v-if="req.output !== undefined" class="lc-detail-metric">{{ t('detail.output', { n: fmt(req.output) }) }}</span>
          <span v-if="req.prompt !== undefined && req.cacheRead !== undefined" class="lc-detail-metric">
            {{ t('detail.cache', { n: cacheHitPercent(req.cacheRead, req.prompt) ?? '—' }) }}
          </span>
          <span class="lc-detail-metric">{{ t('detail.estTotal', { n: fmt(req.total) }) }}</span>
        </template>
      </span>
    </div>
    <div class="lc-brief">
      <component :is="locatable ? 'button' : 'div'" v-if="req.brief?.opener" type="button" class="lc-brief-row"
        :class="{ 'lc-brief-row-link hover:bg-(--dsw-alias-interactive-bg-hover)': locatable }" @click="locate('user', false)">
        <span class="lc-brief-tag group/tip">{{ t('brief.turn') }}
          <span class="lc-tip lc-brief-tip group-hover/tip:opacity-100" role="tooltip">{{ t('brief.turnTip') }}</span>
        </span>
        <span class="lc-brief-text" :title="req.brief.opener + hint">{{ req.brief.opener }}</span>
      </component>
      <component :is="locatable && inputs.length ? 'button' : 'div'" type="button" class="lc-brief-row"
        :class="{ 'lc-brief-row-link hover:bg-(--dsw-alias-interactive-bg-hover)': locatable && inputs.length }"
        @click="inputs.length && locate(inputs[0].cat, false)">
        <span class="lc-brief-tag group/tip">{{ t('brief.input') }}
          <span class="lc-tip lc-brief-tip group-hover/tip:opacity-100" role="tooltip">{{ t('brief.inputTip') }}</span>
        </span>
        <template v-if="inputs.length">
          <span v-for="(n, i) in inputs.slice(0, MAX_CHIPS)" :key="i" class="lc-brief-chip"
            :class="{ 'lc-brief-chip-link hover:bg-(--dsw-alias-interactive-bg-hover)': locatable }"
            :title="factTitle(chipParts(n).tag, chipParts(n).text) + hint" @click.stop="locate(n.cat, false)">
            <span v-if="chipParts(n).tag" class="lc-brief-chip-tag">{{ chipParts(n).tag }}</span>
            <span v-if="chipParts(n).text" class="lc-brief-chip-text">{{ chipParts(n).text }}</span>
          </span>
          <span v-if="inputs.length > MAX_CHIPS" class="lc-brief-more">{{ t('brief.more', { n: inputs.length - MAX_CHIPS }) }}</span>
        </template>
        <span v-else class="lc-brief-empty">{{ t('brief.noInputs') }}</span>
      </component>
      <component :is="locatable ? 'button' : 'div'" v-if="response" type="button" class="lc-brief-row"
        :class="{ 'lc-brief-row-link hover:bg-(--dsw-alias-interactive-bg-hover)': locatable }" @click="locate('assistant', true)">
        <span class="lc-brief-tag group/tip">{{ t('brief.reply') }}
          <span class="lc-tip lc-brief-tip group-hover/tip:opacity-100" role="tooltip">{{ t('brief.replyTip') }}</span>
        </span>
        <span class="lc-brief-chip lc-brief-chip-grow" :title="factTitle(response.tag, response.text) + hint">
          <span v-if="response.tag" class="lc-brief-chip-tag">{{ response.tag }}</span>
          <span v-if="response.text" class="lc-brief-chip-text">{{ response.text }}</span>
        </span>
      </component>
    </div>
    <StackedBar :parts="parts" :height="10" :hover-key="hoverKey" :show-tip="false" />
    <CatLegend :parts="legendParts" :hover-key="hoverKey" :delta="delta" @hover="emit('hover', $event)" />
  </div>
</template>
