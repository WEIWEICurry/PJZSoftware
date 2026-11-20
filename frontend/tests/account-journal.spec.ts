import { test, expect } from "@playwright/test";

test("账户流水链接支持全部日期、刷新、分页、筛选和归档账户", async ({
  page,
  context,
}) => {
  const accounts = [
    {
      id: "a",
      name: "合成银行卡",
      kind: "bank",
      balance_fen: "10000",
      opening_date: "2025-01-01",
      archived: false,
      revision: 1,
    },
    {
      id: "b",
      name: "合成旧账户",
      kind: "cash",
      balance_fen: "0",
      opening_date: "2025-01-01",
      archived: true,
      revision: 1,
    },
  ];
  await context.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic" } }),
  );
  await context.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic", revision: 1 } }),
  );
  await context.route("**/api/v1/accounts", (r) =>
    r.fulfill({ json: accounts }),
  );
  await context.route("**/api/v1/categories", (r) =>
    r.fulfill({ json: [{ id: "c", name: "合成工资", direction: "income" }] }),
  );
  let latest = new URLSearchParams();
  await context.route("**/api/v1/events?*", (r) => {
    latest = new URL(r.request().url()).searchParams;
    const offset = Number(latest.get("offset"));
    const selected = latest.get("account_id") || "a";
    return r.fulfill({
      json: {
        total: 21,
        items: Array.from({ length: offset ? 1 : 20 }, (_, i) => ({
          id: `row${offset + i}`,
          account_id: selected,
          target_account_id: null,
          kind: "income",
          amount_fen: "100",
          fee_fen: "0",
          category_id: "c",
          status: "active",
          revision: 1,
          effective_date: "2025-01-02",
          note: `合成流水${offset + i}`,
          original_event_id: null,
          covered_by_history: false,
        })),
      },
    });
  });
  await page.goto("/accounts/");
  const link = page.getByRole("link", {
    name: "查看合成银行卡的流水",
    exact: true,
  });
  await expect(link).toHaveAttribute("href", "/journal/?account_id=a");
  await page
    .locator(".account-card")
    .filter({ hasText: "合成银行卡" })
    .getByRole("button", { name: "编辑名称" })
    .click();
  await expect(page).toHaveURL(/\/accounts\/$/);
  await page.screenshot({
    path: "test-results/account-journal-card.png",
    fullPage: true,
  });
  await link.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/journal\/\?account_id=a$/);
  await expect(
    page.getByRole("combobox", { name: "账户筛选", exact: true }),
  ).toHaveValue("a");
  await expect(page.getByLabel("全部日期", { exact: true })).toBeChecked();
  await expect.poll(() => latest.get("start")).toBe("0001-01-01");
  expect(latest.get("account_id")).toBe("a");
  await expect(page.locator(".journal-panel tbody tr")).toHaveCount(20);
  await page.screenshot({
    path: "test-results/account-journal-view.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.locator(".journal-panel tbody tr")).toHaveCount(1);
  expect(latest.get("offset")).toBe("20");
  await page.getByLabel("全部日期", { exact: true }).uncheck();
  await page.getByLabel("月份", { exact: true }).fill("2025-02");
  await expect.poll(() => latest.get("start")).toBe("2025-02-01");
  expect(latest.get("end")).toBe("2025-02-28");
  expect(latest.get("offset")).toBe("0");
  await page
    .getByRole("combobox", { name: "类型筛选", exact: true })
    .selectOption("income");
  await expect.poll(() => latest.get("kind")).toBe("income");
  await page.reload();
  await expect(
    page.getByRole("combobox", { name: "账户筛选", exact: true }),
  ).toHaveValue("a");
  await expect(page.getByLabel("全部日期", { exact: true })).toBeChecked();
  await page.goBack();
  await expect(page).toHaveURL(/\/accounts\/$/);
  await page.getByRole("button", { name: /已归档账户（1）/ }).click();
  const old = page.getByRole("link", { name: "查看合成旧账户的流水" });
  const other = await context.newPage();
  await other.goto((await old.getAttribute("href"))!);
  await expect(
    other.getByRole("combobox", { name: "账户筛选", exact: true }),
  ).toHaveValue("b");
  await expect(other.getByLabel("全部日期", { exact: true })).toBeChecked();
  await other.close();
  await page.getByRole("button", { name: "日常账本", exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "账户筛选", exact: true }),
  ).toHaveValue("");
  await expect(page.getByLabel("全部日期", { exact: true })).not.toBeChecked();
  await page
    .getByRole("combobox", { name: "账户筛选", exact: true })
    .selectOption("a");
  await expect.poll(() => latest.get("account_id")).toBe("a");
  await page
    .getByRole("combobox", { name: "账户筛选", exact: true })
    .selectOption("");
  await expect.poll(() => latest.has("account_id")).toBe(false);
});

