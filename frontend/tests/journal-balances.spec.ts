import { test, expect } from "@playwright/test";

test("流水正负红绿、逐笔小字余额和转账账户视角", async ({ page }) => {
  await page.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic" } }),
  );
  await page.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic", revision: 1 } }),
  );
  const accounts = [
    {
      id: "bank",
      name: "合成银行卡",
      kind: "bank",
      balance_fen: "20000",
      opening_date: "2026-01-01",
      archived: false,
      revision: 1,
    },
    {
      id: "cash",
      name: "合成现金",
      kind: "cash",
      balance_fen: "20000",
      opening_date: "2026-01-01",
      archived: false,
      revision: 1,
    },
  ];
  await page.route("**/api/v1/accounts", (r) => r.fulfill({ json: accounts }));
  await page.route("**/api/v1/categories", (r) => r.fulfill({ json: [] }));
  const effect = (
    id: string,
    delta: string,
    balance: string,
    kind = "bank",
  ) => ({
    account_id: id,
    account_name: id === "bank" ? "合成银行卡" : "合成现金",
    account_kind: kind,
    delta_fen: delta,
    balance_fen: balance,
  });
  const entries = [
    {
      id: "expense",
      kind: "expense",
      amount_fen: "1230",
      fee_fen: "0",
      cash_effects: [effect("bank", "-1230", "98770")],
    },
    {
      id: "transfer",
      kind: "transfer",
      amount_fen: "20000",
      fee_fen: "100",
      target_account_id: "cash",
      cash_effects: [
        effect("bank", "-20100", "78670"),
        effect("cash", "20000", "20000", "cash"),
      ],
    },
    {
      id: "income",
      kind: "income",
      amount_fen: "5000",
      fee_fen: "0",
      cash_effects: [effect("bank", "5000", "83670")],
    },
    {
      id: "void",
      kind: "expense",
      amount_fen: "1230",
      fee_fen: "0",
      status: "void",
      cash_effects: [],
    },
    {
      id: "debt",
      kind: "adjustment",
      amount_fen: "-400",
      fee_fen: "0",
      cash_effects: [effect("bank", "-400", "600", "liability")],
    },
    {
      id: "zero",
      kind: "opening",
      amount_fen: "0",
      fee_fen: "0",
      cash_effects: [effect("bank", "0", "0")],
    },
  ];
  await page.route("**/api/v1/events?*", (r) => {
    const selected = new URL(r.request().url()).searchParams.get("account_id");
    const items = entries.map((row) => ({
      account_id: "bank",
      target_account_id: null,
      category_id: null,
      original_event_id: null,
      status: "active",
      revision: 1,
      effective_date: "2026-01-10",
      note: row.id,
      covered_by_history: false,
      ...row,
      cash_effects: row.cash_effects.filter(
        (e) => !selected || e.account_id === selected,
      ),
    }));
    return r.fulfill({ json: { items, total: items.length } });
  });
  await page.goto("/journal/");
  const panel = page.locator(".journal-panel");
  const rows = panel.locator("tbody tr");
  await expect(rows).toHaveCount(6);
  const expense = rows.nth(0);
  await expect(expense.locator(".journal-cash-value")).toHaveText("-¥12.30");
  await expect(expense.locator(".journal-cash-value")).toHaveCSS(
    "color",
    "rgb(8, 127, 107)",
  );
  await expect(expense.locator(".journal-running-balance")).toHaveText(
    "余额：¥987.70",
  );
  await expect(rows.nth(2).locator(".journal-cash-value")).toHaveText(
    "+¥50.00",
  );
  await expect(rows.nth(2).locator(".journal-cash-value")).toHaveCSS(
    "color",
    "rgb(197, 48, 48)",
  );
  const transfer = rows.nth(1);
  await expect(transfer.locator(".journal-cash-effect")).toHaveCount(2);
  await expect(transfer).toContainText("-¥201.00");
  await expect(transfer).toContainText("+¥200.00");
  await expect(transfer).toContainText("合成银行卡 · 余额：¥786.70");
  await expect(transfer).toContainText("合成现金 · 余额：¥200.00");
  await expect(rows.nth(3)).toContainText("已作废，未影响余额");
  await expect(rows.nth(3)).toContainText("原金额：¥12.30");
  await expect(rows.nth(3).locator(".journal-running-balance")).toHaveCount(0);
  await expect(rows.nth(4).locator(".journal-running-balance")).toHaveText(
    "欠款：¥6.00",
  );
  await expect(rows.nth(5).locator(".journal-cash-value")).toHaveText("¥0.00");
  await expect(
    rows.nth(5).locator(".journal-cash-in, .journal-cash-out"),
  ).toHaveCount(0);
  await panel.screenshot({ path: "test-results/journal-balances.png" });
  await page
    .getByRole("combobox", { name: "账户筛选", exact: true })
    .selectOption("cash");
  await expect(transfer.locator(".journal-cash-effect")).toHaveCount(1);
  await expect(transfer.locator(".journal-cash-value")).toHaveText("+¥200.00");
  await expect(transfer.locator(".journal-running-balance")).toHaveText(
    "余额：¥200.00",
  );
});
