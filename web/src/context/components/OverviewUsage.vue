<script setup>
// 照搬 dsh-context components/overviewUsage.tsx：近 7 天 Token / 费用双柱图，左右各一条刻度轴。
import { computed } from 'vue';
import { t } from '../i18n.js';
import { fmt, fmtCost } from '../kit.js';

const TICKS = [0, 25, 50, 75, 100];
const props = defineProps({ days: { type: Array, required: true } });
const empty = computed(() => props.days.every(d => d.tokens <= 0 && d.cost === null));
const maxTokens = computed(() => Math.max(0, ...props.days.map(d => d.tokens)));
const maxCost = computed(() => Math.max(0, ...props.days.map(d => d.cost ?? 0)));
const heightOf = (value, max) => (max <= 0 || value <= 0 ? '0%' : `${Math.max(4, Math.round((value / max) * 100))}%`);
const costTick = p => (maxCost.value <= 0 ? '—' : p === 0 ? '0' : fmtCost((maxCost.value * p) / 100));
</script>

<template>
  <div class="lc-card lc-ov-usage">
    <div class="lc-card-title"><span class="lc-card-title-text">{{ t('ov.usage.title') }}</span></div>
    <div v-if="empty" class="lc-empty">{{ t('ov.usage.empty') }}</div>
    <div v-else class="lc-ov-usage-plot" role="group" :aria-label="t('ov.usage.title')">
      <div class="lc-ov-usage-rail lc-ov-usage-rail-l" aria-hidden="true">
        <span v-for="p in TICKS" :key="p" class="lc-ov-usage-tick" :style="{ top: `${100 - p}%` }">{{ fmt(Math.round(maxTokens * p / 100)) }}</span>
      </div>
      <div class="lc-ov-usage-grid">
        <div class="lc-ov-usage-cols">
          <span v-for="p in TICKS" :key="p" class="lc-ov-usage-line" :class="{ 'lc-ov-usage-line-0': p === 0 }" :style="{ bottom: `${p}%` }" aria-hidden="true" />
          <div v-for="d in days" :key="d.day" class="lc-ov-usage-col"
            :title="`${d.day}\n${t('ov.usage.tokens')} ${fmt(d.tokens)}\n${t('ov.usage.cost')} ${fmtCost(d.cost)}`">
            <div class="lc-ov-usage-bars">
              <span class="lc-ov-usage-bar lc-ov-usage-tokens" :style="{ height: heightOf(d.tokens, maxTokens) }">
                <span v-if="d.tokens > 0" class="lc-ov-usage-value">{{ fmt(d.tokens) }}</span>
              </span>
              <span class="lc-ov-usage-bar lc-ov-usage-cost" :style="{ height: d.cost === null ? '0%' : heightOf(d.cost, maxCost) }" />
            </div>
          </div>
        </div>
      </div>
      <div class="lc-ov-usage-rail lc-ov-usage-rail-r" aria-hidden="true">
        <span v-for="p in TICKS" :key="p" class="lc-ov-usage-tick" :style="{ top: `${100 - p}%` }">{{ costTick(p) }}</span>
      </div>
      <div class="lc-ov-usage-days" aria-hidden="true">
        <span v-for="d in days" :key="d.day" class="lc-ov-usage-day">{{ d.day.slice(5) }}</span>
      </div>
    </div>
    <div class="lc-ov-usage-key" aria-hidden="true">
      <span class="lc-ov-usage-swatch lc-ov-usage-tokens" /><span class="lc-ov-usage-key-label">{{ t('ov.usage.tokens') }}</span>
      <span class="lc-ov-usage-swatch lc-ov-usage-cost" /><span class="lc-ov-usage-key-label">{{ t('ov.usage.cost') }}</span>
    </div>
  </div>
</template>
