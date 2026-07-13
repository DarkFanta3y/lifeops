import { useEffect, useMemo, useState } from "react";
import { Button, Pagination, Segmented, Space, Table, Tag, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

const { Text, Title } = Typography;
const PAGE_SIZE = 8;

function McpToolList({ tools }) {
  return <div className="mcp-tool-list">{tools.map((tool) => (
    <div className="mcp-tool-item" key={tool.name}>
      <Text strong>{tool.name}</Text>
      <Text type="secondary">{tool.description || "无描述"}</Text>
      <Text type="secondary">参数：{Object.keys(tool.parameters?.properties || {}).join(", ") || "无"}</Text>
    </div>
  ))}</div>;
}

export default function ToolsWorkspace({ tools, mcpServers, loading, onRefresh }) {
  const [activeToolsTab, setActiveToolsTab] = useState("tool");
  const [page, setPage] = useState(1);
  const toolRows = useMemo(() => tools.filter((tool) => tool.category !== "mcp").map((tool) => ({
    ...tool, rowType: "tool", rowKey: `tool:${tool.name}`,
  })), [tools]);
  const mcpRows = useMemo(() => mcpServers.map((server) => ({
    rowType: "mcp-server", rowKey: `mcp:${server.name}`, name: server.name,
    description: `${server.tools.length} 个 MCP 工具`, category: "mcp-server",
    parameters: { properties: {} }, tools: server.tools,
  })), [mcpServers]);
  const rows = activeToolsTab === "tool" ? toolRows : mcpRows;
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const hasPagination = rows.length > PAGE_SIZE;
  const pagedRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const columns = [
    { title: "名称", dataIndex: "name", key: "name", width: 220 },
    { title: "描述", dataIndex: "description", key: "description" },
    { title: "分类", dataIndex: "category", key: "category", width: 140,
      render: (category) => category === "mcp-server" ? "MCP Server" : category },
    { title: "参数", key: "parameters",
      render: (_, item) => Object.keys(item.parameters?.properties || {}).join(", ") || "无" },
  ];

  useEffect(() => setPage(1), [activeToolsTab]);
  useEffect(() => setPage((current) => Math.min(current, pageCount)), [pageCount]);

  return (
    <section className="workspace table-workspace">
      <div className="toolbar">
        <Space><Title level={4}>Tool 列表</Title><Tag>{rows.length}</Tag></Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={onRefresh}>刷新</Button>
          <Segmented value={activeToolsTab} onChange={setActiveToolsTab}
            options={[{ label: "TOOL", value: "tool" }, { label: "MCP", value: "mcp" }]} />
        </Space>
      </div>
      <div className={`table-body${hasPagination ? " with-pagination" : ""}`}>
        <Table rowKey="rowKey" columns={columns} dataSource={pagedRows} loading={loading}
          pagination={false} expandable={{
            rowExpandable: (record) => activeToolsTab === "mcp" && record.rowType === "mcp-server",
            expandedRowRender: (record) => <McpToolList tools={record.tools || []} />,
          }} />
      </div>
      {hasPagination ? (
        <>
          <div className="workspace-pagination-overlay" aria-hidden="true" />
          <Pagination className="workspace-pagination" current={page} pageSize={PAGE_SIZE}
            total={rows.length} showSizeChanger={false} onChange={setPage} />
        </>
      ) : null}
    </section>
  );
}
