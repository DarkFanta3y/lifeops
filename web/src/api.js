export const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8081";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `请求失败：${response.status}`);
  }
  return payload;
}

export function fetchConversations(query = "", limit = null, offset = null) {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (limit !== null) params.set("limit", limit);
  if (offset !== null) params.set("offset", offset);
  const qs = params.toString();
  return request(`/api/conversations${qs ? `?${qs}` : ""}`);
}

export function fetchConversation(conversationId, limit = null, offset = null) {
  const params = new URLSearchParams();
  if (limit !== null) params.set("limit", limit);
  if (offset !== null) params.set("offset", offset);
  const qs = params.toString();
  return request(`/api/conversations/${conversationId}${qs ? `?${qs}` : ""}`);
}

export function searchMessages(query, limit = 20, offset = 0) {
  const params = new URLSearchParams();
  params.set("q", query);
  params.set("limit", limit);
  params.set("offset", offset);
  return request(`/api/search/messages?${params.toString()}`);
}

export async function sendChatMessage({ message, conversationId, onToken }) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId || undefined }),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  if (!response.body) {
    return response.json();
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = {};

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      const events = parseSSEMessages(part + "\n\n");
      for (const event of events) {
        if (event.type === "token") {
          const tokenData = event.data ?? event.content ?? "";
          onToken?.(tokenData);
        } else if (event.type === "done") {
          result = { ...event };
          if (event.data && typeof event.data === "object" && !Array.isArray(event.data)) {
            result = { ...result, ...event.data };
          }
        }
      }
    }
  }

  return result;
}

export function deleteConversation(conversationId) {
  return request(`/api/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

export function fetchSkills() {
  return request("/api/skills");
}

export function createSkill(skill) {
  return request("/api/skills", {
    method: "POST",
    body: JSON.stringify(skill),
  });
}

export function fetchTools() {
  return request("/api/tools");
}

export function parseSSEMessages(rawText) {
  if (!rawText) return [];

  const results = [];
  const messages = rawText.split("\n\n");

  for (const msg of messages) {
    const lines = msg.split("\n");
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          results.push(JSON.parse(line.slice(6)));
        } catch {
          // 跳过无法解析的 data 行
        }
      }
    }
  }

  return results;
}
