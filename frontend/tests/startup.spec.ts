import { test, expect } from "@playwright/test";

test("静态加载动画覆盖会话等待，减少动画设置和连接成功生效", async ({
  page,
}) => {
  let ready!: () => void;
  const gate = new Promise<void>((resolve) => {
    ready = resolve;
  });
  await page.route("**/api/v1/session", async (route) => {
    await gate;
    await route.fulfill({ json: { csrf_token: "synthetic-startup" } });
  });
  await page.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic startup ledger", revision: 1 } }),
  );
  const html = await (await page.request.get("/")).text();
  expect(html).toContain('class="startup-spinner"');
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "正在打开你的账本" }),
  ).toBeVisible();
  expect(
    await page
      .locator(".startup-spinner")
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe("none");
  await page.screenshot({ path: "test-results/startup-loading.png" });
  ready();
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  await expect(page.locator(".startup-screen")).toHaveCount(0);
});

test("连接失败显示明确错误并可重新加载", async ({ page }) => {
  let attempts = 0;
  await page.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic-startup" } }),
  );
  await page.route("**/api/v1/ledger", (r) =>
    ++attempts === 1
      ? r.fulfill({ status: 401, json: { error: { code: "UNAUTHENTICATED" } } })
      : r.fulfill({ json: { name: "Synthetic startup ledger", revision: 1 } }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "暂时无法连接账本" }),
  ).toBeVisible();
  await expect(
    page.locator(".startup-screen").getByRole("alert"),
  ).toContainText("会话未连接");
  await page.getByRole("button", { name: "重新加载", exact: true }).click();
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
});
