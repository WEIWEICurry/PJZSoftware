import { test, expect, type Page } from "@playwright/test";

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1sAAAAASUVORK5CYII=",
  "base64",
);
const file = (n: number) => ({
  name: "holding-" + n + ".png",
  mimeType: "image/png",
  buffer: Buffer.concat([png, Buffer.from([n])]),
});
async function setup(page: Page) {
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
          id: "holding",
          name: "支付宝",
          kind: "securities",
          archived: false,
          balance_fen: "0",
        },
      ],
    }),
  );
  await page.route("**/api/v1/investments", (r) =>
    r.fulfill({
      json: {
        instruments: [
          {
            id: "a",
            name: "合成基金A",
            code: "000001",
            kind: "fund",
            market: "FUND",
          },
          {
            id: "b",
            name: "合成基金B",
            code: "000002",
            kind: "fund",
            market: "FUND",
          },
        ],
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
  await page.goto("/investments/");
  await page.getByRole("button", { name: "持仓对账", exact: true }).click();
  return page.getByRole("region", { name: "支付宝持仓对账", exact: true });
}
function preview(code = "000001", day = "01-09") {
  return {
    product: "合成基金",
    code,
    quantity: "2.12",
    amount: "4.24",
    pending: "10.00",
    unit_nav: "2",
    nav_date: null,
    nav_month_day: day,
    cost_price: "2.5",
    warnings: ["净值年份请核对。"],
  };
}
test("批量持仓截图去重、识别重试、人工核对、只读结果和原交易跳转", async ({
  page,
}) => {
  const panel = await setup(page);
  const requests: unknown[] = [];
  let reads = 0;
  await page.route("**/api/v1/investments/holding-preview", (r) => {
    reads++;
    return reads === 2
      ? r.fulfill({
          status: 422,
          json: { error: { code: "OCR_UNSUPPORTED_HOLDING" } },
        })
      : r.fulfill({
          json: preview(
            reads === 1 ? "000001" : "000002",
            reads === 1 ? "01-09" : "01-10",
          ),
        });
  });
  await page.route("**/api/v1/investments/holdings/reconcile", (r) => {
    requests.push(r.request().postDataJSON());
    return r.fulfill({
      json: {
        revision: 7,
        as_of: "2026-01-11",
        account_id: "holding",
        unprovided: [
          { instrument_id: "z", name: "未提供合成基金", quantity: "5" },
        ],
        rows: [
          {
            instrument_id: "a",
            name: "合成基金A",
            code: "000001",
            platform_quantity: "2.12",
            local_quantity: "2.12345678",
            quantity_status: "display",
            quantity_delta: "0.00345678",
            platform_value_fen: "424",
            pending_fen: "1000",
            unit_nav: "2",
            nav_date: "2026-01-09",
            reference_value_fen: "425",
            value_delta_fen: "1",
            local_value_fen: "319",
            local_price: "1.5",
            local_price_date: "2026-01-08",
            local_cost_fen: "500",
            same_price_date: false,
          },
          {
            instrument_id: "b",
            name: "合成基金B",
            code: "000002",
            platform_quantity: "2.12",
            local_quantity: "0",
            quantity_status: "different",
            quantity_delta: "-2.12",
            platform_value_fen: "424",
            pending_fen: "0",
            unit_nav: "2",
            nav_date: "2026-01-10",
            reference_value_fen: "0",
            value_delta_fen: "-424",
            local_value_fen: "0",
            local_price: null,
            local_price_date: null,
            local_cost_fen: "0",
            same_price_date: false,
          },
        ],
      },
    });
  });
  await panel.getByLabel("截图持仓日期", { exact: true }).fill("2026-01-11");
  await panel
    .getByLabel("添加持仓截图")
    .setInputFiles([file(1), file(2), file(1)]);
  await expect(panel.getByRole("button", { name: /核对第/ })).toHaveCount(2);
  expect(reads).toBe(0);
  await panel.getByRole("button", { name: "识别持仓截图及失败项" }).click();
  await expect(panel).toContainText("识别失败");
  await panel.getByRole("button", { name: "识别持仓截图及失败项" }).click();
  await expect.poll(() => reads).toBe(3);
  for (const n of [1, 2]) {
    await panel
      .getByRole("button", { name: "核对第" + n + "张", exact: true })
      .click();
    await panel
      .getByRole("checkbox", { name: "已核对持仓日期及本张截图" })
      .check();
  }
  expect(requests).toHaveLength(0);
  await panel.getByRole("button", { name: "开始对账（2张）" }).click();
  const results = panel.getByRole("region", { name: "持仓对账结果" });
  await expect(results).toContainText("按截图精度一致");
  await expect(results).toContainText("份额有差异");
  await expect(results).toContainText("舍入差异");
  await results
    .getByText("合成基金A · 金额与日期核对", { exact: true })
    .click();
  await expect(results).toContainText("估值日期不同");
  await expect(results).toContainText("平台有待确认资金");
  await expect(results).toContainText("未提供截图的本地持仓");
  expect(requests[0]).toMatchObject({
    account_id: "holding",
    as_of: "2026-01-11",
    rows: [
      {
        instrument_id: "a",
        quantity: "2.12",
        amount_fen: "424",
        nav_date: "2026-01-09",
        pending_fen: "1000",
      },
      { instrument_id: "b", nav_date: "2026-01-10" },
    ],
  });
  await results
    .getByRole("button", { name: "查看相关投资记录" })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "投资记录", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "持仓对账", exact: true }).click();
  await expect(results).toBeVisible();
  await panel.getByLabel("截图持有份额", { exact: true }).fill("3");
  await expect(results).toHaveCount(0);
  await expect(
    panel.getByRole("checkbox", { name: "已核对持仓日期及本张截图" }),
  ).not.toBeChecked();
});

test("跨年净值年份推定、手改日期保留、重复基金排除及清空", async ({ page }) => {
  const panel = await setup(page);
  await page.route("**/api/v1/investments/holding-preview", (r) =>
    r.fulfill({ json: preview("000001", "12-31") }),
  );
  await panel.getByLabel("截图持仓日期", { exact: true }).fill("2026-01-02");
  await panel.getByLabel("添加持仓截图").setInputFiles([file(1), file(2)]);
  await panel.getByRole("button", { name: "识别持仓截图及失败项" }).click();
  await expect(panel.getByLabel("对账净值所属日", { exact: true })).toHaveValue(
    "2025-12-31",
  );
  await panel.getByLabel("对账净值所属日", { exact: true }).fill("2026-01-01");
  await panel
    .getByRole("checkbox", { name: "已核对持仓日期及本张截图" })
    .check();
  await panel.getByLabel("截图持仓日期", { exact: true }).fill("2026-01-03");
  await expect(panel.getByLabel("对账净值所属日", { exact: true })).toHaveValue(
    "2026-01-01",
  );
  await expect(
    panel.getByRole("checkbox", { name: "已核对持仓日期及本张截图" }),
  ).not.toBeChecked();
  await panel
    .getByRole("checkbox", { name: "已核对持仓日期及本张截图" })
    .check();
  await expect(panel).toContainText("同一基金存在多张截图");
  await panel.getByRole("checkbox", { name: "对账第2张" }).uncheck();
  await expect(
    panel.getByRole("button", { name: "开始对账（1张）" }),
  ).toBeEnabled();
  await panel.getByRole("button", { name: "清空本批截图" }).click();
  await expect(panel.getByRole("button", { name: /核对第/ })).toHaveCount(0);
});
