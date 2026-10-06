<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { Coin, Plus, Refresh, Edit, Delete, UploadFilled } from '@element-plus/icons-vue';
import { fetchRagSources, updateRagSource, deleteRagSource, checkRagImportConflict,
  uploadRagImport, previewRagImport, startRagImport, fetchRagImport, deleteRagImport } from '../api.js';

const sources = ref([]), loading = ref(false), error = ref('');
const selected = ref(null), editing = ref(false), saving = ref(false);
const wizard = ref(false), busy = ref(false), step = ref(0), wizardError = ref('');
const importId = ref(null), tree = ref([]), firstMarkdown = ref(''), preview = ref(null);
const strategy = ref('heading'), chunkSize = ref(900), status = ref('');
const blankSource = () => ({ source_id: '', name: '', description: '', call_when: '', enabled: true });
const form = ref(blankSource());
let pollTimer, disposed = false, previewGeneration = 0;
const validSource = computed(() => /^[a-z][a-z0-9_-]{0,63}$/.test(form.value.source_id)
  && form.value.name.trim() && form.value.name.length <= 100
  && form.value.description.trim() && form.value.description.length <= 1000
  && form.value.call_when.trim() && form.value.call_when.length <= 1000);
async function load() {
  loading.value = true; error.value = '';
  try { sources.value = (await fetchRagSources()).sources || []; }
  catch (err) { error.value = err.message; }
  finally { loading.value = false; }
}
function openCreate() {
  clearTimeout(pollTimer); ++previewGeneration;
  form.value = blankSource(); step.value = 0; importId.value = null; tree.value = [];
  preview.value = null; strategy.value = 'heading'; chunkSize.value = 900;
  firstMarkdown.value = ''; status.value = ''; wizardError.value = ''; wizard.value = true;
}
function openEdit(source) { form.value = { ...source }; selected.value = null; error.value = ''; editing.value = true; }
async function save() {
  if (!validSource.value || saving.value) return;
  saving.value = true; error.value = '';
  try {
    const { name, description, call_when, enabled } = form.value;
    await updateRagSource(form.value.source_id, { name, description, call_when, enabled });
    editing.value = false; ElMessage.success('数据源已保存，重启 LifeOps 后生效'); await load();
  } catch (err) { error.value = err.message; }
  finally { saving.value = false; }
}
async function remove(source) {
  try { await ElMessageBox.confirm('只删除数据源配置，不删除本地文件。', '删除数据源配置？',
    { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }); }
  catch { return; }
  try { await deleteRagSource(source.source_id); selected.value = null;
    ElMessage.success('配置已删除，重启 LifeOps 后生效；本地文件未删除'); await load(); }
  catch (err) { error.value = err.message; }
}
function toTree(nodes) {
  return (nodes || []).map(node => ({ label: node.name, id: node.path, children: node.children ? toTree(node.children) : undefined }));
}
async function upload(file) {
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(form.value.source_id)) {
    wizardError.value = '请先填写小写安全标识，以字母开头，最多 64 个字符'; return false;
  }
  if (!file.name.toLowerCase().endsWith('.zip') || file.size > 100 * 1024 * 1024) {
    wizardError.value = '请选择不超过 100MB 的 ZIP 压缩包'; return false;
  }
  busy.value = true; wizardError.value = '';
  try {
    const conflict = await checkRagImportConflict(form.value.source_id);
    if (conflict.conflict) {
      try { await ElMessageBox.confirm('继续上传会覆盖已有知识库。', '知识库已存在',
        { confirmButtonText: '继续覆盖', cancelButtonText: '取消', type: 'warning' }); }
      catch { return false; }
    }
    const data = await uploadRagImport(form.value.source_id, file, Boolean(conflict.conflict));
    importId.value = data.import_id; tree.value = toTree(data.tree); firstMarkdown.value = data.markdown_files?.[0] || '';
    ElMessage.success('压缩包已解压');
  } catch (err) { wizardError.value = err.message; }
  finally { busy.value = false; }
  return false;
}
async function loadPreview() {
  const generation = ++previewGeneration;
  busy.value = true; wizardError.value = '';
  try {
    const data = await previewRagImport(importId.value, strategy.value, chunkSize.value);
    if (generation !== previewGeneration) return false;
    preview.value = data; return true;
  } catch (err) { if (generation === previewGeneration) wizardError.value = err.message; return false; }
  finally { if (generation === previewGeneration) busy.value = false; }
}
async function next() {
  if (busy.value) return;
  if (!validSource.value) { wizardError.value = '请完整填写标识、名称、描述和调用条件'; return; }
  if (step.value === 0) {
    if (!importId.value) { wizardError.value = '请先上传 ZIP 压缩包'; return; }
    if (await loadPreview()) step.value = 1;
    return;
  }
  busy.value = true; wizardError.value = '';
  try { await startRagImport(importId.value, form.value, strategy.value, chunkSize.value);
    status.value = 'processing'; step.value = 2; poll(); }
  catch (err) { wizardError.value = err.message; }
  finally { busy.value = false; }
}
async function poll() {
  if (disposed || status.value !== 'processing') return;
  try {
    const data = await fetchRagImport(importId.value);
    if (disposed) return;
    status.value = data.status;
    if (status.value === 'completed') { wizardError.value = ''; ElMessage.success('知识库入库完成，重启服务后生效'); await load(); }
    if (status.value === 'failed') {
      wizardError.value = data.error || '知识库入库失败';
      error.value = wizardError.value;
    }
  } catch (err) { if (!disposed) {
    wizardError.value = `状态查询失败，将重试：${err.message}`;
    if (!wizard.value) error.value = wizardError.value;
  } }
  if (!disposed && status.value === 'processing') pollTimer = setTimeout(poll, 1000);
}
async function closeWizard(done) {
  if (busy.value) return;
  if (importId.value && !['processing', 'completed'].includes(status.value)) {
    busy.value = true;
    try { await deleteRagImport(importId.value); }
    catch (err) { wizardError.value = `清理暂存资料失败：${err.message}`; busy.value = false; return; }
    importId.value = null; status.value = '';
    busy.value = false;
  }
  wizard.value = false;
  if (typeof done === 'function') done();
}
onMounted(load);
onUnmounted(() => { disposed = true; ++previewGeneration; clearTimeout(pollTimer); });
</script>

