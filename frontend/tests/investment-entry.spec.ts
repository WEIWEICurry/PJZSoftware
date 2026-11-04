import { test, expect } from "@playwright/test";

test("投资默认值、日期跟随和手动独立、状态及收益排序", async ({ page }) => {
  const account = {
    id: "a",
    name: "支付宝",
    archived: false,
    kind: "securities",
    balance_fen: "100000",
  };
  const instruments = [0, 1].map((i) => ({
    id: `f${i}`,
    name: `Synthetic fund ${i}`,
    market: "FUND",
    kind: "fund",
    code: `00000${i}`,
    revision: 1,
  }));
  const positions = [0, 1].map((i) => ({
    account_id: "a",
    instrument_id: `f${i}`,
    quantity: "10",
    cost_fen: "1000",
    value_fen: i ? "1200" : "900",
    unrealized_fen: i ? "200" : "-100",
    holding_return_bps: i ? "2000" : "-1000",
    total_profit_fen: i ? "400" : "-50",
    total_return_bps: i ? "4000" : "-500",
    share_bps: "5000",
    price: "1",
    price_date: "2026-01-10",
  }));
  const trades = [0, 1, 2].map((i) => ({
    id: `t${i}`,
    account_id: "a",
    instrument_id: "f0",
    effective_date: "2026-01-10",
    nav_date: "2026-01-08",
    nav_date_source: "manual",
    is_recurring: i === 2,
    action: i === 1 ? "sell" : "buy",
    quantity: "1",
    gross_fen: "100",
    costs_fen: "0",
    status: i === 0 ? "void" : "active",
    note: "",
    revision: 1,
    cost_basis_fen: null,
  }));
  await page.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic" } }),
  );
  await page.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic", revision: 1 } }),
  );
  await page.route("**/api/v1/accounts", (r) => r.fulfill({ json: [account] }));
  await page.route("**/api/v1/investments", (r) =>
    r.fulfill({
      json: {
        positions,
        instruments,
        trades,
        valuations: [],
        known_value_fen: "2100",
        missing_price_count: 0,
        unknown_cost_count: 0,
        realized_fen: "0",
        unrealized_fen: "100",
        total_profit_fen: "350",
        holding_return_bps: "500",
        total_return_bps: "1750",
        cash_dividends_fen: "0",
        reinvested_dividends_fen: "0",
      },
    }),
  );
  let saved: Record<string, string> | null = null;
  await page.route("**/api/v1/investments/trades", (r) => {
    saved = r.request().postDataJSON();
    return r.fulfill({ json: { id: "new" } });
  });
  await page.goto("/investments/");
  const table = page.locator(".investment-table");
  for (const name of ["持仓收益率", "累计盈亏", "累计收益率"]) {
    await table.getByRole("button", { name, exact: true }).click();
    await expect(table.locator("tbody tr").first()).toContainText(
      "Synthetic fund 1",
    );
    await table.getByRole("button", { name, exact: true }).click();
    await expect(table.locator("tbody tr").first()).toContainText(
      "Synthetic fund 0",
    );
  }
  await page.screenshot({
    path: "test-results/investment-metrics.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "记一笔投资", exact: true }).click();
  const form = page.locator("#investment-entry-form");
  await expect(form.getByLabel("持仓账户", { exact: true })).toHaveValue("a");
  await expect(form.getByLabel("金额口径", { exact: true })).toHaveValue("net");
  await expect(form.getByLabel("费用合计（元）")).toHaveValue("");
  await form.getByLabel("成交／确认日期", { exact: true }).fill("2026-01-10");
  await expect(form.getByLabel("成交净值所属日", { exact: true })).toHaveValue(
    "2026-01-10",
  );
  await form
    .getByRole("button", { name: "成交／确认日期前一天", exact: true })
    .click();
  await expect(form.getByLabel("成交净值所属日", { exact: true })).toHaveValue(
    "2026-01-09",
  );
  await form
    .getByRole("button", { name: "成交净值所属日前一天", exact: true })
    .click();
  await form
    .getByRole("button", { name: "成交／确认日期后一天", exact: true })
    .click();
  await expect(form.getByLabel("成交净值所属日", { exact: true })).toHaveValue(
    "2026-01-08",
  );
  await form.getByLabel("投资标的", { exact: true }).selectOption("f0");
  await form.getByLabel("数量（份／股）", { exact: true }).fill("1");
  await form.getByLabel("实际扣款（元）", { exact: true }).fill("10");
  await form.getByRole("button", { name: "保存投资记录", exact: true }).click();
  await expect
    .poll(() => saved)
    .toMatchObject({
      nav_date: "2026-01-08",
      effective_date: "2026-01-10",
      amount_mode: "net",
      costs_fen: "0",
    });
  await page.getByRole("button", { name: "投资记录", exact: true }).click();
  await expect(
    table.getByRole("columnheader", { name: "净值所属日", exact: true }),
  ).toBeVisible();
  await expect(table.locator(".trade-blue")).toHaveText("买入／申购");
  await expect(table.locator(".trade-red")).toHaveText([
    "卖出／赎回",
    "定投买入",
  ]);
  await expect(table.getByText("已作废", { exact: true })).not.toHaveClass(
    /trade-red/,
  );
  await page.getByRole("button", { name: "标的与估值", exact: true }).click();
  await page.getByLabel("价格／净值日期", { exact: true }).fill("2026-01-01");
  await page
    .getByRole("button", { name: "价格／净值日期前一天", exact: true })
    .click();
  await expect(page.getByLabel("价格／净值日期", { exact: true })).toHaveValue(
    "2025-12-31",
  );
  await page.screenshot({
    path: "test-results/investment-dates.png",
    fullPage: true,
  });
});
