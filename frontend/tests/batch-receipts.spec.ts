import { test, expect, type Page } from "@playwright/test";

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1sAAAAASUVORK5CYII=",
  "base64",
);
const file = (n: number) => ({
  name: "synthetic-" + n + ".png",
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
        {
          id: "bank",
          name: "中国银行卡",
          kind: "bank",
          archived: false,
          balance_fen: "100000",
        },
      ],
    }),
  );
  await page.route("**/api/v1/investments", (r) =>
    r.fulfill({
      json: {
        instruments: [
          {
            id: "fund",
            name: "合成基金A",
            code: "000001",
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
  await page.getByRole("button", { name: "记一笔投资", exact: true }).click();
  await page.getByRole("button", { name: "批量截图录入", exact: true }).click();
  return page.getByRole("region", { name: "批量截图核对", exact: true });
}
function preview(quantity = "1") {
  return {
    product: "合成基金A",
    code: "000001",
    payment_hint: "中国银行储蓄卡(4321)",
    amount: "10.00",
    fee: "0.01",
    confirmed_amount: "9.99",
    quantity,
    unit_nav: "1",
    purchase_date: "2026-01-09",
    purchase_time: "14:00:00",
    confirmation_date: "2026-01-10",
    nav_date: "2026-01-09",
    nav_date_estimated: true,
    warnings: ["请核对推算净值日。"],
  };
}
test("多图去重、部分识别失败重试、逐张核对、排除和原子保存业务失败", async ({
  page,
}) => {
  const panel = await setup(page);
  let previews = 0;
  await page.route("**/api/v1/investments/receipt-preview", (r) => {
    previews++;
    if (previews === 2)
      return r.fulfill({
        status: 422,
        json: { error: { code: "OCR_UNSUPPORTED_RECEIPT" } },
      });
    return r.fulfill({ json: preview(String(previews)) });
  });
  const saved: unknown[] = [];
  await page.route("**/api/v1/investments/receipt-batches", (r) => {
    saved.push(r.request().postDataJSON());
    return saved.length === 1
      ? r.fulfill({
          status: 422,
          json: { error: { code: "FEE_EXCEEDS_AMOUNT" } },
        })
      : r.fulfill({ json: { ids: ["one", "two"] } });
  });
  await panel.getByLabel("添加多张截图").setInputFiles([
    file(1),
    file(2),
    file(3),
    file(1),
    {
      name: "invalid.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("synthetic"),
    },
  ]);
  await expect(panel.getByRole("button", { name: /查看第/ })).toHaveCount(3);
  await expect(panel).toContainText("相同截图已在队列");
  expect(previews).toBe(0);
  await panel.getByRole("button", { name: "识别待处理及失败截图" }).click();
  await expect(panel).toContainText("识别失败");
  await panel.getByRole("button", { name: "识别待处理及失败截图" }).click();
  await expect.poll(() => previews).toBe(4);
  await expect(
    panel.getByRole("button", { name: "识别待处理及失败截图" }),
  ).toBeDisabled();
  await expect(panel.getByLabel("投资标的", { exact: true })).toHaveValue(
    "fund",
  );
  await expect(panel.getByLabel("扣款账户", { exact: true })).toHaveValue(
    "bank",
  );
  const save = panel.getByRole("button", { name: "确认保存所选交易" });
  await expect(save).toBeDisabled();
  await panel.getByRole("checkbox", { name: "已核对本张截图" }).check();
  await panel.getByLabel("实际扣款（元，含费）", { exact: true }).fill("11.00");
  await expect(
    panel.getByRole("checkbox", { name: "已核对本张截图" }),
  ).not.toBeChecked();
  await panel.getByRole("checkbox", { name: "已核对本张截图" }).check();
  await panel.getByRole("button", { name: "查看第2张", exact: true }).click();
  await panel.getByRole("checkbox", { name: "已核对本张截图" }).check();
  await panel.getByRole("checkbox", { name: "录入第3张" }).uncheck();
  await expect(save).toBeEnabled();
  await expect(panel).toContainText("¥21.00");
  await panel.screenshot({ path: "test-results/batch-receipt-review.png" });
  expect(saved).toHaveLength(0);
  await save.click();
  await expect(panel).toContainText("本批次全部未保存");
  await expect(save).toBeEnabled();
  await save.click();
  await expect(panel).toContainText("所选 2 笔交易已全部保存");
  await expect(
    panel.getByRole("checkbox", { name: "录入第1张" }),
  ).toBeDisabled();
  await expect(save).toBeDisabled();
  expect(saved[1]).toMatchObject({
    rows: [
      {
        account_id: "holding",
        cash_account_id: "bank",
        instrument_id: "fund",
        quantity: "1",
        amount_fen: "1100",
        costs_fen: "1",
        amount_mode: "net",
        nav_date: "2026-01-09",
      },
      { quantity: "4", amount_fen: "1000", costs_fen: "1" },
    ],
  });
});

test("重复交易须人工确认，断线后冻结并重试原批次使用同一幂等键", async ({
  page,
}) => {
  const panel = await setup(page);
  await page.route("**/api/v1/investments/receipt-preview", (r) =>
    r.fulfill({ json: preview() }),
  );
  const requests: { body: unknown; key: string | undefined }[] = [];
  await page.route("**/api/v1/investments/receipt-batches", (r) => {
    requests.push({
      body: r.request().postDataJSON(),
      key: r.request().headers()["idempotency-key"],
    });
    return requests.length === 1
      ? r.abort("failed")
      : r.fulfill({ json: { ids: ["one", "two"] } });
  });
  await panel.getByLabel("添加多张截图").setInputFiles([file(1), file(2)]);
  await panel.getByRole("button", { name: "识别待处理及失败截图" }).click();
  await expect(panel).toContainText("识别结束");
  for (const n of [1, 2]) {
    await panel
      .getByRole("button", { name: "查看第" + n + "张", exact: true })
      .click();
    await panel.getByRole("checkbox", { name: "已核对本张截图" }).check();
  }
  const save = panel.getByRole("button", { name: "确认保存所选交易" });
  await expect(save).toBeDisabled();
  for (const n of [1, 2]) {
    await panel
      .getByRole("button", { name: "查看第" + n + "张", exact: true })
      .click();
    await panel
      .getByRole("checkbox", { name: "已核对疑似重复，确认是独立交易" })
      .check();
    await panel.getByRole("checkbox", { name: "已核对本张截图" }).check();
  }
  await save.click();
  await expect(panel).toContainText("保存结果尚未确认");
  await expect(panel.getByLabel("确认份额", { exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "关闭批量截图录入", exact: true }),
  ).toBeDisabled();
  await panel.getByRole("button", { name: "重试确认原批次保存结果" }).click();
  await expect(panel).toContainText("所选 2 笔交易已全部保存");
  expect(requests[0].key).toBeTruthy();
  expect(requests[1]).toEqual(requests[0]);
});
