import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Empty,
  Input,
  Layout,
  Menu,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  AppstoreOutlined,
  MessageOutlined,
  ReloadOutlined,
  SendOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import {
  fetchConversation,
  fetchConversations,
  fetchSkills,
  fetchTools,
  sendChatMessage,
} from "./api.js";

const { Header, Sider, Content } = Layout;
const { Text, Title } = Typography;

const NAV_ITEMS = [
  { key: "chat", icon: <MessageOutlined />, label: "对话" },
  { key: "skills", icon: <AppstoreOutlined />, label: "SKILLS" },
  { key: "tools", icon: <ToolOutlined />, label: "TOOLS" },
];

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

  async function loadConversations(nextSelectedId) {
    setLoading(true);
    setError("");
    try {
      const payload = await fetchConversations();
      const nextConversations = payload.conversations || [];
      const nextId =
        nextSelectedId ||
        selectedConversationId ||
        nextConversations[0]?.conversation_id ||
        null;
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

  async function handleSend() {
    const content = chatInput.trim();
    if (!content || sending) {
      return;
    }

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
      await loadConversations(payload.conversation_id);
    } catch (err) {
      setError(err.message);
      setConversationMessages((current) => current.filter((item) => item !== optimisticUserMessage));
    } finally {
      setSending(false);
    }
  }

  function renderContent() {
    if (activeView === "chat") {
      return (
        <ChatWorkspace
          conversations={conversations}
          selectedConversation={selectedConversation}
          selectedConversationId={selectedConversationId}
          messages={conversationMessages}
          chatInput={chatInput}
          loading={loading}
          sending={sending}
          onInputChange={setChatInput}
          onRefresh={() => loadConversations()}
          onSelectConversation={loadConversation}
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
      <Sider className="sidebar" width={220} breakpoint="md" collapsedWidth={72}>
        <div className="brand">
          <img src="/lifeops_logo.svg" alt="LifeOps" />
        </div>
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[activeView]}
          items={NAV_ITEMS}
          onClick={({ key }) => setActiveView(key)}
        />
      </Sider>
      <Layout className="main-layout">
        <Header className="topbar">
          <div>
            <Text className="eyebrow">本地控制台</Text>
            <Title level={3}>{titleForView(activeView)}</Title>
          </div>
          {error ? <Alert type="error" message={error} showIcon /> : null}
        </Header>
        <Content className="content">{renderContent()}</Content>
      </Layout>
    </Layout>
  );
}

function ChatWorkspace({
  conversations,
  selectedConversation,
  selectedConversationId,
  messages,
  chatInput,
  loading,
  sending,
  onInputChange,
  onRefresh,
  onSelectConversation,
  onSend,
}) {
  return (
    <section className="workspace chat-grid">
      <aside className="history-pane">
        <div className="pane-head">
          <Text strong>对话历史</Text>
          <Button icon={<ReloadOutlined />} onClick={onRefresh} aria-label="刷新对话历史" />
        </div>
        <Spin spinning={loading}>
          <div className="conversation-list">
            {conversations.length === 0 ? (
              <div className="empty-wrap">
                <Empty description="暂无对话" />
              </div>
            ) : (
              conversations.map((item) => (
                <button
                  type="button"
                  key={item.conversation_id}
                  className={
                    item.conversation_id === selectedConversationId
                      ? "conversation-item active"
                      : "conversation-item"
                  }
                  onClick={() => onSelectConversation(item.conversation_id)}
                >
                  <div>
                    <Text strong>{item.title || "未命名对话"}</Text>
                    <Text type="secondary">{item.last_message}</Text>
                  </div>
                  <Tag>{item.source}</Tag>
                </button>
              ))
            )}
          </div>
        </Spin>
      </aside>
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

function titleForView(view) {
  if (view === "skills") {
    return "Skills";
  }
  if (view === "tools") {
    return "Tools";
  }
  return "对话";
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
