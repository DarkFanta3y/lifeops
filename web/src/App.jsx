import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App as AntApp,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Spin,
  Tooltip,
  Typography,
} from "antd";
import {
  Database as DatabaseIcon,
  LayoutGrid,
  MessageSquare,
  PanelLeftIcon,
  PlusIcon,
  SearchIcon,
  Trash2,
  Wrench,
} from "lucide-react";

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
} from "./api.js";
import {
  canLoadMore,
  isCurrentGeneration,
  mergeUniqueById,
} from "./pagination.js";
import useInfiniteSentinel from "./useInfiniteSentinel.js";

const SkillsWorkspace = lazy(() => import("./workspaces/SkillsWorkspace.jsx"));
const DatabaseWorkspace = lazy(() => import("./workspaces/DatabaseWorkspace.jsx"));
const ToolsWorkspace = lazy(() => import("./workspaces/ToolsWorkspace.jsx"));
const ChatWorkspace = lazy(() => import("./chat/ChatWorkspace.jsx"));
const LoggingModal = lazy(() => import("./modals/LoggingModal.jsx"));
const SkillModal = lazy(() => import("./modals/SkillModal.jsx"));

const { Text } = Typography;
const CONVERSATION_PAGE_SIZE = 30;
const SEARCH_PAGE_SIZE = 20;
const MESSAGE_PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 250;

const NAV_ITEMS = [
  { key: "skills", label: "SKILLS", icon: LayoutGrid },
  { key: "tools", label: "TOOLS", icon: Wrench },
  { key: "database", label: "DATABASE", icon: DatabaseIcon },
];

function LoadingFallback() {
  return <div className="lazy-fallback"><Spin /></div>;
}

// 未引入 Tailwind preflight，原生 button 需要显式重置 UA 样式
const sidebarButtonClass =
  "group flex w-full cursor-pointer items-center gap-2.5 overflow-hidden rounded-lg border-0 bg-transparent px-2.5 py-2 text-left text-sm text-[#0d0d0d] transition-colors hover:bg-black/[0.06]";

