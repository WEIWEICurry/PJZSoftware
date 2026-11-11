import { test, expect } from "@playwright/test";

test("卖出按持仓筛选、历史查询失败重试与切换、清仓历史可编辑", async ({
  page,
}) => {
  const instruments = ["a", "b", "closed"].map((id) => ({
    id,
    name: `Synthetic ${id}`,
    code: "000001",
    kind: "fund",
    market: "FUND",
    revision: 1,
  }));
  const accounts = ["a", "b", "empty"].map((id) => ({
    id,
    name: id === "a" ? "支付宝" : `Synthetic ${id}`,
    kind: "securities",
    archived: false,
    balance_fen: "1000",
  }));
  const positions = ["a", "b", "closed"].map((id) => ({
    account_id: id === "closed" ? "a" : id,
    instrument_id: id,
    quantity: id === "closed" ? "0" : "2.00000001",
    value_fen: "0",
    cost_fen: "0",
    unrealized_fen: "0",
    share_bps: null,
    holding_return_bps: null,
    total_profit_fen: "0",
    total_return_bps: null,
  }));
  const trades = [
    {
      id: "old",
      account_id: "a",
      instrument_id: "closed",
      action: "sell",
      effective_date: "2026-01-20",
      nav_date: "2026-01-19",
      quantity: "1",
      gross_fen: "100",
      costs_fen: "0",
      cost_basis_fen: null,
      status: "active",
      revision: 1,
      note: "",
    },
  ];
  await page.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic" } }),
  );
  await page.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic", revision: 1 } }),
  );
  await page.route("**/api/v1/accounts", (r) => r.fulfill({ json: accounts }));
  await page.route("**/api/v1/investments", (r) =>
    r.fulfill({
      json: {
        instruments,
        positions,
        trades,
        valuations: [],
        known_value_fen: "0",
        missing_price_count: 0,
        realized_fen: "0",
        unrealized_fen: "0",
        total_profit_fen: "0",
        cash_dividends_fen: "0",
        reinvested_dividends_fen: "0",
      },
    }),
  );
  let failed = false;
  let releaseStale!: () => void;
  const staleGate = new Promise<void>((resolve) => {
    releaseStale = resolve;
  });
  await page.route("**/api/v1/investments/sell-options?**", async (r) => {
    const url = new URL(r.request().url());
    if (
      url.searchParams.get("effective_date") === "2026-01-11" &&
      url.searchParams.get("account_id") === "a"
    )
      await staleGate;
    if (url.searchParams.get("effective_date") === "2026-01-10" && !failed) {
      failed = true;
      await r.fulfill({
        status: 422,
        json: { error: { code: "SYNTHETIC_FAILURE" } },
      });
      return;
    }
    await r.fulfill({
      json:
        url.searchParams.get("account_id") === "empty"
          ? []
          : [{ instrument_id: "closed", quantity: "1.12345678" }],
    });
  });
  await page.goto("/investments/");
  await page.getByRole("button", { name: "记一笔投资", exact: true }).click();
  const form = page.getByRole("region", { name: "投资记录表单" });
  const asset = form.getByLabel("投资标的", { exact: true });
  const account = form.getByLabel("持仓账户", { exact: true });
  await expect(asset.locator("option")).toHaveCount(3);
  await expect(asset.locator("option[value='b']")).toHaveCount(0);
  await asset.selectOption("a");
  await form.getByLabel("数量（份／股）", { exact: true }).fill("1");
  await account.selectOption("b");
  await expect(asset).toHaveValue("");
  await expect(form.getByLabel("数量（份／股）", { exact: true })).toHaveValue(
    "",
  );
  await expect(asset.locator("option[value='a']")).toHaveCount(0);
  await expect(asset.locator("option[value='b']")).toHaveCount(1);
  await account.selectOption("empty");
  await expect(asset).toBeDisabled();
  const newAsset = form.getByRole("checkbox", { name: "选择该账户的新标的" });
  await newAsset.check();
  await expect(asset).toBeEnabled();
  await expect(asset.locator("option")).toHaveCount(4);
  await asset.selectOption("a");
  await newAsset.uncheck();
  await expect(asset).toHaveValue("");
  await expect(asset).toBeDisabled();
  await newAsset.check();
  await account.selectOption("a");
  await expect(newAsset).not.toBeChecked();
  await form.screenshot({
    path: "test-results/account-instrument-options.png",
  });
  await form
    .getByRole("combobox", { name: "操作", exact: true })
    .selectOption("sell");
  await expect(asset.locator("option")).toHaveCount(2);
  await asset.selectOption("a");
  await expect(form).toContainText("当前持有 2.00000001 份／股");
  await form.getByLabel("数量（份／股）", { exact: true }).fill("1");
  await account.selectOption("b");
  await expect(asset).toHaveValue("");
  await expect(form.getByLabel("数量（份／股）", { exact: true })).toHaveValue(
    "",
  );
  await expect(asset.locator("option[value='a']")).toHaveCount(0);
  await expect(asset.locator("option[value='b']")).toHaveCount(1);
  await account.selectOption("empty");
  await expect(asset).toBeDisabled();
  await expect(form).toContainText("该账户暂无可卖出的持仓");
  await expect(
    form.getByRole("button", { name: "保存投资记录" }),
  ).toBeDisabled();
  await account.selectOption("");
  await expect(form).toContainText("请先选择持仓账户");
  await account.selectOption("a");
  await form.getByLabel("成交／确认日期", { exact: true }).fill("2026-01-10");
  await expect(form).toContainText("持仓查询失败");
  await expect(asset).toBeDisabled();
  await form.getByRole("button", { name: "重试持仓查询" }).click();
  await expect(asset).toBeEnabled();
  await asset.selectOption("closed");
  await expect(form).toContainText("所选日期剩余 1.12345678");
  await form.getByLabel("成交／确认日期", { exact: true }).fill("2026-01-11");
  await expect(form).toContainText("正在读取该日期的持仓");
  await account.selectOption("empty");
  await expect(form).toContainText("该账户在所选日期暂无可卖出的持仓");
  const staleResponse = page.waitForResponse((response) =>
    response.url().includes("account_id=a&effective_date=2026-01-11"),
  );
  releaseStale();
  await staleResponse;
  await expect(asset).toBeDisabled();
  await expect(asset.locator("option")).toHaveCount(1);
  await form
    .getByRole("combobox", { name: "操作", exact: true })
    .selectOption("buy");
  await expect(asset).toBeDisabled();
  await form.getByRole("checkbox", { name: "选择该账户的新标的" }).check();
  await expect(asset).toBeEnabled();
  await expect(asset.locator("option")).toHaveCount(4);
  await form.getByRole("button", { name: "取消编辑" }).click();
  await page.getByRole("button", { name: "投资记录", exact: true }).click();
  await page.getByRole("button", { name: "修改", exact: true }).click();
  await expect(asset).toHaveValue("closed");
  await expect(asset).toBeDisabled();
  await expect(account).toBeDisabled();
  await expect(
    form.getByLabel("数量（份／股）", { exact: true }),
  ).toBeEnabled();
  await expect(form).toContainText(
    "当前剩余 0 份／股；历史修改以保存时重算校验为准",
  );
});
