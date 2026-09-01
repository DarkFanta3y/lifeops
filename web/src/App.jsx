import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App as AntApp,
  Button,
  Empty,
  Input,
  Layout,
  Modal,
  Popconfirm,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  AppstoreOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  DownOutlined,
  FileTextOutlined,
  PlusOutlined,
  RightOutlined,
  SafetyOutlined,
  SearchOutlined,
  SendOutlined,
  ToolOutlined,
} from "@ant-design/icons";

import {
  createRagSource,
  createSkill,
  deleteRagSource,
  deleteConversation,
  fetchConversationCursor,
  fetchConversations,
  fetchRagSources,
  fetchSkills,
  fetchTools,
  updateRagSource,
  sendChatMessage,
  approveRequest,
} from "./api.js";
import MarkdownRenderer from "./MarkdownRenderer.jsx";
import {
  canLoadMore,
  isCurrentGeneration,
  mergeUniqueById,
  prependUniqueById,
  restorePrependScrollPosition,
} from "./pagination.js";
import { isNearBottom } from "./scroll.js";
import useInfiniteSentinel from "./useInfiniteSentinel.js";

const SkillsWorkspace = lazy(() => import("./workspaces/SkillsWorkspace.jsx"));
const DatabaseWorkspace = lazy(() => import("./workspaces/DatabaseWorkspace.jsx"));
const ToolsWorkspace = lazy(() => import("./workspaces/ToolsWorkspace.jsx"));
const LoggingModal = lazy(() => import("./modals/LoggingModal.jsx"));
const SkillModal = lazy(() => import("./modals/SkillModal.jsx"));

const { Sider, Content } = Layout;
const { Text, Title } = Typography;
const CONVERSATION_PAGE_SIZE = 30;
const SEARCH_PAGE_SIZE = 20;
const MESSAGE_PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 250;

function LoadingFallback() {
  return <div className="lazy-fallback"><Spin /></div>;
}

