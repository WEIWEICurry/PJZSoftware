import { test, expect } from "@playwright/test";
import { sortPositions } from "../src/position-sort";

test("金额排序保留精度、负数、零值、未知置底与同值原序", () => {
  const rows = [
    {
      id: "low",
      cost_fen: "9007199254740992",
      value_fen: "0",
      unrealized_fen: "-500",
      share_bps: "0",
    },
    {
      id: "high",
      cost_fen: "9007199254740993",
      value_fen: "1000",
      unrealized_fen: "100",
      share_bps: "10000",
    },
    {
      id: "missing",
      cost_fen: null,
      value_fen: null,
      unrealized_fen: null,
      share_bps: null,
    },
    {
      id: "equal",
      cost_fen: "9007199254740992",
      value_fen: "0",
      unrealized_fen: "-500",
      share_bps: "0",
    },
  ];
  const ids = (items: typeof rows) => items.map((item) => item.id);
  expect(
    ids(sortPositions(rows, { key: "cost_fen", direction: "descending" })),
  ).toEqual(["high", "low", "equal", "missing"]);
  expect(
    ids(sortPositions(rows, { key: "cost_fen", direction: "ascending" })),
  ).toEqual(["low", "equal", "high", "missing"]);
  expect(
    ids(sortPositions(rows, { key: "value_fen", direction: "ascending" })),
  ).toEqual(["low", "equal", "high", "missing"]);
  expect(
    ids(sortPositions(rows, { key: "unrealized_fen", direction: "ascending" })),
  ).toEqual(["low", "equal", "high", "missing"]);
  expect(
    ids(sortPositions(rows, { key: "share_bps", direction: "descending" })),
  ).toEqual(["high", "low", "equal", "missing"]);
  expect(
    ids(sortPositions(rows, { key: "share_bps", direction: "ascending" })),
  ).toEqual(["low", "equal", "high", "missing"]);
  expect(ids(sortPositions(rows, null))).toEqual([
    "low",
    "high",
    "missing",
    "equal",
  ]);
  expect(ids(rows)).toEqual(["low", "high", "missing", "equal"]);
});

