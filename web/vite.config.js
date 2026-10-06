import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import AutoImport from 'unplugin-auto-import/vite';
import Components from 'unplugin-vue-components/vite';
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers';

// 避免库根入口把未使用的组件带进手动分包。保留官方样式解析，JS 走组件入口。
const elementResolvers = ElementPlusResolver().map(resolver => ({
  ...resolver,
  async resolve(name) {
    const result = await resolver.resolve(name);
    if (result?.from !== 'element-plus/es') return result;
    const component = result.name.replace(/^El/, '').replace(/Directive$/, '').replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
    return { ...result, from: `element-plus/es/components/${({ 'form-item': 'form', 'table-column': 'table', 'radio-button': 'radio', 'radio-group': 'radio', 'descriptions-item': 'descriptions', step: 'steps' })[component] || component}/index.mjs` };
  },
}));

export default defineConfig({
  plugins: [vue(),
    AutoImport({ resolvers: elementResolvers, dts: false }),
    Components({ resolvers: elementResolvers, dts: false }),
  ],
  // 预热懒加载页面的组件样式，避免首次切页触发依赖重优化并刷新会话。
  optimizeDeps: { include: [
    ...'base loading config-provider dialog empty input alert icon button message-box message tag form form-item pagination table table-column radio-group radio-button result input-number slider tree upload steps step switch drawer descriptions descriptions-item'.split(' ').map(name => `element-plus/es/components/${name}/style/css`),
    ...'loading config-provider dialog empty input alert icon button message-box message tag form pagination table radio result input-number slider tree upload steps switch drawer descriptions'.split(' ').map(name => `element-plus/es/components/${name}/index.mjs`),
  ] },
  // 1.3.0 根入口有 Markdown/高亮副作用，按模板实际使用的三个组件加载。
  resolve: { alias: { '@element-plus-x': new URL('./node_modules/vue-element-plus-x/dist/es', import.meta.url).pathname } },
  build: {
    manifest: true,
    rollupOptions: { output: {
      manualChunks(id) {
        if (!id.includes('node_modules')) return;
        if (/node_modules\/(vue|@vue)\//.test(id)) return 'vue-vendor';
        if (id.includes('node_modules/@element-plus/icons-vue/')) return 'icons-vendor';
        if (id.includes('node_modules/vue-element-plus-x/')) return 'chat-vendor';
        if (/node_modules\/(markdown-it|dompurify|entities|linkify-it|mdurl|uc.micro|punycode.js)\//.test(id)) return 'markdown-vendor';
        if (id.includes('node_modules/element-plus/')) return 'element-vendor';
      },
    } },
  },
  server: { host: '127.0.0.1', port: 5173 },
});
