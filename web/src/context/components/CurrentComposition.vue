<script setup>
// 照搬 dsh-context components/currentComposition.tsx：当前上下文总量 / 窗口 / 占用率 + 构成条与图例。
import { t } from '../i18n.js';
import { fmt } from '../kit.js';
import CatLegend from './CatLegend.vue';
import StackedBar from './StackedBar.vue';

defineProps({ head: { type: Object, required: true }, subtitle: String, hoverKey: { type: String, default: null } });
const emit = defineEmits(['hover']);
</script>

<template>
  <div class="lc-card" data-lc-current>
    <div class="lc-card-title">
      <span class="lc-card-title-text">{{ t('overview.title') }}</span>
      <span v-if="subtitle" class="lc-card-sub">{{ subtitle }}</span>
    </div>
    <div class="lc-overview-num">
      <b>{{ fmt(head.tokens) }}</b>
      <span>{{ head.window ? ' / ' + fmt(head.window) + ' tokens' : ' ' + t('overview.estimate') }}</span>
      <span v-if="head.pct !== null" class="lc-overview-pct"><b>{{ head.pct.toFixed(1) }}%</b>{{ t('overview.used') }}</span>
    </div>
    <StackedBar :parts="head.parts" :height="16" :max="head.window" :hover-key="hoverKey" :reserve="head.reserve"
      @hover="emit('hover', $event)" />
    <CatLegend :parts="head.parts" :hover-key="hoverKey" @hover="emit('hover', $event)" />
  </div>
</template>
