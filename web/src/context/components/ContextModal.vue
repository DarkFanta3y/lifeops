<script setup>
// 照搬 dsh-context components/contextModal.tsx：/context 命令弹出的当前构成 + 上下文浏览器。
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { fetchContextHead } from '../../api.js';
import '../styles/index.js';
import { t } from '../i18n.js';
import { headlineOf } from '../kit.js';
import { turnStepsOf } from '../trend.js';
import ContextBrowser from './ContextBrowser.vue';
import CurrentComposition from './CurrentComposition.vue';

const props = defineProps({ modelValue: Boolean, conversationId: String });
const emit = defineEmits(['update:modelValue']);
const data = ref(null);
const error = ref('');
const hoverCat = ref(null);
const head = computed(() => (data.value ? headlineOf(data.value) : null));
const stepsOf = computed(() => turnStepsOf(data.value?.requests || []));
function close() { emit('update:modelValue', false); }
function onKey(event) { if (event.key === 'Escape') close(); }
watch(() => [props.modelValue, props.conversationId], async ([open, id]) => {
  window.removeEventListener('keydown', onKey, true);
  if (!open) return;
  window.addEventListener('keydown', onKey, true);
  data.value = null;
  error.value = '';
  if (!id) return;
  try { data.value = await fetchContextHead(id); } catch (err) { error.value = err.message; }
}, { immediate: true });
onBeforeUnmount(() => window.removeEventListener('keydown', onKey, true));
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="lc-modal-backdrop" @click="close">
      <div class="lc-modal-card" @click.stop>
        <div class="lc-modal-head">
          <span class="lc-modal-title">{{ t('cmd.label') }}</span>
          <button class="lc-modal-close hover:text-(--dsw-alias-label-primary) hover:bg-(--dsw-alias-bg-layer-2)"
            :aria-label="t('cmd.close')" @click="close">×</button>
        </div>
        <div v-if="!conversationId" class="lc-empty">{{ t('trend.empty') }}</div>
        <div v-else-if="error" class="lc-empty">{{ t('error') }}{{ error }}</div>
        <div v-else-if="!data || !head" class="lc-empty">{{ t('loading') }}</div>
        <div v-else>
          <CurrentComposition :head="head" :subtitle="data.model || ''" :hover-key="hoverCat" @hover="hoverCat = $event" />
          <ContextBrowser :requests="data.requests" :steps-of="stepsOf" :hover-key="hoverCat" @hover="hoverCat = $event" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
