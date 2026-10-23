<script setup>
// 照搬 dsh-context components/browser.tsx（不含 DNA、附件）：任选一次请求，按七类展开为元素行，再展开为实际内容。
import { computed, nextTick, ref, watch } from 'vue';
import { fetchContextSnapshot } from '../../api.js';
import { t } from '../i18n.js';
import { CATS, catLabel, fmt, fmtTime, partsOf } from '../kit.js';
import BrowserTreemap from './BrowserTreemap.vue';
import StackedBar from './StackedBar.vue';
import TextSection from './TextSection.vue';

const ROW_KINDS = ['thinking', 'tools', 'answer'];
const props = defineProps({
  requests: { type: Array, required: true },
  stepsOf: { type: Function, required: true },
  previewSeq: { type: Number, default: null },
  pinSeq: { type: Number, default: null },
  focus: { type: Object, default: null },
  hoverKey: { type: String, default: null },
  title: { type: String, default: '' },
});
const emit = defineEmits(['hover', 'open-cat', 'focus-handled']);
const cache = new Map();
const sel = ref(null);
const detail = ref(null);
const loading = ref(false);
const error = ref('');
const openCat = ref(null);
const openElem = ref(null);
const rowQuery = ref('');
const rowKind = ref(null);
const toolSort = ref('size');
const mapOn = ref(false);
const rootRef = ref(null);
let previewTimer;
let generation = 0;

const latestSeq = computed(() => (props.requests.length ? props.requests[props.requests.length - 1].seq : null));
const shownSeq = computed(() => props.previewSeq ?? sel.value ?? latestSeq.value);
const req = computed(() => props.requests.find(r => r.seq === shownSeq.value) || null);

async function load(seq) {
  if (seq === null) { detail.value = null; return; }
  const current = ++generation;
  if (cache.has(seq)) { detail.value = cache.get(seq); error.value = ''; return; }
  loading.value = true;
  try {
    const payload = await fetchContextSnapshot(seq);
    cache.set(seq, payload);
    if (current === generation) { detail.value = payload; error.value = ''; }
  } catch (err) {
    if (current === generation) error.value = err.message;
  } finally {
    if (current === generation) loading.value = false;
  }
}
watch(shownSeq, (seq) => {
  clearTimeout(previewTimer);
  // 悬停预览稍作延迟，避免扫过趋势图时逐根请求
  if (props.previewSeq !== null && !cache.has(seq)) previewTimer = setTimeout(() => load(seq), 150);
  else load(seq);
}, { immediate: true });
watch(() => props.pinSeq, (seq) => { sel.value = seq; setCat(null); openElem.value = null; });
watch(() => props.focus, async (focus) => {
  if (!focus) return;
  sel.value = focus.seq;
  await load(focus.seq);
  setCat(focus.cat);
  rowQuery.value = '';
  rowKind.value = null;
  const rows = (detail.value?.elements || []).filter(e => e.cat === focus.cat);
  const target = focus.call ? rows.find(e => e.call === focus.call)
    : focus.name ? rows.find(e => e.name === focus.name) : rows.find(e => e.isNew) || rows[rows.length - 1];
  openElem.value = target?.key ?? null;
  emit('focus-handled');
  await nextTick();
  rootRef.value?.querySelector('.lc-br-elem-on')?.scrollIntoView({ block: 'nearest' });
});

const elements = computed(() => detail.value?.elements || []);
const breakdown = computed(() => detail.value?.categories || req.value || {});
const parts = computed(() => partsOf(breakdown.value));
const total = computed(() => CATS.reduce((sum, c) => sum + (breakdown.value[c.key] || 0), 0));
const byCat = computed(() => {
  const groups = {};
  for (const e of elements.value) (groups[e.cat] ||= []).push(e);
  return groups;
});
const linkKey = computed(() => (props.hoverKey && props.hoverKey !== 'free' ? props.hoverKey : null));

