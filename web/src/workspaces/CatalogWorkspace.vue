<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { Plus, Refresh, Collection, Tools } from '@element-plus/icons-vue';
import { createSkill, fetchSkills, fetchTools } from '../api.js';
import MarkdownRenderer from '../MarkdownRenderer.vue';

const props = defineProps({ kind: String });
const skills = ref([]), tools = ref([]), servers = ref([]);
const loading = ref(false), error = ref(''), tab = ref('tool'), page = ref(1);
const modal = ref(false), saving = ref(false);
const blankSkill = () => ({ name: '', description: '', license: '', compatibility: '', allowed_tools: [], metadata: '', content: '' });
const form = ref(blankSkill());
const rows = computed(() => props.kind === 'skills' ? skills.value
  : tab.value === 'tool' ? tools.value.filter(tool => tool.category !== 'mcp') : servers.value);
const pagedRows = computed(() => rows.value.slice((page.value - 1) * 8, page.value * 8));
const canSave = computed(() => /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(form.value.name)
  && form.value.name.length <= 64 && form.value.description.trim().length > 0
  && form.value.description.length <= 1024 && form.value.compatibility.length <= 500 && form.value.content.trim());
watch(tab, () => { page.value = 1; });
watch(() => rows.value.length, length => { page.value = Math.min(page.value, Math.max(1, Math.ceil(length / 8))); });
async function load() {
  loading.value = true; error.value = '';
  try {
    if (props.kind === 'skills') skills.value = (await fetchSkills()).skills || [];
    else { const data = await fetchTools(); tools.value = data.tools || []; servers.value = data.mcp_servers || []; }
  } catch (err) { error.value = err.message; }
  finally { loading.value = false; }
}
async function save() {
  if (!canSave.value || saving.value) return;
  saving.value = true; error.value = '';
  try { await createSkill(form.value); modal.value = false; ElMessage.success('Skill 已创建'); await load(); }
  catch (err) { error.value = err.message; }
  finally { saving.value = false; }
}
function parameters(tool) { return Object.keys(tool.parameters?.properties || {}).join(', ') || '无'; }
onMounted(load);
</script>

<template>
  <section class="workspace catalog-workspace">
    <div class="toolbar"><div><p class="eyebrow">{{ kind === 'skills' ? '能力扩展' : '执行能力' }}</p>
      <h2>{{ kind === 'skills' ? 'Skill 列表' : '工具与 MCP' }} <span class="count">{{ rows.length }}</span></h2></div>
      <div class="actions"><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="kind === 'skills'" type="primary" :icon="Plus" @click="form = blankSkill(); modal = true">新增 Skill</el-button>
        <el-radio-group v-else v-model="tab"><el-radio-button value="tool">TOOL</el-radio-button><el-radio-button value="mcp">MCP</el-radio-button></el-radio-group>
      </div></div>
    <el-alert v-if="error" :title="error" type="error" show-icon />
    <div class="table-body" v-loading="loading">
      <el-table :data="pagedRows" row-key="name" empty-text="暂无数据" stripe>
        <el-table-column v-if="kind === 'tools' && tab === 'mcp'" type="expand">
          <template #default="{ row }"><div class="mcp-tools"><article v-for="tool in row.tools" :key="tool.name">
            <strong>{{ tool.name }}</strong><p>{{ tool.description || '无描述' }}</p><small>参数：{{ parameters(tool) }}</small>
          </article></div></template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="180"><template #default="{ row }">
          <div class="catalog-name"><el-icon><Collection v-if="kind === 'skills'" /><Tools v-else /></el-icon>{{ row.name }}</div>
        </template></el-table-column>
        <el-table-column label="描述" min-width="280"><template #default="{ row }">{{ row.description || (tab === 'mcp' ? `${row.tools?.length || 0} 个 MCP 工具` : '无描述') }}</template></el-table-column>
        <template v-if="kind === 'skills'">
          <el-table-column prop="license" label="License" min-width="100" />
          <el-table-column prop="compatibility" label="Compatibility" min-width="150" show-overflow-tooltip />
          <el-table-column prop="source" label="来源" min-width="100" />
          <el-table-column prop="path" label="路径" min-width="200" show-overflow-tooltip />
        </template>
        <template v-else-if="tab === 'tool'">
          <el-table-column prop="category" label="分类" min-width="100" />
          <el-table-column label="参数" min-width="240"><template #default="{ row }">{{ parameters(row) }}</template></el-table-column>
        </template>
      </el-table>
    </div>
    <div v-if="rows.length > 8" class="workspace-pagination"><el-pagination v-model:current-page="page" :page-size="8" :total="rows.length" layout="prev, pager, next" /></div>
    <el-dialog v-model="modal" title="新增 Skill" width="min(780px, 94vw)" :close-on-click-modal="!saving" destroy-on-close>
      <el-form label-position="top" class="skill-form" @submit.prevent="save">
        <el-form-item label="名称"><el-input v-model="form.name" maxlength="64" placeholder="weekly-review，仅小写字母、数字、短横线" aria-label="Skill 名称" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="1024" aria-label="Skill 描述" /></el-form-item>
        <div class="markdown-preview" aria-label="描述预览"><MarkdownRenderer :content="form.description || '描述预览'" /></div>
        <div class="form-columns"><el-form-item label="License"><el-input v-model="form.license" placeholder="MIT" /></el-form-item>
          <el-form-item label="Compatibility"><el-input v-model="form.compatibility" maxlength="500" /></el-form-item></div>
        <el-form-item label="Allowed Tools"><el-input :model-value="form.allowed_tools.join(' ')" placeholder="file_read bash"
          @update:model-value="form = { ...form, allowed_tools: $event.split(/\s+/).filter(Boolean) }" /></el-form-item>
        <el-form-item label="metadata（YAML）"><el-input v-model="form.metadata" type="textarea" :rows="2" placeholder="owner: lifeops" /></el-form-item>
        <el-form-item label="SKILL 内容"><el-input v-model="form.content" type="textarea" :rows="6" aria-label="SKILL 内容" /></el-form-item>
      </el-form>
      <el-alert v-if="error" :title="error" type="error" show-icon />
      <template #footer><el-button :disabled="saving" @click="modal = false">取消</el-button>
        <el-button type="primary" :disabled="!canSave" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
  </section>
</template>
