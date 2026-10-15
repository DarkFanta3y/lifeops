<script setup>
// 照搬 dsh-context components/fileCard.tsx：按文件聚合的读/写/搜索，筛选、排序、行数增删与逐次操作跳转。
import { computed, ref } from 'vue';
import { t } from '../i18n.js';
import { fmt, fmtTime } from '../kit.js';
import { aggregateOps, displayPathOf, glyphOf } from '../fileActivity.js';

const props = defineProps({ ops: { type: Array, default: () => [] }, before: { type: Number, default: null },
  scope: String, workspace: String });
const emit = defineEmits(['locate']);
const filter = ref('all');
const sort = ref('count');
const query = ref('');
const openPath = ref(null);
const activity = computed(() => aggregateOps(props.ops, props.before));
const displayOf = e => (e.pattern ? e.path : displayPathOf(e.path, props.workspace));
const countOf = e => (filter.value === 'read' ? e.reads : filter.value === 'write' ? e.writes : filter.value === 'search' ? e.searches : e.ops.length);
function matches(e) {
  if (filter.value === 'all') return true;
  if (filter.value === 'read') return e.reads > 0;
  if (filter.value === 'write') return e.writes > 0;
  return e.searches > 0;
}
const shown = computed(() => {
  const q = query.value.trim().toLowerCase();
  return activity.value.entries
    .filter(e => matches(e) && (!q || displayOf(e).toLowerCase().includes(q)))
    .sort((a, b) => (sort.value === 'count' ? (countOf(b) - countOf(a)) || (b.ops[0].seq - a.ops[0].seq)
      : sort.value === 'latest' ? b.ops[0].seq - a.ops[0].seq : (a.path < b.path ? -1 : 1)));
});
const chips = computed(() => {
  const totals = activity.value.totals;
  return [
    { key: 'all', files: activity.value.entries.length, ops: totals.read.ops + totals.write.ops + totals.search.ops },
    { key: 'read', files: totals.read.files, ops: totals.read.ops },
    { key: 'write', files: totals.write.files, ops: totals.write.ops },
    { key: 'search', files: totals.search.files, ops: totals.search.ops },
  ];
});
function split(e) {
  const display = displayOf(e);
  const trimmed = display.endsWith('/') ? display.slice(0, -1) : display;
  const slash = trimmed.lastIndexOf('/');
  return { dir: slash >= 0 ? trimmed.slice(0, slash + 1) : '', base: slash >= 0 ? trimmed.slice(slash + 1) : trimmed };
}
</script>