function setCat(cat) { openCat.value = cat; emit('open-cat', cat); }
function toggleCat(cat) {
  const rows = byCat.value[cat] || [];
  if (!rows.length) return;
  if (openCat.value === cat) { setCat(null); openElem.value = null; return; }
  setCat(cat);
  rowQuery.value = '';
  rowKind.value = null;
  openElem.value = rows.length === 1 ? rows[0].key : null;
}
function pickBlock(cat, block) {
  setCat(cat);
  rowKind.value = null;
  if (block.elem) { rowQuery.value = ''; openElem.value = block.elem; } else { openElem.value = null; rowQuery.value = block.query || ''; }
}
function pick(value) { sel.value = Number(value); setCat(null); openElem.value = null; }

function kindsOf(e) { return new Set(e.kinds || []); }
function rowsOf(cat) {
  let rows = (byCat.value[cat] || []).slice();
  if (cat === 'tools') {
    rows.sort((a, b) => (toolSort.value === 'size' ? b.tokens - a.tokens : (a.name < b.name ? -1 : 1)));
  } else if (cat !== 'system') {
    rows.reverse();
  }
  const q = rowQuery.value.trim().toLowerCase();
  return rows.filter(e => (rowKind.value === null || kindsOf(e).has(rowKind.value))
    && (!q || e.name.toLowerCase().includes(q) || (e.tool || '').toLowerCase().includes(q)
      || (e.calls || []).join(' ').toLowerCase().includes(q) || (e.content?.text || '').toLowerCase().includes(q)));
}
function kindCounts() {
  const rows = byCat.value.assistant || [];
  return ROW_KINDS.map(k => ({ k, n: rows.filter(e => kindsOf(e).has(k)).length }));
}
function tagOf(e) {
  if (e.cat === 'tool') return e.tool || '?';
  if (e.cat === 'assistant' && e.calls?.length) return e.calls.join(' › ');
  if (e.cat === 'tools') return e.source || null;
  if (e.cat === 'skill' || e.cat === 'inject') return catLabel(e.cat);
  return null;
}
function previewOf(e) {
  if (e.cat === 'tool') return (e.content?.text || '').replace(/\s+/g, ' ').slice(0, 80) || t('node.toolResult');
  if (e.cat === 'assistant' && e.calls?.length && e.name.startsWith('调用 ')) return e.content?.text?.slice(0, 80) || '';
  return e.name;
}
function errOf(e) { return e.cat === 'tool' && (e.content?.text || '').startsWith('Error'); }
function schemaOf(e) {
  try { return JSON.parse(e.content?.text || '{}').function || {}; } catch { return {}; }
}
function paramsOf(e) {
  const params = schemaOf(e).parameters || {};
  const required = new Set(params.required || []);
  return Object.entries(params.properties || {}).map(([name, schema]) => ({
    name, required: required.has(name), desc: schema.description || '',
    type: schema.type || (schema.anyOf ? schema.anyOf.map(s => s.type).filter(Boolean).join(' | ') : schema.enum ? 'enum' : ''),
  }));
}
function prettyArgs(raw) {
  try { return JSON.stringify(JSON.parse(raw), null, 2); } catch { return raw || ''; }
}
const jsonOpen = ref(new Set());
function toggleJson(key) {
  const next = new Set(jsonOpen.value);
  if (next.has(key)) next.delete(key); else next.add(key);
  jsonOpen.value = next;
}
</script>

