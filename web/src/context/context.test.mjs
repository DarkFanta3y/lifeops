import assert from "node:assert/strict";
import test from "node:test";

import { forestOf, layoutForest, lineageOf } from "./agentTree.js";
import { aggregateOps, displayPathOf, glyphOf } from "./fileActivity.js";
import { anchoredParts, billedParts, fmt, headlineOf, reserveGeometry } from "./kit.js";
import { mapOf, squarify } from "./treemap.js";
import { aggregateByTurn, attachMarkers, preprocessTrend, trendMaxima } from "./trend.js";

const record = (seq, turn, values, extra = {}) => ({
  seq, turn, step: 1, time: seq * 1000,
  system: 0, tools: 0, user: 0, inject: 0, skill: 0, assistant: 0, tool: 0, ...values,
  total: Object.values(values).reduce((a, b) => a + b, 0), ...extra,
});

test("格式化与锚定比例沿用 dsh 规则", () => {
  assert.equal(fmt(1530), "1.5k");
  assert.equal(fmt(null), "—");
  const parts = anchoredParts([{ key: "system", value: 100 }, { key: "user", value: 300 }], 800);
  assert.deepEqual(parts.map(p => [p.value, p.raw]), [[200, 100], [600, 300]]);
});

test("计费拆分把实际输入按构成比例分配，输出单列", () => {
  const parts = billedParts({ system: 50, user: 50 }, { uncachedInputTokens: 150, cacheReadTokens: 50, cacheWriteTokens: 0, outputTokens: 7 });
  assert.equal(parts.find(p => p.key === "system").value, 100);
  assert.equal(parts.at(-1).key, "output");
  assert.equal(parts.at(-1).value, 7);
});

test("头部占用率以最新请求的实际 prompt 为锚，预留按比例画在窗口尾部", () => {
  const data = { current: { system: 100, user: 100, total: 200 }, contextWindow: 1000, reserveRatio: 0.1,
    requests: [record(1, 1, { system: 100, user: 100 }, { prompt: 300 })] };
  const head = headlineOf(data);
  assert.equal(head.tokens, 300);
  assert.equal(head.pct, 30);
  assert.deepEqual(reserveGeometry(1000, 0.1), { threshold: 900, headroom: 100, output: 0 });
  assert.equal(reserveGeometry(0, 0.1), undefined);
});

test("按轮聚合保留末步并累加耗时，增量模式输出带符号变化", () => {
  const requests = [record(1, 1, { user: 10 }, { activeMs: 5 }), record(2, 1, { user: 30 }, { activeMs: 7 }), record(3, 2, { user: 20 })];
  const turns = aggregateByTurn(requests);
  assert.equal(turns.length, 2);
  assert.equal(turns[0].stepCount, 2);
  assert.equal(turns[0].activeMs, 12);
  const { requests: deltas } = preprocessTrend(requests, true, null);
  assert.equal(deltas[1].user, 20);
  assert.equal(deltas[2].net, -10);
  assert.deepEqual(trendMaxima(deltas, true), { maxTotal: 1, maxUp: 20, maxDown: 10 });
});

test("压缩事件挂到其后第一条请求", () => {
  const markers = attachMarkers([record(1, 1, {}), record(5, 1, {})], [{ kind: "compaction", time: 2000 }, { kind: "inject", time: 1500 }]);
  assert.equal(markers[0], undefined);
  assert.equal(markers[1].kind, "compaction");
});

test("文件活动按路径聚合并支持截止时间", () => {
  const ops = [
    { seq: 1, path: "/w/a.py", kind: "read", tool: "file_read", time: 1, err: false, added: 0, removed: 0 },
    { seq: 2, path: "/w/a.py", kind: "write", tool: "file_replace", time: 5, err: false, added: 3, removed: 1 },
    { seq: 3, path: "TODO", kind: "search", tool: "grep", time: 6, err: true, added: 0, removed: 0, pattern: true },
  ];
  const all = aggregateOps(ops);
  assert.equal(all.entries.length, 2);
  assert.equal(all.totals.added, 3);
  assert.equal(aggregateOps(ops, 2).entries.length, 1);
  assert.equal(displayPathOf("/w/src/a.py", "/w"), "src/a.py");
  assert.equal(glyphOf("src/a.py", "text").glyph, "PY");
});

test("矩形树图按工具名合并结果块，布局面积守恒", () => {
  const cats = mapOf([
    { key: "tool:0", cat: "tool", name: "file_read", tool: "file_read", tokens: 30 },
    { key: "tool:1", cat: "tool", name: "file_read", tool: "file_read", tokens: 20 },
    { key: "user:2", cat: "user", name: "你好", tokens: 50 },
  ]);
  const tool = cats.find(c => c.cat === "tool");
  assert.equal(tool.blocks[0].count, 2);
  assert.equal(tool.blocks[0].query, "file_read");
  const laid = squarify(cats, { x: 0, y: 0, w: 100, h: 50 });
  const area = laid.reduce((sum, l) => sum + l.rect.w * l.rect.h, 0);
  assert.ok(Math.abs(area - 5000) < 1e-6);
});

test("编队森林：主智能体为根，子智能体挂在其下", () => {
  const forest = forestOf({ agents: [
    { id: "main", parent: null, title: "主", status: "done", steps: 3, current: { user: 100, total: 100 }, window: 1000 },
    { id: "sub_a", parent: "main", title: "子", status: "running", steps: 1, current: {}, window: 0 },
  ] });
  assert.equal(forest.solo, false);
  assert.equal(forest.nodes[0].head.pct, 10);
  assert.equal(forest.nodes[1].running, true);
  const layout = layoutForest(forest, 0);
  assert.equal(layout.links.length, 1);
  assert.deepEqual([...lineageOf(forest, "sub_a")].sort(), ["main", "sub_a"]);
});
