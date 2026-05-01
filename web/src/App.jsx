import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Empty,
  Input,
  Layout,
  Modal,
  Popconfirm,
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
  MessageOutlined,
  PlusOutlined,
  ReloadOutlined,
  RightOutlined,
  SearchOutlined,
  SendOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import {
  deleteConversation,
  fetchConversation,
  fetchConversations,
  fetchSkills,
  fetchTools,
  sendChatMessage,
} from "./api.js";

const { Sider, Content } = Layout;
const { Text, Title } = Typography;

function App() {
  const { message } = AntApp.useApp();
  const [activeView, setActiveView] = useState("chat");
  const [conversations, setConversations] = useState([]);
  const [selectedConversationId, setSelectedConversationId] = useState(null);
  const [conversationMessages, setConversationMessages] = useState([]);
  const [skills, setSkills] = useState([]);
  const [tools, setTools] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);

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
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function handleNewChat() {
    setActiveView("chat");
    setSelectedConversationId(null);
    setConversationMessages([]);
    setChatInput("");
    setError("");
  }

  async function handleSearch(rawQuery = searchQuery) {
    const query = rawQuery.trim();
    setSearchQuery(rawQuery);
    if (!query) {
      setSearchResults([]);
      return;
    }

    setSearchLoading(true);
    try {
      const payload = await fetchConversations(query);
      setSearchResults(payload.conversations || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setSearchLoading(false);
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
      const payload = await sendChatMessage({
        message: content,
        conversationId: selectedConversationId,
      });
      message.success("已发送");
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
          chatInput={chatInput}
          sending={sending}
          onInputChange={setChatInput}
          onSend={handleSend}
        />
      );
    }

    if (activeView === "skills") {
      return <SkillsWorkspace skills={skills} loading={loading} onRefresh={loadSkills} />;
    }

    return <ToolsWorkspace tools={tools} loading={loading} onRefresh={loadTools} />;
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
            }}
          >
            搜索聊天
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
        onQueryChange={setSearchQuery}
        onSearch={handleSearch}
        onSelect={handleSelectSearchResult}
        onClose={() => setSearchOpen(false)}
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
  onQueryChange,
  onSearch,
  onSelect,
  onClose,
}) {
  return (
    <Modal title="搜索聊天" open={open} onCancel={onClose} footer={null} destroyOnHidden>
      <Input.Search
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        onSearch={onSearch}
        enterButton="搜索"
        loading={loading}
        allowClear
        autoFocus
      />
      <div className="search-results">
        <Spin spinning={loading}>
          {results.length === 0 ? (
            <Empty description={query.trim() ? "无匹配对话" : "输入关键词后搜索"} />
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
  chatInput,
  sending,
  onInputChange,
  onSend,
}) {
  return (
    <section className="workspace chat-workspace">
      <main className="chat-pane">
        <div className="chat-head">
          <div>
            <Text type="secondary">当前对话</Text>
            <Title level={4}>{selectedConversation?.title || "新对话"}</Title>
          </div>
          <Tag color="blue">{messages.length} 条消息</Tag>
        </div>
        <div className="message-stream">
          {messages.length === 0 ? (
            <Empty description="从下方输入开始一次新对话" />
          ) : (
            messages.map((item, index) => (
              <div className={`message-row ${item.role}`} key={`${item.created_at}-${index}`}>
                <div className="message-bubble">
                  <Text className="role-label">{roleLabel(item.role)}</Text>
                  <p>{item.content}</p>
                </div>
              </div>
            ))
          )}
        </div>
        <div className="composer">
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
          <Button type="primary" icon={<SendOutlined />} loading={sending} onClick={onSend}>
            发送
          </Button>
        </div>
      </main>
    </section>
  );
}

function SkillsWorkspace({ skills, loading, onRefresh }) {
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

  return (
    <section className="workspace table-workspace">
      <Toolbar title="Skill 列表" count={skills.length} onRefresh={onRefresh} />
      <Table
        rowKey="name"
        columns={columns}
        dataSource={skills}
        loading={loading}
        pagination={{ pageSize: 8 }}
      />
    </section>
  );
}

function ToolsWorkspace({ tools, loading, onRefresh }) {
  const columns = [
    { title: "名称", dataIndex: "name", key: "name", width: 220 },
    { title: "描述", dataIndex: "description", key: "description" },
    { title: "分类", dataIndex: "category", key: "category", width: 140 },
    {
      title: "参数",
      key: "parameters",
      render: (_, item) => Object.keys(item.parameters?.properties || {}).join(", ") || "无",
    },
  ];

  return (
    <section className="workspace table-workspace">
      <Toolbar title="Tool 列表" count={tools.length} onRefresh={onRefresh} />
      <Table
        rowKey="name"
        columns={columns}
        dataSource={tools}
        loading={loading}
        pagination={{ pageSize: 8 }}
      />
    </section>
  );
}

function Toolbar({ title, count, onRefresh }) {
  return (
    <div className="toolbar">
      <Space>
        <Title level={4}>{title}</Title>
        <Tag>{count}</Tag>
      </Space>
      <Button icon={<ReloadOutlined />} onClick={onRefresh}>
        刷新
      </Button>
    </div>
  );
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
