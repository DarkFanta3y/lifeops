// 照搬 dsh-context trendChart.tsx 的纯函数与 events.tsx 的事件文案；事件按时间而非 seq 挂到请求上。
import { t } from './i18n.js';
import { CATS, catLabel, fmt, fmtDuration } from './kit.js';

export const TURN_FILLS = [
  'color-mix(in srgb, var(--color-neutral-500) 12%, transparent)',
  'color-mix(in srgb, var(--color-neutral-500) 26%, transparent)',
];

export function aggregateByTurn(requests) {
  const out = [];
  let runSteps = 0;
  let runActiveMs = 0;
  let runHasActiveMs = false;
  for (const req of requests) {
    const last = out.length ? out[out.length - 1] : null;
    if (last && (last.turn ?? 0) === (req.turn ?? 0)) {
      runSteps++;
      if (req.activeMs !== undefined) { runActiveMs += req.activeMs; runHasActiveMs = true; }
      out[out.length - 1] = { ...req, stepCount: runSteps, ...(runHasActiveMs ? { activeMs: runActiveMs } : {}) };
    } else {
      runSteps = 1;
      runActiveMs = req.activeMs ?? 0;
      runHasActiveMs = req.activeMs !== undefined;
      out.push({ ...req, stepCount: 1 });
    }
  }
  return out;
}

export function turnStepsOf(requests) {
  const counts = new Map();
  for (const req of requests) counts.set(req.turn ?? 0, (counts.get(req.turn ?? 0) ?? 0) + 1);
  return turn => counts.get(turn ?? 0) ?? 1;
}

// 压缩/剪枝事件挂到其后第一条请求上（LifeOps 事件以时间定位）。
export function attachMarkers(requests, events) {
  const markers = new Array(requests.length);
  for (const ev of events) {
    if (ev.kind !== 'compaction' && ev.kind !== 'prune') continue;
    const index = requests.findIndex(req => req.time >= ev.time);
    if (index >= 0 && markers[index] === undefined) markers[index] = ev;
  }
  return markers;
}

function focusOf(req, cat) {
  const out = { ...req };
  const v = req[cat] || 0;
  out.total = v;
  for (const c of CATS) out[c.key] = c.key === cat ? v : 0;
  return out;
}

function deltaOf(req, prev) {
  const { prompt: _prompt, output: _output, ...out } = req;
  let churn = 0;
  let net = 0;
  for (const c of CATS) {
    const d = prev ? (req[c.key] || 0) - (prev[c.key] || 0) : 0;
    out[c.key] = d;
    churn += Math.abs(d);
    net += d;
  }
  out.total = churn;
  out.net = net;
  return out;
}

export function preprocessTrend(requests, delta, focusCat) {
  const focus = focusCat && CATS.some(c => c.key === focusCat) ? focusCat : null;
  const base = focus ? requests.map(req => focusOf(req, focus)) : requests;
  return { requests: delta ? base.map((req, i) => deltaOf(req, i > 0 ? base[i - 1] : null)) : base, focus };
}

export function trendMaxima(requests, delta) {
  let maxTotal = 1;
  let maxUp = 0;
  let maxDown = 0;
  if (delta) {
    for (const req of requests) {
      let up = 0;
      let down = 0;
      for (const c of CATS) {
        const d = req[c.key] || 0;
        if (d > 0) up += d; else down -= d;
      }
      maxUp = Math.max(maxUp, up);
      maxDown = Math.max(maxDown, down);
    }
  } else {
    for (const req of requests) maxTotal = Math.max(maxTotal, req.total);
  }
  return { maxTotal, maxUp, maxDown };
}

export function trendTipRows(opts, req) {
  const n = req.stepCount ?? 1;
  const head = opts.granularity === 'turn'
    ? t('tip.turn', { t: req.turn ?? 0, n })
    : t('tip.step', { t: req.turn ?? 0, s: req.step ?? 0, n: opts.stepsOf(req.turn) });
  let metric;
  if (opts.delta) metric = t('tip.delta', { n: (req.net ?? 0) > 0 ? '+' + fmt(req.net ?? 0) : fmt(req.net ?? 0) });
  else metric = opts.focus ? t('tip.cat', { cat: catLabel(opts.focus), n: fmt(req.total) }) : t('tip.total', { n: fmt(req.total) });
  const rows = [head, metric];
  if (opts.durationOn && req.activeMs !== undefined) rows.push(t('tip.duration', { n: fmtDuration(req.activeMs) }));
  return rows;
}

export function eventLabel(ev) {
  if (ev.kind === 'compaction') return t('ev.compaction', { form: t('form.' + (ev.form || 'summarize')) });
  if (ev.kind === 'prune') return t('ev.prune', { detail: ev.detail || t('form.' + (ev.form || 'trim')) });
  if (ev.kind === 'model') return t('ev.model', { a: ev.from || '?', b: ev.to || '?' });
  if (ev.kind === 'mode') return t('ev.mode.' + (ev.name || '?'), { n: ev.count ?? 0 });
  if (ev.sub === 'skill') return t('ev.skill', { name: ev.name || '?' }) + (ev.form ? '，' + t('form.' + ev.form) : '');
  return ev.name || ev.detail || '';
}

