// 照搬 dsh-context timingStrip.tsx 的配色与标签；LifeOps 只有模型等待 / 回复 / 工具 / 其他四类。
export const TIMING_COLOR = {
  ttft: 'var(--color-blue-500)',
  text: 'var(--color-pink-500)',
  tools: 'var(--color-teal-500)',
  other: 'var(--color-slate-400)',
};

export const TIMING_LABEL = {
  ttft: 'timing.ttft',
  text: 'timing.text',
  tools: 'timing.tools',
  other: 'timing.other',
};

export function formatTokensPerSecond(tps) {
  const clamped = Math.max(0, tps);
  return clamped >= 10 ? String(Math.round(clamped)) : String(Math.round(clamped * 10) / 10);
}
