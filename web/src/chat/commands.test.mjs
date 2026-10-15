import { test } from 'node:test';
import assert from 'node:assert/strict';
import { COMMANDS, findCommand, matchCommands } from './commands.js';

const names = list => list.map(command => command.name);

test('只输入“/”时列出全部命令', () => {
  assert.deepEqual(names(matchCommands('/')), names(COMMANDS));
});

test('按命令名前缀或中文名过滤', () => {
  assert.deepEqual(names(matchCommands('/re')), ['regenerate', 'rename']);
  assert.deepEqual(names(matchCommands('/CON')), ['context']);
  assert.deepEqual(names(matchCommands('/导出')), ['export']);
});

test('非命令输入不弹出候选', () => {
  assert.deepEqual(matchCommands(''), []);
  assert.deepEqual(matchCommands('帮我 /new'), []);
  assert.deepEqual(matchCommands('/new 对话'), []);
  assert.deepEqual(matchCommands('/Users/cxy'), []);
});

test('整条输入完全匹配时识别为命令', () => {
  assert.equal(findCommand(' /context ').name, 'context');
  assert.equal(findCommand('/Logs').name, 'logs');
  assert.equal(findCommand('/contex'), null);
  assert.equal(findCommand('/context 一下'), null);
});
