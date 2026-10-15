// 照搬 dsh-context agentTree.ts 的布局与配色（layoutForest / linksOf / lineageOf / barSegments），
// 森林由 /context/fleet 接口的主智能体 + 子智能体构造。
import { partsOf } from './kit.js';

export const AGENT_CARD_H = 116;
const SLOT_MAX = 276;
const SLOT_MIN = 190;
const CARD_GUTTER = 12;
const LEVEL_H = AGENT_CARD_H + 64;
const PAD_Y = 48;

export function familyHue(index) {
  return `hsl(${Math.round(index * 137.508) % 360} 58% 52%)`;
}

export function forestOf(fleet) {
  const agents = fleet?.agents || [];
  const nodes = agents.map((agent, index) => {
    const window = agent.window || 0;
    const tokens = agent.current?.total || 0;
    return {
      id: agent.id,
      parentId: agent.parent || undefined,
      depth: agent.parent ? 1 : 0,
      family: index,
      label: agent.title,
      isCurrent: agent.id === 'main',
      running: agent.status === 'running',
      completed: agent.status === 'done',
      requests: agent.steps,
      durationMs: agent.durationMs ?? null,
      billed: agent.billed,
      cost: agent.cost,
      model: agent.model || undefined,
      agent,
      head: tokens > 0 ? { tokens, pct: window > 0 ? Math.min(100, Math.round(tokens / window * 100)) : null, parts: partsOf(agent.current) } : null,
    };
  });
  const edges = nodes.filter(n => n.parentId).map(n => ({ from: n.parentId, to: n.id }));
  return { nodes, edges, overflow: 0, solo: nodes.length <= 1 };
}

function linksOf(forest, points) {
  const pointOf = new Map(points.map(p => [p.id, p]));
  const nodeOf = new Map(forest.nodes.map(n => [n.id, n]));
  return forest.edges.map((edge) => {
    const from = pointOf.get(edge.from);
    const to = pointOf.get(edge.to);
    if (!from || !to) return null;
    const node = nodeOf.get(edge.to);
    return { to: edge.to, running: Boolean(node?.running), color: familyHue(node?.family ?? 0),
      x1: from.x, y1: from.y + AGENT_CARD_H, x2: to.x, y2: to.y };
  }).filter(Boolean);
}

export function layoutForest(forest, stageWidth = 0) {
  const childrenOf = new Map();
  for (const n of forest.nodes) {
    if (!n.parentId) continue;
    const kids = childrenOf.get(n.parentId) ?? [];
    kids.push(n);
    childrenOf.set(n.parentId, kids);
  }
  const slotOf = new Map();
  let leafSlots = 0;
  const place = (node) => {
    const kids = childrenOf.get(node.id) ?? [];
    if (!kids.length) { const slot = leafSlots++; slotOf.set(node.id, slot); return slot; }
    let first = 0;
    let last = 0;
    kids.forEach((kid, index) => { const slot = place(kid); if (index === 0) first = slot; last = slot; });
    const slot = (first + last) / 2;
    slotOf.set(node.id, slot);
    return slot;
  };
  if (forest.nodes.length) place(forest.nodes[0]);
  const perLevel = stageWidth > 0 ? Math.max(1, Math.floor(stageWidth / SLOT_MIN)) : 0;
  if (perLevel > 0 && leafSlots > perLevel) {
    // 子节点超过一行容量时按行折叠（照搬 dsh 的 band 布局）
    const bandSlot = Math.min(SLOT_MAX, stageWidth / perLevel);
    const width = perLevel * bandSlot;
    const points = [];
    let row = 0;
    const emitBand = (nodes, depth) => {
      const inset = (width - nodes.length * bandSlot) / 2;
      nodes.forEach((node, i) => points.push({ id: node.id, x: inset + (i + 0.5) * bandSlot, y: PAD_Y + row * LEVEL_H, depth }));
      row++;
      let band = [];
      const flush = () => { if (!band.length) return; const packed = band; band = []; emitBand(packed, depth + 1); };
      for (const node of nodes) {
        const kids = childrenOf.get(node.id) ?? [];
        for (let start = 0; start < kids.length; start += perLevel) {
          const group = kids.slice(start, start + perLevel);
          if (band.length + group.length > perLevel) flush();
          band.push(...group);
          if (band.length === perLevel) flush();
        }
      }
      flush();
    };
    if (forest.nodes.length) emitBand([forest.nodes[0]], 0);
    return { width, height: PAD_Y + (row - 1) * LEVEL_H + AGENT_CARD_H + 24, cardW: bandSlot - CARD_GUTTER, points, links: linksOf(forest, points) };
  }
  const slot = stageWidth > 0 && leafSlots > 1 ? Math.min(SLOT_MAX, stageWidth / leafSlots) : SLOT_MAX;
  const points = forest.nodes.map(node => ({ id: node.id, x: (slotOf.get(node.id) ?? 0) * slot + slot / 2,
    y: PAD_Y + node.depth * LEVEL_H, depth: node.depth }));
  const maxDepth = points.reduce((max, p) => Math.max(max, p.depth), 0);
  return { width: leafSlots * slot, height: PAD_Y + maxDepth * LEVEL_H + AGENT_CARD_H + 24, cardW: slot - CARD_GUTTER,
    points, links: linksOf(forest, points) };
}

export function lineageOf(forest, id) {
  if (id === null) return null;
  const byId = new Map(forest.nodes.map(n => [n.id, n]));
  let cur = byId.get(id);
  if (!cur) return null;
  const lit = new Set();
  while (cur) { lit.add(cur.id); cur = cur.parentId ? byId.get(cur.parentId) : undefined; }
  const queue = [id];
  for (let i = 0; i < queue.length; i++) {
    for (const n of forest.nodes) if (n.parentId === queue[i] && !lit.has(n.id)) { lit.add(n.id); queue.push(n.id); }
  }
  return lit;
}

export function pressureColorOf(pct) {
  if (pct === null) return 'var(--dsw-alias-border-l1)';
  if (pct >= 90) return 'var(--color-red-500)';
  if (pct >= 70) return 'var(--color-amber-500)';
  return 'var(--color-green-500)';
}

export function barSegments(parts, pct, fallbackColor) {
  const occ = pct === null ? 1 : Math.min(100, Math.max(0, pct)) / 100;
  const total = parts.reduce((sum, p) => sum + (p.value > 0 ? p.value : 0), 0);
  const segs = [];
  let acc = 0;
  if (total > 0) {
    for (const p of parts) {
      if (p.value <= 0) continue;
      const share = (p.value / total) * occ;
      if (share <= 0) continue;
      segs.push({ key: p.key, color: p.color, share, free: false });
      acc += share;
    }
  } else if (pct !== null && occ > 0) {
    segs.push({ key: 'fill', color: fallbackColor, share: occ, free: false });
    acc = occ;
  }
  if (pct !== null && acc < 1) segs.push({ key: 'free', color: '', share: 1 - acc, free: true });
  return segs;
}

export function fmtDurationCompact(ms) {
  if (!Number.isFinite(ms) || ms < 0) return '—';
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}m`;
}
