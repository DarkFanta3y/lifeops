<script setup>
import { computed } from 'vue';
import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
import { API_BASE } from './api.js';

const props = defineProps({ content: { type: String, default: '' } });
const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true });
const defaultImage = markdown.renderer.rules.image;
markdown.renderer.rules.image = (tokens, index, options, env, self) => {
  const source = tokens[index].attrGet('src') || '';
  if (source.startsWith('/api/')) tokens[index].attrSet('src', `${API_BASE}${source}`);
  return defaultImage(tokens, index, options, env, self);
};
const html = computed(() => DOMPurify.sanitize(markdown.render(props.content), {
  FORBID_TAGS: ['style', 'form', 'input'],
}));
</script>

<template><div class="markdown-body" v-html="html" /></template>
