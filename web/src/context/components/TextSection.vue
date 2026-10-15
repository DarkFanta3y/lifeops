<script setup>
// 照搬 dsh-context browserToolCard.tsx 的 TextSection：带行号的原文 / Markdown 切换、复制与行数。
import { computed, ref } from 'vue';
import MarkdownRenderer from '../../MarkdownRenderer.vue';
import { t } from '../i18n.js';

const props = defineProps({ label: String, text: { type: String, default: '' }, markdown: Boolean, clipped: Number });
const mode = ref(props.markdown ? 'md' : 'raw');
const copied = ref(false);
const lines = computed(() => props.text.split(/\r\n|\r|\n/));
async function copy() {
  try {
    await navigator.clipboard.writeText(props.text);
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 1200);
  } catch { /* 剪贴板不可用时静默 */ }
}
</script>

<template>
  <div class="lc-ts-card">
    <div class="lc-ts-card-head lc-ts-card-head-wrap">
      <b :title="label">{{ label }}</b>
      <span class="lc-ts-card-right">
        <span class="lc-ts-card-meta">{{ t('block.lines', { n: lines.length }) }}</span>
        <span class="lc-gran">
          <button type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': mode === 'raw' }" @click="mode = 'raw'">{{ t('rich.raw') }}</button>
          <button type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': mode === 'md' }" @click="mode = 'md'">{{ t('rich.md') }}</button>
        </span>
        <button type="button" class="lc-rich-copy" :class="{ 'lc-rich-copy-on': copied }" :title="t('rich.copy')" @click="copy">
          {{ copied ? t('rich.copied') : t('rich.copy') }}
        </button>
      </span>
    </div>
    <div v-if="clipped" class="lc-br-note">{{ t('browser.clipped', { n: text.length }) }}</div>
    <div v-if="mode === 'md'" class="lc-ts-desc-md"><MarkdownRenderer :content="text" /></div>
    <pre v-else class="lc-ts-desc-body lc-ts-lines"><span v-for="(line, i) in lines" :key="i" class="lc-ts-line">{{ line }}</span></pre>
  </div>
</template>