function App() {
  const { message } = AntApp.useApp();
  const [activeView, setActiveView] = useState("chat");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [conversationListLoading, setConversationListLoading] = useState(false);
  const [conversationsLoadingMore, setConversationsLoadingMore] = useState(false);
  const [selectedConversationId, setSelectedConversationId] = useState(null);
  const [conversationMessages, setConversationMessages] = useState([]);
  const [intermediateMessages, setIntermediateMessages] = useState([]);
  const [skills, setSkills] = useState([]);
  const [ragSources, setRagSources] = useState([]);
  const [tools, setTools] = useState([]);
  const [mcpServers, setMcpServers] = useState([]);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
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
  }

  async function loadConversation(conversationId) {
    const generation = conversationRequestRef.current + 1;
    conversationRequestRef.current = generation;
    setActiveView("chat");
    setSelectedConversationId(conversationId);
    setConversationMessages([]);
    setIntermediateMessages([]);
    setError("");
    try {
      // 游标翻页取全量历史（首页取最新，再向前拼接；40 页上限防失控）
      const allMessages = [];
      const allIntermediate = [];
      let beforeId = null;
      for (let page = 0; page < 40; page++) {
        const payload = await fetchConversationCursor(
          conversationId, MESSAGE_PAGE_SIZE, beforeId,
        );
        if (!isCurrentGeneration(generation, conversationRequestRef.current)) return;
        if (beforeId === null) {
          allMessages.push(...(payload.messages || []));
          allIntermediate.push(...(payload.intermediate_messages || []));
        } else {
          allMessages.unshift(...(payload.messages || []));
          allIntermediate.unshift(...(payload.intermediate_messages || []));
        }
        if (!payload.has_more || !payload.next_before_id) break;
        beforeId = payload.next_before_id;
      }
      setConversationMessages(allMessages);
      setIntermediateMessages(allIntermediate);
    } catch (err) {
      if (generation === conversationRequestRef.current) setError(err.message);
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

  function renderContent() {
    if (activeView === "chat") {
      return <Suspense fallback={<LoadingFallback />}><ChatWorkspace
        selectedConversation={selectedConversation}
        conversationId={selectedConversationId}
        messages={conversationMessages} setMessages={setConversationMessages}
        intermediateMessages={intermediateMessages} sending={sending}
        setSending={setSending} refreshConversations={refreshConversations}
        onError={setError} /></Suspense>;
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
    <div className="bg-background text-foreground flex h-screen overflow-hidden">
      <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed((c) => !c)}
        activeView={activeView} onView={setActiveView}
        conversations={conversations} conversationTotal={conversationTotal}
        selectedConversationId={selectedConversationId} onSelect={loadConversation}
        onDelete={handleDeleteConversation}
        hasMore={conversations.length < conversationTotal}
        loadingMore={conversationsLoadingMore} onLoadMore={loadMoreConversations}
        listLoading={conversationListLoading}
        onNewChat={handleNewChat}
        onOpenSearch={() => {
          setSearchOpen(true); setSearchQuery(""); setSearchResults([]); setSearchError("");
        }} />
      <main className="flex min-w-0 flex-1 flex-col">
        {error ? <Alert className="content-alert" type="error" message={error} showIcon /> : null}
        <div className="min-h-0 flex-1">{renderContent()}</div>
      </main>
      <SearchModal open={searchOpen} query={searchQuery} results={searchResults}
        loading={searchLoading} loadingMore={searchLoadingMore} error={searchError}
        hasMore={searchResults.length < searchTotal} onLoadMore={loadMoreSearchResults}
        onQueryChange={setSearchQuery} onSearch={restartSearch}
        onSelect={async (id) => { setSearchOpen(false); await loadConversation(id); }}
        onClose={() => setSearchOpen(false)} />
      {skillModalOpen ? <Suspense fallback={<LoadingFallback />}><SkillModal open
        value={skillForm} saving={savingSkill} onChange={setSkillForm} onSave={handleCreateSkill}
        onClose={() => setSkillModalOpen(false)} /></Suspense> : null}
    </div>
  );
}

function Sidebar({
  collapsed, onToggle, activeView, onView, conversations, conversationTotal,
  selectedConversationId, onSelect, onDelete, hasMore, loadingMore, onLoadMore,
  listLoading, onNewChat, onOpenSearch,
}) {
  const listRef = useRef(null);
  const sentinelRef = useInfiniteSentinel({
    rootRef: listRef, disabled: !hasMore || loadingMore, onIntersect: onLoadMore,
  });

  return (
    <aside
      className="border-border/60 bg-[#f9f9f9] flex h-full shrink-0 flex-col overflow-hidden border-r transition-[width] duration-200"
      style={{ width: collapsed ? 56 : 260 }}
    >
      <div className="flex h-12 shrink-0 items-center gap-2 overflow-hidden px-2">
        <Tooltip title={collapsed ? "展开侧栏" : "收起侧栏"}>
          <button type="button" aria-label="切换侧栏" onClick={onToggle}
            className="hover:bg-black/[0.06] flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent text-[#0d0d0d] transition-colors">
            <PanelLeftIcon className="size-4.5" />
          </button>
        </Tooltip>
        {!collapsed ? (
          <img src="/lifeops_logo.svg" alt="LifeOps" className="h-7 w-auto object-contain" />
        ) : null}
      </div>

      <div className="flex shrink-0 flex-col gap-0.5 px-2">
        <button type="button" className={sidebarButtonClass} onClick={onNewChat}
          title={collapsed ? "新聊天" : undefined}>
          <PlusIcon className="size-4 shrink-0" />
          {!collapsed ? <span className="truncate">新聊天</span> : null}
        </button>
        <button type="button" className={sidebarButtonClass} onClick={onOpenSearch}
          title={collapsed ? "搜索标题" : undefined}>
          <SearchIcon className="size-4 shrink-0" />
          {!collapsed ? <span className="truncate">搜索标题</span> : null}
        </button>
        {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
          <button key={key} type="button" title={collapsed ? label : undefined}
            className={`${sidebarButtonClass}${activeView === key ? " bg-black/[0.08] font-medium" : ""}`}
            onClick={() => onView(key)}>
            <Icon className="size-4 shrink-0" />
            {!collapsed ? <span className="truncate">{label}</span> : null}
          </button>
        ))}
      </div>

      {!collapsed ? (
        <div className="mt-4 flex min-h-0 flex-1 flex-col">
          <div className="text-muted-foreground flex items-center gap-2 px-3.5 pb-1 text-xs font-medium">
            <MessageSquare className="size-3.5" aria-hidden />
            <span>对话</span>
            <span className="rounded-full bg-black/[0.06] px-1.5 py-0.5 tabular-nums">
              {conversationTotal}
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" ref={listRef}>
            {listLoading && conversations.length === 0 ? (
              <div className="flex justify-center py-6"><Spin size="small" /></div>
            ) : conversations.length === 0 ? (
              <div className="text-muted-foreground px-2.5 py-6 text-center text-xs">
                暂无对话
              </div>
            ) : conversations.map((item) => (
              <div key={item.conversation_id}
                className={`group relative${item.conversation_id === selectedConversationId ? " bg-black/[0.06]" : ""}`}>
                <button type="button"
                  className={`${sidebarButtonClass} pr-7${item.conversation_id === selectedConversationId ? " font-medium" : ""}`}
                  onClick={() => onSelect(item.conversation_id)}>
                  <span className="truncate">{item.title || "未命名对话"}</span>
                </button>
                <Popconfirm title="删除对话？" description="该对话的历史消息会从本地记录中移除。"
                  okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
                  onConfirm={() => onDelete(item.conversation_id)}>
                  <Tooltip title="删除">
                    <button type="button" aria-label="删除对话"
                      className="text-muted-foreground hover:text-destructive absolute top-1/2 right-1.5 hidden -translate-y-1/2 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent p-1 transition-colors hover:bg-black/[0.06] group-hover:flex">
                      <Trash2 className="size-3.5" />
                    </button>
                  </Tooltip>
                </Popconfirm>
              </div>
            ))}
            <div ref={sentinelRef} className="infinite-sentinel">
              {loadingMore ? <Spin size="small" /> : null}
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1" />
      )}
    </aside>
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

export default App;
