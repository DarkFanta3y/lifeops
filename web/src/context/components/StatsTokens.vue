<script setup>
// 照搬 dsh-context components/statsTokens.tsx：计费总量按构成比例拆分，输出单列，角标为缓存命中率。
import { computed, ref } from 'vue';
import { t } from '../i18n.js';
import { billedParts, cacheHitPercent, catLabel, fmt, fmtShare } from '../kit.js';
import Donut from './Donut.vue';
import SliceList from './SliceList.vue';

const props = defineProps({ usage: Object, current: Object });
const hoverKey = ref(null);
const input = computed(() => (props.usage ? props.usage.uncachedInputTokens + props.usage.cacheReadTokens + props.usage.cacheWriteTokens : 0));
const total = computed(() => input.value + (props.usage?.outputTokens || 0));
const hit = computed(() => (props.usage ? cacheHitPercent(props.usage.cacheReadTokens, input.value) : null));
const shown = computed(() => {
  const parts = billedParts(props.current, props.usage);
  return total.value > 0 ? parts.filter(p => p.value > 0) : parts;
});
const rows = computed(() => shown.value.map(p => ({
  key: p.key, color: p.color,
  label: p.key === 'output' ? t('tokens.output') : catLabel(p.key),
  pct: fmtShare(p.value, total.value),
  count: p.key === 'output' ? `${fmt(p.value)} · ${t('tokens.outputNote')}` : '≈' + fmt(p.value),
})));
</script>

<template>
  <div class="lc-card lc-col-donut flex-1 min-w-[min(360px,100%)]">
    <div class="lc-card-title">
      <span class="lc-card-title-text">{{ t('tokens.title') }}</span>
      <span v-if="hit !== null" class="lc-card-rate" :title="t('stats.cacheHitTip')">{{ t('stats.cacheHit') }} {{ hit }}%</span>
    </div>
    <div v-if="total === 0" class="lc-empty">{{ t('tokens.empty') }}</div>
    <div v-else class="lc-donut-row flex items-center justify-start gap-3 min-w-0 @max-[320px]/lc-card:gap-2 @max-[240px]/lc-card:flex-wrap">
      <Donut :segments="shown" :size="96" :center-top="fmt(total)" :center-sub="t('tokens.total')"
        :hover-key="hoverKey" @hover="hoverKey = $event" />
      <SliceList :rows="rows" :hover-key="hoverKey" @hover="hoverKey = $event" />
    </div>
  </div>
</template>
