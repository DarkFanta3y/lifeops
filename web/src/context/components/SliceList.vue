<script setup>
// 照搬 dsh-context components/sliceList.tsx：环图图例行，与扇区双向悬停联动。
defineProps({ rows: { type: Array, required: true }, hoverKey: { type: String, default: null } });
const emit = defineEmits(['hover']);
</script>

<template>
  <div class="lc-sl flex-auto @max-[240px]/lc-card:basis-full" @mouseleave="emit('hover', null)">
    <div v-for="r in rows" :key="r.key" class="lc-sl-row"
      :class="{ 'lc-sl-row-dim': r.dim, 'lc-sl-row-on': hoverKey === r.key }" @mouseenter="emit('hover', r.key)">
      <div class="lc-sl-main">
        <i class="lc-sl-dot" :style="{ background: r.color }" />
        <span class="lc-sl-label" :title="r.label">{{ r.label }}</span>
        <span class="lc-sl-pct">{{ r.pct }}</span>
      </div>
      <div v-if="r.count" class="lc-sl-sub" :title="r.count">{{ r.count }}</div>
    </div>
  </div>
</template>