<template>
  <section class="workspace database-workspace">
    <div class="toolbar"><div><p class="eyebrow">资料与记忆</p><h2>本地知识库 <span class="count">{{ sources.length }}</span></h2></div>
      <div class="actions"><el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="importId && status" @click="wizard = true">查看入库进度</el-button>
        <el-button type="primary" :icon="Plus" :disabled="['processing', 'failed'].includes(status)" @click="openCreate">新增本地知识库</el-button></div></div>
    <el-alert v-if="error" :title="error" type="error" show-icon />
    <div class="database-body" v-loading="loading"><el-empty v-if="!sources.length" description="暂无数据源" />
      <div v-else class="database-card-grid"><article v-for="source in sources" :key="source.source_id" class="database-source-card"
        role="button" tabindex="0" :aria-label="`查看 ${source.name} 详情`" @click="selected = source"
        @keydown.enter="selected = source" @keydown.space.prevent="selected = source">
        <div class="database-card-heading"><el-icon class="source-icon"><Coin /></el-icon>
          <el-tag :type="source.enabled ? 'success' : 'info'">{{ source.enabled ? '启用' : '停用' }}</el-tag></div>
        <h3>{{ source.name }}</h3><p>{{ source.description || '无描述' }}</p>
        <div class="source-condition"><small>调用条件</small><p>{{ source.call_when || '未设置' }}</p></div>
        <div class="card-actions" @click.stop @keydown.stop><el-button text :icon="Edit" :aria-label="`编辑 ${source.name}`" @click="openEdit(source)" />
          <el-button text type="danger" :icon="Delete" :aria-label="`删除 ${source.name}`" @click="remove(source)" /></div>
      </article></div></div>
    <el-drawer :model-value="Boolean(selected)" :title="selected?.name || '数据源详情'" size="min(460px, 96vw)" @close="selected = null">
      <el-descriptions v-if="selected" :column="1" border>
        <el-descriptions-item v-for="[key, label] in [['name','名称'],['source_id','标识'],['path_prefix','目录'],['description','描述'],['call_when','调用条件']]" :key="key" :label="label">{{ selected[key] }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ selected.enabled ? '启用' : '停用' }}</el-descriptions-item>
      </el-descriptions><template #footer><el-button v-if="selected" :icon="Edit" @click="openEdit(selected)">编辑数据源</el-button></template>
    </el-drawer>
    <el-dialog v-model="editing" title="编辑本地知识库" width="min(540px, 94vw)" :close-on-click-modal="!saving">
      <el-form label-position="top"><el-form-item label="名称" for="source-name"><el-input id="source-name" v-model="form.name" maxlength="100" /></el-form-item>
        <el-form-item label="描述" for="source-description"><el-input id="source-description" v-model="form.description" type="textarea" maxlength="1000" /></el-form-item>
        <el-form-item label="调用条件" for="source-condition"><el-input id="source-condition" v-model="form.call_when" type="textarea" maxlength="1000" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" aria-label="启用数据源" /></el-form-item></el-form>
      <el-alert v-if="error" :title="error" type="error" />
      <template #footer><el-button :disabled="saving" @click="editing = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!validSource" @click="save">保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="wizard" title="新增本地知识库" width="min(1120px, 94vw)" :before-close="closeWizard" :close-on-click-modal="false" destroy-on-close>
      <el-steps :active="step" finish-status="success" align-center><el-step title="上传资料" /><el-step title="选择切片策略" /><el-step title="入库" /></el-steps>
      <el-alert v-if="wizardError" :title="wizardError" type="error" show-icon :closable="false" />
      <p class="muted">暂时只支持 Markdown（可包含常见图片资源）</p>
      <div v-if="step === 0" class="import-columns"><el-form label-position="top">
        <el-form-item label="标识" for="import-id"><el-input id="import-id" v-model="form.source_id" :disabled="Boolean(importId) || busy" maxlength="64" placeholder="例如 work_notes" /></el-form-item>
        <el-form-item label="名称" for="import-name"><el-input id="import-name" v-model="form.name" maxlength="100" /></el-form-item>
        <el-form-item label="描述" for="import-description"><el-input id="import-description" v-model="form.description" type="textarea" maxlength="1000" /></el-form-item>
        <el-form-item label="调用条件" for="import-condition"><el-input id="import-condition" v-model="form.call_when" type="textarea" maxlength="1000" /></el-form-item>
      </el-form><div v-loading="busy"><el-upload drag accept=".zip" :before-upload="upload" :show-file-list="false" :disabled="busy || Boolean(importId)">
        <el-icon class="upload-icon"><UploadFilled /></el-icon><p>点击或拖拽 ZIP 压缩包到这里</p><small>最多 100MB，解压后最多 500MB、2000 个文件</small>
      </el-upload><div v-if="importId" class="import-tree"><strong>解压目录</strong><el-tree :data="tree" node-key="id" default-expand-all /></div></div></div>
      <div v-else-if="step === 1" class="import-columns" v-loading="busy"><div class="preview-file"><strong>{{ firstMarkdown }}</strong><pre>{{ preview?.content }}</pre></div>
        <div><el-radio-group v-model="strategy" :disabled="busy" @change="loadPreview"><el-radio-button value="heading">按标题切块</el-radio-button><el-radio-button value="fixed">固定大小</el-radio-button></el-radio-group>
          <div v-if="strategy === 'fixed'" class="chunk-control"><el-slider v-model="chunkSize" :min="150" :max="900" :disabled="busy" @change="loadPreview" />
            <el-input-number v-model="chunkSize" :min="150" :max="900" :disabled="busy" @change="loadPreview" /></div>
          <div class="chunk-list"><article v-for="(chunk, index) in preview?.chunks || []" :key="index"><strong>块 {{ index + 1 }} · {{ chunk.heading_breadcrumb }}</strong><pre>{{ chunk.content }}</pre></article></div></div></div>
      <div v-else class="import-status"><el-result :icon="status === 'completed' ? 'success' : status === 'failed' ? 'error' : 'info'"
        :title="status === 'completed' ? '处理完成' : status === 'failed' ? '处理失败' : '正在处理知识库'"
        :sub-title="status === 'completed' ? '知识库将在下次重启服务后加载。' : '正在切片、生成向量并建立 BM25 索引，关闭弹窗不会中断处理。'" /></div>
      <template #footer><el-button :disabled="busy" @click="closeWizard">{{ step === 2 ? '关闭' : '取消' }}</el-button>
        <el-button v-if="step === 1" :disabled="busy" @click="step = 0">上一步</el-button>
        <el-button v-if="step < 2" type="primary" :loading="busy" @click="next">{{ step === 1 ? '开始入库' : '下一步' }}</el-button></template>
    </el-dialog>
  </section>
</template>
