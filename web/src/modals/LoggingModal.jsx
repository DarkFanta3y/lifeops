import { useMemo, useState } from "react";
import { Empty, Modal, Typography } from "antd";

import MarkdownRenderer from "../MarkdownRenderer.jsx";

const { Text } = Typography;

function ToolCallDetails({ toolCalls }) {
  return <div className="tool-call-list">{toolCalls.map((toolCall, index) => (
    <div className="tool-call-item" key={toolCall.id || index}>
      <Text strong>{toolCall.function?.name || "未知工具"}</Text>
      {toolCall.id ? <Text type="secondary">调用ID: {toolCall.id}</Text> : null}
      <pre>{toolCall.function?.arguments || "{}"}</pre>
    </div>
  ))}</div>;
}

function entryType(message) {
  if (message.role === "assistant" && message.tool_calls) return "工具调用";
  if (message.role === "tool") return "工具结果";
  return "中间信息";
}

function entrySummary(message) {
  if (message.role === "assistant" && message.tool_calls?.length) {
    return message.tool_calls.map((call) => call.function?.name || "未知工具").join(", ");
  }
  const content = message.content || "(无内容)";
  return content.slice(0, 60) + (content.length > 60 ? "..." : "");
}

export default function LoggingModal({ open, intermediateMessages, onClose }) {
  const [selectedKey, setSelectedKey] = useState(null);
  const items = useMemo(() => {
    const result = [];
    const processed = new Set();
    intermediateMessages.forEach((message, index) => {
      if (message.role === "assistant" && message.tool_calls?.length > 0) {
        message.tool_calls.forEach((toolCall) => {
          if (!toolCall.id || processed.has(toolCall.id)) return;
          processed.add(toolCall.id);
          result.push({ key: toolCall.id, type: "tool-call",
            toolName: toolCall.function?.name || "未知工具", toolCall,
            toolResults: intermediateMessages.filter(
              (item) => item.role === "tool" && item.tool_call_id === toolCall.id,
            ) });
        });
      } else if (!(message.role === "tool" && message.tool_call_id)) {
        result.push({ key: message.message_id || `${message.created_at}-${index}`, type: "message",
          entryType: entryType(message), entrySummary: entrySummary(message),
          content: message.content || "" });
      }
    });
    return result;
  }, [intermediateMessages]);
  const selectedItem = items.find((item) => item.key === selectedKey) || items[0];
  const modalProps = { title: "回答中间信息", open, onCancel: onClose, footer: null,
    width: "90vw", style: { top: "5vh" }, destroyOnHidden: true };

  if (intermediateMessages.length === 0) {
    return <Modal {...modalProps} styles={{ body: { padding: "16px 24px", height: "80vh",
      overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center" } }}>
      <Empty description="暂无中间信息" image={Empty.PRESENTED_IMAGE_SIMPLE} />
    </Modal>;
  }
  return (
    <Modal {...modalProps} styles={{ body: { padding: 0, height: "80vh", overflow: "hidden" } }}>
      <div className="logging-split-view">
        <div className="logging-list">{items.map((item) => (
          <button type="button" key={item.key}
            className={`logging-list-item ${selectedItem?.key === item.key ? "active" : ""}`}
            onClick={() => setSelectedKey(item.key)}>
            <div className="logging-list-item-content">
              <Text className="role-label">{item.type === "tool-call" ? "工具调用" : item.entryType}</Text>
              <Text strong={item.type === "tool-call"} type={item.type === "tool-call" ? undefined : "secondary"}>
                {item.type === "tool-call" ? item.toolName : item.entrySummary}
              </Text>
            </div>
          </button>
        ))}</div>
        <div className="logging-preview">{selectedItem ? selectedItem.type === "tool-call" ? (
          <div className="logging-entry">
            <div><Text strong>调用参数：</Text><ToolCallDetails toolCalls={[selectedItem.toolCall]} /></div>
            {selectedItem.toolResults?.length > 0 ? <div style={{ marginTop: 16 }}>
              <Text strong>执行结果：</Text>{selectedItem.toolResults.map((result) => (
                <div key={result.message_id || result.created_at} style={{ marginTop: 10 }}>
                  <div className="logging-meta"><Text type="secondary">工具: {result.tool_name}</Text></div>
                  <MarkdownRenderer content={result.content || ""} emptyText="(无内容)" />
                </div>
              ))}
            </div> : null}
          </div>
        ) : <div className="logging-entry"><MarkdownRenderer content={selectedItem.content} emptyText="(无内容)" /></div>
        : null}</div>
      </div>
    </Modal>
  );
}
