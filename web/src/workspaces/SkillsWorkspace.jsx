import { useEffect, useState } from "react";
import { Button, Pagination, Space, Table, Tag, Tooltip, Typography } from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";

const { Title } = Typography;
const PAGE_SIZE = 8;

export default function SkillsWorkspace({ skills, loading, onRefresh, onAdd }) {
  const [page, setPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(skills.length / PAGE_SIZE));
  const hasPagination = skills.length > PAGE_SIZE;
  const pagedSkills = skills.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const columns = [
    { title: "名称", dataIndex: "name", key: "name", width: 220 },
    { title: "描述", dataIndex: "description", key: "description" },
    { title: "来源", dataIndex: "source", key: "source", width: 120 },
    { title: "路径", dataIndex: "path", key: "path", ellipsis: true },
  ];

  useEffect(() => setPage((current) => Math.min(current, pageCount)), [pageCount]);

  return (
    <section className="workspace table-workspace">
      <div className="toolbar">
        <Space><Title level={4}>Skill 列表</Title><Tag>{skills.length}</Tag></Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={onRefresh}>刷新</Button>
          <Tooltip title="新增 Skill">
            <Button icon={<PlusOutlined />} onClick={onAdd} aria-label="新增 Skill" />
          </Tooltip>
        </Space>
      </div>
      <div className={`table-body${hasPagination ? " with-pagination" : ""}`}>
        <Table rowKey="name" columns={columns} dataSource={pagedSkills} loading={loading} pagination={false} />
      </div>
      {hasPagination ? (
        <>
          <div className="workspace-pagination-overlay" aria-hidden="true" />
          <Pagination className="workspace-pagination" current={page} pageSize={PAGE_SIZE}
            total={skills.length} showSizeChanger={false} onChange={setPage} />
        </>
      ) : null}
    </section>
  );
}
