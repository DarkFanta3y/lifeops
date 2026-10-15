<script setup>
// 上下文洞察总览页：照搬 dsh-context components/overviewPanel.tsx 的 KPI / 7 天用量 / 构成 / 热力图 / 会话卡片。
import { computed, onMounted, ref, watch } from 'vue';
import { fetchContextOverview } from '../api.js';
import '../context/styles/index.js';
import { t } from '../context/i18n.js';
import { fmt, fmtCost } from '../context/kit.js';
import ActivityHeatmap from '../context/components/ActivityHeatmap.vue';
import OverviewCard from '../context/components/OverviewCard.vue';
import OverviewUsage from '../context/components/OverviewUsage.vue';
import StatsTokens from '../context/components/StatsTokens.vue';

const RANGES = ['7d', '30d', 'all'];
const SORTS = ['recent', 'tokens', 'context'];
const METRICS = [['requests', '步数'], ['sessions', '会话']];
const PAGE_SIZE = 12;
const emit = defineEmits(['open']);
const range = ref('7d');
const data = ref(null);
const error = ref('');
const loading = ref(false);
const day = ref(null);
const query = ref('');
const sort = ref('recent');
const metric = ref('requests');
const page = ref(0);
const now = ref(Date.now());

async function load() {
  loading.value = true;
  try {
    data.value = await fetchContextOverview(range.value);
    now.value = Date.now();
    error.value = '';
  } catch (err) { error.value = err.message; } finally { loading.value = false; }
}
watch(range, load);
onMounted(load);
watch([day, query, sort, range], () => { page.value = 0; });

const kpi = computed(() => data.value?.kpi);
const visible = computed(() => {
  const q = query.value.trim().toLowerCase();
  const rows = (data.value?.sessions || []).filter(row => (!day.value || row.days.includes(day.value))
    && (!q || row.title.toLowerCase().includes(q)));
  const key = { recent: row => row.lastActive, tokens: row => row.billed, context: row => row.current.total }[sort.value];
  return rows.slice().sort((a, b) => key(b) - key(a));
});
const pageCount = computed(() => Math.max(1, Math.ceil(visible.value.length / PAGE_SIZE)));
const paged = computed(() => visible.value.slice(page.value * PAGE_SIZE, (page.value + 1) * PAGE_SIZE));
</script>

<template>
  <section class="lc-ov-page workspace" :aria-label="t('ov.title')" v-loading="loading && !data">
    <div class="lc-ov-pagescroll">
      <div class="lc-ov-pagecontent">
        <div class="lc-ov-pagehead">
          <div class="lc-ov-headctl">
            <div class="lc-gran lc-ov-range" role="group" :aria-label="t('ov.range.label')">
              <button v-for="r in RANGES" :key="r" type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': range === r }"
                @click="range = r">{{ t('ov.range.' + r) }}</button>
            </div>
          </div>
        </div>
        <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
        <template v-if="data">
          <div class="lc-ov-first">
            <div class="lc-ov-kpis">
              <div class="lc-stat lc-ov-kpi">
                <span class="lc-stat-label">{{ t('ov.kpi.sessions') }}</span>
                <span class="lc-stat-value">{{ kpi.sessions }}</span>
                <span class="lc-stat-sub">{{ t('ov.range.' + data.range) }}</span>
              </div>
              <div class="lc-stat lc-ov-kpi">
                <span class="lc-stat-label">{{ t('ov.kpi.tokens') }}</span>
                <span class="lc-stat-value">{{ fmt(kpi.billed) }}</span>
                <span class="lc-stat-sub">{{ t('ov.kpi.sessionsSub', { n: kpi.sessions }) }}</span>
              </div>
              <div class="lc-stat lc-ov-kpi">
                <span class="lc-stat-label">{{ t('ov.kpi.cost') }}</span>
                <span class="lc-stat-value">{{ fmtCost(kpi.cost) }}</span>
                <span class="lc-stat-sub" :title="data.prices ? t('stats.costTip') : t('stats.costUnset')">{{ data.prices ? t('ov.kpi.costSub') : t('ov.kpi.costUnset') }}</span>
              </div>
              <div class="lc-stat lc-ov-kpi">
                <span class="lc-stat-label">{{ t('ov.kpi.cacheHit') }}</span>
                <span class="lc-stat-value">{{ kpi.cacheHit === null ? '—' : (kpi.cacheHit * 100).toFixed(1) + '%' }}</span>
                <span class="lc-stat-sub">{{ t('stats.cacheHitTip') }}</span>
              </div>
              <div class="lc-stat lc-ov-kpi">
                <span class="lc-stat-label">{{ t('ov.kpi.requests') }}</span>
                <span class="lc-stat-value">{{ fmt(kpi.requests) }}</span>
                <span class="lc-stat-sub">{{ t('ov.range.' + data.range) }}</span>
              </div>
            </div>
            <OverviewUsage :days="data.usage7" />
          </div>
          <div class="lc-ov-stats">
            <StatsTokens :usage="kpi.usage" :current="data.composition" />
          </div>
          <div class="lc-ov-body">
            <div class="lc-ov-left">
              <div class="lc-card lc-ov-heat-card">
                <div class="lc-card-title">
                  <span class="lc-card-title-text">{{ t('ov.heat.title') }}</span>
                  <span class="lc-heat-ctl">
                    <span class="lc-card-sub">{{ t('ov.heat.sub') }}</span>
                    <div class="lc-gran" role="group">
                      <button v-for="[m, label] in METRICS" :key="m" type="button" class="lc-gran-btn"
                        :class="{ 'lc-gran-on': metric === m }" @click="metric = m">{{ label }}</button>
                    </div>
                  </span>
                </div>
                <ActivityHeatmap :days="data.heatmap" :metric="metric" :selected="day" @select="day = $event" />
              </div>
            </div>
            <div class="lc-ov-right">
              <div class="lc-ov-list-head">
                <span class="lc-ov-list-title">{{ t('ov.list.title') }}</span>
                <span class="lc-ov-list-count">{{ visible.length }}</span>
                <button v-if="day" type="button" class="lc-ov-day-chip" :title="t('ov.list.dayClear')" @click="day = null">
                  {{ t('ov.list.dayFilter', { day }) }} ×
                </button>
                <input v-model="query" class="lc-ov-search" type="search" :placeholder="t('ov.list.search')" :aria-label="t('ov.list.search')" />
                <div class="lc-gran" role="group">
                  <button v-for="s in SORTS" :key="s" type="button" class="lc-gran-btn" :class="{ 'lc-gran-on': sort === s }"
                    @click="sort = s">{{ t('ov.list.sort.' + s) }}</button>
                </div>
              </div>
              <div v-if="!visible.length" class="lc-empty">{{ t(data.sessions.length ? 'ov.list.noMatch' : 'ov.list.empty') }}</div>
              <template v-else>
                <div class="lc-ov-grid">
                  <OverviewCard v-for="row in paged" :key="row.conversationId" :row="row" :now="now" @open="emit('open', $event)" />
                </div>
                <div v-if="pageCount > 1" class="lc-ov-pager" role="navigation">
                  <button type="button" class="lc-ov-pager-btn" :disabled="page === 0" @click="page--">‹</button>
                  <span class="lc-ov-pager-n">第 {{ page + 1 }} / {{ pageCount }} 页</span>
                  <button type="button" class="lc-ov-pager-btn" :disabled="page === pageCount - 1" @click="page++">›</button>
                </div>
              </template>
            </div>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>
