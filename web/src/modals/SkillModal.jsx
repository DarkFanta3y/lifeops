import { Input, Modal, Typography } from "antd";

import MarkdownRenderer from "../MarkdownRenderer.jsx";

const { Text } = Typography;

export default function SkillModal({ open, value, saving, onChange, onSave, onClose }) {
  const updateField = (field, nextValue) => onChange({ ...value, [field]: nextValue });
  const canSave = /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.name)
    && value.description.trim() && value.content.trim();
  return (
    <Modal title="新增 Skill" open={open} onCancel={onClose} onOk={onSave} okText="保存"
      cancelText="取消" confirmLoading={saving} okButtonProps={{ disabled: !canSave }}
      width={780} destroyOnHidden>
      <div className="skill-form">
        <label><Text strong>名称</Text><Input value={value.name}
          onChange={(event) => updateField("name", event.target.value)} placeholder="weekly-review" autoFocus />
          <Text type="secondary">仅支持小写字母、数字和短横线。</Text></label>
        <label><Text strong>描述</Text><Input.TextArea value={value.description}
          onChange={(event) => updateField("description", event.target.value)} rows={5}
          placeholder="写入 Markdown 描述，保存为 YAML block scalar。" />
          <div className="markdown-preview" aria-label="描述预览">
            <MarkdownRenderer content={value.description} emptyText="描述预览" />
          </div></label>
        <label><Text strong>metadata</Text><Input.TextArea value={value.metadata}
          onChange={(event) => updateField("metadata", event.target.value)} rows={4}
          placeholder={"short-description: 周复盘\nowner: lifeops"} /></label>
        <label><Text strong>SKILL 内容</Text><Input.TextArea value={value.content}
          onChange={(event) => updateField("content", event.target.value)} rows={8}
          placeholder="# Skill\n\n写入执行步骤。" /></label>
      </div>
    </Modal>
  );
}
