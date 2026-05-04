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

export function sendChatMessage({ message, conversationId }) {
  return request("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      conversation_id: conversationId || undefined,
    }),
  });
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
