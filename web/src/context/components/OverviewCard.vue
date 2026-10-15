<script setup>
// 照搬 dsh-context components/overviewCard.tsx：会话画像卡片（构成环 + 轮次 / 用量 / 费用）。
import { t } from '../i18n.js';
import { fmt, fmtAgo, fmtCost, fmtShare, partsOf } from '../kit.js';
import Donut from './Donut.vue';

defineProps({ row: { type: Object, required: true }, now: Number });
const emit = defineEmits(['open']);
</script>

<template>
  <button type="button" class="lc-ov-session" @click="emit('open', row.conversationId)">
    <span class="lc-ov-session-head">
      <span class="lc-ov-session-title" :title="row.title">{{ row.title }}</span>
      <span class="lc-ov-session-times"><span class="lc-ov-session-time">{{ fmtAgo(row.lastActive, now) }}</span></span>
    </span>
    <span class="lc-ov-session-body">
      <Donut :size="64" :segments="partsOf(row.current)" :center-top="fmt(row.current.total)"
        :center-sub="row.window ? fmtShare(row.current.total, row.window) : undefined" />
      <span class="lc-ov-mini-stats">
        <span class="lc-ov-mini-stat"><span class="lc-ov-mini-label">{{ t('stats.turns') }}</span>
          <span class="lc-ov-mini-value">{{ t('ov.card.turns', { n: row.runs, s: row.requests }) }}</span></span>
        <span class="lc-ov-mini-stat"><span class="lc-ov-mini-label">{{ t('ov.usage.tokens') }}</span>
          <span class="lc-ov-mini-value">{{ fmt(row.billed) }}</span></span>
        <span class="lc-ov-mini-stat"><span class="lc-ov-mini-label">{{ t('stats.cost') }}</span>
          <span class="lc-ov-mini-value">{{ fmtCost(row.cost) }}</span></span>
      </span>
    </span>
  </button>
</template>
