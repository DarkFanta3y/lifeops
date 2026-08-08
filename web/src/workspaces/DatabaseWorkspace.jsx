import { useEffect, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Slider,
  Space,
  Spin,
  Steps,
  Switch,
  Tag,
  Tooltip,
  Tree,
  Typography,
  Upload,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  FileMarkdownOutlined,
  InboxOutlined,
  LoadingOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  checkRagImportConflict,
  deleteRagImport,
  fetchRagImport,
  previewRagImport,
  startRagImport,
  uploadRagImport,
} from "../api.js";

const { Dragger } = Upload;
const { Title, Text } = Typography;
const EMPTY_SOURCE = {
  source_id: "",
  name: "",
  description: "",
  call_when: "",
  enabled: true,
};

function toTreeData(nodes = []) {
  return nodes.map((node) => ({
    key: node.path,
    title: node.name,
    isLeaf: node.type === "file",
    children: node.children ? toTreeData(node.children) : undefined,
  }));
}

export default function DatabaseWorkspace({
  sources,
  loading,
  onRefresh,
  onAdd,
  onEdit,
  onDelete,
}) {
  const { message } = AntApp.useApp();
  const [selectedSource, setSelectedSource] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [editingSource, setEditingSource] = useState(null);
  const [saving, setSaving] = useState(false);
  const [wizardLoading, setWizardLoading] = useState(false);
  const [wizardError, setWizardError] = useState("");
  const [step, setStep] = useState(0);
  const [importId, setImportId] = useState(null);
  const [treeData, setTreeData] = useState([]);
  const [firstMarkdown, setFirstMarkdown] = useState("");
  const [strategy, setStrategy] = useState("heading");
  const [chunkSize, setChunkSize] = useState(900);
  const [preview, setPreview] = useState(null);
  const [jobStatus, setJobStatus] = useState("");
  const [form] = Form.useForm();

  useEffect(() => {
    if (!importId || jobStatus !== "processing") return undefined;
    let active = true;
    const poll = async () => {
      try {
        const payload = await fetchRagImport(importId);
        if (!active) return;
        setJobStatus(payload.status);
        if (payload.status === "completed") {
          message.success("知识库入库完成，重启服务后生效");
          onRefresh();
        } else if (payload.status === "failed") {
          setWizardError(payload.error || "知识库入库失败");
        }
      } catch (error) {
        if (active) setWizardError(error.message);
      }
    };
    poll();
    const timer = window.setInterval(poll, 1000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [importId, jobStatus, message, onRefresh]);

  function openDetails(source) {
    setSelectedSource(source);
  }

  function closeDetails() {
    setSelectedSource(null);
  }

  function handleCardKeyDown(event, source) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openDetails(source);
  }

  function resetWizard() {
    form.resetFields();
    form.setFieldsValue(EMPTY_SOURCE);
    setStep(0);
    setImportId(null);
    setTreeData([]);
    setFirstMarkdown("");
    setStrategy("heading");
    setChunkSize(900);
    setPreview(null);
    setJobStatus("");
    setWizardError("");
  }

  function openCreate() {
    setEditingSource(null);
    resetWizard();
    setWizardOpen(true);
  }

  function openEdit(source) {
    closeDetails();
    setEditingSource(source);
    setWizardError("");
    form.setFieldsValue(source);
    setModalOpen(true);
  }

  async function uploadArchive(file, overwrite = false) {
    const sourceId = form.getFieldValue("source_id");
    if (!sourceId) {
      message.error("请先填写标识，再上传压缩包");
      return;
    }
    setWizardLoading(true);
    setWizardError("");
    try {
      const payload = await uploadRagImport(sourceId, file, overwrite);
      setImportId(payload.import_id);
      setTreeData(toTreeData(payload.tree));
      setFirstMarkdown(payload.markdown_files?.[0] || "");
      message.success("压缩包已解压，可以进入下一步");
    } catch (error) {
      setWizardError(error.message);
    } finally {
      setWizardLoading(false);
    }
  }

  async function handleBeforeUpload(file) {
    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.error("暂时只支持 ZIP 压缩包");
      return Upload.LIST_IGNORE;
    }
    try {
      const sourceId = await form.validateFields(["source_id"]);
      const conflict = await checkRagImportConflict(sourceId.source_id);
      if (conflict.conflict) {
        Modal.confirm({
          title: "知识库已存在",
          content: "继续上传会覆盖已有知识库，确定继续吗？",
          okText: "继续覆盖",
          cancelText: "取消",
          okButtonProps: { danger: true },
          onOk: () => uploadArchive(file, true),
        });
      } else {
        await uploadArchive(file);
      }
    } catch (error) {
      if (!error?.errorFields) setWizardError(error.message);
    }
    return Upload.LIST_IGNORE;
  }

  async function loadPreview(nextStrategy = strategy, nextChunkSize = chunkSize) {
    if (!importId) return;
    setWizardLoading(true);
    setWizardError("");
    try {
      const payload = await previewRagImport(importId, nextStrategy, nextChunkSize);
      setPreview(payload);
    } catch (error) {
      setWizardError(error.message);
    } finally {
      setWizardLoading(false);
    }
  }

  async function goNext() {
    if (step === 0) {
      await form.validateFields(["source_id", "name", "description", "call_when"]);
      if (!importId) {
        setWizardError("请先上传 ZIP 压缩包");
        return;
      }
      await loadPreview();
      setStep(1);
      return;
    }
    if (step === 1) {
      const values = await form.validateFields(["source_id", "name", "description", "call_when"]);
      setWizardLoading(true);
      setWizardError("");
      try {
        await startRagImport(importId, values, strategy, chunkSize);
        setJobStatus("processing");
        setStep(2);
      } catch (error) {
        setWizardError(error.message);
      } finally {
        setWizardLoading(false);
      }
    }
  }

  async function closeWizard() {
    setWizardOpen(false);
    if (importId && !["processing", "completed"].includes(jobStatus)) {
      try {
        await deleteRagImport(importId);
      } catch {
        // 暂存目录会在服务端启动时再次清理
      }
    }
  }

  async function handleSave() {
    setWizardError("");
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editingSource) {
        await onEdit(editingSource.source_id, {
          name: values.name,
          description: values.description,
          call_when: values.call_when,
          enabled: values.enabled,
        });
      } else {
        await onAdd(values);
      }
      setModalOpen(false);
    } catch (error) {
      if (error?.errorFields) return;
      setWizardError(error.message);
    } finally {
      setSaving(false);
    }
  }

  const wizardFooter = step === 2 ? (
    <Button onClick={closeWizard}>关闭</Button>
  ) : (
    <Space>
      <Button onClick={closeWizard}>取消</Button>
      {step === 1 ? <Button onClick={() => setStep(0)}>上一步</Button> : null}
      <Button type="primary" onClick={goNext} loading={wizardLoading}>
        {step === 1 ? "开始入库" : "下一步"}
      </Button>
    </Space>
  );

  return (
    <section className="workspace database-workspace">
      <div className="toolbar">
        <Space><Title level={4}>本地知识库</Title><Tag>{sources.length}</Tag></Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={onRefresh}>刷新</Button>
          <Tooltip title="新增数据源">
            <Button icon={<PlusOutlined />} onClick={openCreate} aria-label="新增本地知识库" />
          </Tooltip>
        </Space>
      </div>
      <div className="database-body">
        <Spin spinning={loading} className="database-loading">
          {sources.length === 0 ? <Empty description="暂无数据源" /> : (
            <div className="database-card-grid">
              {sources.map((source) => (
                <Card
                  key={source.source_id}
                  className="database-source-card"
                  hoverable
                  role="button"
                  tabIndex={0}
                  aria-label={`查看 ${source.name} 详情`}
                  onClick={() => openDetails(source)}
                  onKeyDown={(event) => handleCardKeyDown(event, source)}
                >
                  <div className="database-card-heading">
                    <Text strong className="database-card-name">{source.name}</Text>
                    <Tag color={source.enabled ? "green" : "default"}>
                      {source.enabled ? "启用" : "停用"}
                    </Tag>
                  </div>
                  <div className="database-card-field">
                    <Text type="secondary" className="database-card-label">描述</Text>
                    <Text className="database-card-summary">{source.description || "无描述"}</Text>
                  </div>
                  <div className="database-card-field">
                    <Text type="secondary" className="database-card-label">调用条件</Text>
                    <Text className="database-card-summary">{source.call_when || "未设置"}</Text>
                  </div>
                  <div className="database-card-actions" onClick={(event) => event.stopPropagation()}>
                    <Tooltip title="编辑">
                      <Button type="text" icon={<EditOutlined />} aria-label={`编辑 ${source.name}`} onClick={() => openEdit(source)} />
                    </Tooltip>
                    <Popconfirm
                      title="删除数据源配置？"
                      description="只删除数据源配置，不删除本地文件。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => onDelete(source.source_id)}
                    >
                      <Tooltip title="删除">
                        <Button danger type="text" icon={<DeleteOutlined />} aria-label={`删除 ${source.name}`} />
                      </Tooltip>
                    </Popconfirm>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </Spin>
      </div>
      <Drawer
        title={selectedSource?.name || "数据源详情"}
        open={Boolean(selectedSource)}
        onClose={closeDetails}
        width={460}
        destroyOnHidden
        footer={selectedSource ? <Button icon={<EditOutlined />} onClick={() => openEdit(selectedSource)}>编辑数据源</Button> : null}
      >
        {selectedSource ? (
          <Descriptions bordered column={1} items={[
            { key: "name", label: "名称", children: selectedSource.name },
            { key: "source_id", label: "标识", children: selectedSource.source_id },
            { key: "path", label: "目录", children: selectedSource.path_prefix },
            { key: "description", label: "描述", children: selectedSource.description },
            { key: "call_when", label: "调用条件", children: selectedSource.call_when },
            { key: "enabled", label: "状态", children: <Tag color={selectedSource.enabled ? "green" : "default"}>{selectedSource.enabled ? "启用" : "停用"}</Tag> },
          ]} />
        ) : null}
      </Drawer>
      <Modal
        title="新增本地知识库"
        open={wizardOpen}
        onCancel={closeWizard}
        footer={wizardFooter}
        width={1120}
        destroyOnHidden
      >
        <Steps current={step} items={[{ title: "上传资料" }, { title: "选择切片策略" }, { title: "入库" }]} />
        {wizardError ? <Alert className="database-import-alert" type="error" message={wizardError} showIcon /> : null}
        <Text type="secondary" className="database-import-format">暂时只支持 Markdown（可包含常见图片资源）</Text>
        {step === 0 ? (
          <div className="database-import-columns">
            <Form form={form} layout="vertical" initialValues={EMPTY_SOURCE} className="database-import-form">
              <Form.Item name="source_id" label="标识" rules={[{ required: true, message: "请输入小写安全标识" }]}>
                <Input disabled={Boolean(importId)} placeholder="例如 work_notes" />
              </Form.Item>
              <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}><Input /></Form.Item>
              <Form.Item name="description" label="描述" rules={[{ required: true, message: "请输入描述" }]}><Input.TextArea rows={2} /></Form.Item>
              <Form.Item name="call_when" label="调用条件" rules={[{ required: true, message: "请输入调用条件" }]}><Input.TextArea rows={2} /></Form.Item>
            </Form>
            <div className="database-import-upload-panel">
              <Dragger beforeUpload={handleBeforeUpload} showUploadList={false} disabled={wizardLoading || Boolean(importId)}>
                {wizardLoading ? <LoadingOutlined className="database-import-upload-icon" /> : <InboxOutlined className="database-import-upload-icon" />}
                <p>点击或拖拽 ZIP 压缩包到这里</p>
                <Text type="secondary">压缩包最多 100MB，解压后最多 500MB、2000 个文件</Text>
              </Dragger>
              {importId ? <div className="database-import-tree"><Text strong>解压目录</Text><Tree treeData={treeData} defaultExpandAll height={300} /></div> : null}
            </div>
          </div>
        ) : null}
        {step === 1 ? (
          <div className="database-import-columns database-preview-columns">
            <div className="database-import-file-card">
              <FileMarkdownOutlined className="database-import-file-icon" />
              <Text strong>{firstMarkdown || "首个 Markdown 文件"}</Text>
              <Text type="secondary">按文件名顺序选择预览文件</Text>
              <pre>{preview?.content || "选择切片策略后生成预览"}</pre>
              <Text type="secondary">暂时只支持 Markdown</Text>
            </div>
            <div className="database-import-preview-panel">
              <Space className="database-strategy-buttons">
                <Button type={strategy === "heading" ? "primary" : "default"} onClick={() => { setStrategy("heading"); loadPreview("heading", chunkSize); }}>按标题切块</Button>
                <Button type={strategy === "fixed" ? "primary" : "default"} onClick={() => { setStrategy("fixed"); loadPreview("fixed", chunkSize); }}>固定大小</Button>
              </Space>
              {strategy === "fixed" ? <div className="database-chunk-control"><Slider min={150} max={900} value={chunkSize} onChange={setChunkSize} onChangeComplete={(value) => loadPreview("fixed", value)} /><InputNumber min={150} max={900} value={chunkSize} onChange={(value) => { const next = value || 150; setChunkSize(next); loadPreview("fixed", next); }} /></div> : null}
              <Spin spinning={wizardLoading}><div className="database-chunk-list">{preview?.chunks?.map((chunk, index) => <Card size="small" key={`${chunk.heading_breadcrumb}-${index}`} title={`块 ${index + 1} · ${chunk.heading_breadcrumb}`}>{chunk.content}</Card>)}</div></Spin>
            </div>
          </div>
        ) : null}
        {step === 2 ? (
          <div className="database-import-processing">
            {jobStatus === "processing" ? <><Spin size="large" /><Title level={4}>正在处理知识库</Title><Text type="secondary">正在切片、生成向量并建立 BM25 索引，关闭弹窗不会中断处理。</Text></> : null}
            {jobStatus === "completed" ? <><Tag color="green">处理完成</Tag><Text>知识库将在下次重启服务后加载。</Text></> : null}
            {jobStatus === "failed" ? <Tag color="red">处理失败</Tag> : null}
          </div>
        ) : null}
      </Modal>
      <Modal title="编辑本地知识库" open={modalOpen} onCancel={() => setModalOpen(false)} onOk={handleSave} okText="保存" cancelText="取消" confirmLoading={saving} destroyOnHidden>
        {wizardError ? <Text type="danger">{wizardError}</Text> : null}
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述" rules={[{ required: true, message: "请输入描述" }]}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="call_when" label="调用条件" rules={[{ required: true, message: "请输入调用条件" }]}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </section>
  );
}
