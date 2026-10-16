import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRunTracker, createSpeedMeter, estimateTokens, formatTokens, usageStats } from './runMetrics.js';

test('Token 缩写：小数位随量级收敛并去掉多余的 .0', () => {
  assert.equal(formatTokens(0), '0');
  assert.equal(formatTokens(940), '940');
  assert.equal(formatTokens(1274), '1.27K');
  assert.equal(formatTokens(12740), '12.7K');
  assert.equal(formatTokens(127400), '127K');
  assert.equal(formatTokens(2400000), '2.4M');
  assert.equal(formatTokens(127_000_000), '127M');
});

test('Token 估算：空串为 0，按字符数折半向上取整', () => {
  assert.equal(estimateTokens(''), 0);
  assert.equal(estimateTokens(undefined), 0);
  assert.equal(estimateTokens('一二三'), 2);
  assert.equal(estimateTokens('abcde'), 3);
});

test('速率表：滑动窗口内的字符差换算 tok/s，窗口外样本不计', () => {
  let at = 0;
  const meter = createSpeedMeter({ windowMs: 4000, now: () => at });
  assert.equal(meter.rate(), 0);
  meter.add('x'.repeat(100));
  at = 1000;
  meter.add('x'.repeat(100));
  // 1s 内新增 100 字符 ≈ 50 token → 50 tok/s
  assert.equal(meter.rate(), 50);
  at = 5000;
  assert.equal(meter.rate(), 0);
  meter.reset();
  assert.equal(meter.rate(), 0);
});

test('轮次跟踪：首轮不计步前轮次，工具批次与工具后的文本各推进一轮', () => {
  const tracker = createRunTracker({ maxRounds: 50 });
  assert.equal(tracker.progress(), 2);
  tracker.onToken();
  assert.equal(tracker.rounds, 1);
  // 首个工具批：3 个并行调用仍属第 1 轮
  tracker.onToolCall('a'); tracker.onToolCall('a'); tracker.onToolCall('b');
  assert.equal(tracker.rounds, 1);
  assert.equal(tracker.steps, 3);
  tracker.onToolResult(); tracker.onToolResult(); tracker.onToolResult();
  // 工具结果回到模型 → 第 2 轮；文本只推进一次
  tracker.onToken(); tracker.onToken();
  assert.equal(tracker.rounds, 2);
  // 第二个工具批 → 第 3 轮；finish_task 不计入步骤
  tracker.onToolCall('c'); tracker.onToolCall('finish_task');
  assert.equal(tracker.rounds, 3);
  assert.equal(tracker.steps, 4);
  tracker.onToolResult();
  tracker.onToken();
  assert.equal(tracker.rounds, 4);
  assert.equal(tracker.progress(), 8);
  tracker.reset();
  assert.equal(tracker.rounds, 1);
  assert.equal(tracker.steps, 0);
});

test('进度：按最大轮次上限收敛，超限时封顶 100', () => {
  const tracker = createRunTracker({ maxRounds: 4 });
  assert.equal(tracker.progress(), 25);
  // 每批一个调用并回流结果，模拟 5 个轮次
  for (let i = 0; i < 5; i += 1) { tracker.onToolCall(`t${i}`); tracker.onToolResult(); }
  assert.equal(tracker.rounds, 5);
  assert.equal(tracker.progress(), 100);
});

test('usage 统计：缓存命中率取 prompt 占比，缺数字时退回 null', () => {
  assert.deepEqual(usageStats({ prompt_tokens: 100, completion_tokens: 20, cached_tokens: 84, total_tokens: 120 }),
    { tokens: 120, cacheHit: 0.84 });
  assert.equal(usageStats({ prompt_tokens: 100 })?.cacheHit, 0);
  assert.equal(usageStats(null), null);
  assert.equal(usageStats({}), null);
});
