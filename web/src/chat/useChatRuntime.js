import { useCallback, useRef } from "react";
import { useExternalStoreRuntime } from "@assistant-ui/react";

import { sendChatMessage } from "../api.js";
import { convertMessage } from "./convertMessage.js";

/**
 * ExternalStoreRuntime 桥接：把 LifeOps 的 FastAPI SSE 聊天流接入 assistant-ui。
 *
 * 流式过程中，token 与工具事件按到达顺序写入最后一条助手消息的 parts 数组；
 * assistantPartsRef 同步维护当前流式消息的 parts（React state 更新是批处理
 * 异步的，事件间的关联匹配需要同步真源）。
 *
 * 工具审批复用 part.approval（id = 后端 request_id）。审批等待期间后端已暂停
 * 运行（SSE 静默），此时 isRunning 必须置 false，assistant-ui 的 auto-status
 * 才会把该工具 part 派生为 requires-action，审批卡片才会渲染；决策提交后由
 * approval_resolved 事件恢复 running。
 *
 * @param {object} params
 * @param {Array} params.messages 会话消息（App 的 conversationMessages）
 * @param {boolean} params.isRunning 是否正在流式生成
 * @param {boolean} [params.isDisabled] 禁用输入区（审批等待时防误发）
 * @param {(updater: (current: Array) => Array) => void} params.setMessages
 * @param {(running: boolean) => void} params.setIsRunning
 * @param {object} params.callbacks 每次渲染刷新的回调集合：
 *   conversationId, onDone, onError, onApprovalRequested, onSettled
 */
