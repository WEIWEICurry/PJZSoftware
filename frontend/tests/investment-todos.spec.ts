import { test, expect, type Page } from "@playwright/test";

const fund = {
  id: "fund",
  name: "合成基金A",
  code: "000001",
  kind: "fund",
  market: "FUND",
};
const holding = {
  id: "cash",
  name: "支付宝",
  kind: "securities",
  archived: false,
  balance_fen: "100000",
};
const portfolio = {
  instruments: [fund],
  positions: [],
  valuations: [],
  trades: [],
  known_value_fen: "0",
  missing_price_count: 0,
  unrealized_fen: "0",
  total_profit_fen: "0",
  realized_fen: "0",
  cash_dividends_fen: "0",
  reinvested_dividends_fen: "0",
};
const items = [
  {
    kind: "recurring",
    id: "plan",
    title: "合成定投",
    detail: "最早 2026-01-02",
    count: 2,
    plan_id: "plan",
    start: "2026-01-02",
    end: "2026-01-10",
  },
  {
    kind: "missing_price",
    id: "fund",
    title: "合成基金A",
    detail: "涉及支付宝",
    count: 1,
    instrument_id: "fund",
  },
  {
    kind: "stale_price",
    id: "old",
    title: "合成基金A",
    detail: "最近 2026-01-01",
    count: 1,
    instrument_id: "fund",
  },
  {
    kind: "unknown_cost",
    id: "cost",
    title: "合成基金A",
    detail: "支付宝 · 成本待补齐",
    count: 1,
    instrument_id: "fund",
    account_id: "cash",
  },
];
async function setup(page: Page) {
  await page.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic" } }),
  );
  await page.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic", revision: 1 } }),
  );
  await page.route("**/api/v1/accounts", (r) => r.fulfill({ json: [holding] }));
  await page.route("**/api/v1/investments", (r) =>
    r.fulfill({ json: portfolio }),
  );
}
test("首页待办可直接定位定投、基金估值与持仓记录，刷新后消失", async ({
  page,
}) => {
  await setup(page);
  let cleared = false;
  let remote = 0;
  await page.route("**/api/v1/investments/todos", (r) =>
    r.fulfill({
      json: { as_of: "2026-01-20", revision: 1, items: cleared ? [] : items },
    }),
  );
  await page.route("**/api/v1/fund-nav/**", (r) => {
    remote++;
    return r.abort();
  });
  const plan = {
    id: "plan",
    name: "合成定投",
    account_id: "cash",
    cash_account_id: null,
    instrument_id: "fund",
    start_date: "2026-01-01",
    frequency: "daily",
    weekday: 0,
    amount_fen: "1000",
    costs_fen: "1",
    paused: false,
    deleted: false,
    has_drafts: true,
    pending_count: 2,
    confirmed_count: 0,
    revision: 1,
  };
  await page.route("**/api/v1/recurring?include_deleted=true", (r) =>
    r.fulfill({ json: [plan] }),
  );
  const draftUrls: string[] = [];
  await page.route("**/api/v1/recurring/plan/drafts?**", (r) => {
    draftUrls.push(r.request().url());
    if (draftUrls.length === 1)
      return r.fulfill({
        status: 422,
        json: { error: { code: "RECURRING_INVALID_RANGE" } },
      });
    return r.fulfill({
      json: [
        {
          id: "draft",
          plan_id: "plan",
          scheduled_date: "2026-01-02",
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
    });
  });
  await page.goto("/investments/");
  const todo = page.getByRole("region", { name: "投资待办", exact: true });
  await expect(todo).toContainText("合成定投");
  await todo.getByRole("button", { name: "查看待核对项", exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "选择定投计划" }),
  ).toHaveValue("plan");
  await expect(page.getByLabel("核对开始日期", { exact: true })).toHaveValue(
    "2026-01-02",
  );
  await expect(page.getByLabel("核对结束日期", { exact: true })).toHaveValue(
    "2026-01-10",
  );
  await expect.poll(() => draftUrls.length).toBe(1);
  expect(draftUrls[0]).toContain("start=2026-01-02&end=2026-01-10");
  await expect(
    page.getByText("请选择有效范围，一次最多 366 天。", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "查看待核对项", exact: true }).click();
  await expect.poll(() => draftUrls.length).toBe(2);

  await expect(
    page.getByRole("table", { name: "定投待核对列表" }),
  ).toContainText("2026-01-02");
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  await todo.getByRole("button", { name: /缺少有效估值/ }).click();
  await todo.getByRole("button", { name: "去更新估值", exact: true }).click();
  await expect(page.getByLabel("合成基金A价格", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("switch", { name: "启用本次联网查询", exact: true }),
  ).toBeVisible();
  expect(remote).toBe(0);
  await page
    .getByRole("switch", { name: "启用本次联网查询", exact: true })
    .click();
  await expect(page.getByRole("checkbox", { name: /合成基金A/ })).toBeChecked();
  expect(remote).toBe(0);
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  await todo.getByRole("button", { name: /持仓成本待补齐/ }).click();
  await todo.getByRole("button", { name: "查看持仓记录", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "投资记录", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  await expect(todo).toContainText("合成定投");
  await todo.screenshot({ path: "test-results/investment-todos.png" });
  cleared = true;
  await page.getByRole("button", { name: "刷新投资", exact: true }).click();
  await expect(todo).toContainText("当前没有待处理事项");
});

test("待办读取失败提供重试，较早请求返回不会覆盖刷新结果", async ({ page }) => {
  await setup(page);
  let calls = 0;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/investments/todos", async (r) => {
    calls++;
    if (calls === 1)
      return r.fulfill({ status: 500, json: { error: { code: "UNKNOWN" } } });
    if (calls === 2) {
      await gate;
      return r.fulfill({ json: { as_of: "2026-01-20", revision: 1, items } });
    }
    return r.fulfill({ json: { as_of: "2026-01-20", revision: 2, items: [] } });
  });
  await page.goto("/investments/");
  const todo = page.getByRole("region", { name: "投资待办", exact: true });
  await expect(todo).toContainText("待办读取失败");
  await expect(todo.getByRole("button", { name: /定投待核对/ })).toHaveCount(0);
  await todo.getByRole("button", { name: "刷新待办", exact: true }).click();
  await expect.poll(() => calls).toBe(2);
  await page.getByRole("button", { name: "刷新投资", exact: true }).click();
  await expect(todo).toContainText("当前没有待处理事项");
  const stale = page.waitForResponse((r) =>
    r.url().endsWith("/investments/todos"),
  );
  release();
  await stale;
  await expect(todo).toContainText("当前没有待处理事项");
  await expect(todo).not.toContainText("合成定投");
});
