import { memo } from "react";
import {
  ActionBarMorePrimitive,
  ActionBarPrimitive,
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowUpIcon,
  CheckIcon,
  ChevronDownIcon,
  CopyIcon,
  Download,
  MoreHorizontal,
} from "lucide-react";

import { MarkdownText } from "@/components/assistant-ui/elements/markdown-text";
import { TooltipIconButton } from "@/components/assistant-ui/elements/tooltip-icon-button";
import { cn } from "@/lib/utils";
import { LifeOpsToolFallback } from "./ToolRenderers.jsx";

/**
 * ChatGPT 风格对话流（参照 assistant-ui examples/chatgpt）：
 * 白底居中 max-w-3xl、用户消息深色右对齐气泡、助手消息通栏 +
 * 悬浮操作栏、28px 圆角输入框、底部免责声明。
 */
export const ChatGPTThread = memo(function ChatGPTThread() {
  return (
    <ThreadPrimitive.Root className="flex h-full flex-col items-stretch bg-white px-4 text-[#0d0d0d]">
      <AuiIf condition={(s) => s.thread.isEmpty}>
        <EmptyState />
      </AuiIf>
      <AuiIf condition={(s) => !s.thread.isEmpty}>
        <ThreadPrimitive.Viewport className="flex grow flex-col gap-8 overflow-y-auto pt-8">
          <ThreadPrimitive.Messages>
            {({ message }) => {
              if (message.composer.isEditing) return null;
              if (message.role === "user") return <UserMessage />;
              return <AssistantMessage />;
            }}
          </ThreadPrimitive.Messages>

          <ThreadPrimitive.ViewportFooter className="sticky bottom-0 mx-auto mt-auto flex w-full max-w-3xl flex-col gap-2 overflow-visible rounded-t-3xl bg-white pb-3">
            <ThreadScrollToBottom />
            <Composer />
            <p className="text-muted-foreground/70 text-center text-xs">
              AI 可能会犯错，请核查重要信息。
            </p>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </AuiIf>
    </ThreadPrimitive.Root>
  );
});

const EmptyState = () => {
  return (
    <div className="flex grow flex-col items-center justify-center px-4 pb-[14vh]">
      <div className="mx-auto flex w-full max-w-3xl flex-col items-stretch gap-6">
        <h1 className="text-center text-2xl font-normal leading-7">
          有什么可以帮你？
        </h1>
        <p className="text-muted-foreground -mt-3 text-center text-sm">
          输入任务或问题，助手会调用工具、维护计划并给出回答。
        </p>
        <Composer />
      </div>
    </div>
  );
};

const Composer = () => {
  return (
    <ComposerPrimitive.Root data-slot="lifeops-composer" className="focus-within:border-[#d0d0d0] flex w-full flex-col rounded-[28px] border border-[#e5e5e5] bg-white px-2 py-2 transition-colors">
      <div className="flex items-end gap-1">
        <ComposerPrimitive.Input
          autoFocus
          placeholder="给 LifeOps 发送消息"
          rows={1}
          className="placeholder:text-[#8e8e8e] max-h-52 min-h-9 flex-1 resize-none bg-transparent py-1.5 pr-2 pl-3 text-base outline-none"
        />
        <div className="flex shrink-0 items-center gap-1">
          <ComposerPrimaryAction />
        </div>
      </div>
    </ComposerPrimitive.Root>
  );
};

const ComposerPrimaryAction = () => {
  return (
    <div className="flex items-center gap-1">
      <AuiIf condition={(s) => s.thread.isRunning}>
        <ComposerPrimitive.Cancel
          className="flex size-9 items-center justify-center rounded-full bg-[#0d0d0d] text-white transition-opacity"
          aria-label="停止生成"
        >
          <div className="size-2.5 rounded-[2px] bg-current" />
        </ComposerPrimitive.Cancel>
      </AuiIf>
      <AuiIf
        condition={(s) => !s.thread.isRunning && !s.composer.isEmpty}
      >
        <ComposerPrimitive.Send
          className="flex size-9 items-center justify-center rounded-full bg-[#0d0d0d] text-white transition-opacity disabled:opacity-30"
          aria-label="发送消息"
        >
          <ArrowUpIcon className="size-5" />
        </ComposerPrimitive.Send>
      </AuiIf>
    </div>
  );
};

const ThreadScrollToBottom = () => {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <TooltipIconButton
        tooltip="滚动到底部"
        className="bg-background absolute -top-10 z-10 self-center rounded-full border p-2 disabled:invisible"
      >
        <ChevronDownIcon className="size-5" />
      </TooltipIconButton>
    </ThreadPrimitive.ScrollToBottom>
  );
};

