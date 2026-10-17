// 运行状态栏的纯逻辑：Token 缩写、生成速率、轮次/步骤/进度跟踪。
// 从 ChatWorkspace 的 SSE 事件中抽取，保持无依赖，便于 node --test 直接测试。

// 中英混合文本的粗略 Token 估算：中文约 1 字 ≈ 0.6~1 token，英文约 4 字符 ≈ 1 token，取 chars/2 作为折中。
function charsToTokens(chars) {
  return Math.ceil(chars / 2);
}

export function estimateTokens(text) {
  return charsToTokens((text || '').length);
}

// 大数值缩写：940 → "940"，127400 → "127.4K"，2400000 → "2.4M"；去掉多余的 .0。
export function formatTokens(value) {
  if (!Number.isFinite(value) || value <= 0) return '0';
  const units = [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']];
  for (const [size, suffix] of units) {
    if (value >= size) {
      const scaled = value / size;
      const digits = scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2;
      return `${parseFloat(scaled.toFixed(digits))}${suffix}`;
    }
  }
  return String(Math.round(value));
}

// 滑动窗口速率表：只统计最近 windowMs 内流入的字符，得到 tok/s。
export function createSpeedMeter({ windowMs = 4000, now = Date.now } = {}) {
  let samples = [];
  let chars = 0;
  return {
    add(text) {
      const at = now();
      chars += (text || '').length;
      samples.push([at, chars]);
      const cutoff = at - windowMs;
      while (samples.length > 1 && samples[0][0] < cutoff) samples.shift();
    },
    rate() {
      const at = now();
      const cutoff = at - windowMs;
      while (samples.length > 1 && samples[0][0] < cutoff) samples.shift();
      if (samples.length < 2) return 0;
      const [startAt, startChars] = samples[0];
      const [endAt, endChars] = samples.at(-1);
      const seconds = (endAt - startAt) / 1000;
      if (seconds <= 0) return 0;
      return Math.ceil(Math.max(0, endChars - startChars) / 2) / seconds;
    },
    reset() { samples = []; chars = 0; },
  };
}

// 轮次/步骤跟踪：轮 = LLM 调用次数（首个工具批之前为第 1 轮，工具结果回到模型后进入下一轮），
// 步 = 工具调用次数（finish_task 是内部收尾协议，不计入）。
export function createRunTracker({ maxRounds = 50 } = {}) {
  let rounds = 1;
  let steps = 0;
  let pending = 0;
  let textAfterTools = false;
  return {
    get rounds() { return rounds; },
    get steps() { return steps; },
    progress() { return Math.min(100, Math.round((rounds / maxRounds) * 100)); },
    onToolCall(name) {
      if ((name || '') === 'finish_task') return;
      if (pending === 0 && steps > 0) { rounds += 1; textAfterTools = false; }
      steps += 1; pending += 1;
    },
    onToolResult() { pending = Math.max(0, pending - 1); },
    onToken() {
      if (steps > 0 && pending === 0 && !textAfterTools) { rounds += 1; textAfterTools = true; }
    },
    reset() { rounds = 1; steps = 0; pending = 0; textAfterTools = false; },
  };
}

// 运行中的用量表：每次 LLM 调用结束都会推送一条真实 usage，累加得到实时总 Token 与缓存命中率；
// 调用尚未结束时用已流入字符数估算补齐，避免状态栏长时间停在 0。
export function createUsageMeter() {
  let prompt = 0;
  let completion = 0;
  let cached = 0;
  let total = 0;
  let pendingChars = 0;
  return {
    addText(text) { pendingChars += (text || '').length; },
    addUsage(usage) {
      if (!usage || typeof usage !== 'object') return;
      const callPrompt = Number(usage.prompt_tokens) || 0;
      const callCompletion = Number(usage.completion_tokens) || 0;
      prompt += callPrompt;
      completion += callCompletion;
      cached += Number(usage.cached_tokens) || 0;
      total += Number(usage.total_tokens) || callPrompt + callCompletion;
      pendingChars = 0;
    },
    snapshot() {
      return {
        tokens: total + charsToTokens(pendingChars),
        cacheHit: prompt > 0 ? Math.min(1, cached / prompt) : null,
      };
    },
    reset() { prompt = 0; completion = 0; cached = 0; total = 0; pendingChars = 0; },
  };
}

// 运行结束时优先采用后端真实 usage，拿不到再退回前端估算。
export function usageStats(usage) {
  if (!usage || typeof usage !== 'object') return null;
  const prompt = Number(usage.prompt_tokens) || 0;
  const total = Number(usage.total_tokens) || 0;
  if (prompt <= 0 && total <= 0) return null;
  const meter = createUsageMeter();
  meter.addUsage(usage);
  return meter.snapshot();
}