test("账户流水包含投资真实扣款到账，投资行只读且可关闭", async ({ page }) => {
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
          id: "bank",
          name: "合成扣款卡",
          kind: "bank",
          balance_fen: "10000",
          opening_date: "2026-01-01",
          archived: false,
          revision: 1,
        },
        {
          id: "platform",
          name: "合成持仓平台",
          kind: "payment",
          balance_fen: "0",
          opening_date: "2026-01-01",
          archived: false,
          revision: 1,
        },
      ],
    }),
  );
  await page.route("**/api/v1/categories", (r) => r.fulfill({ json: [] }));
  let latest = new URLSearchParams();
  await page.route("**/api/v1/events?*", (r) => {
    latest = new URL(r.request().url()).searchParams;
    const items =
      latest.get("include_investments") === "true"
        ? ["buy", "sell", "void"].map((action, i) => ({
            id: `investment${i}`,
            kind: "investment",
            account_id: "platform",
            target_account_id: null,
            investment_cash_account_id: "bank",
            instrument_name: "合成基金",
            instrument_code: "000001",
            investment_action: action === "void" ? "buy" : action,
            cash_delta_fen: ["-10100", "4950", null][i],
            effective_date: "2026-01-10",
            category_id: null,
            original_event_id: null,
            amount_fen: "0",
            fee_fen: "0",
            note: "",
            status: action === "void" ? "void" : "active",
            revision: 1,
            covered_by_history: false,
          }))
        : [];
    return r.fulfill({ json: { items, total: items.length } });
  });
  await page.goto("/journal/?account_id=bank");
  const toggle = page.getByRole("checkbox", {
    name: "包含投资资金流水",
    exact: true,
  });
  await expect(toggle).toBeChecked();
  const rows = page.locator(".journal-panel tbody tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText("投资买入扣款");
  await expect(rows.nth(0)).toContainText("¥-101.00");
  await expect(rows.nth(0)).toContainText("合成扣款卡");
  await expect(rows.nth(0)).toContainText("持仓账户：合成持仓平台");
  await expect(rows.nth(0)).toContainText("合成基金");
  await expect(rows.nth(1)).toContainText("+¥49.50");
  await expect(rows.nth(2)).toContainText("已作废，未影响余额");
  await expect(rows.getByRole("button")).toHaveCount(0);
  await expect(rows.getByRole("link", { name: "投资管理" })).toHaveCount(3);
  await expect(
    page
      .getByRole("combobox", { name: "类型", exact: true })
      .locator('option[value="investment"]'),
  ).toHaveCount(0);
  await page
    .getByRole("combobox", { name: "类型筛选", exact: true })
    .selectOption("investment");
  await expect.poll(() => latest.get("kind")).toBe("investment");
  await toggle.uncheck();
  await expect(rows).toHaveCount(0);
  expect(latest.has("include_investments")).toBe(false);
  expect(latest.has("kind")).toBe(false);
  await expect(
    page.getByRole("combobox", { name: "类型筛选", exact: true }),
  ).toHaveValue("");
});