<template>
  <div class="lc-card lc-col flex-1 min-w-[min(360px,100%)]">
    <div class="lc-card-title">
      <span class="lc-card-title-text">{{ t('files.title') }}</span>
      <span class="lc-card-sub">{{ scope || t('files.scopeLatest') }}</span>
    </div>
    <div>
      <div class="lc-fa-ctl">
        <div class="lc-gran @max-[380px]/lc-card:flex-wrap">
          <button v-for="c in chips" :key="c.key" type="button" class="lc-gran-btn"
            :class="[{ 'lc-gran-on': filter === c.key }, c.key !== 'all' ? 'lc-fa-chip-' + c.key : '']"
            :title="t('files.chipTip', { files: c.files, ops: c.ops })" @click="filter = filter === c.key ? 'all' : c.key">
            {{ t('files.kind.' + c.key) }}<b class="lc-fa-n">{{ fmt(c.ops) }}</b>
          </button>
        </div>
        <input v-model="query" class="lc-fa-search" :placeholder="t('files.search')" />
      </div>
      <div class="lc-fa-meta">
        <span>{{ t('files.files', { n: activity.entries.length }) }}</span>
        <span v-if="activity.totals.added + activity.totals.removed > 0" class="lc-fa-meta-delta group/tip">
          <span class="lc-fa-delta">
            <span v-if="activity.totals.added > 0" class="lc-fa-up">+{{ fmt(activity.totals.added) }}</span>
            <span v-if="activity.totals.removed > 0" class="lc-fa-down">−{{ fmt(activity.totals.removed) }}</span>
          </span>
          <span class="lc-tip lc-fa-meta-tip group-hover/tip:opacity-100" role="tooltip">{{ t('files.deltaTip') }}</span>
        </span>
        <span class="lc-gran lc-fa-sort" role="group" :title="t('files.sortTip')">
          <button v-for="k in ['count', 'latest', 'path']" :key="k" type="button" class="lc-gran-btn"
            :class="{ 'lc-gran-on': sort === k }" @click="sort = k">{{ t('files.sort.' + k) }}</button>
        </span>
      </div>
      <div v-if="!shown.length" class="lc-empty lc-lane">{{ t(activity.entries.length ? 'files.noMatch' : 'files.empty') }}</div>
      <div v-else class="lc-fa-list">
        <div v-for="e in shown" :key="e.path" class="lc-fa-item" :class="{ 'lc-fa-item-on': openPath === e.path }">
          <button type="button" class="lc-fa-row hover:bg-(--dsw-alias-interactive-bg-hover) @max-[380px]/lc-card:flex-wrap"
            :title="e.path" @click="openPath = openPath === e.path ? null : e.path">
            <span class="lc-br-chev" :class="{ 'lc-br-chev-on': openPath === e.path }" />
            <span class="lc-fa-form" :title="t(glyphOf(e.path, e.form).tip)">
              <span v-if="glyphOf(e.path, e.form).color" class="lc-fa-lang"
                :style="{ background: glyphOf(e.path, e.form).color, color: glyphOf(e.path, e.form).text }">{{ glyphOf(e.path, e.form).glyph }}</span>
              <template v-else>{{ glyphOf(e.path, e.form).glyph }}</template>
            </span>
            <span class="lc-fa-path flex-1 @max-[380px]/lc-card:basis-[calc(100%-46px)]">
              <em v-if="split(e).dir">{{ split(e).dir }}</em><b>{{ split(e).base }}</b>
            </span>
            <span v-if="e.reads" class="lc-fa-badge lc-fa-b-read" :title="t('files.kind.read')"><i />{{ fmt(e.reads) }}</span>
            <span v-if="e.writes" class="lc-fa-badge lc-fa-b-write" :title="t('files.kind.write')"><i />{{ fmt(e.writes) }}</span>
            <span v-if="e.searches" class="lc-fa-badge lc-fa-b-search" :title="t('files.kind.search')"><i />{{ fmt(e.searches) }}</span>
            <span v-if="e.added + e.removed > 0" class="lc-fa-delta">
              <span v-if="e.added" class="lc-fa-up">+{{ fmt(e.added) }}</span><span v-if="e.removed" class="lc-fa-down">−{{ fmt(e.removed) }}</span>
            </span>
            <span v-if="e.errs" class="lc-br-err-dot" :title="t('files.errs', { n: e.errs })" />
            <span v-if="e.ops[0].time" class="lc-fa-time">{{ fmtTime(e.ops[0].time) }}</span>
          </button>
          <div v-if="openPath === e.path" class="lc-fa-ops">
            <component :is="op.snapshot ? 'button' : 'div'" v-for="(op, i) in e.ops" :key="`${op.seq}:${i}`" type="button"
              class="lc-fa-op" :class="{ 'lc-fa-op-link hover:bg-(--dsw-alias-interactive-bg-hover)': op.snapshot }"
              :title="op.snapshot ? t('files.locate') : undefined" @click="op.snapshot && emit('locate', op)">
              <span class="lc-fa-op-tool" :title="op.tool">{{ op.tool }}</span>
              <span v-if="op.read" class="lc-fa-read"
                :title="t('files.readTip', { a: fmt(op.read.start), b: fmt(op.read.start + op.read.count - 1) })">>>{{ fmt(op.read.count) }}</span>
              <span v-if="op.detail" class="lc-fa-op-detail">{{ op.detail }}</span>
              <span v-if="op.hits" class="lc-fa-op-detail">{{ t('files.hits', { n: fmt(op.hits) }) }}</span>
              <span v-if="op.added + op.removed > 0" class="lc-fa-delta">
                <span v-if="op.added" class="lc-fa-up">+{{ fmt(op.added) }}</span><span v-if="op.removed" class="lc-fa-down">−{{ fmt(op.removed) }}</span>
              </span>
              <span v-if="op.err" class="lc-br-err-dot" />
              <span class="lc-fa-op-time">{{ op.time ? fmtTime(op.time) : '—' }}</span>
            </component>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
