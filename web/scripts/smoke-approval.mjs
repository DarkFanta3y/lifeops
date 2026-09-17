// 审批流冒烟：触发高风险工具 → 审批卡片 → 允许一次 → 工具完成。
import { chromium } from "playwright";

const errors = [];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(`[console] ${msg.text()}`);
});
page.on("pageerror", (err) => errors.push(`[pageerror] ${err.message}`));

await page.goto("http://127.0.0.1:5174/", { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-slot=aui_composer-shell]", { timeout: 20000 });

const chatDone = page.waitForResponse((r) => r.url().includes("/api/chat"), { timeout: 30000 });
await page.locator("[data-slot=aui_composer-shell] textarea").first()
  .fill("用 bash 命令在 /tmp 创建文件 lifeops-smoke-approval.txt，内容为 hello");
await page.keyboard.press("Enter");
console.log("已发送，等待审批卡片…");

// 审批卡片出现
await page.waitForSelector("[data-slot=lifeops-approval-card]", { timeout: 180_000 });
console.log("OK 审批卡片出现");
const cardText = await page.locator("[data-slot=lifeops-approval-card]").innerText();
console.log("卡片内容:", cardText.replace(/\n/g, " | ").slice(0, 200));
await page.screenshot({ path: "/tmp/smoke-approval.png" });

// 点击「允许一次」，等待流结束（同一 SSE 连接继续）
await page.locator("[data-slot=lifeops-approval-card]").getByRole("button", { name: "允许一次" }).click();
console.log("已点击允许一次，等待运行完成…");
await chatDone;
// 等待生成结束：停止按钮出现后消失（引用带引号的选择器，超时兜底）
await page.waitForSelector('[aria-label="停止生成"]', { timeout: 5000 })
  .catch(() => {});
await page.waitForSelector('[aria-label="停止生成"]', { state: "detached", timeout: 180_000 })
  .catch(() => console.log("WARN 生成尚未结束，继续检查"));
await page.waitForTimeout(1500);

const assistantText = await page
  .locator("[data-slot=aui_assistant-message-root]")
  .last()
  .innerText();
console.log(`助手消息: ${assistantText.slice(0, 200).replace(/\n/g, " | ")}`);
await page.screenshot({ path: "/tmp/smoke-approval-after.png" });

if (!assistantText.includes("lifeops-smoke-approval")) {
  errors.push("完成后消息未提及目标文件（工具可能未执行）");
}
if (errors.length > 0) {
  console.log("\n== 问题 ==");
  for (const err of errors) console.log(err);
  process.exit(1);
}
console.log("\n审批流冒烟通过，无页面错误");
