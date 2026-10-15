// 照搬 dsh-context treemap.ts：squarify 布局 + 按类别分组的区块；LifeOps 直接用快照元素分组。
import { t } from './i18n.js';

const MAX_BLOCKS = 12;
const TOP_BLOCKS = MAX_BLOCKS - 1;
const MAP_CATS = ['system', 'tools', 'user', 'inject', 'skill', 'assistant', 'tool'];

function pushCat(cats, cat, blocks) {
  if (!blocks.length) return;
  blocks.sort((a, b) => b.tokens - a.tokens);
  let folded = blocks;
  if (blocks.length > MAX_BLOCKS) {
    const rest = blocks.slice(TOP_BLOCKS);
    folded = [...blocks.slice(0, TOP_BLOCKS),
      { key: '~' + cat, label: t('browser.mapOthers', { n: rest.length }), tokens: rest.reduce((s, b) => s + b.tokens, 0), count: rest.length }];
  }
  cats.push({ cat, tokens: folded.reduce((s, b) => s + b.tokens, 0), blocks: folded });
}

export function mapOf(elements) {
  const cats = [];
  for (const cat of MAP_CATS) {
    const blocks = [];
    const groups = new Map();
    for (const e of elements) {
      if (e.cat !== cat || e.tokens <= 0) continue;
      if (cat === 'tool') {
        const name = e.tool || e.name;
        const acc = groups.get(name);
        if (acc) { acc.tokens += e.tokens; acc.count += 1; } else groups.set(name, { key: 'tool:' + name, label: name, tokens: e.tokens, count: 1, elem: e.key });
        continue;
      }
      const label = cat === 'assistant' && e.calls?.length ? e.calls.join(' › ') : e.name;
      blocks.push({ key: e.key, label, tokens: e.tokens, count: 1, elem: e.key });
    }
    for (const g of groups.values()) blocks.push(g.count === 1 ? g : { ...g, elem: undefined, query: g.label });
    pushCat(cats, cat, blocks);
  }
  return cats;
}

export function squarify(items, box) {
  const sized = items.filter(it => it.tokens > 0).sort((a, b) => b.tokens - a.tokens);
  const total = sized.reduce((s, it) => s + it.tokens, 0);
  if (total <= 0 || box.w <= 0 || box.h <= 0) return [];
  const scale = box.w * box.h / total;
  const entries = sized.map(it => ({ it, a: it.tokens * scale }));
  const out = [];
  let rem = { ...box };
  let row = [];
  const worst = (areas, side) => {
    const sum = areas.reduce((s, a) => s + a, 0);
    const thick = sum / side;
    let bad = 0;
    for (const a of areas) {
      const len = a / thick;
      bad = Math.max(bad, len > thick ? len / thick : thick / len);
    }
    return bad;
  };
  const flush = () => {
    const sum = row.reduce((s, r) => s + r.a, 0);
    if (rem.w >= rem.h) {
      const thick = sum / rem.h;
      let y = rem.y;
      for (const r of row) { const len = r.a / thick; out.push({ item: r.it, rect: { x: rem.x, y, w: thick, h: len } }); y += len; }
      rem = { x: rem.x + thick, y: rem.y, w: rem.w - thick, h: rem.h };
    } else {
      const thick = sum / rem.w;
      let x = rem.x;
      for (const r of row) { const len = r.a / thick; out.push({ item: r.it, rect: { x, y: rem.y, w: len, h: thick } }); x += len; }
      rem = { x: rem.x, y: rem.y + thick, w: rem.w, h: rem.h - thick };
    }
    row = [];
  };
  for (const entry of entries) {
    if (row.length) {
      const side = Math.min(rem.w, rem.h);
      if (worst([...row.map(r => r.a), entry.a], side) > worst(row.map(r => r.a), side)) flush();
    }
    row.push(entry);
  }
  flush();
  return out;
}
