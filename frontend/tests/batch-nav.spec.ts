import { test, expect } from "@playwright/test";

test("投资表单折叠保留草稿，批量净值独立查询与部分导入重试", async ({
  page,
}) => {
  const funds = Array.from({ length: 12 }, (_, i) => ({
    id: `fund-${i}`,
    name: `Synthetic fund ${i}`,
    code: String(i).padStart(6, "0"),
    kind: "fund",
    market: "FUND",
    revision: 1,
  }));
  await page.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic-batch" } }),
  );
  await page.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic batch ledger", revision: 1 } }),
  );
  await page.route("**/api/v1/accounts", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/v1/investments", (r) =>
    r.fulfill({
      json: {
        instruments: funds,
        positions: [],
        trades: [],
        valuations: [],
        known_value_fen: "0",
        missing_price_count: 0,
        unknown_cost_count: 0,
        realized_fen: "0",
        unrealized_fen: "0",
        total_profit_fen: "0",
        cash_dividends_fen: "0",
        reinvested_dividends_fen: "0",
      },
    }),
  );
  const queried: string[] = [];
  const imported: string[] = [];
  let failedQuery = false,
    failedImport = false;
  await page.route("**/api/v1/fund-nav/preview", async (route) => {
    const body = route.request().postDataJSON();
    queried.push(body.instrument_id);
    expect(body.enabled).toBe(true);
    if (body.instrument_id === "fund-1" && !failedQuery) {
      failedQuery = true;
      await route.fulfill({
        status: 422,
        json: { error: { code: "NAV_TIMEOUT" } },
      });
      return;
    }
    await route.fulfill({
      json: {
        token: body.instrument_id,
        source: "Synthetic source",
        fetched_at: "2026-01-01",
        rows: [{ price_date: "2026-01-01", price: "1.2345", exists: false }],
      },
    });
  });
  await page.route("**/api/v1/fund-nav/import", async (route) => {
    const token = route.request().postDataJSON().token;
    imported.push(token);
    if (token === "fund-2" && !failedImport) {
      failedImport = true;
      await route.fulfill({
        status: 409,
        json: { error: { code: "NAV_PREVIEW_EXPIRED" } },
      });
      return;
    }
    await route.fulfill({ json: { imported: 1, skipped: 0 } });
  });
  await page.goto("/investments/");
  const toggle = page.getByRole("button", { name: "记一笔投资", exact: true });
  await toggle.click();
  await page
    .getByRole("region", { name: "投资记录表单" })
    .getByLabel("备注", { exact: true })
    .fill("Synthetic draft");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("region", { name: "投资记录表单" })).toHaveCount(
    0,
  );
  await toggle.click();
  await expect(page.getByLabel("备注", { exact: true })).toHaveValue(
    "Synthetic draft",
  );
  await toggle.click();
  await page.getByRole("button", { name: "标的与估值", exact: true }).click();
  const panel = page.getByRole("region", { name: "联网基金净值" });
  expect(queried).toEqual([]);
  await panel.getByRole("switch").click();
  await panel.getByRole("button", { name: "选择前10只基金" }).click();
  await expect(
    panel.getByRole("checkbox", {
      name: "Synthetic fund 11 · 000011",
      exact: true,
    }),
  ).toBeDisabled();
  await panel.getByRole("button", { name: "清空基金选择" }).click();
  for (let i = 0; i < 3; i++)
    await panel
      .getByRole("checkbox", {
        name: `Synthetic fund ${i} · ${String(i).padStart(6, "0")}`,
        exact: true,
      })
      .check();
  await panel.getByRole("button", { name: "获取净值预览" }).click();
  await expect(panel.getByRole("status")).toContainText("查询完成");
  expect(queried).toEqual(["fund-0", "fund-1", "fund-2"]);
  expect(imported).toEqual([]);
  await panel.getByRole("button", { name: "确认导入净值" }).click();
  await expect(panel.getByRole("status")).toContainText("1 只导入失败");
  for (const id of [1, 2]) {
    const item = panel.locator(".preview").filter({
      has: page.getByRole("heading", {
        name: `Synthetic fund ${id} · ${String(id).padStart(6, "0")}`,
        exact: true,
      }),
    });
    await item.getByRole("button", { name: "重查本项" }).click();
    await expect(panel.getByRole("status")).toContainText("查询完成");
  }
  await panel.getByRole("button", { name: "确认导入净值" }).click();
  await expect(panel.getByRole("status")).toContainText("已导入 2 条");
  expect(imported.filter((id) => id === "fund-0")).toHaveLength(1);
  expect(imported).toEqual(["fund-0", "fund-2", "fund-1", "fund-2"]);
  await panel.getByLabel("净值结束日期").fill("2026-01-02");
  await expect(panel.locator(".preview")).toHaveCount(0);
});