function App() {
  const { message } = AntApp.useApp();
  const [activeView, setActiveView] = useState("chat");
  const [conversations, setConversations] = useState([]);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [conversationListLoading, setConversationListLoading] = useState(false);
  const [conversationsLoadingMore, setConversationsLoadingMore] = useState(false);
  const [selectedConversationId, setSelectedConversationId] = useState(null);
  const [conversationMessages, setConversationMessages] = useState([]);
  const [intermediateMessages, setIntermediateMessages] = useState([]);
  const [messageHasMore, setMessageHasMore] = useState(false);
  const [messageBeforeId, setMessageBeforeId] = useState(null);
  const [messagesLoadingOlder, setMessagesLoadingOlder] = useState(false);
  const [skills, setSkills] = useState([]);
  const [ragSources, setRagSources] = useState([]);
  const [tools, setTools] = useState([]);
  const [mcpServers, setMcpServers] = useState([]);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingApproval, setPendingApproval] = useState(null);
  const [error, setError] = useState("");
  const [conversationsOpen, setConversationsOpen] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchLoadingMore, setSearchLoadingMore] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [skillModalOpen, setSkillModalOpen] = useState(false);
  const [savingSkill, setSavingSkill] = useState(false);
  const [skillForm, setSkillForm] = useState({
    name: "", description: "", license: "", compatibility: "", allowed_tools: [],
    metadata: "", content: "",
  });
  const conversationListRequestRef = useRef(0);
  const conversationRequestRef = useRef(0);
  const conversationMoreRef = useRef(false);
  const messageOlderRef = useRef(false);
  const searchGenerationRef = useRef(0);
  const searchMoreRef = useRef(false);

  const selectedConversation = useMemo(
    () => conversations.find((item) => item.conversation_id === selectedConversationId),
    [conversations, selectedConversationId],
  );

  useEffect(() => {
    refreshConversations({ autoSelect: false });
  }, []);

  useEffect(() => {
    if (activeView === "skills" && skills.length === 0) loadSkills();
    if (activeView === "database" && ragSources.length === 0) loadRagSources();
    if (activeView === "tools" && tools.length === 0) loadTools();
  }, [activeView, ragSources.length, skills.length, tools.length]);

  useEffect(() => {
    if (!searchOpen) return undefined;
    const generation = searchGenerationRef.current + 1;
    searchGenerationRef.current = generation;
    searchMoreRef.current = false;
    setSearchResults([]);
    setSearchTotal(0);
    setSearchError("");
    if (!searchQuery.trim()) {
      setSearchLoading(false);
      return undefined;
    }
    const timer = setTimeout(
      () => loadSearchPage(searchQuery.trim(), 0, generation),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [searchOpen, searchQuery]);

  async function refreshConversations(options = {}) {
    const generation = conversationListRequestRef.current + 1;
    conversationListRequestRef.current = generation;
    conversationMoreRef.current = false;
    setConversationsLoadingMore(false);
    const hasRequestedId = Object.prototype.hasOwnProperty.call(options, "nextSelectedId");
    const requestedId = hasRequestedId ? options.nextSelectedId : selectedConversationId;
    const autoSelect = options.autoSelect ?? true;
    const loadSelected = options.loadSelected ?? true;
    setConversationListLoading(true);
    setError("");
    try {
      const payload = await fetchConversations("", CONVERSATION_PAGE_SIZE, 0);
      if (!isCurrentGeneration(generation, conversationListRequestRef.current)) return;
      const nextItems = payload.conversations || [];
      setConversations(nextItems);
      setConversationTotal(payload.total ?? nextItems.length);
      const requestedExists = requestedId
        && nextItems.some((item) => item.conversation_id === requestedId);
      const nextId = requestedExists
        ? requestedId
        : autoSelect ? nextItems[0]?.conversation_id || null : null;
      setSelectedConversationId(nextId);
      if (loadSelected && nextId) {
        await loadConversation(nextId);
      } else if (loadSelected && !nextId) {
        resetMessages();
      }
    } catch (err) {
      if (isCurrentGeneration(generation, conversationListRequestRef.current)) setError(err.message);
    } finally {
      if (isCurrentGeneration(generation, conversationListRequestRef.current)) {
        setConversationListLoading(false);
      }
    }
  }

  async function loadMoreConversations() {
    if (!canLoadMore(conversations.length < conversationTotal, conversationMoreRef.current)) return;
    conversationMoreRef.current = true;
    setConversationsLoadingMore(true);
    const generation = conversationListRequestRef.current;
    const offset = conversations.length;
    try {
      const payload = await fetchConversations("", CONVERSATION_PAGE_SIZE, offset);
      if (!isCurrentGeneration(generation, conversationListRequestRef.current)) return;
      setConversations((current) => mergeUniqueById(
        current, payload.conversations || [], "conversation_id",
      ));
      setConversationTotal(payload.total ?? conversationTotal);
    } catch (err) {
      if (generation === conversationListRequestRef.current) setError(err.message);
    } finally {
      if (generation === conversationListRequestRef.current) {
        conversationMoreRef.current = false;
        setConversationsLoadingMore(false);
      }
    }
  }

  function resetMessages() {
    conversationRequestRef.current += 1;
    setConversationMessages([]);
    setIntermediateMessages([]);
    setMessageHasMore(false);
    setMessageBeforeId(null);
    setMessagesLoadingOlder(false);
    messageOlderRef.current = false;
  }

  async function loadConversation(conversationId) {
    const generation = conversationRequestRef.current + 1;
    conversationRequestRef.current = generation;
    setActiveView("chat");
    setSelectedConversationId(conversationId);
    setConversationMessages([]);
    setIntermediateMessages([]);
    setMessageHasMore(false);
    setMessageBeforeId(null);
    setMessagesLoadingOlder(false);
    messageOlderRef.current = false;
    setError("");
    try {
      const payload = await fetchConversationCursor(conversationId, MESSAGE_PAGE_SIZE);
      if (!isCurrentGeneration(generation, conversationRequestRef.current)) return;
      setConversationMessages(payload.messages || []);
      setIntermediateMessages(payload.intermediate_messages || []);
      setMessageHasMore(Boolean(payload.has_more));
      setMessageBeforeId(payload.next_before_id ?? null);
    } catch (err) {
      if (generation === conversationRequestRef.current) setError(err.message);
    }
  }

  async function loadOlderMessages() {
    if (!selectedConversationId || !messageBeforeId
      || !canLoadMore(messageHasMore, messageOlderRef.current)) {
      return false;
    }
    const generation = conversationRequestRef.current;
    messageOlderRef.current = true;
    setMessagesLoadingOlder(true);
    try {
      const payload = await fetchConversationCursor(
        selectedConversationId, MESSAGE_PAGE_SIZE, messageBeforeId,
      );
      if (!isCurrentGeneration(generation, conversationRequestRef.current)) return false;
      setConversationMessages((current) => prependUniqueById(
        current, payload.messages || [], "message_id",
      ));
      setIntermediateMessages((current) => prependUniqueById(
        current, payload.intermediate_messages || [], "message_id",
      ));
      setMessageHasMore(Boolean(payload.has_more));
      setMessageBeforeId(payload.next_before_id ?? null);
      return true;
    } catch (err) {
      if (generation === conversationRequestRef.current) setError(err.message);
      return false;
    } finally {
      if (generation === conversationRequestRef.current) {
        messageOlderRef.current = false;
        setMessagesLoadingOlder(false);
      }
    }
  }

  async function loadSkills() {
    setWorkspaceLoading(true);
    setError("");
    try {
      const payload = await fetchSkills();
      setSkills(payload.skills || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setWorkspaceLoading(false);
    }
  }

  async function loadTools() {
    setWorkspaceLoading(true);
    setError("");
    try {
      const payload = await fetchTools();
      setTools(payload.tools || []);
      setMcpServers(payload.mcp_servers || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setWorkspaceLoading(false);
    }
  }

  async function loadRagSources() {
    setWorkspaceLoading(true);
    setError("");
    try {
      const payload = await fetchRagSources();
      setRagSources(payload.sources || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setWorkspaceLoading(false);
    }
  }

  async function handleCreateRagSource(source) {
    try {
      await createRagSource(source);
      message.success("数据源已保存，重启 LifeOps 后生效");
      await loadRagSources();
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }

  async function handleEditRagSource(sourceId, fields) {
    try {
      await updateRagSource(sourceId, fields);
      message.success("数据源已保存，重启 LifeOps 后生效");
      await loadRagSources();
    } catch (err) {
      setError(err.message);
      throw err;
    }
  }

  async function handleDeleteRagSource(sourceId) {
    setError("");
    try {
      await deleteRagSource(sourceId);
      message.success("数据源配置已删除，重启 LifeOps 后生效；本地文件未删除");
      await loadRagSources();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleCreateSkill() {
    setSavingSkill(true);
    setError("");
    try {
      await createSkill(skillForm);
      message.success("Skill 已创建");
      setSkillModalOpen(false);
      setSkillForm({
        name: "", description: "", license: "", compatibility: "", allowed_tools: [],
        metadata: "", content: "",
      });
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
    resetMessages();
    setChatInput("");
    setError("");
  }

  async function loadSearchPage(query, offset, generation) {
    const loadingMore = offset > 0;
    if (loadingMore) {
      if (searchMoreRef.current) return;
      searchMoreRef.current = true;
      setSearchLoadingMore(true);
    } else {
      setSearchLoading(true);
    }
    try {
      const payload = await fetchConversations(query, SEARCH_PAGE_SIZE, offset);
      if (!isCurrentGeneration(generation, searchGenerationRef.current)) return;
      const nextItems = payload.conversations || [];
      setSearchResults((current) => loadingMore
        ? mergeUniqueById(current, nextItems, "conversation_id") : nextItems);
      setSearchTotal(payload.total ?? nextItems.length);
    } catch (err) {
      if (generation === searchGenerationRef.current) setSearchError(err.message);
    } finally {
      if (generation === searchGenerationRef.current) {
        if (loadingMore) searchMoreRef.current = false;
        setSearchLoading(false);
        setSearchLoadingMore(false);
      }
    }
  }

  function restartSearch(rawQuery = searchQuery) {
    const query = rawQuery.trim();
    setSearchQuery(rawQuery);
    const generation = searchGenerationRef.current + 1;
    searchGenerationRef.current = generation;
    searchMoreRef.current = false;
    setSearchResults([]);
    setSearchTotal(0);
    setSearchError("");
    if (query) loadSearchPage(query, 0, generation);
  }

  function loadMoreSearchResults() {
    if (!canLoadMore(searchResults.length < searchTotal, searchLoading || searchLoadingMore)) return;
    loadSearchPage(searchQuery.trim(), searchResults.length, searchGenerationRef.current);
  }

  async function handleDeleteConversation(conversationId) {
    setError("");
    try {
      await deleteConversation(conversationId);
      message.success("对话已删除");
      const deletingSelected = conversationId === selectedConversationId;
      if (deletingSelected) {
        setSelectedConversationId(null);
        resetMessages();
      }
      await refreshConversations({
        nextSelectedId: deletingSelected ? null : selectedConversationId,
        autoSelect: false,
        loadSelected: false,
      });
      setSearchResults((current) => current.filter(
        (item) => item.conversation_id !== conversationId,
      ));
      if (searchResults.some((item) => item.conversation_id === conversationId)) {
        setSearchTotal((current) => Math.max(0, current - 1));
      }
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleSend() {
    const content = chatInput.trim();
    if (!content || sending) return;
    setActiveView("chat");
    setSending(true);
    setError("");
    const optimisticUserMessage = {
      message_id: `optimistic-${Date.now()}`,
      role: "user", content, created_at: new Date().toISOString(),
    };
    const streamingAssistantId = `streaming-${Date.now()}`;
    setConversationMessages((current) => [...current, optimisticUserMessage]);
    setChatInput("");
    try {
      let streamedContent = "";
      const payload = await sendChatMessage({
        message: content,
        conversationId: selectedConversationId,
        onApproval: (request) => setPendingApproval(request),
        onToken: (tokenText) => {
          streamedContent += tokenText;
          setConversationMessages((current) => {
            const items = [...current];
            const last = items.at(-1);
            if (last?.role === "assistant" && last.message_id === streamingAssistantId) {
              items[items.length - 1] = { ...last, content: streamedContent };
            } else {
              items.push({ message_id: streamingAssistantId, role: "assistant",
                content: streamedContent, created_at: new Date().toISOString() });
            }
            return items;
          });
        },
      });
      await refreshConversations({
        nextSelectedId: payload.conversation_id,
        autoSelect: false,
        loadSelected: false,
      });
    } catch (err) {
      setError(err.message);
      setConversationMessages((current) => current.filter((item) => item !== optimisticUserMessage));
    } finally {
      setPendingApproval(null);
      setSending(false);
    }
  }

  async function handleApprovalDecision(decision) {
    const request = pendingApproval;
    if (!request) return;
    setPendingApproval(null);
    try {
      await approveRequest(request.request_id, decision);
    } catch (err) {
      setError(`审批提交失败：${err.message}`);
    }
  }

  function renderContent() {
    if (activeView === "chat") {
      return <ChatWorkspace selectedConversation={selectedConversation}
        messages={conversationMessages} intermediateMessages={intermediateMessages}
        selectedConversationId={selectedConversationId} chatInput={chatInput} sending={sending}
        hasMore={messageHasMore} loadingOlder={messagesLoadingOlder}
        pendingApproval={pendingApproval} onApprovalDecision={handleApprovalDecision}
        onLoadOlder={loadOlderMessages} onInputChange={setChatInput} onSend={handleSend} />;
    }
    if (activeView === "skills") {
      return <Suspense fallback={<LoadingFallback />}><SkillsWorkspace skills={skills}
        loading={workspaceLoading} onRefresh={loadSkills} onAdd={() => setSkillModalOpen(true)} />
      </Suspense>;
    }
    if (activeView === "database") {
      return <Suspense fallback={<LoadingFallback />}><DatabaseWorkspace sources={ragSources}
        loading={workspaceLoading} onRefresh={loadRagSources} onAdd={handleCreateRagSource}
        onEdit={handleEditRagSource} onDelete={handleDeleteRagSource} /></Suspense>;
    }
    return <Suspense fallback={<LoadingFallback />}><ToolsWorkspace tools={tools}
      mcpServers={mcpServers} loading={workspaceLoading} onRefresh={loadTools} /></Suspense>;
  }

  return (
    <Layout className="app-shell">
      <Sider className="sidebar" width={264} breakpoint="md" collapsedWidth={72}>
        <div className="brand"><img src="/lifeops_logo.svg" alt="LifeOps" /></div>
        <div className="sidebar-actions">
          <Button type="primary" icon={<PlusOutlined />} block onClick={handleNewChat}>新聊天</Button>
          <Button icon={<SearchOutlined />} block onClick={() => {
            setSearchOpen(true); setSearchQuery(""); setSearchResults([]); setSearchError("");
          }}>搜索标题</Button>
        </div>
        <nav className="sidebar-nav" aria-label="主导航">
          <button type="button" className={`sidebar-nav-item${activeView === "skills" ? " active" : ""}`}
            onClick={() => setActiveView("skills")}><AppstoreOutlined /><span>SKILLS</span></button>
          <button type="button" className={`sidebar-nav-item${activeView === "tools" ? " active" : ""}`}
            onClick={() => setActiveView("tools")}><ToolOutlined /><span>TOOLS</span></button>
          <button type="button" className={`sidebar-nav-item${activeView === "database" ? " active" : ""}`}
            onClick={() => setActiveView("database")}><DatabaseOutlined /><span>DATABASE</span></button>
        </nav>
        <section className="sidebar-conversations">
          <button type="button" className="conversation-group-toggle"
            onClick={() => setConversationsOpen((current) => !current)}>
            {conversationsOpen ? <DownOutlined /> : <RightOutlined />}
            <span>对话</span><Tag>{conversationTotal}</Tag>
          </button>
          {conversationsOpen ? <Spin spinning={conversationListLoading}>
            <ConversationList conversations={conversations} selectedConversationId={selectedConversationId}
              hasMore={conversations.length < conversationTotal} loadingMore={conversationsLoadingMore}
              onLoadMore={loadMoreConversations} onSelect={loadConversation}
              onDelete={handleDeleteConversation} />
          </Spin> : null}
        </section>
      </Sider>
      <Layout className="main-layout"><Content className="content">
        {error ? <Alert className="content-alert" type="error" message={error} showIcon /> : null}
        {renderContent()}
      </Content></Layout>
      <SearchModal open={searchOpen} query={searchQuery} results={searchResults}
        loading={searchLoading} loadingMore={searchLoadingMore} error={searchError}
        hasMore={searchResults.length < searchTotal} onLoadMore={loadMoreSearchResults}
        onQueryChange={setSearchQuery} onSearch={restartSearch}
        onSelect={async (id) => { setSearchOpen(false); await loadConversation(id); }}
        onClose={() => setSearchOpen(false)} />
      {skillModalOpen ? <Suspense fallback={<LoadingFallback />}><SkillModal open
        value={skillForm} saving={savingSkill} onChange={setSkillForm} onSave={handleCreateSkill}
        onClose={() => setSkillModalOpen(false)} /></Suspense> : null}
    </Layout>
  );
}

function ConversationList({ conversations, selectedConversationId, hasMore, loadingMore,
  onLoadMore, onSelect, onDelete }) {
  const listRef = useRef(null);
  const sentinelRef = useInfiniteSentinel({
    rootRef: listRef, disabled: !hasMore || loadingMore, onIntersect: onLoadMore,
  });
  if (conversations.length === 0) {
    return <div className="sidebar-empty"><Empty description="暂无对话"
      image={Empty.PRESENTED_IMAGE_SIMPLE} /></div>;
  }
  return (
    <div className="conversation-list" ref={listRef}>
      {conversations.map((item) => (
        <div key={item.conversation_id}
          className={`conversation-item${item.conversation_id === selectedConversationId ? " active" : ""}`}>
          <button type="button" className="conversation-select"
            onClick={() => onSelect(item.conversation_id)}>
            <Text strong>{item.title || "未命名对话"}</Text>
            <Text type="secondary">{item.last_message}</Text>
          </button>
          <Popconfirm title="删除对话？" description="该对话的历史消息会从本地记录中移除。"
            okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
            onConfirm={() => onDelete(item.conversation_id)}>
            <Tooltip title="删除"><Button danger type="text" size="small"
              icon={<DeleteOutlined />} className="conversation-delete" aria-label="删除对话" /></Tooltip>
          </Popconfirm>
        </div>
      ))}
      <div ref={sentinelRef} className="infinite-sentinel">
        {loadingMore ? <Spin size="small" /> : null}
      </div>
    </div>
  );
}

function SearchModal({ open, query, results, loading, loadingMore, error, hasMore,
  onQueryChange, onSearch, onLoadMore, onSelect, onClose }) {
  const resultsRef = useRef(null);
  const sentinelRef = useInfiniteSentinel({
    rootRef: resultsRef, disabled: !hasMore || loading || loadingMore, onIntersect: onLoadMore,
  });
  return (
    <Modal title="搜索对话标题" open={open} onCancel={onClose} footer={null} destroyOnHidden>
      <Input.Search value={query} onChange={(event) => onQueryChange(event.target.value)}
        onSearch={onSearch} enterButton="搜索" loading={loading} allowClear autoFocus />
      {error ? <Alert className="search-alert" type="error" message={error} showIcon /> : null}
      <div className="search-results" ref={resultsRef}>
        <Spin spinning={loading}>{results.length === 0 ? (
          <Empty description={query.trim() ? "无匹配标题" : "输入标题关键词后搜索"} />
        ) : results.map((item) => (
          <button type="button" key={item.conversation_id} className="search-result-item"
            onClick={() => onSelect(item.conversation_id)}>
            <Text strong>{item.title || "未命名对话"}</Text>
            <Text type="secondary">{item.last_message}</Text>
          </button>
        ))}</Spin>
        <div ref={sentinelRef} className="infinite-sentinel">
          {loadingMore ? <Spin size="small" /> : null}
        </div>
      </div>
    </Modal>
  );
}

function ChatWorkspace({ selectedConversation, messages, intermediateMessages,
  selectedConversationId, chatInput, sending, hasMore, loadingOlder, onLoadOlder,
  pendingApproval, onApprovalDecision, onInputChange, onSend }) {
  const [loggingOpen, setLoggingOpen] = useState(false);
  const messageStreamRef = useRef(null);
  const messagesEndRef = useRef(null);
  const shouldAutoScrollRef = useRef(true);

  useEffect(() => {
    if (shouldAutoScrollRef.current) messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  useEffect(() => {
    shouldAutoScrollRef.current = true;
    messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
  }, [selectedConversationId]);

  async function handleLoadOlder() {
    const stream = messageStreamRef.current;
    if (!stream) return;
    const previousHeight = stream.scrollHeight;
    const previousTop = stream.scrollTop;
    shouldAutoScrollRef.current = false;
    const loaded = await onLoadOlder();
    if (loaded) requestAnimationFrame(() => {
      if (messageStreamRef.current) {
        restorePrependScrollPosition(messageStreamRef.current, previousHeight, previousTop);
      }
    });
  }
  const topSentinelRef = useInfiniteSentinel({
    rootRef: messageStreamRef, disabled: !hasMore || loadingOlder, onIntersect: handleLoadOlder,
  });
  function handleSendFromComposer() {
    shouldAutoScrollRef.current = true;
    onSend();
  }
  return (
    <section className="workspace chat-workspace"><main className="chat-pane">
      <div className="chat-head"><div><Text type="secondary">当前对话</Text>
        <Title level={4}>{selectedConversation?.title || "新对话"}</Title></div>
        <div><Tag color="blue">{selectedConversation?.message_count ?? messages.length} 条消息</Tag>
          <Button type="text" size="small" icon={<FileTextOutlined />} className="logging-btn"
            onClick={() => setLoggingOpen(true)}>Logging</Button></div></div>
      <div ref={messageStreamRef}
        className={`message-stream${messages.length === 0 ? " message-stream-empty" : ""}`}
        onScroll={(event) => { shouldAutoScrollRef.current = isNearBottom(event.currentTarget); }}>
        <div ref={topSentinelRef} className="infinite-sentinel top-sentinel">
          {loadingOlder ? <Spin size="small" /> : null}
        </div>
        {messages.length === 0 ? <Empty description="从下方输入开始一次新对话" />
          : messages.map((item, index) => (
            <div className={`message-row ${item.role}`}
              key={item.message_id ?? `${item.created_at}-${index}`}>
              <div className="message-bubble"><Text className="role-label">{roleLabel(item.role)}</Text>
                <MarkdownRenderer content={item.content} emptyText="" /></div>
            </div>
          ))}
        <div ref={messagesEndRef} />
      </div>
      {pendingApproval ? (
        <div className="approval-card" role="alertdialog" aria-label="工具审批请求">
          <div className="approval-head">
            <SafetyOutlined aria-hidden="true" />
            <Text strong>工具调用需要授权：{pendingApproval.tool_name}</Text>
            <Tag color={pendingApproval.risk_level === "high" ? "red" : "orange"}>
              风险：{pendingApproval.risk_level}
            </Tag>
          </div>
          <pre className="approval-params">{pendingApproval.params_preview}</pre>
          <Text type="secondary">{pendingApproval.reason}</Text>
          <div className="approval-actions">
            <Button size="small" onClick={() => onApprovalDecision("deny")}>拒绝</Button>
            <Button size="small" onClick={() => onApprovalDecision("allow_always")}>总是允许</Button>
            <Button size="small" type="primary" danger={false}
              onClick={() => onApprovalDecision("allow_once")}>允许一次</Button>
          </div>
        </div>
      ) : null}
      <div className="composer"><div className="composer-input"><Input.TextArea value={chatInput}
          onChange={(event) => onInputChange(event.target.value)}
          onPressEnter={(event) => { if (!event.shiftKey) {
            event.preventDefault(); handleSendFromComposer();
          } }} placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          autoSize={{ minRows: 2, maxRows: 6 }} />
          <Tooltip title="发送"><Button className="composer-send" type="primary" shape="circle"
            icon={<SendOutlined />} aria-label="发送消息" loading={sending}
            disabled={!chatInput.trim() || sending} onClick={handleSendFromComposer} /></Tooltip></div>
      </div>
    </main>
    {loggingOpen ? <Suspense fallback={<LoadingFallback />}><LoggingModal open
      intermediateMessages={intermediateMessages} onClose={() => setLoggingOpen(false)} />
    </Suspense> : null}
    </section>
  );
}

function roleLabel(role) {
  if (role === "assistant") return "助手";
  if (role === "tool") return "工具";
  return "用户";
}

export default App;
