<script setup>
// 照搬 dsh-context components/heatmap.tsx：按周排列的 8 周活跃热力图，点击日期筛选会话。
import { computed } from 'vue';
import { t } from '../i18n.js';

const WEEKS = 8;
const WEEKDAYS = { 1: '一', 3: '三', 5: '五' };
const props = defineProps({ days: { type: Array, required: true }, metric: { type: String, default: 'requests' }, selected: String });
const emit = defineEmits(['select']);
const keyOf = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
const columns = computed(() => {
  const byKey = Object.fromEntries(props.days.map(d => [d.day, d]));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayKey = keyOf(today);
  const lastSunday = new Date(today);
  lastSunday.setDate(today.getDate() - today.getDay());
  const result = [];
  for (let w = WEEKS - 1; w >= 0; w--) {
    const column = [];
    for (let d = 0; d < 7; d++) {
      const date = new Date(lastSunday);
      date.setDate(lastSunday.getDate() - 7 * w + d);
      const key = keyOf(date);
      const entry = byKey[key];
      column.push({ key, future: key > todayKey, entry: entry && (entry.tokens > 0 || entry.requests > 0) ? entry : undefined });
    }
    result.push(column);
  }
  return result;
});
const max = computed(() => Math.max(0, ...columns.value.flat().map(c => c.entry?.[props.metric] ?? 0)));
function levelOf(value) {
  if (value <= 0 || max.value <= 0) return 0;
  const ratio = value / max.value;
  return ratio <= 0.25 ? 1 : ratio <= 0.5 ? 2 : ratio <= 0.75 ? 3 : 4;
}
const opens = (column, wi) => wi === 0 || column[0].key.slice(0, 7) !== column[6].key.slice(0, 7) || column[0].key.slice(8, 10) === '01';
const tipOf = cell => `${cell.key}\n${cell.entry.sessions} 个活跃会话\n${t('ov.heat.steps', { n: cell.entry.requests })}`;
</script>

<template>
  <div class="lc-heat-wrap">
    <div class="lc-heat" role="group" :aria-label="t('ov.heat.title')">
      <div class="lc-heat-wds" aria-hidden="true"><span v-for="row in 7" :key="row" class="lc-heat-wd">{{ WEEKDAYS[row - 1] ? '周' + WEEKDAYS[row - 1] : '' }}</span></div>
      <div class="lc-heat-cols">
        <div v-for="(column, wi) in columns" :key="wi" class="lc-heat-col">
          <span v-if="opens(column, wi)" class="lc-heat-mon" aria-hidden="true">{{ Number(column[6].key.slice(5, 7)) }}月</span>
          <template v-for="cell in column" :key="cell.key">
            <span v-if="cell.future" class="lc-heat-cell lc-heat-future" aria-hidden="true" />
            <span v-else-if="!cell.entry" class="lc-heat-cell lc-heat-0" :title="cell.key" />
            <button v-else type="button" :class="`lc-heat-cell lc-heat-${levelOf(cell.entry[metric])}${selected === cell.key ? ' lc-heat-on' : ''}`"
              :title="tipOf(cell)" :aria-label="tipOf(cell)" :aria-pressed="selected === cell.key"
              @click="emit('select', selected === cell.key ? null : cell.key)" />
          </template>
        </div>
      </div>
    </div>
    <div class="lc-heat-legend" aria-hidden="true">
      <span class="lc-heat-key">{{ t('ov.heat.less') }}</span>
      <span v-for="level in 5" :key="level" :class="`lc-heat-cell lc-heat-${level - 1}`" />
      <span class="lc-heat-key">{{ t('ov.heat.more') }}</span>
    </div>
  </div>
</template>