export function useChatRuntime({
  messages, isRunning, isDisabled, setMessages, setIsRunning, callbacks,
}) {
  const abortRef = useRef(null);
  const toolCallSeqRef = useRef(0);
  const streamPartsRef = useRef(new Map());
  const callbacksRef = useRef(callbacks);
  callbacksRef.current = callbacks;

  const updateAssistant = useCallback((assistantId, updater) => {
    setMessages((current) => {
      const index = current.findIndex((item) => item.message_id === assistantId);
      if (index === -1) return current;
      const next = [...current];
      next[index] = updater(next[index]);
      return next;
    });
  }, [setMessages]);

  const appendToken = useCallback((assistantId, token) => {
    if (!token) return;
    const parts = streamPartsRef.current.get(assistantId);
    if (!parts) return;
    const last = parts.at(-1);
    const nextParts = last?.kind === "text"
      ? [...parts.slice(0, -1), { ...last, text: last.text + token }]
      : [...parts, { kind: "text", text: token }];
    streamPartsRef.current.set(assistantId, nextParts);
    updateAssistant(assistantId, (msg) => ({ ...msg, parts: nextParts }));
  }, [updateAssistant]);

  const addToolCall = useCallback((assistantId, data) => {
    const toolName = data.tool_name || data.name;
    const parts = streamPartsRef.current.get(assistantId);
    if (!toolName || !parts) return;
    toolCallSeqRef.current += 1;
    const args = data.args ?? data.params ?? {};
    const nextParts = [...parts, {
      kind: "tool",
      toolCallId: `tc-${toolCallSeqRef.current}`,
      toolName,
      args,
      argsText: JSON.stringify(args, null, 2),
    }];
    streamPartsRef.current.set(assistantId, nextParts);
    updateAssistant(assistantId, (msg) => ({ ...msg, parts: nextParts }));
  }, [updateAssistant]);

  const fillToolResult = useCallback((assistantId, data) => {
    const parts = streamPartsRef.current.get(assistantId);
    if (!parts) return;
    const nextParts = [...parts];
    for (let i = nextParts.length - 1; i >= 0; i--) {
      const part = nextParts[i];
      if (part.kind === "tool" && part.toolName === data.tool_name
        && part.result === undefined) {
        const todos = data.metadata?.kind === "todo" && Array.isArray(data.metadata.todos)
          ? data.metadata.todos
          : undefined;
        nextParts[i] = {
          ...part,
          result: todos ?? data.output ?? data.result ?? data.error ?? "（无输出）",
          isError: data.success === false || undefined,
        };
        streamPartsRef.current.set(assistantId, nextParts);
        updateAssistant(assistantId, (msg) => ({ ...msg, parts: nextParts }));
        return;
      }
    }
  }, [updateAssistant]);

  const markApprovalRequired = useCallback((assistantId, data) => {
    const parts = streamPartsRef.current.get(assistantId);
    if (!parts) return;
    const nextParts = [...parts];
    for (let i = nextParts.length - 1; i >= 0; i--) {
      const part = nextParts[i];
      if (part.kind === "tool" && part.toolName === data.tool_name
        && part.result === undefined && !part.approval) {
        nextParts[i] = {
          ...part,
          approval: { id: data.request_id, reason: data.reason },
        };
        streamPartsRef.current.set(assistantId, nextParts);
        updateAssistant(assistantId, (msg) => ({ ...msg, parts: nextParts }));
        setIsRunning(false);
        callbacksRef.current.onApprovalRequested?.({
          requestId: data.request_id,
          toolName: data.tool_name,
          riskLevel: data.risk_level,
          reason: data.reason,
        });
        return;
      }
    }
  }, [updateAssistant, setIsRunning]);

  const markApprovalResolved = useCallback((assistantId, data) => {
    const parts = streamPartsRef.current.get(assistantId);
    if (!parts) return;
    let matched = false;
    const nextParts = parts.map((part) => {
      if (part.kind === "tool" && part.approval?.id === data.request_id) {
        matched = true;
        return {
          ...part,
          approval: {
            ...part.approval,
            approved: data.decision !== "deny",
            optionId: data.decision,
          },
        };
      }
      return part;
    });
    if (!matched) return;
    streamPartsRef.current.set(assistantId, nextParts);
    updateAssistant(assistantId, (msg) => ({ ...msg, parts: nextParts }));
    setIsRunning(true);
  }, [updateAssistant, setIsRunning]);

  const onNew = useCallback(async (message) => {
    const first = message.content[0];
    if (first?.type !== "text" || !first.text.trim()) {
      throw new Error("仅支持发送文本消息");
    }
    const text = first.text;
    const current = callbacksRef.current;
    const now = () => new Date().toISOString();
    const userMsg = {
      message_id: `optimistic-${Date.now()}`,
      role: "user", content: text, created_at: now(),
    };
    const assistantId = `streaming-${Date.now()}`;
    const assistantMsg = {
      message_id: assistantId, role: "assistant",
      content: "", parts: [], created_at: now(),
    };
    streamPartsRef.current.set(assistantId, []);
    setMessages((currentMessages) => [...currentMessages, userMsg, assistantMsg]);
    setIsRunning(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const payload = await sendChatMessage({
        message: text,
        conversationId: current.conversationId,
        signal: controller.signal,
        onToken: (token) => appendToken(assistantId, token),
        onToolCall: (data) => addToolCall(assistantId, data),
        onToolResult: (data) => fillToolResult(assistantId, data),
        onApproval: (data) => markApprovalRequired(assistantId, data),
        onApprovalResolved: (data) => markApprovalResolved(assistantId, data),
      });
      current.onDone?.(payload);
    } catch (err) {
      if (err?.name !== "AbortError") {
        current.onError?.(err.message);
        setMessages((all) => {
          const kept = all.filter((item) => item.message_id !== userMsg.message_id);
          const index = kept.findIndex((item) => item.message_id === assistantId);
          if (index !== -1) {
            const streamed = kept[index];
            const hasContent = (streamed.parts || []).some(
              (part) => (part.kind === "text" && part.text) || part.kind === "tool",
            );
            if (!hasContent) kept.splice(index, 1);
          }
          return kept;
        });
      }
    } finally {
      abortRef.current = null;
      streamPartsRef.current.delete(assistantId);
      setIsRunning(false);
      current.onSettled?.();
    }
  }, [setMessages, setIsRunning, appendToken, addToolCall, fillToolResult,
    markApprovalRequired, markApprovalResolved]);

  const onCancel = useCallback(async () => {
    abortRef.current?.abort();
  }, []);

  return useExternalStoreRuntime({
    messages,
    convertMessage,
    isRunning,
    isDisabled,
    onNew,
    onCancel,
  });
}
