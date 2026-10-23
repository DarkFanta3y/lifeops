<script setup>
defineProps({
  turns: { type: Array, default: () => [] },
  activeKey: { type: [String, Number], default: null },
});
const emit = defineEmits(['select']);
function previewText(turn) {
  const text = String(turn.preview || '').replace(/\s+/g, ' ').trim();
  if (!text) return '（空消息）';
  return text.length > 200 ? `${text.slice(0, 200)}…` : text;
}
</script>
<template>
  <nav class="turn-nav" aria-label="对话快速导航">
    <el-tooltip v-for="(turn, index) in turns" :key="turn.key" placement="left" effect="light"
      :show-after="120" :hide-after="0" :show-arrow="false" popper-class="turn-nav-popper">
      <template #content>
        <div class="turn-nav-preview">{{ previewText(turn) }}</div>
      </template>
      <button type="button" class="turn-nav-item" :class="{ active: turn.key === activeKey }"
        :aria-label="`第 ${index + 1} 轮：${previewText(turn)}`"
        :aria-current="turn.key === activeKey ? 'true' : undefined" @click="emit('select', turn.key)">
        <span class="turn-nav-bar" aria-hidden="true" />
      </button>
    </el-tooltip>
  </nav>
</template>
<style scoped>
.turn-nav {
  position: absolute;
  top: 50%;
  right: -28px;
  z-index: 4;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  max-height: calc(100% - 32px);
  padding: 4px 0;
  overflow-y: auto;
  scrollbar-width: none;
  transform: translateY(-50%);
}
.turn-nav::-webkit-scrollbar { width: 0; height: 0; }
.turn-nav-item {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: flex-end;
  width: 26px;
  height: 8px;
  padding: 0;
  border: 0;
  background: transparent;
}
.turn-nav-bar {
  width: 12px;
  height: 2px;
  border-radius: 2px;
  background: var(--slate-5, #d9d9e0);
  transition: width .2s ease-out, background-color .2s ease-out;
}
.turn-nav-item:hover .turn-nav-bar { width: 16px; background: var(--slate-8, #b9bbc6); }
.turn-nav-item.active .turn-nav-bar { width: 18px; height: 3px; background: var(--el-color-primary); }
.turn-nav-item:focus-visible { border-radius: 4px; outline: 2px solid var(--el-color-primary); outline-offset: 0; }
@media (prefers-reduced-motion: reduce) { .turn-nav-bar { transition: none; } }
/* 聊天内容两侧没有余量时隐藏，避免小横条压住正文。 */
@container (max-width: 840px) { .turn-nav { display: none; } }
</style>
