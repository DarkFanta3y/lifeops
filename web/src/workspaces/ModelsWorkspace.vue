<script setup>
import { computed, onMounted, ref } from 'vue';
import { Check, Cpu, Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue';
import {
  clearActiveModel, createModelProvider, deleteModelProvider, fetchAvailableModels,
  fetchModels, setActiveModel, updateModelProvider,
} from '../api.js';

const providers = ref([]);
const active = ref(null);
const fallback = ref(null);
const protocols = ref([
  { value: 'openai_chat', label: 'OpenAI Chat Completions' },
  { value: 'openai_responses', label: 'OpenAI Responses' },
  { value: 'anthropic_messages', label: 'Anthropic Messages' },
]);
const loading = ref(false);
const saving = ref(false);
const fetching = ref(false);
const error = ref('');
const formError = ref('');
const dialog = ref(false);
const editing = ref(false);
const selectedId = ref(null);
const availableDialog = ref(false);
const available = ref([]);
const form = ref(blankProvider());
const keyHint = ref('');

const providerIdPattern = /^[a-z][a-z0-9_-]{0,63}$/;
const apiBasePattern = /^https?:\/\/\S+$/i;

const selectedProvider = computed(() => providers.value.find(item => item.provider_id === selectedId.value) || null);
const activeLabel = computed(() => {
  if (active.value) return `${active.value.provider_name} · ${active.value.model_name || active.value.model_id}`;
  return `环境变量默认 · ${fallback.value?.model || '未配置'}`;
});
const validForm = computed(() => {
  if (!providerIdPattern.test(form.value.provider_id) || !form.value.name.trim()) return false;
  if (!apiBasePattern.test(form.value.api_base.trim())) return false;
  if (!['openai_chat', 'openai_responses', 'anthropic_messages'].includes(form.value.protocol)) return false;
  const ids = form.value.models.map(model => model.model_id.trim());
  return ids.every(Boolean) && new Set(ids).size === ids.length;
});

function blankProvider() {
  return {
    provider_id: '', name: '', api_base: '', protocol: 'openai_chat', api_key: '', models: [],
  };
}
function protocolLabel(value) {
  return protocols.value.find(item => item.value === value)?.label || value;
}
function modelRows(provider) {
  return provider?.models || [];
}
async function load() {
  loading.value = true;
  error.value = '';
  try {
    const payload = await fetchModels();
    providers.value = payload.providers || [];
    active.value = payload.active || null;
    fallback.value = payload.fallback || null;
    if (Array.isArray(payload.protocols) && payload.protocols.length) protocols.value = payload.protocols;
    if (selectedId.value && !providers.value.some(item => item.provider_id === selectedId.value)) {
      selectedId.value = null;
    }
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}
function openCreate() {
  form.value = blankProvider();
  editing.value = false;
  keyHint.value = '';
  formError.value = '';
  dialog.value = true;
}
function openEdit(provider) {
  form.value = {
    provider_id: provider.provider_id,
    name: provider.name,
    api_base: provider.api_base,
    protocol: provider.protocol,
    api_key: '',
    models: modelRows(provider).map(model => ({ ...model })),
  };
  editing.value = true;
  keyHint.value = provider.api_key_hint || '';
  formError.value = '';
  dialog.value = true;
}
function addModel() {
  form.value.models.push({ model_id: '', name: '', context_window: null, max_output_tokens: null });
}
function removeModel(index) {
  form.value.models.splice(index, 1);
}
async function save() {
  if (!validForm.value || saving.value) {
    if (!validForm.value) formError.value = '请检查 Provider ID、显示名称、API 地址与模型 ID';
    return;
  }
  saving.value = true;
  formError.value = '';
  const payload = {
    name: form.value.name.trim(),
    api_base: form.value.api_base.trim(),
    protocol: form.value.protocol,
    models: form.value.models.map(model => ({
      model_id: model.model_id.trim(),
      name: (model.name || '').trim() || model.model_id.trim(),
      context_window: model.context_window || null,
      max_output_tokens: model.max_output_tokens || null,
    })),
  };
  if (!editing.value || form.value.api_key.trim()) payload.api_key = form.value.api_key.trim();
  try {
    let created;
    if (editing.value) {
      await updateModelProvider(form.value.provider_id, payload);
    } else {
      created = await createModelProvider({ provider_id: form.value.provider_id, ...payload });
    }
    dialog.value = false;
    await load();
    if (created && !active.value && payload.models.length) {
      await setActiveModel(created.provider.provider_id, payload.models[0].model_id);
      await load();
      ElMessage.success('提供商已创建，并设为当前模型');
    } else {
      ElMessage.success(editing.value ? '提供商已保存' : '提供商已创建');
    }
  } catch (err) {
    formError.value = err.message;
  } finally {
    saving.value = false;
  }
}
async function removeProvider(provider) {
  try {
    await ElMessageBox.confirm('删除后该提供商的模型配置将不可用。', `删除 ${provider.name}？`,
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' });
  } catch {
    return;
  }
  try {
    await deleteModelProvider(provider.provider_id);
    if (selectedId.value === provider.provider_id) selectedId.value = null;
    await load();
    ElMessage.success('提供商已删除');
  } catch (err) {
    error.value = err.message;
  }
}
async function makeActive(provider, model) {
  try {
    await setActiveModel(provider.provider_id, model.model_id);
    await load();
    ElMessage.success(`已切换到 ${provider.name} · ${model.name || model.model_id}`);
  } catch (err) {
    error.value = err.message;
  }
}
async function resetActive() {
  try {
    await clearActiveModel();
    await load();
    ElMessage.success('已恢复环境变量默认模型');
  } catch (err) {
    error.value = err.message;
  }
}
async function loadAvailable() {
  if (fetching.value) return;
  if (!apiBasePattern.test(form.value.api_base.trim())) {
    formError.value = '请先填写有效的 API 地址';
    return;
  }
  fetching.value = true;
  formError.value = '';
  try {
    const payload = await fetchAvailableModels({
      providerId: editing.value ? form.value.provider_id : null,
      apiBase: form.value.api_base.trim(),
      protocol: form.value.protocol,
      apiKey: form.value.api_key.trim() || null,
    });
    const existing = new Set(form.value.models.map(model => model.model_id.trim()));
    available.value = (payload.models || []).map(model => ({
      ...model,
      checked: !existing.has(model.model_id),
    }));
    if (!available.value.length) {
      ElMessage.info('提供商没有返回可用模型');
      return;
    }
    availableDialog.value = true;
  } catch (err) {
    formError.value = err.message;
  } finally {
    fetching.value = false;
  }
}
function selectAllAvailable(checked) {
  available.value.forEach(model => { model.checked = checked; });
}
function addAvailable() {
  const existing = new Set(form.value.models.map(model => model.model_id.trim()));
  for (const model of available.value) {
    if (!model.checked || existing.has(model.model_id)) continue;
    form.value.models.push({
      model_id: model.model_id,
      name: model.name || model.model_id,
      context_window: model.context_window || null,
      max_output_tokens: model.max_output_tokens || null,
    });
    existing.add(model.model_id);
  }
  availableDialog.value = false;
}

onMounted(load);
</script>

<template>
  <section class="workspace models-workspace">
    <div class="toolbar">
      <div>
        <p class="eyebrow">推理与供应商</p>
        <h2>模型管理 <span class="count">{{ providers.length }}</span></h2>
      </div>
      <div class="actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">添加提供商</el-button>
      </div>
    </div>
    <el-alert v-if="error" :title="error" type="error" show-icon closable @close="error = ''" />
    <div class="models-body" v-loading="loading">
      <div class="model-active-bar">
        <div class="model-active-main">
          <span class="model-active-dot" :class="{ fallback: !active }" />
          <div>
            <small>当前模型</small>
            <strong>{{ activeLabel }}</strong>
          </div>
        </div>
        <el-button v-if="active" text @click="resetActive">恢复环境变量默认</el-button>
        <span v-else class="muted">来自 .env 的 LLM_* 配置</span>
      </div>
      <el-empty v-if="!providers.length" description="暂无提供商，添加一个 OpenAI 兼容或 Anthropic 网关" />
      <div v-else class="provider-card-grid">
        <article v-for="provider in providers" :key="provider.provider_id" class="provider-card"
          role="button" tabindex="0" :aria-label="`查看 ${provider.name}`" @click="selectedId = provider.provider_id"
          @keydown.enter="selectedId = provider.provider_id" @keydown.space.prevent="selectedId = provider.provider_id">
          <div class="provider-card-head">
            <span class="provider-icon"><el-icon><Cpu /></el-icon></span>
            <el-tag v-if="active?.provider_id === provider.provider_id" type="success" size="small">当前</el-tag>
          </div>
          <h3>{{ provider.name }}</h3>
          <code>{{ provider.provider_id }}</code>
          <p class="provider-protocol">{{ protocolLabel(provider.protocol) }}</p>
          <p class="provider-base">{{ provider.api_base }}</p>
          <div class="provider-card-footer">
            <span>{{ modelRows(provider).length }} 个模型</span>
            <span :class="provider.has_api_key ? 'key-set' : 'key-missing'">
              {{ provider.has_api_key ? `密钥已保存 ${provider.api_key_hint}` : '未设置密钥' }}
            </span>
          </div>
          <div class="card-actions" @click.stop @keydown.stop>
            <el-button text :icon="Edit" :aria-label="`编辑 ${provider.name}`" @click="openEdit(provider)" />
            <el-button text type="danger" :icon="Delete" :aria-label="`删除 ${provider.name}`" @click="removeProvider(provider)" />
          </div>
        </article>
      </div>
    </div>

    <el-drawer :model-value="Boolean(selectedProvider)" :title="selectedProvider?.name || '提供商详情'"
      size="min(520px, 96vw)" @close="selectedId = null">
      <template v-if="selectedProvider">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="Provider ID"><code>{{ selectedProvider.provider_id }}</code></el-descriptions-item>
          <el-descriptions-item label="API 地址">{{ selectedProvider.api_base }}</el-descriptions-item>
          <el-descriptions-item label="API 协议">{{ protocolLabel(selectedProvider.protocol) }}</el-descriptions-item>
          <el-descriptions-item label="API 密钥">
            {{ selectedProvider.has_api_key ? `已保存 ${selectedProvider.api_key_hint}` : '未设置' }}
          </el-descriptions-item>
        </el-descriptions>
        <div class="provider-model-head">
          <strong>模型目录</strong>
          <span class="muted">{{ modelRows(selectedProvider).length }} 个</span>
        </div>
        <el-empty v-if="!modelRows(selectedProvider).length" description="尚未添加模型" :image-size="72" />
        <div v-else class="provider-model-list">
          <div v-for="model in modelRows(selectedProvider)" :key="model.model_id" class="provider-model-row">
            <div>
              <strong>{{ model.name || model.model_id }}</strong>
              <code>{{ model.model_id }}</code>
              <small v-if="model.context_window">上下文 {{ model.context_window.toLocaleString() }}</small>
            </div>
            <el-tag v-if="active?.provider_id === selectedProvider.provider_id && active?.model_id === model.model_id"
              type="success" size="small" :icon="Check">当前</el-tag>
            <el-button v-else text type="primary" @click="makeActive(selectedProvider, model)">设为当前</el-button>
          </div>
        </div>
      </template>
      <template #footer>
        <el-button v-if="selectedProvider" :icon="Edit" @click="openEdit(selectedProvider)">编辑提供商</el-button>
      </template>
    </el-drawer>

    <el-dialog v-model="dialog" :title="editing ? '编辑提供商' : '添加提供商'"
      width="min(820px, 96vw)" :close-on-click-modal="!saving" destroy-on-close>
      <p class="muted provider-intro">连接中转站、自部署服务或其他兼容 OpenAI / Anthropic 协议的接口，需填写 API 地址、协议和模型。</p>
      <el-alert v-if="formError" :title="formError" type="error" show-icon :closable="false" />
      <el-form label-position="top" class="provider-form">
        <div class="form-columns">
          <el-form-item label="Provider ID">
            <el-input v-model="form.provider_id" :disabled="editing || saving" maxlength="64" placeholder="acme-gateway" />
            <p class="field-hint">以小写字母开头的标识，在请求中唯一标识该提供商，并用于派生凭据名。</p>
          </el-form-item>
          <el-form-item label="显示名称">
            <el-input v-model="form.name" maxlength="100" placeholder="显示名称" />
          </el-form-item>
        </div>
        <el-form-item label="API 地址">
          <el-input v-model="form.api_base" maxlength="2000" placeholder="https://gateway.example/v1" />
        </el-form-item>
        <div class="form-columns">
          <el-form-item label="API 协议">
            <el-select v-model="form.protocol" :disabled="saving" style="width: 100%">
              <el-option v-for="item in protocols" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="API 密钥">
            <el-input v-model="form.api_key" type="password" show-password :disabled="saving" maxlength="10000"
              :placeholder="editing && selectedProvider?.has_api_key ? `已保存 ${keyHint}，留空保持不变` : '输入 API 密钥'" />
          </el-form-item>
        </div>
      </el-form>

      <div class="model-catalog">
        <div class="model-catalog-head">
          <strong>模型目录</strong>
          <el-button text type="primary" :loading="fetching" :disabled="saving" @click="loadAvailable">获取可用模型</el-button>
        </div>
        <div v-if="!form.models.length" class="model-catalog-empty">
          模型选择器中将不显示任何模型；目录外 ID 仍可直接发送。
        </div>
        <div v-else class="model-edit-list">
          <div class="model-edit-head">
            <span>模型 ID</span><span>显示名称</span><span>上下文窗口</span><span>最大输出</span><span />
          </div>
          <div v-for="(model, index) in form.models" :key="index" class="model-edit-row">
            <el-input v-model="model.model_id" maxlength="200" placeholder="gpt-4o-mini" />
            <el-input v-model="model.name" maxlength="200" placeholder="显示名称（可选）" />
            <el-input-number v-model="model.context_window" :min="1" :max="10000000" :controls="false"
              placeholder="如 128000" />
            <el-input-number v-model="model.max_output_tokens" :min="1" :max="1000000" :controls="false"
              placeholder="如 4096" />
            <el-button text type="danger" :icon="Delete" :aria-label="`删除模型 ${index + 1}`" @click="removeModel(index)" />
          </div>
        </div>
        <el-button :icon="Plus" :disabled="saving" @click="addModel">添加模型</el-button>
      </div>

      <template #footer>
        <el-button :disabled="saving" @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!validForm" @click="save">
          {{ editing ? '保存修改' : '创建提供商' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="availableDialog" title="选择要添加的模型" width="min(560px, 94vw)">
      <div class="available-actions">
        <el-button text @click="selectAllAvailable(true)">全选</el-button>
        <el-button text @click="selectAllAvailable(false)">取消全选</el-button>
      </div>
      <div class="available-models">
        <el-checkbox v-for="model in available" :key="model.model_id" v-model="model.checked" class="available-model">
          <span>{{ model.model_id }}</span>
          <small v-if="model.name && model.name !== model.model_id">{{ model.name }}</small>
          <small v-if="model.context_window" class="available-context">{{ model.context_window.toLocaleString() }} 上下文</small>
        </el-checkbox>
      </div>
      <template #footer>
        <el-button @click="availableDialog = false">取消</el-button>
        <el-button type="primary" @click="addAvailable">添加所选模型</el-button>
      </template>
    </el-dialog>
  </section>
</template>
