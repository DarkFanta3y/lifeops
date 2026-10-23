<script setup>
import { computed, ref } from 'vue';
import { ArrowRight, ArrowDown } from '@element-plus/icons-vue';
import MarkdownRenderer from '../MarkdownRenderer.vue';
import ToolRow from './ToolRow.vue';
import { activitySummary, pendingControl, processEntries } from './toolPresentation.js';
const props = defineProps({ parts: { type: Array, default: () => [] }, mode: String, running: Boolean, status: String, error: String, keepProcessOpen: Boolean });
const emit = defineEmits(['layout']);
function changeLayout(change) { emit('layout', change); }
const turnOpen = ref(null), groups = ref({});
const process = computed(() => props.parts.filter(part => !part.final && (part.kind !== 'text' || part.text)));
const final = computed(() => props.parts.filter(part => part.final && part.text));
const entries = computed(() => processEntries(process.value));
const failed = computed(() => ['failed', 'cancelled', 'incomplete'].includes(props.status));
const canFold = computed(() => !props.running && !failed.value && !process.value.some(pendingControl));
const folded = computed(() => props.mode !== 'detailed' && canFold.value && !(turnOpen.value ?? props.keepProcessOpen));
const title = computed(() => activitySummary(process.value.filter(part => part.kind === 'tool'), props.running));
function groupTitle(entry) { return activitySummary(entry.parts, props.running); }
</script>
<template>
  <div class="activity-turn" :class="{ 'activity-detailed': mode === 'detailed' }">
    <div v-if="process.length" class="activity-turn-head">
      <button v-if="canFold && mode !== 'detailed'" type="button" :aria-expanded="!folded" @click="changeLayout(() => { turnOpen = folded; })">
        <el-icon><ArrowRight v-if="folded" /><ArrowDown v-else /></el-icon><span>工作过程：{{ title }}</span>
      </button>
      <span v-else class="activity-turn-status">{{ running ? '正在处理' : status === 'failed' ? '运行失败' : status === 'cancelled' ? '运行已停止' : status === 'incomplete' ? '过程记录不完整' : '工作过程' }}</span>
    </div>
    <template v-for="entry in entries" :key="entry.key">
      <div v-show="!folded || pendingControl(entry.part || {})" class="activity-entry">
        <MarkdownRenderer v-if="entry.kind === 'text'" :content="entry.part.text" />
        <slot v-else-if="entry.kind === 'control'" name="control" :part="entry.part" />
        <div v-else class="activity-group">
          <button v-show="mode !== 'detailed'" type="button" class="activity-group-head" :aria-expanded="Boolean(groups[entry.key])"
            :title="groupTitle(entry)" @click="changeLayout(() => { groups[entry.key] = !groups[entry.key]; })">
            <el-icon><ArrowDown v-if="groups[entry.key]" /><ArrowRight v-else /></el-icon><span>{{ groupTitle(entry) }}</span>
          </button>
          <div v-show="mode === 'detailed' || groups[entry.key]" class="activity-group-body">
            <ToolRow @layout="changeLayout" v-for="(part, i) in entry.parts" :key="part.callId || part.prepareKey || i" :part="part" />
          </div>
        </div>
      </div>
    </template>
    <p v-if="failed && error" class="activity-error">{{ error }}</p>
    <div data-reading-anchor v-for="(part, index) in final" :key="part.key || `final:${index}`" class="activity-answer"><MarkdownRenderer :content="part.text" /></div>
  </div>
</template>
