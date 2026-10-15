<script setup>
// 照搬 dsh-context stackedBar.tsx 的 Legend：类别标签 + 估算值 + 占比，delta 模式显示带符号增减。
import { computed } from 'vue';
import { t } from '../i18n.js';
import { catLabel, fmt } from '../kit.js';

const props = defineProps({ parts: { type: Array, required: true }, hoverKey: String, delta: Boolean });
const emit = defineEmits(['hover']);
const total = computed(() => props.parts.reduce((sum, p) => sum + (p.raw ?? p.value), 0));
</script>

<template>
  <div class="lc-legend">
    <span v-for="p in parts" :key="p.key" class="lc-chip" :class="{ 'lc-chip-on': hoverKey === p.key }"
      :title="delta ? undefined : t('overview.ofUsed')" @mouseenter="emit('hover', p.key)" @mouseleave="emit('hover', null)">
      <i :style="{ background: p.color }" />
      <span class="lc-chip-label">{{ p.label ?? catLabel(p.key) }}</span>
      <span class="lc-chip-nums"
        :class="delta && (p.raw ?? p.value) !== 0 ? 'lc-chip-nums-' + ((p.raw ?? p.value) > 0 ? 'up' : 'down') : ''">
        {{ delta ? ((p.raw ?? p.value) > 0 ? '+' : '') + fmt(p.raw ?? p.value) : '≈' + fmt(p.raw ?? p.value) }}
        <em v-if="!delta && total > 0">{{ Math.round((p.raw ?? p.value) / total * 100) }}%</em>
      </span>
    </span>
  </div>
</template>
