// Browser regression test with recorded REST responses; no model calls or user files.
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import process from "node:process";
import { chromium } from "playwright";
import { createServer } from "vite";

const encode = (data) => `<!-- office-master:1 -->\n\n# ${data.format.toUpperCase()} document\n\n\`\`\`office\n${JSON.stringify(data, null, 2)}\n\`\`\`\n`;
const decode = (text) => JSON.parse(/```office\n([\s\S]*)\n```/.exec(text)[1]);
const models = {
  book: { version: 1, format: "xlsx", design: "preserve", sheets: [{ id: "Budget", name: "Budget", cells: { A1: { kind: "text", value: "Item" }, B2: { kind: "number", value: 70000 }, C2: { kind: "formula", value: "=B2*2" } } }] },
  deck: { version: 1, format: "pptx", design: "preserve", slides: [{ id: "256", shapes: [{ id: "2", kind: "text", paragraphs: ["Our plan"] }] }] },
};
const saved = Object.fromEntries(Object.entries(models).map(([key, data]) => [key, { data, text: encode(data), mtime: 1, source: `${key}.source` }]));
const errors = [];
const server = await createServer({ server: { port: 0, strictPort: false }, logLevel: "error" });
await server.listen();
const chrome = process.env.BROWSER_EXECUTABLE ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
let browser;
try {
  browser = await chromium.launch({ headless: true, ...(existsSync(chrome) ? { executablePath: chrome } : {}) });
  const page = await browser.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  let releaseSave;
  let holdSave = false;
  let saveStarted = false;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const slug = /documents\/(book|deck)\/office/.exec(url.pathname)?.[1];
    if (slug) return route.fulfill({ json: saved[slug] });
    if (url.pathname.endsWith("/file") && request.method() === "PUT") {
      const body = request.postDataJSON();
      const key = body.path.replace(".md", "");
      saveStarted = true;
      if (holdSave) await new Promise((resolve) => { releaseSave = resolve; });
      saved[key] = { data: decode(body.content), text: body.content, mtime: saved[key].mtime + 1, source: `${key}.source` };
      return route.fulfill({ json: { mtime: saved[key].mtime } });
    }
    if (url.pathname.endsWith("/export")) return route.fulfill({ json: { ok: true, files: ["deliverable/export.xlsx"], problems: [] } });
    return route.fulfill({ json: {} });
  });
  await page.goto(`${server.resolvedUrls.local[0]}tests/office-editor.html`);
  const value = page.getByRole("textbox", { name: "Budget!B2", exact: true });
  await value.fill("-12.5");
  await value.press("Tab");
  await page.getByRole("button", { name: "Save", exact: true }).waitFor();
  holdSave = true;
  await page.getByRole("button", { name: "Save", exact: true }).click();
  while (!saveStarted) await new Promise((resolve) => setTimeout(resolve, 10));
  await value.fill("25.75");
  await value.press("Tab");
  holdSave = false;
  releaseSave();
  await page.getByText("Saved.", { exact: true }).waitFor();
  assert.equal(saved.book.data.sheets[0].cells.B2.value, -12.5);
  assert.equal(await page.getByText("Unsaved", { exact: true }).count(), 1);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("button", { name: "Export .xlsx", exact: true }).waitFor();
  await page.waitForFunction(() => ![...document.querySelectorAll("span")].some((e) => e.textContent === "Unsaved"));
  assert.equal(saved.book.data.sheets[0].cells.B2.value, 25.75);
  assert.equal(saved.book.data.sheets[0].cells.C2.value, "=B2*2");

  // A source draft with valid JSON but an invalid structure remains repairable.
  await page.getByRole("button", { name: "Edit source", exact: true }).click();
  await page.getByRole("textbox", { name: "Office document source" }).fill(encode({ ...models.book, sheets: [] }));
  await page.getByRole("alert").waitFor();
  await page.getByRole("button", { name: "Open deck", exact: true }).click();
  await page.getByRole("textbox", { name: "Text box 1", exact: true }).fill("Revised plan");
  await page.getByRole("button", { name: "Open book", exact: true }).click();
  await page.getByRole("alert").waitFor();
  assert.ok((await page.getByRole("textbox", { name: "Office document source" }).inputValue()).includes('"sheets": []'));
  await page.getByRole("button", { name: "Revert", exact: true }).click();
  await page.getByRole("button", { name: "Open deck", exact: true }).click();
  assert.equal(await page.getByRole("textbox", { name: "Text box 1", exact: true }).inputValue(), "Revised plan");
  await page.getByRole("combobox", { name: "Export design" }).selectOption("new");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.waitForFunction(() => ![...document.querySelectorAll("span")].some((e) => e.textContent === "Unsaved"));
  assert.equal(saved.deck.data.design, "new");
  assert.equal(saved.deck.data.slides[0].shapes[0].paragraphs[0], "Revised plan");
  await page.getByRole("button", { name: "Export .pptx", exact: true }).click();
  await page.getByText("Exported and checked by reopening the native file.", { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log("Office browser regressions passed: numeric editing, concurrent save, formula retention, source validation, document switching, design choice, export.");
} finally {
  await browser?.close();
  await server.close();
}
