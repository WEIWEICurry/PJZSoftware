import { expect, test } from "@playwright/test";
import { matchReceiptFund, matchReceiptPayment } from "../src/receipt-matching";

test("截图预填标的、净值日和扣款账户，经核对后显式保存", async ({ page }) => {
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
          archived: false,
          kind: "securities",
          balance_fen: "0",
        },
        {
          id: "bank",
          name: "中国银行卡",
          archived: false,
          kind: "bank",
          balance_fen: "100000",
        },
      ],
    }),
  );
  await page.route("**/api/v1/investments", (r) =>
    r.fulfill({
      json: {
        positions: [],
        valuations: [],
        known_value_fen: "0",
        missing_price_count: 0,
        unrealized_fen: "0",
        total_profit_fen: "0",
        realized_fen: "0",
        cash_dividends_fen: "0",
        reinvested_dividends_fen: "0",
        instruments: [
          {
            id: "a",
            name: "合成测试基金A",
            market: "FUND",
            kind: "fund",
            code: "000001",
          },
          {
            id: "c",
            name: "合成测试基金C",
            market: "FUND",
            kind: "fund",
            code: "000002",
          },
        ],
        trades: [
          {
            id: "existing",
            action: "buy",
            status: "active",
            account_id: "holding",
            instrument_id: "a",
            effective_date: "2026-11-04",
            gross_fen: "9988",
            costs_fen: "12",
            quantity: "93.0800",
          },
        ],
      },
    }),
  );
  let previewCount = 0;
  await page.route("**/api/v1/investments/receipt-preview", (r) => {
    previewCount++;
    expect(r.request().headers()["content-type"]).toContain(
      "multipart/form-data",
    );
    return r.fulfill({
      json: {
        product: "合成测试基金Ａ＞",
        code: null,
        payment_hint: "中国银行储蓄卡(4321)",
        amount: "100.00",
        fee: "0.12",
        confirmed_amount: "99.88",
        quantity: "93.08",
        unit_nav: "1.0730",
        purchase_date: "2026-11-03",
        purchase_time: "14:01:13",
        confirmation_date: "2026-11-04",
        nav_date: "2026-11-03",
        nav_date_estimated: true,
        warnings: ["净值所属日按买入时间和沪深开市日推算，请以实际回执为准。"],
      },
    });
  });
  const saved: unknown[] = [];
  await page.route("**/api/v1/investments/trades", (r) => {
    saved.push(r.request().postDataJSON());
    return r.fulfill({ json: { id: "new" } });
  });

  await page.goto("/investments/");
  await page.getByRole("button", { name: "记一笔投资", exact: true }).click();
  const form = page.getByRole("region", { name: "投资记录表单" });
  await form.getByRole("button", { name: "从截图填入" }).click();
  const review = form.getByRole("region", { name: "截图识别核对" });
  await review.getByLabel("选择截图", { exact: true }).setInputFiles({
    name: "synthetic.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1sAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  expect(previewCount).toBe(0);
  await review.getByRole("button", { name: "识别截图", exact: true }).click();
  await expect(review).toContainText("1.0730");
  expect(saved).toEqual([]);
  await review.getByRole("button", { name: "填入并替换当前草稿" }).click();
  await expect(
    review.getByRole("img", { name: "待核对的基金买入回执" }),
  ).toBeVisible();
  expect(saved).toEqual([]);
  await expect(form.getByLabel("投资标的", { exact: true })).toHaveValue("a");
  await expect(
    form.getByRole("checkbox", { name: "选择该账户的新标的" }),
  ).toBeChecked();
  await expect(form.getByLabel("实际扣款（元）", { exact: true })).toHaveValue(
    "100.00",
  );
  await expect(form.getByLabel("成交／确认日期", { exact: true })).toHaveValue(
    "2026-11-04",
  );
  await expect(form.getByLabel("扣款账户", { exact: true })).toHaveValue(
    "bank",
  );
  await expect(form.getByLabel("成交净值所属日", { exact: true })).toHaveValue(
    "2026-11-03",
  );
  await expect(form).toContainText("按买入时间和沪深开市日推算");
  const save = form.getByRole("button", { name: "保存投资记录", exact: true });
  await expect(save).toBeDisabled();
  await form.getByRole("checkbox", { name: /已核对疑似重复/ }).check();
  await save.click();
  await expect
    .poll(() => saved)
    .toMatchObject([
      {
        account_id: "holding",
        cash_account_id: "bank",
        instrument_id: "a",
        quantity: "93.08",
        amount_fen: "10000",
        costs_fen: "12",
        amount_mode: "net",
        effective_date: "2026-11-04",
        nav_date: "2026-11-03",
        note: "",
      },
    ]);
});

test("基金类别、代码冲突和扣款账户歧义保持独立", () => {
  const funds = [
    { id: "fund-a", kind: "fund", name: "合成基金A", code: "000001" },
    { id: "fund-c", kind: "fund", name: "合成基金C", code: "000002" },
  ];
  expect(matchReceiptFund(funds, null, "合成基金Ａ＞")).toBe("fund-a");
  expect(matchReceiptFund(funds, "000002", "合成基金Ａ＞")).toBe("");
  expect(matchReceiptFund(funds, null, "合成基金")).toBe("");
  const card = { id: "card", kind: "bank", name: "中国银行卡" };
  const card1 = { id: "card1", kind: "bank", name: "中国银行卡 尾号4321" };
  const card2 = { id: "card2", kind: "bank", name: "中国银行储蓄卡（4567）" };
  const hint = "中国银行储蓄卡(4321)";
  expect(matchReceiptPayment([card], hint)).toBe("card");
  expect(matchReceiptPayment([card1, card2], hint)).toBe("card1");
  expect(matchReceiptPayment([card2], hint)).toBe("");
  expect(matchReceiptPayment([card, card2], hint)).toBe("");
  expect(matchReceiptPayment([card1, card2], "中国银行储蓄卡")).toBe("");
});
