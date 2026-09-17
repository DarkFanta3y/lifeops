// 聊天 UI 冒烟测试：需要本地起后端(8081)与前端 dev(5174)。
// 用法: node scripts/smoke-chat.mjs [消息文本] [期望文本片段]
import { chromium } from "playwright";

const MESSAGE = process.argv[2] || "只回复两个字：你好";
const EXPECT = process.argv[3] || "";
const BASE = process.env.SMOKE_BASE || "http://127.0.0.1:5174/";
const errors = [];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(`[console] ${msg.text()}`);
});
page.on("pageerror", (err) => errors.push(`[pageerror] ${err.message}`));

await page.goto(BASE, { waitUntil: "domcontentloaded" });
await page.waitForSelector("text=新聊天", { timeout: 15000 });
console.log("OK 侧边栏渲染");
await page.waitForSelector("[data-slot=aui_composer-shell]", { timeout: 20000 });
console.log("OK 聊天区渲染（composer 出现）");

// 发送消息，并以“/api/chat 响应流结束”为可靠的完成信号
const chatDone = page.waitForResponse(
  (resp) => resp.url().includes("/api/chat"),
  { timeout: 30000 },
);
await page.locator("[data-slot=aui_composer-shell] textarea").first().fill(MESSAGE);
await page.keyboard.press("Enter");
console.log("已发送消息，等待回复…");
await chatDone;
// 等待生成结束：停止按钮出现后消失（引用带引号的选择器，超时兜底）
await page.waitForSelector('[aria-label="停止生成"]', { timeout: 5000 })
  .catch(() => {});
await page.waitForSelector('[aria-label="停止生成"]', { state: "detached", timeout: 180_000 })
  .catch(() => console.log("WARN 生成尚未结束，继续检查"));
console.log("OK 流结束");
await page.waitForTimeout(1200);

const assistantText = await page
  .locator("[data-slot=aui_assistant-message-root]")
  .last()
  .innerText();
console.log(`助手消息文本片段: ${assistantText.slice(0, 160).replace(/\n/g, " | ")}`);
if (assistantText.trim().length === 0) errors.push("助手消息为空");
if (EXPECT && !assistantText.includes(EXPECT)) {
  errors.push(`助手消息未包含期望文本「${EXPECT}」`);
}

const toolGroupCount = await page.getByText(/调用了 \d+ 个工具/).count();
console.log(toolGroupCount > 0
  ? `OK 工具组内联渲染（${toolGroupCount} 处）`
  : "INFO 本轮无工具调用或未出现工具组标签");

await page.screenshot({ path: "/tmp/smoke-chat.png", fullPage: false });
await browser.close();

if (errors.length > 0) {
  console.log("\n== 问题 ==");
  for (const err of errors) console.log(err);
  process.exit(1);
}
console.log("\n冒烟通过，无页面错误");
