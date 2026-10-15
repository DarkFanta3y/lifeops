<script setup>
import { computed } from 'vue';
import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js/lib/core';
import bash from 'highlight.js/lib/languages/bash';
import css from 'highlight.js/lib/languages/css';
import diff from 'highlight.js/lib/languages/diff';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import python from 'highlight.js/lib/languages/python';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';
import { ElMessage } from 'element-plus';
import { API_BASE } from './api.js';

// 只注册常用语言，控制打包体积；别名交给 highlight.js 自带的 aliases。
Object.entries({ bash, css, diff, javascript, json, python, sql, typescript, xml, yaml })
  .forEach(([name, grammar]) => hljs.registerLanguage(name, grammar));

const props = defineProps({ content: { type: String, default: '' } });
const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true });
const defaultImage = markdown.renderer.rules.image;
markdown.renderer.rules.image = (tokens, index, options, env, self) => {
  const source = tokens[index].attrGet('src') || '';
  if (source.startsWith('/api/')) tokens[index].attrSet('src', `${API_BASE}${source}`);
  return defaultImage(tokens, index, options, env, self);
};

// 围栏代码块：顶部语言标签 + 复制按钮，正文按语言高亮（未知语言按纯文本转义）。
markdown.renderer.rules.fence = (tokens, index) => {
  const token = tokens[index];
  const lang = (token.info || '').trim().split(/\s+/)[0].toLowerCase();
  const code = token.content;
  const body = lang && hljs.getLanguage(lang)
    ? hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
    : markdown.utils.escapeHtml(code);
  const label = markdown.utils.escapeHtml(lang || 'text');
  return `<div class="code-block"><div class="code-block-head"><span class="code-lang">${label}</span>`
    + '<button type="button" class="code-copy" aria-label="复制代码">复制</button></div>'
    + `<pre><code class="hljs">${body}</code></pre></div>`;
};

const html = computed(() => DOMPurify.sanitize(markdown.render(props.content), {
  FORBID_TAGS: ['style', 'form', 'input'],
}));

async function onClick(event) {
  const button = event.target.closest?.('.code-copy');
  if (!button) return;
  const code = button.closest('.code-block')?.querySelector('code')?.textContent ?? '';
  try {
    await navigator.clipboard.writeText(code);
    button.textContent = '已复制';
    setTimeout(() => { button.textContent = '复制'; }, 1500);
  } catch {
    ElMessage.error('复制失败，请检查浏览器剪贴板权限');
  }
}
</script>

<template><div class="markdown-body" @click="onClick" v-html="html" /></template>