const UserMessage = () => {
  return (
    <MessagePrimitive.Root data-slot="lifeops-user-message" className="relative mx-auto flex w-full max-w-3xl flex-col items-end gap-1">
      <div className="max-w-[70%] rounded-[22px] bg-[#0d0d0d] px-4 py-2.5 leading-6 whitespace-pre-wrap text-white">
        <MessagePrimitive.Parts />
      </div>
      <div className="flex items-center gap-0.5">
        <ActionBarPrimitive.Root
          hideWhenRunning
          autohide="always"
          className="flex items-center"
        >
          <ActionBarPrimitive.Copy asChild>
            <TooltipIconButton tooltip="复制" side="top" className={actionClassName}>
              <AuiIf condition={(s) => s.message.isCopied}>
                <CheckIcon className="size-4" />
              </AuiIf>
              <AuiIf condition={(s) => !s.message.isCopied}>
                <CopyIcon className="size-4" />
              </AuiIf>
            </TooltipIconButton>
          </ActionBarPrimitive.Copy>
        </ActionBarPrimitive.Root>
      </div>
    </MessagePrimitive.Root>
  );
};

// 首个 token / 工具事件到达前的“思考中”占位。
const ThinkingIndicator = () => {
  const running = useAuiState((s) => s.message.status?.type === "running");
  const hasContent = useAuiState((s) =>
    s.message.content.some(
      (part) =>
        (part.type === "text" && part.text) ||
        part.type === "tool-call" ||
        part.type === "reasoning",
    ),
  );
  if (!running || hasContent) return null;
  return (
    <span
      role="status"
      aria-label="助手正在思考"
      className="text-muted-foreground inline-flex items-center gap-1 py-2"
    >
      <span className="size-2 animate-bounce rounded-full bg-current motion-reduce:animate-none" />
      <span className="size-2 animate-bounce rounded-full bg-current [animation-delay:150ms] motion-reduce:animate-none" />
      <span className="size-2 animate-bounce rounded-full bg-current [animation-delay:300ms] motion-reduce:animate-none" />
    </span>
  );
};

const actionClassName =
  "flex size-8 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent text-[#5d5d5d] transition-colors hover:bg-black/[0.07] hover:text-[#5d5d5d]";

const AssistantMessage = () => {
  return (
    <MessagePrimitive.Root data-slot="lifeops-assistant-message" className="relative mx-auto flex w-full max-w-3xl flex-col">
      <div className="leading-relaxed">
        <ThinkingIndicator />
        <MessagePrimitive.Parts>
          {({ part }) => {
            if (part.type === "text") return <MarkdownText />;
            if (part.type === "tool-call") {
              return <LifeOpsToolFallback {...part} />;
            }
            return null;
          }}
        </MessagePrimitive.Parts>
      </div>

      <div className="-ml-2 flex items-center pt-1">
        <ActionBarPrimitive.Root hideWhenRunning className="flex items-center">
          <ActionBarPrimitive.Copy asChild>
            <TooltipIconButton tooltip="复制" side="top" className={actionClassName}>
              <AuiIf condition={(s) => s.message.isCopied}>
                <CheckIcon className="size-4" />
              </AuiIf>
              <AuiIf condition={(s) => !s.message.isCopied}>
                <CopyIcon className="size-4" />
              </AuiIf>
            </TooltipIconButton>
          </ActionBarPrimitive.Copy>
          <ActionBarMorePrimitive.Root>
            <ActionBarMorePrimitive.Trigger asChild>
              <button
                type="button"
                aria-label="更多"
                className={cn(actionClassName, "data-[state=open]:bg-black/[0.07]")}
              >
                <MoreHorizontal className="size-4" />
              </button>
            </ActionBarMorePrimitive.Trigger>
            <ActionBarMorePrimitive.Content
              side="bottom"
              align="end"
              sideOffset={6}
              className="bg-popover text-popover-foreground data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=closed]:animate-out data-[side=bottom]:slide-in-from-top-2 z-50 min-w-40 overflow-hidden rounded-xl border p-1.5"
            >
              <ActionBarPrimitive.ExportMarkdown asChild>
                <ActionBarMorePrimitive.Item className="text-muted-foreground focus:bg-accent focus:text-accent-foreground flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 text-sm outline-none select-none">
                  <Download className="size-4" />
                  导出 Markdown
                </ActionBarMorePrimitive.Item>
              </ActionBarPrimitive.ExportMarkdown>
            </ActionBarMorePrimitive.Content>
          </ActionBarMorePrimitive.Root>
        </ActionBarPrimitive.Root>
      </div>
    </MessagePrimitive.Root>
  );
};
