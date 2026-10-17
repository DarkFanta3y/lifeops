<script setup>
// 自己拥有滚动跟随，避免上游 BubbleList 在折叠/切换模式时强制滚到底部。
import { nextTick, onMounted, onBeforeUnmount, ref } from 'vue';
import Bubble from '@element-plus-x/Bubble/index.js';
const props = defineProps({ list: { type: Array, default: () => [] } });
const viewport = ref(null), body = ref(null), following = ref(true), showBack = ref(false);
let observer, preserving = 0, lastTop = 0;
function onScroll() {
  const element = viewport.value;
  if (!element || preserving) return;
  const distance = element.scrollHeight - element.clientHeight - element.scrollTop;
  showBack.value = distance > 80;
  if (element.scrollTop < lastTop || distance < 25) following.value = distance < 25;
  lastTop = element.scrollTop;
}
function wheel(event) { if (event.deltaY < 0) following.value = false; }
function keyboard(event) { if (['ArrowUp', 'PageUp', 'Home'].includes(event.key)) following.value = false; }
async function scrollToBottom() {
  await nextTick();
  if (!viewport.value) return;
  viewport.value.scrollTop = viewport.value.scrollHeight;
  lastTop = viewport.value.scrollTop; following.value = true; showBack.value = false;
}
async function preserveLayout(change) {
  const element = viewport.value;
  if (!element) { change(); return; }
  const top = element.scrollTop, wasFollowing = following.value;
  const rect = element.getBoundingClientRect();
  const anchors = [...element.querySelectorAll('[data-reading-anchor]')]
    .map(node => ({ node, top: node.getBoundingClientRect().top }))
    .filter(item => item.top >= rect.top && item.top < rect.bottom);
  preserving += 1;
  change();
  await nextTick();
  const anchor = anchors.find(item => item.node.isConnected && item.node.getClientRects().length);
  element.scrollTop = anchor ? top + anchor.node.getBoundingClientRect().top - anchor.top : top;
  lastTop = element.scrollTop;
  await new Promise(resolve => requestAnimationFrame(resolve));
  preserving -= 1; following.value = wasFollowing;
}
function scrollToTop() { following.value = false; if (viewport.value) viewport.value.scrollTop = 0; }
onMounted(() => {
  observer = new ResizeObserver(() => {
    if (!preserving && following.value && viewport.value) {
      viewport.value.scrollTop = viewport.value.scrollHeight;
      lastTop = viewport.value.scrollTop;
    }
  });
  observer.observe(body.value);
});
onBeforeUnmount(() => observer?.disconnect());
defineExpose({ scrollToBottom, scrollToTop, preserveLayout, isFollowing: () => following.value });
</script>
<template>
  <div ref="viewport" class="el-bubble-list lifeops-message-list" tabindex="0" aria-label="对话记录"
    @scroll.passive="onScroll" @wheel.passive="wheel" @keydown="keyboard">
    <div ref="body">
      <Bubble v-for="item in props.list" :key="item.key" :content="item.content" :placement="item.placement"
        :loading="item.loading" :no-style="item.noStyle" :typing="false">
        <template #content><div data-reading-anchor><slot name="content" :item="item" /></div></template>
        <template #footer><slot name="footer" :item="item" /></template>
      </Bubble>
    </div>
    <button v-if="showBack" type="button" class="activity-back-bottom" @click="scrollToBottom">回到最新</button>
  </div>
</template>
