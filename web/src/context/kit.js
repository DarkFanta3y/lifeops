// 照搬 dsh-context 的 format.ts / categories.ts / headline.ts / reserve.ts（去掉类型，按 LifeOps 数据改写锚定与预留）。
import { t } from './i18n.js';

export function fmt(n) {
  if (n === undefined || n === null || Number.isNaN(n)) return '—';
  const sign = n < 0 ? '-' : '';
  const a = Math.abs(n);
  if (a >= 1e9) return sign + (a / 1e9).toFixed(1) + 'B';
  if (a >= 1e6) return sign + (a / 1e6).toFixed(1) + 'M';
  if (a >= 1000) return sign + (a / 1000).toFixed(1) + 'k';
  return sign + String(Math.round(a));
}

export function cacheHitPercent(reads, billed) {
  if (!(billed > 0)) return null;
  const scaled = Math.trunc((reads / billed) * 100 * 100 + 1e-9);
  return `${Math.floor(scaled / 100)}.${String(scaled % 100).padStart(2, '0')}`;
}

const TIME_FMT = new Intl.DateTimeFormat('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

export function fmtTime(ms) {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return '—';
  return TIME_FMT.format(d);
}

export function fmtShare(part, total) {
  if (!Number.isFinite(part) || !Number.isFinite(total) || total <= 0) return '—';
  if (part <= 0) return '0.0%';
  const pct = Math.min(1, part / total) * 100;
  if (pct < 0.1) return '<0.1%';
  return `${pct.toFixed(1)}%`;
}

export function fmtDuration(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (ms < 3_600_000) return `${m}m${s}s`;
  return `${Math.floor(m / 60)}h${m % 60}m`;
}

export function fmtCost(value) {
  if (value === null || value === undefined) return '—';
  if (value === 0) return '¥0';
  if (value < 0.01) return '<¥0.01';
  return `¥${value.toFixed(value < 10 ? 2 : 1)}`;
}

export function fmtAgo(ms, now = Date.now()) {
  if (!ms) return '—';
  const diff = Math.max(0, now - ms);
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return t('ov.time.now');
  if (minutes < 60) return t('ov.time.m', { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('ov.time.h', { n: hours });
  return t('ov.time.d', { n: Math.floor(hours / 24) });
}

export const catLabel = key => t('cat.' + key);

export const CATS = [
  { key: 'system', color: 'var(--color-indigo-500)' },
  { key: 'tools', color: 'var(--color-amber-500)' },
  { key: 'user', color: 'var(--color-green-500)' },
  { key: 'inject', color: 'var(--color-purple-500)' },
  { key: 'skill', color: 'var(--color-orange-500)' },
  { key: 'assistant', color: 'var(--color-blue-500)' },
  { key: 'tool', color: 'var(--color-teal-500)' },
];

export const CAT_COLOR = Object.fromEntries(CATS.map(c => [c.key, c.color]));
export const OUTPUT_COLOR = 'var(--color-pink-500)';
export const CAT_KEYS = CATS.map(c => c.key);

export function partsOf(breakdown) {
  return CATS.map(c => ({ key: c.key, color: c.color, value: breakdown?.[c.key] || 0 }));
}

// 启发式提供比例，厂商实际值提供总量：value 为锚定后的宽度，raw 保留估算值。
export function anchoredParts(parts, target) {
  const sourced = parts.map(p => ({ ...p, raw: p.raw ?? p.value }));
  if (target === null || target === undefined || target <= 0) return sourced;
  let total = 0;
  for (const p of sourced) total += p.raw;
  if (total <= 0) return sourced;
  if (total === target) return sourced.map(p => ({ ...p, value: p.raw }));
  const scale = target / total;
  return sourced.map(p => ({ ...p, value: Math.round(p.raw * scale) }));
}

export function billedParts(current, usage) {
  const input = (usage?.uncachedInputTokens || 0) + (usage?.cacheReadTokens || 0) + (usage?.cacheWriteTokens || 0);
  const estimated = partsOf(current);
  const prompt = input > 0 ? anchoredParts(estimated, input) : estimated.map(p => ({ ...p, value: 0 }));
  return [...prompt, { key: 'output', color: OUTPUT_COLOR, value: Math.max(0, usage?.outputTokens || 0) }];
}

// LifeOps 的预留：ContextManager.reserve_ratio 对应的窗口尾部。
export function reserveGeometry(window, ratio) {
  if (!Number.isFinite(window) || window <= 0 || !(ratio > 0)) return undefined;
  const headroom = Math.round(window * Math.min(ratio, 1));
  return { threshold: window - headroom, headroom, output: 0 };
}

export function occupancyPercent(tokens, window) {
  return Math.min(100, Math.round(tokens / window * 1000) / 10);
}

export function headlineOf(data) {
  const current = data.current || {};
  const requests = data.requests || [];
  const last = requests.length ? requests[requests.length - 1] : null;
  const anchor = last && typeof last.prompt === 'number' ? last.prompt + ((current.total || 0) - last.total) : null;
  const tokens = anchor ?? current.total ?? 0;
  const window = data.contextWindow || undefined;
  const pct = window ? occupancyPercent(tokens, window) : null;
  const parts = anchoredParts(partsOf(current), anchor !== null && tokens > 0 ? tokens : null);
  const reserve = reserveGeometry(window, data.reserveRatio);
  return { tokens, window, pct, parts, reserve, anchored: anchor !== null };
}

export function totalOf(record) {
  return CAT_KEYS.reduce((sum, key) => sum + (record?.[key] || 0), 0);
}
