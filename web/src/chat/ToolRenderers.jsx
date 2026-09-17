import { createContext, useContext, useState } from "react";
import {
  CheckIcon,
  LoaderIcon,
  ShieldAlertIcon,
  SparklesIcon,
} from "lucide-react";

import {
  ToolFallback,
} from "@/components/assistant-ui/elements/tool-fallback.aui";
import { Button } from "@/components/ui/button";

/**
 * 审批上下文：onDecision 由 App 提供（POST /api/approvals/{request_id}），
 * riskLevel / reason 来自最近一次 approval_required 事件（审批严格串行）。
 */
export const ApprovalContext = createContext({
  onDecision: null,
  riskLevel: null,
  reason: null,
});

/**
 * 审批等待中的工具卡片：展示风险与参数，提供后端支持的三种决策。
 * 决策提交成功后，后端 approval_resolved 事件会把 part.approval.approved
 * 置位，状态自动回到 running，此卡片随之被默认工具渲染取代。
 */
function ApprovalCard({ toolName, argsText, approval }) {
  const { onDecision, riskLevel, reason } = useContext(ApprovalContext);
  const [submitting, setSubmitting] = useState(false);
  const risk = riskLevel || "unknown";
  const riskClass = risk === "high"
    ? "border-destructive/60 text-destructive"
    : "border-amber-500/60 text-amber-600";

  const decide = (decision) => {
    if (submitting) return;
    setSubmitting(true);
    Promise.resolve(onDecision?.(approval.id, decision))
      .catch(() => {})
      .finally(() => setSubmitting(false));
  };

  return (
    <div
      role="alertdialog"
      aria-label="工具审批请求"
      data-slot="lifeops-approval-card"
      className="my-2 w-full max-w-3xl rounded-2xl border p-4"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <ShieldAlertIcon className="size-4" aria-hidden />
        <span>工具调用需要授权：</span>
        <b>{toolName}</b>
        <span className={`rounded-full border px-2 py-0.5 text-xs ${riskClass}`}>
          风险：{risk}
        </span>
      </div>
      {argsText ? (
        <pre className="bg-muted/60 mt-3 rounded-xl p-3 text-xs whitespace-pre-wrap">
          {argsText}
        </pre>
      ) : null}
      {reason ? <p className="text-muted-foreground mt-2 text-xs">{reason}</p> : null}
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={submitting}
          onClick={() => decide("deny")}>拒绝</Button>
        <Button size="sm" variant="outline" disabled={submitting}
          onClick={() => decide("allow_always")}>总是允许</Button>
        <Button size="sm" disabled={submitting}
          onClick={() => decide("allow_once")}>允许一次</Button>
      </div>
    </div>
  );
}

/** todo_write 工具的计划卡片：常驻展开，展示各步骤状态。 */
function TodoCard({ todos }) {
  return (
    <div data-slot="lifeops-todo-card" aria-label="任务计划"
      className="my-2 w-full max-w-3xl rounded-2xl border px-4 py-3">
      <p className="text-muted-foreground mb-2 flex items-center gap-1.5 text-xs font-medium">
        <SparklesIcon className="size-3.5" aria-hidden /> 任务计划
      </p>
      <ul className="flex flex-col gap-1.5">
        {todos.map((item, index) => (
          <li key={`${index}-${item.content}`} className="flex items-start gap-2 text-sm">
            {item.status === "completed" ? (
              <CheckIcon className="text-muted-foreground mt-0.5 size-3.5 shrink-0" aria-hidden />
            ) : item.status === "in_progress" ? (
              <LoaderIcon className="text-muted-foreground mt-0.5 size-3.5 shrink-0 animate-spin [animation-duration:1.2s] motion-reduce:animate-none" aria-hidden />
            ) : (
              <span aria-hidden
                className="border-muted-foreground/50 mt-0.5 size-3.5 shrink-0 rounded-[4px] border" />
            )}
            <span className={item.status === "completed" ? "text-muted-foreground line-through" : ""}>
              {item.content}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * ChatGPT 风格消息流中的工具渲染（无折叠分组，每个工具一个可折叠卡片）：
 * - 审批等待（requires-action + approval 未决）→ 审批卡片
 * - todo_write 且结果为计划数组 → 计划卡片
 * - 其余 → 官方默认折叠渲染
 */
export function LifeOpsToolFallback(props) {
  const { toolName, argsText, result, status, approval } = props;
  if (status?.type === "requires-action" && approval
    && approval.approved === undefined) {
    return <ApprovalCard toolName={toolName} argsText={argsText} approval={approval} />;
  }
  if (toolName === "todo_write" && Array.isArray(result)) {
    return <TodoCard todos={result} />;
  }
  return <ToolFallback {...props} />;
}
