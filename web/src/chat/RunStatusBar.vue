<script setup>
// 运行指标状态栏：轮次/步骤 · 生成速率 · Token 总量 · 缓存命中率 · 进度环。
// 纯展示组件，全部数据由 Props 传入，便于在 Agent 运行过程中响应式更新。
import { computed } from 'vue';
import { Timer, Coin } from '@element-plus/icons-vue';
import { formatTokens } from './runMetrics.js';

const props = defineProps({
  rounds: { type: Number, default: 0 },
  steps: { type: Number, default: 0 },
  speed: { type: Number, default: 0 },
  tokens: { type: Number, default: 0 },
  cacheHit: { type: Number, default: null },
  progress: { type: Number, default: 0 },
  running: { type: Boolean, default: false },
});

const RING_RADIUS = 7;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;
const tokenText = computed(() => formatTokens(props.tokens));
const speedText = computed(() => `${Math.max(0, Math.round(props.speed))} tok/s`);
const hitText = computed(() => props.cacheHit === null ? '—' : `${Math.round(props.cacheHit * 100)}%`);
const progressText = computed(() => `${Math.min(100, Math.max(0, Math.round(props.progress)))}%`);
const dashOffset = computed(() =>
  RING_CIRCUMFERENCE * (1 - Math.min(100, Math.max(0, props.progress)) / 100));
</script>

<template>
  <div class="run-status" role="status" aria-label="运行指标">
    <span class="rs-item" title="本轮任务的执行轮次（LLM 调用）与工具步骤数">
      <el-icon :size="13"><Timer /></el-icon>{{ rounds }} 轮 {{ steps }} 步
    </span>
    <span class="rs-item" title="按滑动窗口估算的实时生成速率"><span class="rs-sep">·</span>{{ speedText }}</span>
    <span class="rs-item" title="本次运行消耗的 Token 总量（后端统计，缺失时为估算值）">
      <span class="rs-sep">·</span><el-icon :size="13"><Coin /></el-icon>{{ tokenText }} tok
    </span>
    <span class="rs-item" title="提示词缓存命中占比"><span class="rs-sep">·</span>缓存命中率 {{ hitText }}</span>
    <span class="rs-item" title="任务进度（当前轮次 / 最大轮次上限）">
      <span class="rs-sep">·</span>
      <svg class="rs-ring" :class="{ running }" viewBox="0 0 20 20" aria-hidden="true">
        <circle class="rs-ring-track" cx="10" cy="10" :r="RING_RADIUS" />
        <circle v-if="running" class="rs-ring-spin" cx="10" cy="10" :r="RING_RADIUS" />
        <circle class="rs-ring-arc" cx="10" cy="10" :r="RING_RADIUS"
          :stroke-dasharray="RING_CIRCUMFERENCE" :stroke-dashoffset="dashOffset" />
      </svg>{{ progressText }}
    </span>
  </div>
</template>

<style scoped>
/* 暗色/亮色自适应：跟随系统偏好，同时兼容 Element Plus 的 html.dark 主题类。 */
.run-status {
  --rs-text: #9096a0;
  --rs-icon: #a0a8b4;
  --rs-accent: #0057ff;
  --rs-track: #00000014;
}
/* 兼容 Element Plus 的 html.dark 主题类；系统级暗色由下方媒体查询覆盖。 */
:global(html.dark) .run-status {
  --rs-text: #98a2b3;
  --rs-icon: #8b93a1;
  --rs-accent: #7da2ff;
  --rs-track: #ffffff1f;
}
@media (prefers-color-scheme: dark) {
  .run-status {
    --rs-text: #98a2b3;
    --rs-icon: #8b93a1;
    --rs-accent: #7da2ff;
    --rs-track: #ffffff1f;
  }
}
.run-status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 10px;
  width: 100%;
  max-width: 768px;
  flex-shrink: 0;
  /* 盖过输入框上方的白色渐隐遮罩，避免文字被洗掉 */
  position: relative;
  z-index: 1;
  padding: 0 6px 2px;
  color: var(--rs-text);
  font-size: 12px;
  line-height: 18px;
  user-select: none;
}
.rs-item { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.rs-item .el-icon { color: var(--rs-icon); }
.rs-sep { margin-right: 6px; opacity: .7; }
.rs-ring { width: 14px; height: 14px; transform: rotate(-90deg); }
.rs-ring circle { fill: none; stroke-width: 2.6; }
.rs-ring-track { stroke: var(--rs-track); }
.rs-ring-arc { stroke: var(--rs-accent); stroke-linecap: round; transition: stroke-dashoffset .4s ease; }
.rs-ring-spin { stroke: var(--rs-accent); stroke-linecap: round; stroke-dasharray: 8 36; opacity: .55;
  animation: rs-spin 1.1s linear infinite; transform-origin: center; }
@keyframes rs-spin { to { transform: rotate(360deg); } }
</style>
