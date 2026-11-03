import { test, expect } from "@playwright/test";

test("模块路径直达、刷新、历史导航、新标签和未知路径", async ({
  page,
  context,
}) => {
  await context.route("**/api/v1/session", (route) =>
    route.fulfill({ json: { csrf_token: "synthetic-routing" } }),
  );
  await context.route("**/api/v1/ledger", (route) =>
    route.fulfill({ json: { name: "Synthetic routing ledger", revision: 1 } }),
  );
  const routes = [
    ["/", "总览"],
    ["/accounts/", "账户"],
    ["/journal/", "日常账本"],
    ["/reports/", "报表与预算"],
    ["/investments/", "投资"],
    ["/investment-reports/", "投资报表"],
    ["/data/", "数据管理"],
    ["/plan/", "开发计划"],
  ];
  for (const [path, name] of routes) {
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("button", { name, exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await page.reload();
    await expect(
      page.getByRole("button", { name, exact: true }),
    ).toHaveAttribute("aria-current", "page");
  }
  await page.getByRole("button", { name: "日常账本", exact: true }).click();
  await expect(page).toHaveURL(/\/journal\/$/);
  await page.getByRole("button", { name: "投资", exact: true }).click();
  await expect(page).toHaveURL(/\/investments\/$/);
  await page.goBack();
  await expect(
    page.getByRole("button", { name: "日常账本", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await page.goForward();
  await expect(
    page.getByRole("button", { name: "投资", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  const other = await context.newPage();
  await other.goto("/data/");
  await expect(
    other.getByRole("heading", { name: "数据管理", exact: true }),
  ).toBeVisible();
  const missing = await other.goto("/missing-module/");
  expect(missing?.status()).toBe(404);
  await expect(other.getByRole("navigation", { name: "主导航" })).toHaveCount(
    0,
  );
});