<template>
  <div ref="rootRef" class="lc-card">
    <div class="lc-card-title">
      <span class="lc-card-title-text">{{ title || t('browser.title') }}</span>
      <select v-if="requests.length" class="lc-br-pick ml-auto" :value="shownSeq ?? ''" @change="pick($event.target.value)">
        <option v-for="r in requests.slice().reverse()" :key="r.seq" :value="r.seq">
          {{ t('detail.step', { t: r.turn ?? 0, s: r.step ?? 0, n: stepsOf(r.turn) }) }}
        </option>
      </select>
    </div>
    <div v-if="!requests.length" class="lc-empty">{{ t('trend.empty') }}</div>
    <template v-else>
      <div class="lc-br-bar">
        <div class="lc-br-bar-main">
          <div class="lc-br-meta">
            <b v-if="req">{{ t('detail.step', { t: req.turn ?? 0, s: req.step ?? 0, n: stepsOf(req.turn) }) }}</b>
            <span v-if="req">{{ fmtTime(req.time) }}</span>
            <span class="lc-est">{{ t('detail.estTotal', { n: fmt(total) }) }}</span>
            <span v-if="req?.prompt !== undefined">{{ t('detail.actual', { n: fmt(req.prompt) }) }}</span>
          </div>
          <StackedBar :parts="parts" :height="10" :hover-key="linkKey ?? (openCat && breakdown[openCat] ? openCat : null)"
            :show-tip="false" @hover="emit('hover', $event)" />
        </div>
        <button type="button" class="lc-br-map-btn" :class="{ 'lc-br-map-btn-on': mapOn }" :title="t('browser.mapTip')"
          :aria-pressed="mapOn" @click="mapOn = !mapOn">
          <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <rect x="1.2" y="1.2" width="8" height="6" rx="1" /><rect x="10.6" y="1.2" width="4.2" height="6" rx="1" />
            <rect x="1.2" y="8.6" width="5" height="6.2" rx="1" /><rect x="7.6" y="8.6" width="7.2" height="6.2" rx="1" />
          </svg>
        </button>
      </div>
      <BrowserTreemap v-if="mapOn && detail" :elements="elements" :open-cat="openCat" :hover-key="linkKey"
        @hover="emit('hover', $event)" @pick-cat="toggleCat" @pick-block="pickBlock" />
      <div v-if="loading && !detail" class="lc-br-note">{{ t('browser.loading') }}</div>
      <div v-if="error" class="lc-br-note">{{ t('error') }}{{ error }}</div>
      <div class="lc-br-cats">
        <div v-for="c in CATS" :key="c.key" class="lc-br-cat" :class="{ 'lc-br-cat-empty': !(byCat[c.key] || []).length }">
          <button type="button" class="lc-br-cat-row hover:bg-(--dsw-alias-interactive-bg-hover)"
            :class="{ 'lc-br-cat-open': openCat === c.key, 'lc-br-cat-on': hoverKey === c.key }"
            @mouseenter="emit('hover', c.key)" @mouseleave="emit('hover', null)" @click="toggleCat(c.key)">
            <span class="lc-br-chev" :class="{ 'lc-br-chev-on': openCat === c.key }" />
            <i :style="{ background: c.color }" />
            <span class="lc-br-cat-label">{{ catLabel(c.key) }}</span>
            <span class="lc-br-count-grp">
              <span class="lc-br-cat-count">{{ t('browser.items', { n: (byCat[c.key] || []).length }) }}</span>
              <span v-if="detail?.delta?.[c.key]?.items" class="lc-br-delta"
                :class="detail.delta[c.key].items > 0 ? 'lc-br-delta-up' : 'lc-br-delta-down'">
                {{ (detail.delta[c.key].items > 0 ? '+' : '') + detail.delta[c.key].items }}
              </span>
            </span>
            <span class="lc-br-tokens-grp">
              <span v-if="detail?.delta?.[c.key]?.tokens" class="lc-br-tdelta"
                :class="detail.delta[c.key].tokens > 0 ? 'lc-br-tdelta-up' : 'lc-br-tdelta-down'">
                {{ (detail.delta[c.key].tokens > 0 ? '+' : '') + fmt(detail.delta[c.key].tokens) }}
              </span>
              <span class="lc-br-tokens">≈{{ fmt(breakdown[c.key] || 0) }}</span>
            </span>
            <span class="lc-br-pct">{{ total > 0 ? `${Math.round((breakdown[c.key] || 0) / total * 100)}%` : '' }}</span>
          </button>
          <div v-if="openCat === c.key && (byCat[c.key] || []).length" class="lc-br-body">
            <div v-if="c.key !== 'system'" class="lc-br-toolctl">
              <input v-model="rowQuery" class="lc-br-tool-search" :placeholder="t('browser.search.' + c.key)" />
              <span v-if="c.key === 'tools'" class="lc-gran" role="group">
                <button v-for="k in ['size', 'name']" :key="k" type="button" class="lc-gran-btn"
                  :class="{ 'lc-gran-on': toolSort === k }" @click="toolSort = k">{{ t('tool.sort.' + k) }}</button>
              </span>
              <span v-else-if="c.key === 'assistant'" class="lc-gran" role="group" :title="t('browser.kindTip')">
                <button v-for="{ k, n } in kindCounts()" :key="k" type="button" class="lc-gran-btn"
                  :class="{ 'lc-gran-on': rowKind === k }" @click="rowKind = rowKind === k ? null : k">
                  {{ t('browser.kind.' + k) }}<span class="lc-kind-n">{{ fmt(n) }}</span>
                </button>
              </span>
            </div>
            <div v-if="!rowsOf(c.key).length" class="lc-br-note">{{ t('browser.rowNoMatch') }}</div>
            <div v-for="e in rowsOf(c.key)" :key="e.key" class="lc-br-elem" :class="{ 'lc-br-elem-on': openElem === e.key }">
              <button type="button" class="lc-br-elem-row hover:bg-(--dsw-alias-interactive-bg-hover)"
                @click="openElem = openElem === e.key ? null : e.key">
                <span class="lc-br-chev" :class="{ 'lc-br-chev-on': openElem === e.key }" />
                <span v-if="errOf(e)" class="lc-br-err-dot" />
                <span v-if="tagOf(e)" class="lc-br-tags"><span class="lc-br-tag" :class="{ 'lc-br-tool-plugin': c.key === 'tools' }"
                  :title="c.key === 'tools' ? t('tool.source') : undefined">{{ tagOf(e) }}</span></span>
                <span class="lc-br-preview">{{ previewOf(e) }}</span>
                <span v-if="e.isNew" class="lc-br-time">{{ t('browser.new') }}</span>
                <span class="lc-br-tokens">≈{{ fmt(e.tokens) }}</span>
              </button>
              <div v-if="openElem === e.key" class="lc-br-content">
                <template v-if="c.key === 'tools'">
                  <TextSection v-if="schemaOf(e).description" :label="catLabel('tools')" :text="schemaOf(e).description" markdown />
                  <div v-if="paramsOf(e).length" class="lc-ts-card">
                    <div class="lc-ts-card-head"><b>{{ t('tool.params') }}</b><span class="lc-ts-card-count">{{ paramsOf(e).length }}</span></div>
                    <div v-for="p in paramsOf(e)" :key="p.name" class="lc-ts-param-row">
                      <span class="lc-ts-param-name">{{ p.name }}</span>
                      <span class="lc-ts-param-type">{{ p.type }}</span>
                      <span :class="p.required ? 'lc-ts-param-req' : 'lc-ts-param-req-off'">{{ p.required ? '✓' : '—' }}</span>
                      <span v-if="p.desc" class="lc-ts-param-desc">{{ p.desc }}</span>
                    </div>
                  </div>
                  <div class="lc-ts-json">
                    <button type="button" class="lc-ts-json-toggle" @click="toggleJson(e.key)">
                      {{ jsonOpen.has(e.key) ? '▾ JSON' : '▸ JSON' }}
                    </button>
                    <pre v-if="jsonOpen.has(e.key)" class="lc-ts-desc-body lc-br-dim">{{ e.content?.text }}</pre>
                  </div>
                </template>
                <template v-else-if="c.key === 'assistant'">
                  <TextSection v-if="e.content?.reasoning" :label="t('block.thinking')" :text="e.content.reasoning" />
                  <TextSection v-if="e.content?.text" :label="t('block.answer')" :text="e.content.text" markdown />
                  <div v-for="call in e.content?.calls || []" :key="call.id || call.name" class="lc-ts-card">
                    <div class="lc-ts-card-head"><b class="lc-ts-call-name">{{ call.name }}</b></div>
                    <pre class="lc-ts-desc-body">{{ prettyArgs(call.arguments) }}</pre>
                  </div>
                </template>
                <template v-else-if="c.key === 'tool'">
                  <div class="lc-ts-card-head">
                    <span class="lc-ts-call-state" :class="errOf(e) ? 'lc-ts-call-err' : 'lc-ts-call-ok'">
                      <i />{{ errOf(e) ? t('call.fail') : t('call.ok') }}
                    </span>
                  </div>
                  <TextSection :label="t('block.result')" :text="e.content?.text || ''" :clipped="e.content?.clipped" />
                </template>
                <TextSection v-else :label="catLabel(c.key) + '：' + e.name" :text="e.content?.text || ''"
                  :clipped="e.content?.clipped" :markdown="c.key === 'skill' || c.key === 'inject'" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
