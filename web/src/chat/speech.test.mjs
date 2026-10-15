import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitSpeechChunks, toSpeechText } from './speech.js';

test('Markdown 转朗读文本：去掉标记、代码块与链接地址', () => {
  const markdown = [
    '## 今日计划',
    '',
    '- **整理**待办，参考 [文档](https://example.com/a)',
    '1. 运行 `uv sync`',
    '> 注意休息',
    '![图](/img.png)',
    '```bash',
    'rm -rf build',
    '```',
    '| 项目 | 状态 |',
    '| --- | :-: |',
    '| 周报 | 完成 |',
    '详见 https://example.com/b 。',
  ].join('\n');
  assert.equal(toSpeechText(markdown), [
    '今日计划', '整理待办，参考 文档', '运行 uv sync', '注意休息', '（代码略）', '项目 状态', '周报 完成', '详见 。',
  ].join('\n'));
});

test('未闭合代码块（流式中途）同样略过', () => {
  assert.equal(toSpeechText('先看代码\n```py\nprint(1)'), '先看代码\n（代码略）');
});

test('按句切分并合并为不超过上限的段', () => {
  assert.deepEqual(splitSpeechChunks('第一句。第二句！第三句？', 8), ['第一句。第二句！', '第三句？']);
  const long = '长'.repeat(25);
  const chunks = splitSpeechChunks(long, 10);
  assert.deepEqual(chunks.map(chunk => chunk.length), [10, 10, 5]);
  assert.ok(splitSpeechChunks('a. b. c. '.repeat(50), 20).every(chunk => chunk.length <= 20));
  assert.deepEqual(splitSpeechChunks('   '), []);
});