test("持仓表头点击与键盘切换排序，筛选和视图切换保持方向", async ({ page }) => {
  const accountId = "11111111-1111-4111-8111-111111111111";
  const otherAccount = "44444444-4444-4444-8444-444444444444";
  let complete = false;
  const instruments = ["合成甲", "合成乙", "合成丙", "合成丁", "合成戊"].map(
    (name, index) => ({
      id: `22222222-2222-4222-8222-22222222222${index}`,
      name,
      market: "FUND",
      kind: "fund",
      code: `10000${index}`,
      revision: 1,
    }),
  );
  const positionValues = [
    ["1000", "500", "-500"],
    ["900", "1000", "100"],
    [null, "2000", null],
    ["1000", null, null],
    ["1000", "500", "-500"],
  ];
  const positions = positionValues.map(
    ([cost_fen, value_fen, unrealized_fen], index) => ({
      account_id: index === 4 ? otherAccount : accountId,
      instrument_id: instruments[index].id,
      quantity: "1",
      cost_fen,
      value_fen,
      unrealized_fen,
      share_bps: null,
      realized_fen: "0",
      cash_dividends_fen: "0",
      reinvested_dividends_fen: "0",
      valuation_required_from: null,
      price: ["5", "10", "20", null, "5"][index],
      price_date: value_fen === null ? null : "2026-01-01",
    }),
  );
  const writes: string[] = [];
  page.on("request", (request) => {
    if (
      request.url().includes("/api/v1/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method())
    )
      writes.push(request.url());
  });
  await page.route("**/api/v1/session", (route) =>
    route.fulfill({ json: { csrf_token: "synthetic-sort-session" } }),
  );
  await page.route("**/api/v1/ledger", (route) =>
    route.fulfill({
      json: {
        id: accountId,
        name: "Synthetic sorting ledger",
        revision: 1,
        created_at: "2026-01-01",
        directory: "Synthetic directory",
        schema_version: 7,
        encrypted: false,
        stage: "M3",
      },
    }),
  );
  await page.route("**/api/v1/accounts", (route) =>
    route.fulfill({
      json: [
        {
          id: accountId,
          name: "合成投资账户",
          kind: "bank",
          opening_date: "2026-01-01",
          balance_fen: "10000",
          archived: false,
          revision: 1,
        },
        {
          id: otherAccount,
          name: "合成第二账户",
          kind: "bank",
          opening_date: "2026-01-01",
          balance_fen: "0",
          archived: false,
          revision: 1,
        },
      ],
    }),
  );
  await page.route("**/api/v1/investments", (route) =>
    route.fulfill({
      json: {
        instruments,
        positions: complete
          ? positions.map((p, index) => ({
              ...p,
              ...(index === 3
                ? {
                    value_fen: "1000",
                    unrealized_fen: "0",
                    price: "10",
                    price_date: "2026-01-01",
                  }
                : {}),
              share_bps: ["1000", "2000", "4000", "2000", "1000"][index],
            }))
          : positions,
        trades: [],
        valuations: [],
        known_value_fen: complete ? "5000" : "4000",
        missing_price_count: complete ? 0 : 1,
        unknown_cost_count: 1,
        realized_fen: "0",
        cash_dividends_fen: "0",
        reinvested_dividends_fen: "0",
        unrealized_fen: null,
        total_profit_fen: null,
        known_net_fen: complete ? "15000" : "14000",
        net_fen: complete ? "15000" : null,
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("已连接本机服务")).toBeVisible();
  await page.getByRole("button", { name: "投资", exact: true }).click();
  const table = page.locator(".investment-table");
  const names = async () =>
    (await table.locator("tbody td:first-child").allTextContents()).map(
      (value) => value.split(" · ")[0],
    );
  await expect(table.locator("tbody tr")).toHaveCount(5);
  const cost = table.getByRole("button", { name: "剩余成本", exact: true });
  const value = table.getByRole("button", { name: "市值", exact: true });
  const profit = table.getByRole("button", { name: "持仓盈亏", exact: true });
  await cost.click();
  await expect(
    table.getByRole("columnheader", { name: "剩余成本", exact: true }),
  ).toHaveAttribute("aria-sort", "descending");
  expect(await names()).toEqual([
    "合成甲",
    "合成丁",
    "合成戊",
    "合成乙",
    "合成丙",
  ]);
  await cost.click();
  expect(await names()).toEqual([
    "合成乙",
    "合成甲",
    "合成丁",
    "合成戊",
    "合成丙",
  ]);
  await expect(
    table.getByRole("columnheader", { name: "剩余成本", exact: true }),
  ).toHaveAttribute("aria-sort", "ascending");
  await cost.focus();
  await page.keyboard.press("Enter");
  expect(await names()).toEqual([
    "合成甲",
    "合成丁",
    "合成戊",
    "合成乙",
    "合成丙",
  ]);
  await value.click();
  expect(await names()).toEqual([
    "合成丙",
    "合成乙",
    "合成甲",
    "合成戊",
    "合成丁",
  ]);
  await value.click();
  expect(await names()).toEqual([
    "合成甲",
    "合成戊",
    "合成乙",
    "合成丙",
    "合成丁",
  ]);
  await profit.click();
  expect(await names()).toEqual([
    "合成乙",
    "合成甲",
    "合成戊",
    "合成丙",
    "合成丁",
  ]);
  await profit.click();
  expect(await names()).toEqual([
    "合成甲",
    "合成戊",
    "合成乙",
    "合成丙",
    "合成丁",
  ]);
  await page
    .getByRole("combobox", { name: "投资类型", exact: true })
    .selectOption("fund");
  await page.getByRole("button", { name: "投资记录", exact: true }).click();
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  await expect(
    table.getByRole("columnheader", { name: "持仓盈亏", exact: true }),
  ).toHaveAttribute("aria-sort", "ascending");
  expect(await names()).toEqual([
    "合成甲",
    "合成戊",
    "合成乙",
    "合成丙",
    "合成丁",
  ]);
  await page.getByRole("button", { name: "刷新投资", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("投资数据已刷新");
  expect(await names()).toEqual([
    "合成甲",
    "合成戊",
    "合成乙",
    "合成丙",
    "合成丁",
  ]);
  const share = table.getByRole("button", { name: "持仓占比", exact: true });
  await share.click();
  await expect(
    table.locator("tbody tr td:nth-child(6)").filter({ hasText: "待估值" }),
  ).toHaveCount(5);
  complete = true;
  await page.getByRole("button", { name: "刷新投资", exact: true }).click();
  await expect(table.locator("tbody tr").first()).toContainText("40.00%");
  expect(await names()).toEqual([
    "合成丙",
    "合成乙",
    "合成丁",
    "合成甲",
    "合成戊",
  ]);
  await share.click();
  await expect(
    table.getByRole("columnheader", { name: "持仓占比", exact: true }),
  ).toHaveAttribute("aria-sort", "ascending");
  expect(await names()).toEqual([
    "合成甲",
    "合成戊",
    "合成乙",
    "合成丁",
    "合成丙",
  ]);
  await page
    .getByRole("combobox", { name: "账户筛选", exact: true })
    .selectOption(accountId);
  expect(await names()).toEqual(["合成甲", "合成乙", "合成丁", "合成丙"]);
  await expect(
    table
      .locator("tbody tr")
      .first()
      .getByRole("cell", { name: "10.00%", exact: true }),
  ).toBeVisible();
  expect(writes).toEqual([]);
});
