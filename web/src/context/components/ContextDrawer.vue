<script setup>
// 对话页右侧抽屉：对应 dsh-context 的「上下文 / 编队」两个会话标签页。
import { defineAsyncComponent, ref, watch } from 'vue';
import '../styles/index.js';
import { t } from '../i18n.js';
import ContextPanel from './ContextPanel.vue';

const FleetView = defineAsyncComponent(() => import('./FleetView.vue'));
const props = defineProps({ modelValue: Boolean, conversationId: String, running: Boolean, title: String });
const emit = defineEmits(['update:modelValue']);
const tab = ref('context');
watch(() => props.conversationId, () => { tab.value = 'context'; });
</script>

<template>
  <el-drawer :model-value="modelValue" size="min(1180px, 96vw)" class="lc-drawer" destroy-on-close
    @update:model-value="emit('update:modelValue', $event)">
    <template #header>
      <div class="lc-drawer-head">
        <strong>{{ title || t('cmd.label') }}</strong>
        <span class="lc-gran" role="tablist">
          <button type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': tab === 'context' }" @click="tab = 'context'">上下文</button>
          <button type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': tab === 'fleet' }" @click="tab = 'fleet'">编队</button>
        </span>
      </div>
    </template>
    <template v-if="conversationId">
      <ContextPanel v-if="tab === 'context'" :conversation-id="conversationId" :running="running" @team="tab = 'fleet'" />
      <FleetView v-else :conversation-id="conversationId" :running="running" />
    </template>
    <div v-else class="lc-root"><div class="lc-empty">{{ t('trend.empty') }}</div></div>
  </el-drawer>
</template>
