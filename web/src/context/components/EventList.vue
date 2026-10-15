<script setup>
// 照搬 dsh-context components/events.tsx：倒序事件列表，按类别着色，注入事件可跳到上下文浏览器。
import { t } from '../i18n.js';
import { fmt, fmtTime } from '../kit.js';
import { eventAt, eventLabel } from '../trend.js';

const EVENT_ICONS = { compaction: '✂', prune: '✂', mode: '⇄', inject: '+', model: '⎇' };
const props = defineProps({ events: { type: Array, required: true } });
const emit = defineEmits(['focus']);
const labelClass = 'lc-event-label flex-1 @max-[380px]/lc-card:basis-[calc(100%-92px)]';
</script>

<template>
  <div v-if="!events.length" class="lc-empty lc-lane">{{ t('events.empty') }}</div>
  <div v-else class="lc-events">
    <div v-for="ev in events.slice().reverse()" :key="ev.seq" class="lc-event @max-[380px]/lc-card:flex-wrap">
      <span :class="'lc-event-icon lc-event-' + ev.kind">{{ EVENT_ICONS[ev.kind] || '•' }}</span>
      <span :class="'lc-kind lc-kind-' + ev.kind">{{ t('kind.' + ev.kind) }}</span>
      <button v-if="ev.kind === 'inject' && typeof ev.step === 'number'" type="button" :class="labelClass + ' lc-event-jump'"
        :title="eventLabel(ev)" @click="emit('focus', ev)">{{ eventLabel(ev) }}</button>
      <span v-else :class="labelClass" :title="eventLabel(ev)">{{ eventLabel(ev) }}</span>
      <span v-if="eventAt(ev)" class="lc-event-at">{{ eventAt(ev) }}</span>
      <span v-if="ev.tokens" class="lc-event-tokens" :class="ev.kind === 'inject' ? 'lc-up' : 'lc-down'">
        {{ (ev.kind === 'inject' ? '+' : '−') + fmt(ev.tokens) }}
      </span>
      <span class="lc-event-time">{{ fmtTime(ev.time) }}</span>
    </div>
  </div>
</template>
