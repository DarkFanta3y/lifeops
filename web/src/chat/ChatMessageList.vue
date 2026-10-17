<script setup>
// 自己拥有滚动跟随，避免上游 BubbleList 在折叠/切换模式时强制滚到底部。
import { nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue';
import Bubble from '@element-plus-x/Bubble/index.js';
const props = defineProps({ list: { type: Array, default: () => [] } });
const emit = defineEmits(['turn-change']);
const viewport = ref(null), body = ref(null), following = ref(true), showBack = ref(false);
let observer, preserving = 0, lastTop = 0, measureFrame = 0, activeTurn = null;
function turnAnchors() {
  return viewport.value ? [...viewport.value.querySelectorAll('[data-turn-key]')] : [];
}
// 以滚动区顶部往下约 1/4（最多 140px）为判定线：最后一条越过判定线的用户提问即当前轮次。
// 滚到底部时直接高亮最后一轮，避免长回答下方没有下一条提问时高亮停留在上一轮。
function measureTurn() {
  const element = viewport.value;
  if (!element) return;
  const anchors = turnAnchors();
  if (!anchors.length) return setActiveTurn(null);
  const distance = element.scrollHeight - element.clientHeight - element.scrollTop;
  if (distance <= 4) return setActiveTurn(anchors.at(-1).dataset.turnKey);
  const top = element.getBoundingClientRect().top;
  const line = Math.min(140, Math.max(48, element.clientHeight * 0.25));
  let current = anchors[0];
  for (const anchor of anchors) {
    if (anchor.getBoundingClientRect().top - top <= line) current = anchor;
    else break;
  }
  setActiveTurn(current.dataset.turnKey);
}
function setActiveTurn(key) {
  if (key === activeTurn) return;
  activeTurn = key;
  emit('turn-change', key);
}
function scheduleMeasure() {
  if (measureFrame) return;
  measureFrame = requestAnimationFrame(() => { measureFrame = 0; measureTurn(); });
}
function onScroll() {
  const element = viewport.value;
  if (!element || preserving) return;
  const distance = element.scrollHeight - element.clientHeight - element.scrollTop;
  showBack.value = distance > 80;
  if (element.scrollTop < lastTop || distance < 25) following.value = distance < 25;
  lastTop = element.scrollTop;
  scheduleMeasure();
}
function wheel(event) { if (event.deltaY < 0) following.value = false; }
function keyboard(event) { if (['ArrowUp', 'PageUp', 'Home'].includes(event.key)) following.value = false; }
async function scrollToBottom() {
  await nextTick();
  if (!viewport.value) return;
  viewport.value.scrollTop = viewport.value.scrollHeight;
  lastTop = viewport.value.scrollTop; following.value = true; showBack.value = false;
}
// 点击导航条时把对应提问滚到滚动区顶部附近，并暂停自动跟随，避免阅读位置被新输出拉走。
function scrollToKey(key) {
  const element = viewport.value;
  if (!element) return;
  const target = turnAnchors().find(anchor => anchor.dataset.turnKey === String(key));
  if (!target) return;
  const top = element.scrollTop + target.getBoundingClientRect().top - element.getBoundingClientRect().top - 20;
  following.value = false;
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  element.scrollTo({ top: Math.max(0, top), behavior: reduceMotion ? 'auto' : 'smooth' });
  lastTop = element.scrollTop;
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
  measureTurn();
});
onBeforeUnmount(() => {
  observer?.disconnect();
  if (measureFrame) cancelAnimationFrame(measureFrame);
});
watch(() => props.list.length, async () => { await nextTick(); scheduleMeasure(); });
defineExpose({ scrollToBottom, scrollToTop, scrollToKey, preserveLayout, isFollowing: () => following.value });
</script>
<template>
  <div ref="viewport" class="el-bubble-list lifeops-message-list" tabindex="0" aria-label="对话记录"
    @scroll.passive="onScroll" @wheel.passive="wheel" @keydown="keyboard">
    <div ref="body">
      <Bubble v-for="item in props.list" :key="item.key" :content="item.content" :placement="item.placement"
        :loading="item.loading" :no-style="item.noStyle" :typing="false">
        <template #content><div data-reading-anchor :data-turn-key="item.role === 'user' ? String(item.key) : undefined"><slot name="content" :item="item" /></div></template>
        <template #footer><slot name="footer" :item="item" /></template>
      </Bubble>
    </div>
    <button v-if="showBack" type="button" class="activity-back-bottom" @click="scrollToBottom">回到最新</button>
  </div>
</template>
