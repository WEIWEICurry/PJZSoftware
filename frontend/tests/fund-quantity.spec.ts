import { test, expect } from "@playwright/test";
test("手工基金及定投按净值预填，手改优先且字段变化重算", async ({ page }) => {
  const fund = {
    id: "fund",
    name: "合成基金A",
    market: "FUND",
    code: "000001",
    kind: "fund",
  };
  await page.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic" } }),
  );
  await page.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic", revision: 1 } }),
  );
  await page.route("**/api/v1/accounts", (r) =>
    r.fulfill({
      json: [
        {
          id: "cash",
          name: "支付宝",
          kind: "securities",
          archived: false,
          balance_fen: "100000",
        },
      ],
    }),
  );
  await page.route("**/api/v1/investments", (r) =>
    r.fulfill({
      json: {
        instruments: [fund],
        positions: [],
        trades: [],
        valuations: [],
        known_value_fen: "0",
        missing_price_count: 0,
        unrealized_fen: "0",
        total_profit_fen: "0",
        realized_fen: "0",
        cash_dividends_fen: "0",
        reinvested_dividends_fen: "0",
      },
    }),
  );
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let delayed = false;
  await page.route("**/api/v1/investments/quantity-estimates", async (r) => {
    const rows = r.request().postDataJSON().rows;
    if (
      rows.some((row: { nav_date: string }) => row.nav_date === "2026-01-12")
    ) {
      delayed = true;
      await gate;
    }
    return r.fulfill({
      json: rows.map(
        (row: {
          id: string;
          nav_date: string;
          costs_fen: string;
          amount_mode: string;
        }) => ({
          id: row.id,
          price: row.nav_date === "2026-01-11" ? null : "2",
          quantity:
            row.nav_date === "2026-01-11"
              ? null
              : row.nav_date === "2026-01-12"
                ? "9.99"
                : row.costs_fen === "2" && row.amount_mode === "net"
                  ? "4.99"
                  : "5.00",
          code: row.nav_date === "2026-01-11" ? "ESTIMATE_NAV_MISSING" : null,
        }),
      ),
    });
  });
  const saved: unknown[] = [];
  await page.route("**/api/v1/investments/trades", (r) => {
    saved.push(r.request().postDataJSON());
    return r.fulfill({ json: { id: "saved" } });
  });
  await page.goto("/investments/");
  await page.getByRole("button", { name: "记一笔投资", exact: true }).click();
  const form = page.getByRole("region", { name: "投资记录表单" });
  await form.getByRole("checkbox", { name: "选择该账户的新标的" }).check();
  await form.getByLabel("投资标的", { exact: true }).selectOption("fund");
  await form.getByLabel("成交／确认日期", { exact: true }).fill("2026-01-13");
  const nav = form.getByLabel("成交净值所属日", { exact: true });
  await nav.fill("2026-01-10");
  await form.getByLabel("实际扣款（元）", { exact: true }).fill("10.00");
  await form.getByLabel("费用合计（元）").fill("0.01");
  const units = form.getByLabel("数量（份／股）", { exact: true });
  await expect(units).toHaveValue("5.00");
  await form.getByLabel("费用合计（元）").fill("0.02");
  await expect(units).toHaveValue("4.99");
  await form.getByLabel("金额口径", { exact: true }).selectOption("gross");
  await expect(units).toHaveValue("5.00");
  await units.fill("6.12345678");
  await form.getByLabel("金额口径", { exact: true }).selectOption("net");
  await expect(units).toHaveValue("6.12345678");
  await form.getByRole("button", { name: "按净值重算份额" }).click();
  await expect(units).toHaveValue("4.99");
  await nav.fill("2026-01-11");
  await expect(units).toHaveValue("");
  await expect(form).toContainText("本地暂无该日有效净值");
  await nav.fill("2026-01-12");
  await expect.poll(() => delayed).toBe(true);
  await nav.fill("2026-01-10");
  await expect(units).toHaveValue("4.99");
  const response = page.waitForResponse((r) =>
    r.url().endsWith("/investments/quantity-estimates"),
  );
  release();
  await response;
  await expect(units).toHaveValue("4.99");
  await form.getByRole("button", { name: "保存投资记录", exact: true }).click();
  await expect.poll(() => saved.length).toBe(1);
  expect(saved[0]).toMatchObject({
    quantity: "4.99",
    costs_fen: "2",
    amount_mode: "net",
    nav_date: "2026-01-10",
  });
  await page.route("**/api/v1/recurring?include_deleted=true", (r) =>
    r.fulfill({
      json: [
        {
          id: "plan",
          name: "合成定投",
          account_id: "cash",
          instrument_id: "fund",
          start_date: "2026-01-01",
          frequency: "daily",
          weekday: 0,
          amount_fen: "1000",
          costs_fen: "1",
          paused: false,
          deleted: false,
          revision: 1,
        },
      ],
    }),
  );
  await page.route("**/api/v1/recurring/plan/drafts?**", (r) =>
    r.fulfill({
      json: [
        {
          id: "draft",
          plan_id: "plan",
          scheduled_date: "2026-01-10",
          amount_fen: "1000",
          costs_fen: "1",
          status: "pending",
          revision: 1,
          event_id: null,
          event_status: null,
          effective_date: null,
          quantity: null,
          nav_date: null,
          nav_price: null,
        },
      ],
    }),
  );
  await page.getByRole("button", { name: "定投计划", exact: true }).click();
  await page
    .getByRole("combobox", { name: "选择定投计划" })
    .selectOption("plan");
  await page.getByLabel("核对开始日期", { exact: true }).fill("2026-01-01");
  await page.getByLabel("核对结束日期", { exact: true }).fill("2026-01-20");
  await page.getByRole("button", { name: "查看待核对项", exact: true }).click();
  const row = page
    .getByRole("table", { name: "定投待核对列表" })
    .locator("tbody tr")
    .first();
  await expect(row.locator('input[type="date"]').last()).toHaveValue(
    "2026-01-10",
  );
  const recurringUnits = page.getByLabel("2026-01-10 份额", { exact: true });
  await expect(recurringUnits).toHaveValue("5.00");
  await page.getByLabel("选择 2026-01-10", { exact: true }).check();
  await page.getByLabel("2026-01-10 费用", { exact: true }).fill("0.02");
  await expect(recurringUnits).toHaveValue("4.99");
  await recurringUnits.fill("7");
  await page.getByLabel("2026-01-10 费用", { exact: true }).fill("0.01");
  await expect(recurringUnits).toHaveValue("7");
  await page.getByRole("button", { name: "按净值重算", exact: true }).click();
  await expect(recurringUnits).toHaveValue("5.00");
  await page
    .getByLabel("2026-01-10 确认日期", { exact: true })
    .fill("2026-01-13");
  await page
    .getByRole("button", { name: "预览所选确认／跳过", exact: true })
    .click();
  await expect(page.getByText(/实际份额 5.00/)).toBeVisible();
});