export function eventAt(ev) {
  if (typeof ev.turn !== 'number' || typeof ev.step !== 'number') return null;
  if ((ev.kind === 'compaction' || ev.kind === 'prune') && typeof ev.fromTurn === 'number' && typeof ev.fromStep === 'number') {
    if (ev.fromTurn === ev.turn) return t('events.range', { t: ev.turn, a: ev.fromStep, b: ev.step });
    return t('events.rangeTo', { a: ev.fromTurn, as: ev.fromStep, b: ev.turn, bs: ev.step });
  }
  return t('events.at', { t: ev.turn, s: ev.step });
}

const FLAG_FRACS = [0.25, 0.5, 0.75, 1];
const RIBBON_H = 112;

// 照搬 trendOverview.tsx 的 ribbonGeometry：每个类别一条累积带状多边形。
export function ribbonGeometry(requests, delta, durationOn) {
  const n = requests.length;
  const geo = { maxTotal: 1, maxUp: 0, maxDown: 0, upPx: 0, span: 1, maxActiveMs: 0, polys: [], durationRuns: [], durationDots: [] };
  if (n === 0) return geo;
  Object.assign(geo, trendMaxima(requests, delta));
  const span = Math.max(1, geo.maxUp + geo.maxDown);
  const deltaScale = RIBBON_H / span;
  geo.span = span;
  geo.upPx = Math.round(geo.maxUp * deltaScale);
  const u = n > 1 ? n - 1 : 1;
  const xs = n === 1 ? [0, u] : Array.from({ length: n }, (_, i) => i);
  const cumAt = (v, x) => v[n === 1 ? 0 : x];
  const yFor = (cum, scale, baseline, dir) => Math.round((baseline - dir * cum * scale) * 100) / 100;
  const ribbon = (upper, lower, scale, baseline, dir) => {
    let width = 0;
    for (let i = 0; i < n; i++) width = Math.max(width, Math.abs(upper[i] - lower[i]));
    if (width <= 0) return '';
    const pts = [];
    for (const x of xs) pts.push(`${x},${yFor(cumAt(upper, x), scale, baseline, dir)}`);
    for (let k = xs.length - 1; k >= 0; k--) pts.push(`${xs[k]},${yFor(cumAt(lower, xs[k]), scale, baseline, dir)}`);
    return pts.join(' ');
  };
  if (delta) {
    const up = new Array(n).fill(0);
    const down = new Array(n).fill(0);
    for (const c of CATS) {
      const upPrev = up.slice();
      const downPrev = down.slice();
      for (let i = 0; i < n; i++) {
        const d = requests[i][c.key] || 0;
        up[i] += Math.max(0, d);
        down[i] += Math.max(0, -d);
      }
      const upPts = ribbon(up, upPrev, deltaScale, geo.upPx, 1);
      if (upPts) geo.polys.push({ cat: c.key, points: upPts });
      const downPts = ribbon(downPrev, down, deltaScale, geo.upPx, -1);
      if (downPts) geo.polys.push({ cat: c.key, points: downPts });
    }
  } else {
    const scale = RIBBON_H / geo.maxTotal;
    const acc = new Array(n).fill(0);
    for (const c of CATS) {
      const prev = acc.slice();
      for (let i = 0; i < n; i++) acc[i] += requests[i][c.key] || 0;
      const pts = ribbon(acc, prev, scale, RIBBON_H, 1);
      if (pts) geo.polys.push({ cat: c.key, points: pts });
    }
  }
  if (durationOn) {
    geo.maxActiveMs = requests.reduce((max, req) => Math.max(max, req.activeMs ?? 0), 0);
    const scale = RIBBON_H / Math.max(1, geo.maxActiveMs);
    let run = [];
    const flush = () => {
      if (run.length >= 2) geo.durationRuns.push(run.map(p => `${p[0]},${p[1]}`).join(' '));
      else if (run.length === 1) geo.durationDots.push(run[0]);
      run = [];
    };
    requests.forEach((req, i) => {
      if (req.activeMs === undefined) { flush(); return; }
      run.push([i, Math.round((RIBBON_H - req.activeMs * scale) * 100) / 100]);
    });
    flush();
  }
  return geo;
}

export function wideQuartiles(groups) {
  const total = groups.reduce((s, g) => s + g.span, 0);
  const picks = [];
  for (const q of FLAG_FRACS) {
    let acc = 0;
    let pick = groups.length - 1;
    for (let g = 0; g + 1 < groups.length; g++) {
      acc += groups[g].span;
      if (acc > q * total) { pick = g; break; }
    }
    if (!picks.includes(pick)) picks.push(pick);
  }
  return picks;
}

export function flagStepsOf(n, granularity) {
  return granularity === 'step' ? [...new Set(FLAG_FRACS.map(q => Math.round(q * (n - 1))))].filter(idx => idx > 0) : [];
}
