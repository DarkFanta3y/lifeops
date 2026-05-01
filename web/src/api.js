const API_BASE = import.meta.env.VITE_API_URL || "http://127.0.0.1:8081";

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

export function fetchConversations(query) {
  const params = new URLSearchParams();
  if (query) {
    params.set("query", query);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request(`/api/conversations${suffix}`);
}

export function fetchConversation(conversationId) {
  return request(`/api/conversations/${conversationId}`);
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

export function fetchTools() {
  return request("/api/tools");
}
