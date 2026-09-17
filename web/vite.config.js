import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) {
            return "react-vendor";
          }
          if (/node_modules\/clsx\//.test(id)) {
            return "clsx-vendor";
          }
          if (/node_modules\/(react-markdown|remark-|rehype-|unified|micromark|mdast-|hast-|unist-|vfile|streamdown|shiki)/.test(id)) {
            return "markdown-vendor";
          }
          // 注意：clsx 同时被 antd 依赖，不能放进 chat-vendor，
          // 否则会把整个聊天依赖桶拖成入口的静态 import。
          if (/node_modules\/(@radix-ui|@base-ui|lucide-react|zustand|class-variance-authority|tailwind-merge|tw-shimmer|@assistant-ui)/.test(id)) {
            return "chat-vendor";
          }
          return undefined;
        },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
});
