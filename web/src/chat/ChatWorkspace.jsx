import { lazy, Suspense, useState } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { Button } from "antd";
import { FileTextOutlined } from "@ant-design/icons";
import { ChatGPTThread } from "./ChatGPTThread";

import { approveRequest } from "../api.js";
import { useChatRuntime } from "./useChatRuntime.js";
import { ApprovalContext } from "./ToolRenderers.jsx";

const LoggingModal = lazy(() => import("../modals/LoggingModal.jsx"));

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

  const approvalContextValue = {
    onDecision: handleApprovalDecision,
    riskLevel: approvalExtra?.riskLevel ?? null,
    reason: approvalExtra?.reason ?? null,
  };

  return (
    <AssistantRuntimeProvider runtime={chatRuntime}>
      <ApprovalContext.Provider value={approvalContextValue}>
        <section className="workspace chat-workspace">
          <div className="flex h-full min-h-0 flex-col bg-white">
            <header className="flex h-12 shrink-0 items-center justify-between px-5">
              <div className="flex min-w-0 items-baseline gap-2.5">
                <h1 className="truncate text-[15px] font-medium">
                  {selectedConversation?.title || "新对话"}
                </h1>
                <span className="text-muted-foreground shrink-0 text-xs">
                  {selectedConversation?.message_count ?? messages.length} 条消息
                </span>
              </div>
              <Button type="text" size="small" icon={<FileTextOutlined />}
                onClick={() => setLoggingOpen(true)}>Logging</Button>
            </header>
            <div className="min-h-0 flex-1">
              <ChatGPTThread />
            </div>
          </div>
        </section>
        {loggingOpen ? <Suspense fallback={<LoggingFallback />}><LoggingModal open
          intermediateMessages={intermediateMessages} onClose={() => setLoggingOpen(false)} />
        </Suspense> : null}
      </ApprovalContext.Provider>
    </AssistantRuntimeProvider>
  );
}
