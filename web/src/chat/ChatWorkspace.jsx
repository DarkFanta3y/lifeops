import { lazy, Suspense, useMemo, useState } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { Button, Tag, Typography } from "antd";
import { FileTextOutlined } from "@ant-design/icons";
import { Thread } from "@/components/assistant-ui/elements/thread.aui";

import { approveRequest } from "../api.js";
import { useChatRuntime } from "./useChatRuntime.js";
import {
  ApprovalContext,
  LifeOpsToolFallback,
  LifeOpsToolGroup,
} from "./ToolRenderers.jsx";

const LoggingModal = lazy(() => import("../modals/LoggingModal.jsx"));
const { Text, Title } = Typography;

function ChatWelcome() {
  return (
    <div className="mb-6 flex flex-col gap-1 px-2">
      <h1 className="text-2xl font-medium tracking-tight">有什么可以帮你？</h1>
      <p className="text-muted-foreground text-sm">
        输入任务或问题，助手会调用工具、维护计划并给出回答。
      </p>
    </div>
  );
}

function LoggingFallback() {
  return null;
}

export default function ChatWorkspace({
  selectedConversation,
  conversationId,
  messages,
  setMessages,
  intermediateMessages,
  sending,
  setSending,
  refreshConversations,
  onError,
}) {
  const [loggingOpen, setLoggingOpen] = useState(false);
  const [approvalExtra, setApprovalExtra] = useState(null);

  const chatRuntime = useChatRuntime({
    messages,
    isRunning: sending,
    isDisabled: approvalExtra !== null,
    setMessages,
    setIsRunning: setSending,
    callbacks: {
      conversationId,
      onDone: (payload) => refreshConversations({
        nextSelectedId: payload?.conversation_id,
        autoSelect: false,
        loadSelected: false,
      }),
      onError,
      onApprovalRequested: setApprovalExtra,
      onSettled: () => setApprovalExtra(null),
    },
  });

  async function handleApprovalDecision(requestId, decision) {
    try {
      await approveRequest(requestId, decision);
    } catch (err) {
      onError(`审批提交失败：${err.message}`);
      throw err;
    }
  }

  const threadComponents = useMemo(() => ({
    Welcome: ChatWelcome,
    ToolFallback: LifeOpsToolFallback,
    ToolGroup: LifeOpsToolGroup,
  }), []);
  const approvalContextValue = {
    onDecision: handleApprovalDecision,
    riskLevel: approvalExtra?.riskLevel ?? null,
    reason: approvalExtra?.reason ?? null,
  };

  return (
    <AssistantRuntimeProvider runtime={chatRuntime}>
      <ApprovalContext.Provider value={approvalContextValue}>
        <section className="workspace chat-workspace"><main className="chat-pane">
          <div className="chat-head"><div><Text type="secondary">当前对话</Text>
            <Title level={4}>{selectedConversation?.title || "新对话"}</Title></div>
            <div><Tag color="blue">
              {selectedConversation?.message_count ?? messages.length} 条消息</Tag>
              <Button type="text" size="small" icon={<FileTextOutlined />} className="logging-btn"
                onClick={() => setLoggingOpen(true)}>Logging</Button></div></div>
          <div className="thread-shell">
            <Thread components={threadComponents} />
          </div>
        </main>
        {loggingOpen ? <Suspense fallback={<LoggingFallback />}><LoggingModal open
          intermediateMessages={intermediateMessages} onClose={() => setLoggingOpen(false)} />
        </Suspense> : null}
        </section>
      </ApprovalContext.Provider>
    </AssistantRuntimeProvider>
  );
}
