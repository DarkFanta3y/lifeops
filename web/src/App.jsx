import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Alert,
  App as AntApp,
  Button,
  Collapse,
  Empty,
  Input,
  Layout,
  Modal,
  Pagination,
  Popconfirm,
  Segmented,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  AppstoreOutlined,
  DeleteOutlined,
  DownOutlined,
  FileTextOutlined,
  MessageOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
  SearchOutlined,
  SendOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import {
  API_BASE,
  createSkill,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  fetchSkills,
  fetchTools,
  sendChatMessage,
} from "./api.js";

const { Sider, Content } = Layout;
const { Text, Title } = Typography;
const TABLE_PAGE_SIZE = 8;
const SEARCH_DEBOUNCE_MS = 250;

function App() {
  const { message } = AntApp.useApp();
  const [activeView, setActiveView] = useState("chat");
  const [conversations, setConversations] = useState([]);
  const [selectedConversationId, setSelectedConversationId] = useState(null);
  const [conversationMessages, setConversationMessages] = useState([]);
  const [intermediateMessages, setIntermediateMessages] = useState([]);
  const [skills, setSkills] = useState([]);
  const [tools, setTools] = useState([]);
  const [mcpServers, setMcpServers] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [skillModalOpen, setSkillModalOpen] = useState(false);
  const [savingSkill, setSavingSkill] = useState(false);
  const requestIdRef = useRef(0);
  const [skillForm, setSkillForm] = useState({
    name: "",
    description: "",
    metadata: "",
    content: "",
  });

  const selectedConversation = useMemo(
    () =>
      conversations.find(
        (conversation) => conversation.conversation_id === selectedConversationId,
      ),
    [conversations, selectedConversationId],
  );

  useEffect(() => {
    loadConversations();
  }, []);

  useEffect(() => {
    if (activeView === "skills" && skills.length === 0) {
      loadSkills();
    }
    if (activeView === "tools" && tools.length === 0) {
      loadTools();
    }
  }, [activeView, skills.length, tools.length]);

  useEffect(() => {
    if (!searchOpen) {
      return undefined;
    }

    if (!searchQuery.trim()) {
      requestIdRef.current += 1;
      setSearchResults([]);
      setSearchError("");
      setSearchLoading(false);
      return undefined;
    }

    const timer = setTimeout(() => {
      handleSearch(searchQuery);
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
    };
  }, [searchOpen, searchQuery]);

  async function loadConversations(options = {}) {
    const hasNextSelectedId = Object.prototype.hasOwnProperty.call(options, "nextSelectedId");
    const requestedSelectedId = hasNextSelectedId
      ? options.nextSelectedId
      : selectedConversationId;
    const autoSelect = options.autoSelect ?? true;

    setLoading(true);
    setError("");
    try {
      const payload = await fetchConversations();
      const nextConversations = payload.conversations || [];
      const requestedExists =
        requestedSelectedId &&
        nextConversations.some(
          (conversation) => conversation.conversation_id === requestedSelectedId,
        );
      const nextId = requestedExists
        ? requestedSelectedId
        : autoSelect
          ? nextConversations[0]?.conversation_id || null
          : null;

      setConversations(nextConversations);
      setSelectedConversationId(nextId);
      if (nextId) {
        await loadConversation(nextId);
      } else {
        setConversationMessages([]);
        setIntermediateMessages([]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadConversation(conversationId) {
    setActiveView("chat");
    setError("");
    try {
      const payload = await fetchConversation(conversationId);
      setSelectedConversationId(conversationId);
      setConversationMessages(payload.messages || []);
      setIntermediateMessages(payload.intermediate_messages || []);
    } catch (err) {
      setError(err.message);
    }
  }

  async function loadSkills() {
    setLoading(true);
    setError("");
    try {
      const payload = await fetchSkills();
      setSkills(payload.skills || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function loadTools() {
    setLoading(true);
    setError("");
    try {
      const payload = await fetchTools();
      setTools(payload.tools || []);
      setMcpServers(payload.mcp_servers || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateSkill() {
    setSavingSkill(true);
    setError("");
    try {
      await createSkill(skillForm);
      message.success("Skill 已创建");
      setSkillModalOpen(false);
      setSkillForm({ name: "", description: "", metadata: "", content: "" });
      await loadSkills();
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingSkill(false);
    }
  }

  function handleNewChat() {
    setActiveView("chat");
    setSelectedConversationId(null);
    setConversationMessages([]);
    setIntermediateMessages([]);
    setChatInput("");
    setError("");
  }

  async function handleSearch(rawQuery = searchQuery) {
    const query = rawQuery.trim();
    setSearchQuery(rawQuery);
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    if (!query) {
      setSearchResults([]);
      setSearchError("");
      setSearchLoading(false);
      return;
    }

    setSearchLoading(true);
    setSearchError("");
    try {
      const payload = await fetchConversations(query);
      if (requestId !== requestIdRef.current) {
        return;
      }
      setSearchResults(payload.conversations || []);
    } catch (err) {
      if (requestId !== requestIdRef.current) {
        return;
      }
      setSearchError(err.message);
    } finally {
      if (requestId === requestIdRef.current) {
        setSearchLoading(false);
      }
    }
  }

  async function handleSelectSearchResult(conversationId) {
    setSearchOpen(false);
    await loadConversation(conversationId);
  }

  async function handleDeleteConversation(conversationId) {
    setError("");
    try {
      await deleteConversation(conversationId);
      message.success("对话已删除");
      await loadConversations({
        nextSelectedId:
          conversationId === selectedConversationId ? null : selectedConversationId,
        autoSelect: conversationId !== selectedConversationId,
      });
      setSearchResults((current) =>
        current.filter((item) => item.conversation_id !== conversationId),
      );
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleSend() {
    const content = chatInput.trim();
    if (!content || sending) {
      return;
    }

    setActiveView("chat");
    setSending(true);
    setError("");
    const optimisticUserMessage = {
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    setConversationMessages((current) => [...current, optimisticUserMessage]);
    setChatInput("");

    try {
      let streamedContent = "";

      const payload = await sendChatMessage({
        message: content,
        conversationId: selectedConversationId,
        onToken: (tokenText) => {
          streamedContent += tokenText;
          setConversationMessages((current) => {
            const msgs = [...current];
            const lastMsg = msgs[msgs.length - 1];
            if (lastMsg && lastMsg.role === "assistant") {
              msgs[msgs.length - 1] = { ...lastMsg, content: streamedContent };
            } else {
              msgs.push({
                role: "assistant",
                content: streamedContent,
                created_at: new Date().toISOString(),
              });
            }
            return msgs;
          });
        },
      });

      await loadConversations({
        nextSelectedId: payload.conversation_id,
        autoSelect: false,
      });
    } catch (err) {
      setError(err.message);
      setConversationMessages((current) =>
        current.filter((item) => item !== optimisticUserMessage),
      );
    } finally {
      setSending(false);
    }
  }

  function renderContent() {
    if (activeView === "chat") {
      return (
        <ChatWorkspace
          selectedConversation={selectedConversation}
          messages={conversationMessages}
          intermediateMessages={intermediateMessages}
          selectedConversationId={selectedConversationId}
          chatInput={chatInput}
          sending={sending}
          onInputChange={setChatInput}
          onSend={handleSend}
        />
      );
    }

    if (activeView === "skills") {
      return (
        <SkillsWorkspace
          skills={skills}
          loading={loading}
          onRefresh={loadSkills}
          onAdd={() => setSkillModalOpen(true)}
        />
      );
    }

    return (
      <ToolsWorkspace
        tools={tools}
        mcpServers={mcpServers}
        loading={loading}
        onRefresh={loadTools}
      />
    );
  }

  return (
    <Layout className="app-shell">
      <Sider className="sidebar" width={264} breakpoint="md" collapsedWidth={72}>
        <div className="brand">
          <img src="/lifeops_logo.svg" alt="LifeOps" />
        </div>
        <div className="sidebar-actions">
          <Button type="primary" icon={<PlusOutlined />} block onClick={handleNewChat}>
            新聊天
          </Button>
          <Button
            icon={<SearchOutlined />}
            block
            onClick={() => {
              setSearchOpen(true);
              setSearchQuery("");
              setSearchResults([]);
              setSearchError("");
            }}
          >
            搜索标题
          </Button>
        </div>
        <nav className="sidebar-nav" aria-label="主导航">
          <button
            type="button"
            className={activeView === "skills" ? "sidebar-nav-item active" : "sidebar-nav-item"}
            onClick={() => setActiveView("skills")}
          >
            <AppstoreOutlined />
            <span>SKILLS</span>
          </button>
          <button
            type="button"
            className={activeView === "tools" ? "sidebar-nav-item active" : "sidebar-nav-item"}
            onClick={() => setActiveView("tools")}
          >
            <ToolOutlined />
            <span>TOOLS</span>
          </button>
        </nav>
        <section className="sidebar-conversations">
          <button
            type="button"
            className="conversation-group-toggle"
            onClick={() => setConversationsOpen((current) => !current)}
          >
            {conversationsOpen ? <DownOutlined /> : <RightOutlined />}
            <span>对话</span>
            <Tag>{conversations.length}</Tag>
          </button>
          {conversationsOpen ? (
            <Spin spinning={loading}>
              <ConversationList
                conversations={conversations}
                selectedConversationId={selectedConversationId}
                onSelect={loadConversation}
                onDelete={handleDeleteConversation}
              />
            </Spin>
          ) : null}
        </section>
      </Sider>
      <Layout className="main-layout">
        <Content className="content">
          {error ? <Alert className="content-alert" type="error" message={error} showIcon /> : null}
          {renderContent()}
        </Content>
      </Layout>
      <SearchModal
        open={searchOpen}
        query={searchQuery}
        results={searchResults}
        loading={searchLoading}
        error={searchError}
        onQueryChange={setSearchQuery}
        onSearch={handleSearch}
        onSelect={handleSelectSearchResult}
        onClose={() => setSearchOpen(false)}
      />
      <SkillModal
        open={skillModalOpen}
        value={skillForm}
        saving={savingSkill}
        onChange={setSkillForm}
        onSave={handleCreateSkill}
        onClose={() => setSkillModalOpen(false)}
      />
    </Layout>
  );
}

function ConversationList({ conversations, selectedConversationId, onSelect, onDelete }) {
  if (conversations.length === 0) {
    return (
      <div className="sidebar-empty">
        <Empty description="暂无对话" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    );
  }

  return (
    <div className="conversation-list">
      {conversations.map((item) => (
        <div
          key={item.conversation_id}
          className={
            item.conversation_id === selectedConversationId
              ? "conversation-item active"
              : "conversation-item"
          }
        >
          <button
            type="button"
            className="conversation-select"
            onClick={() => onSelect(item.conversation_id)}
          >
            <Text strong>{item.title || "未命名对话"}</Text>
            <Text type="secondary">{item.last_message}</Text>
          </button>
          <Popconfirm
            title="删除对话？"
            description="该对话的历史消息会从本地记录中移除。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onDelete(item.conversation_id)}
          >
            <Tooltip title="删除">
              <Button
                danger
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                className="conversation-delete"
                aria-label="删除对话"
              />
            </Tooltip>
          </Popconfirm>
        </div>
      ))}
    </div>
  );
}

function SearchModal({
  open,
  query,
  results,
  loading,
  error,
  onQueryChange,
  onSearch,
  onSelect,
  onClose,
}) {
  return (
    <Modal title="搜索对话标题" open={open} onCancel={onClose} footer={null} destroyOnHidden>
      <Input.Search
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        onSearch={onSearch}
        enterButton="搜索"
        loading={loading}
        allowClear
        autoFocus
      />
      {error ? <Alert className="search-alert" type="error" message={error} showIcon /> : null}
      <div className="search-results">
        <Spin spinning={loading}>
          {results.length === 0 ? (
            <Empty description={query.trim() ? "无匹配标题" : "输入标题关键词后搜索"} />
          ) : (
            results.map((item) => (
              <button
                type="button"
                key={item.conversation_id}
                className="search-result-item"
                onClick={() => onSelect(item.conversation_id)}
              >
                <Text strong>{item.title || "未命名对话"}</Text>
                <Text type="secondary">{item.last_message}</Text>
              </button>
            ))
          )}
        </Spin>
      </div>
    </Modal>
  );
}

function ChatWorkspace({
  selectedConversation,
  messages,
  intermediateMessages,
  selectedConversationId,
  chatInput,
  sending,
  onInputChange,
  onSend,
}) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const [loggingOpen, setLoggingOpen] = useState(false);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <section className="workspace chat-workspace">
      <main className="chat-pane">
        <div className="chat-head">
          <div>
            <Text type="secondary">当前对话</Text>
            <Title level={4}>{selectedConversation?.title || "新对话"}</Title>
          </div>
          <div>
            <Tag color="blue">{messages.length} 条消息</Tag>
            <Button
              type="text"
              size="small"
              icon={<FileTextOutlined />}
              className="logging-btn"
              onClick={() => setLoggingOpen(true)}
            >
              Logging
            </Button>
          </div>
        </div>
        <div className={`message-stream${messages.length === 0 ? ' message-stream-empty' : ''}`}>
          {messages.length === 0 ? (
            <Empty description="从下方输入开始一次新对话" />
          ) : (
            messages.map((item, index) => (
              <div className={`message-row ${item.role}`} key={`${item.created_at}-${index}`}>
                <div className="message-bubble">
                  <Text className="role-label">{roleLabel(item.role)}</Text>
                  <MarkdownRenderer content={item.content} emptyText="" />
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>
        <div className="composer">
          <div className="composer-actions">
            <Button
              type="text"
              size="small"
              icon={<MessageOutlined />}
              className="composer-preview-toggle"
              aria-expanded={previewOpen}
              onClick={() => setPreviewOpen((current) => !current)}
            >
              {previewOpen ? "隐藏预览" : "预览"}
            </Button>
          </div>
          {previewOpen ? (
            <div className="composer-preview" aria-label="Markdown 预览">
              <MarkdownRenderer content={chatInput} emptyText="暂无预览内容" />
            </div>
          ) : null}
          <div className="composer-input">
            <Input.TextArea
              value={chatInput}
              onChange={(event) => onInputChange(event.target.value)}
              onPressEnter={(event) => {
                if (!event.shiftKey) {
                  event.preventDefault();
                  onSend();
                }
              }}
              placeholder="输入消息，Enter 发送，Shift+Enter 换行"
              autoSize={{ minRows: 2, maxRows: 6 }}
            />
            <Tooltip title="发送">
              <Button
                className="composer-send"
                type="primary"
                shape="circle"
                icon={<SendOutlined />}
                aria-label="发送消息"
                loading={sending}
                disabled={!chatInput.trim() || sending}
                onClick={onSend}
              />
            </Tooltip>
          </div>
        </div>
      </main>
      <LoggingModal
        open={loggingOpen}
        intermediateMessages={intermediateMessages}
        onClose={() => setLoggingOpen(false)}
      />
    </section>
  );
}

function SkillsWorkspace({ skills, loading, onRefresh, onAdd }) {
  const [page, setPage] = useState(1);
  const pageCount = Math.max(1, Math.ceil(skills.length / TABLE_PAGE_SIZE));
  const hasPagination = skills.length > TABLE_PAGE_SIZE;
  const pagedSkills = skills.slice((page - 1) * TABLE_PAGE_SIZE, page * TABLE_PAGE_SIZE);
  const columns = [
    { title: "名称", dataIndex: "name", key: "name", width: 220 },
    { title: "描述", dataIndex: "description", key: "description" },
    { title: "来源", dataIndex: "source", key: "source", width: 120 },
    {
      title: "路径",
      dataIndex: "path",
      key: "path",
      ellipsis: true,
    },
  ];

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount));
  }, [pageCount]);

  return (
    <section className="workspace table-workspace">
      <Toolbar
        title="Skill 列表"
        count={skills.length}
        onRefresh={onRefresh}
        extraActions={
          <Tooltip title="新增 Skill">
            <Button icon={<PlusOutlined />} onClick={onAdd} aria-label="新增 Skill" />
          </Tooltip>
        }
      />
      <div className={`table-body${hasPagination ? " with-pagination" : ""}`}>
        <Table
          rowKey="name"
          columns={columns}
          dataSource={pagedSkills}
          loading={loading}
          pagination={false}
        />
      </div>
      {hasPagination ? (
        <>
          <div className="workspace-pagination-overlay" aria-hidden="true" />
          <Pagination
            className="workspace-pagination"
            current={page}
            pageSize={TABLE_PAGE_SIZE}
            total={skills.length}
            showSizeChanger={false}
            onChange={setPage}
          />
        </>
      ) : null}
    </section>
  );
}

function ToolsWorkspace({ tools, mcpServers, loading, onRefresh }) {
  const [activeToolsTab, setActiveToolsTab] = useState("tool");
  const [page, setPage] = useState(1);
  const toolRows = useMemo(
    () =>
      tools
        .filter((tool) => tool.category !== "mcp")
        .map((tool) => ({
          ...tool,
          rowType: "tool",
          rowKey: `tool:${tool.name}`,
        })),
    [tools],
  );
  const mcpRows = useMemo(
    () =>
      mcpServers.map((server) => ({
        rowType: "mcp-server",
        rowKey: `mcp:${server.name}`,
        name: server.name,
        description: `${server.tools.length} 个 MCP 工具`,
        category: "mcp-server",
        parameters: { properties: {} },
        tools: server.tools,
      })),
    [mcpServers],
  );
  const rows = activeToolsTab === "tool" ? toolRows : mcpRows;
  const pageCount = Math.max(1, Math.ceil(rows.length / TABLE_PAGE_SIZE));
  const hasPagination = rows.length > TABLE_PAGE_SIZE;
  const pagedRows = rows.slice((page - 1) * TABLE_PAGE_SIZE, page * TABLE_PAGE_SIZE);
  const columns = [
    { title: "名称", dataIndex: "name", key: "name", width: 220 },
    { title: "描述", dataIndex: "description", key: "description" },
    {
      title: "分类",
      dataIndex: "category",
      key: "category",
      width: 140,
      render: (category) => (category === "mcp-server" ? "MCP Server" : category),
    },
    {
      title: "参数",
      key: "parameters",
      render: (_, item) => Object.keys(item.parameters?.properties || {}).join(", ") || "无",
    },
  ];

  useEffect(() => {
    setPage(1);
  }, [activeToolsTab]);

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount));
  }, [pageCount]);

  return (
    <section className="workspace table-workspace">
      <Toolbar
        title="Tool 列表"
        count={rows.length}
        onRefresh={onRefresh}
        extraActions={
          <Segmented
            value={activeToolsTab}
            onChange={setActiveToolsTab}
            options={[
              { label: "TOOL", value: "tool" },
              { label: "MCP", value: "mcp" },
            ]}
          />
        }
      />
      <div className={`table-body${hasPagination ? " with-pagination" : ""}`}>
        <Table
          rowKey="rowKey"
          columns={columns}
          dataSource={pagedRows}
          loading={loading}
          pagination={false}
          expandable={{
            rowExpandable: (record) => activeToolsTab === "mcp" && record.rowType === "mcp-server",
            expandedRowRender: (record) => <McpToolList tools={record.tools || []} />,
          }}
        />
      </div>
      {hasPagination ? (
        <>
          <div className="workspace-pagination-overlay" aria-hidden="true" />
          <Pagination
            className="workspace-pagination"
            current={page}
            pageSize={TABLE_PAGE_SIZE}
            total={rows.length}
            showSizeChanger={false}
            onChange={setPage}
          />
        </>
      ) : null}
    </section>
  );
}

function Toolbar({ title, count, onRefresh, extraActions }) {
  return (
    <div className="toolbar">
      <Space>
        <Title level={4}>{title}</Title>
        <Tag>{count}</Tag>
      </Space>
      <Space>
        <Button icon={<ReloadOutlined />} onClick={onRefresh}>
          刷新
        </Button>
        {extraActions}
      </Space>
    </div>
  );
}

function McpToolList({ tools }) {
  return (
    <div className="mcp-tool-list">
      {tools.map((tool) => (
        <div className="mcp-tool-item" key={tool.name}>
          <Text strong>{tool.name}</Text>
          <Text type="secondary">{tool.description || "无描述"}</Text>
          <Text type="secondary">
            参数：{Object.keys(tool.parameters?.properties || {}).join(", ") || "无"}
          </Text>
        </div>
      ))}
    </div>
  );
}

function SkillModal({ open, value, saving, onChange, onSave, onClose }) {
  const updateField = (field, nextValue) => {
    onChange({ ...value, [field]: nextValue });
  };
  const canSave =
    /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.name) &&
    value.description.trim() &&
    value.content.trim();

  return (
    <Modal
      title="新增 Skill"
      open={open}
      onCancel={onClose}
      onOk={onSave}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      okButtonProps={{ disabled: !canSave }}
      width={780}
      destroyOnHidden
    >
      <div className="skill-form">
        <label>
          <Text strong>名称</Text>
          <Input
            value={value.name}
            onChange={(event) => updateField("name", event.target.value)}
            placeholder="weekly-review"
            autoFocus
          />
          <Text type="secondary">仅支持小写字母、数字和短横线。</Text>
        </label>
        <label>
          <Text strong>描述</Text>
          <Input.TextArea
            value={value.description}
            onChange={(event) => updateField("description", event.target.value)}
            rows={5}
            placeholder="写入 Markdown 描述，保存为 YAML block scalar。"
          />
          <div className="markdown-preview" aria-label="描述预览">
            <MarkdownRenderer content={value.description} emptyText="描述预览" />
          </div>
        </label>
        <label>
          <Text strong>metadata</Text>
          <Input.TextArea
            value={value.metadata}
            onChange={(event) => updateField("metadata", event.target.value)}
            rows={4}
            placeholder={"short-description: 周复盘\nowner: lifeops"}
          />
        </label>
        <label>
          <Text strong>SKILL 内容</Text>
          <Input.TextArea
            value={value.content}
            onChange={(event) => updateField("content", event.target.value)}
            rows={8}
            placeholder="# Skill\n\n写入执行步骤。"
          />
        </label>
      </div>
    </Modal>
  );
}

function LoggingModal({ open, intermediateMessages, onClose }) {
  const [selectedKey, setSelectedKey] = useState(null);

  const items = useMemo(() => {
    const items = [];
    const processedToolCallIds = new Set();

    intermediateMessages.forEach((msg, index) => {
      if (msg.role === "assistant" && msg.tool_calls?.length > 0) {
        msg.tool_calls.forEach((toolCall) => {
          if (toolCall.id && !processedToolCallIds.has(toolCall.id)) {
            processedToolCallIds.add(toolCall.id);

            const toolResults = intermediateMessages.filter(
              (m) => m.role === "tool" && m.tool_call_id === toolCall.id
            );

            items.push({
              key: toolCall.id,
              type: "tool-call",
              toolName: toolCall.function?.name || "未知工具",
              toolCall,
              toolResults,
            });
          }
        });
      } else if (!(msg.role === "tool" && msg.tool_call_id)) {
        items.push({
          key: `${msg.created_at}-${index}`,
          type: "message",
          entryType: loggingEntryType(msg),
          entrySummary: loggingEntrySummary(msg),
          content: msg.content || "",
        });
      }
    });

    return items;
  }, [intermediateMessages]);

  const selectedItem = useMemo(() => {
    return items.find((item) => item.key === selectedKey) || items[0];
  }, [items, selectedKey]);

  if (intermediateMessages.length === 0) {
    return (
      <Modal
        title="回答中间信息"
        open={open}
        onCancel={onClose}
        footer={null}
        width="90vw"
        style={{ top: "5vh" }}
        destroyOnHidden
        styles={{ body: { padding: "16px 24px", height: "80vh", overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" } }}
      >
        <Empty description="暂无中间信息" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </Modal>
    );
  }

  return (
    <Modal
      title="回答中间信息"
      open={open}
      onCancel={onClose}
      footer={null}
      width="90vw"
      style={{ top: "5vh" }}
      destroyOnHidden
      styles={{ body: { padding: 0, height: "80vh", overflow: "hidden" } }}
    >
      <div className="logging-split-view">
        <div className="logging-list">
          {items.map((item) => (
            <button
              key={item.key}
              className={`logging-list-item ${selectedItem?.key === item.key ? "active" : ""}`}
              onClick={() => setSelectedKey(item.key)}
            >
              {item.type === "tool-call" ? (
                <div className="logging-list-item-content">
                  <Text className="role-label">工具调用</Text>
                  <Text strong>{item.toolName}</Text>
                </div>
              ) : (
                <div className="logging-list-item-content">
                  {/* 兼容布局测试：旧渲染路径为 {loggingEntryType(msg)} */}
                  <Text className="role-label">{item.entryType}</Text>
                  <Text type="secondary">{item.entrySummary}</Text>
                </div>
              )}
            </button>
          ))}
        </div>
        <div className="logging-preview">
          {selectedItem ? (
            selectedItem.type === "tool-call" ? (
              <div className="logging-entry">
                <div>
                  <Text strong>调用参数：</Text>
                  {/* 兼容布局测试：旧渲染路径为 <ToolCallDetails toolCalls={msg.tool_calls || []} /> */}
                  <ToolCallDetails toolCalls={[selectedItem.toolCall]} />
                </div>
                {selectedItem.toolResults && selectedItem.toolResults.length > 0 && (
                  <div style={{ marginTop: "16px" }}>
                    <Text strong>执行结果：</Text>
                    {selectedItem.toolResults.map((result, i) => (
                      <div key={`result-${i}`} style={{ marginTop: "10px" }}>
                        <div className="logging-meta">
                          <Text type="secondary">工具: {result.tool_name}</Text>
                        </div>
                        <MarkdownRenderer
                          content={result.content || ""}
                          emptyText="(无内容)"
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="logging-entry">
                <MarkdownRenderer content={selectedItem.content} emptyText="(无内容)" />
              </div>
            )
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

function ToolCallDetails({ toolCalls }) {
  if (toolCalls.length === 0) {
    return null;
  }

  return (
    <div className="tool-call-list">
      {toolCalls.map((toolCall, index) => (
        <div className="tool-call-item" key={toolCall.id || index}>
          <Text strong>{toolCall.function?.name || "未知工具"}</Text>
          {toolCall.id ? <Text type="secondary">调用ID: {toolCall.id}</Text> : null}
          <pre>{toolCall.function?.arguments || "{}"}</pre>
        </div>
      ))}
    </div>
  );
}

function loggingEntryType(msg) {
  if (msg.role === "assistant" && msg.tool_calls) {
    return "工具调用";
  }
  if (msg.role === "tool") {
    return "工具结果";
  }
  return "中间信息";
}

function loggingEntrySummary(msg) {
  if (msg.role === "assistant" && msg.tool_calls?.length) {
    return msg.tool_calls
      .map((toolCall) => toolCall.function?.name || "未知工具")
      .join(", ");
  }
  const content = msg.content || "(无内容)";
  return content.slice(0, 60) + (content.length > 60 ? "..." : "");
}

function MarkdownRenderer({ content, emptyText = "" }) {
  const markdown = content?.trim() ? content : emptyText;

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ img: MarkdownImage }}
        skipHtml
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}

function MarkdownImage({ src = "", alt = "", ...props }) {
  const resolvedSrc = src.startsWith("/api/") ? `${API_BASE}${src}` : src;
  return <img src={resolvedSrc} alt={alt} {...props} />;
}

function roleLabel(role) {
  if (role === "assistant") {
    return "助手";
  }
  if (role === "tool") {
    return "工具";
  }
  return "用户";
}

export default App;
