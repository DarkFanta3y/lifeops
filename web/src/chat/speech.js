// 助手回答朗读：浏览器内置 Web Speech API，Markdown 先转纯文本再分段排队。
export const speechSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;

export function toSpeechText(markdown = '') {
  return markdown
    .replace(/```[\s\S]*?(```|$)/g, '\n（代码略）\n')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/<[^>]+>/g, '')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/gm, '')
    .replace(/^\s{0,3}(#{1,6}|>+|[-*+]|\d+[.)])\s+/gm, '')
    .replace(/\|/g, ' ')
    .replace(/(\*\*|__|\*|_|~~)(?=\S)([\s\S]*?\S)\1/g, '$2')
    .replace(/[ \t]+/g, ' ')
    .replace(/\s*\n\s*/g, '\n')
    .trim();
}

// Chrome 单条 utterance 过长会在约 15 秒后静默中断，按句切成短段排队播放。
export function splitSpeechChunks(text, max = 200) {
  const chunks = [];
  let current = '';
  for (const sentence of text.match(/[^。！？；.!?;\n]+[。！？；.!?;\n]*/g) || []) {
    for (let i = 0; i < sentence.length; i += max) {
      const piece = sentence.slice(i, i + max);
      if (current && (current + piece).length > max) { chunks.push(current.trim()); current = ''; }
      current += piece;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.filter(Boolean);
}

let token = 0;

export function stopSpeaking() {
  token += 1;
  if (speechSupported) window.speechSynthesis.cancel();
}

export function speak(text, { onEnd } = {}) {
  stopSpeaking();
  const chunks = splitSpeechChunks(text);
  if (!speechSupported || !chunks.length) { onEnd?.(); return; }
  const current = token;
  const chinese = /[一-鿿]/.test(text);
  const voice = chinese ? window.speechSynthesis.getVoices().find(item => item.lang.toLowerCase().startsWith('zh')) : null;
  const finish = () => { if (current === token) onEnd?.(); };
  chunks.forEach((chunk, index) => {
    const utterance = new SpeechSynthesisUtterance(chunk);
    if (chinese) utterance.lang = 'zh-CN';
    if (voice) utterance.voice = voice;
    utterance.onerror = finish;
    if (index === chunks.length - 1) utterance.onend = finish;
    window.speechSynthesis.speak(utterance);
  });
}
