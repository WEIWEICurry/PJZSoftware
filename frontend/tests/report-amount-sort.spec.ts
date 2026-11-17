import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";

test("收支构成金额表头切换、分页归零、筛选保留与导出顺序参数", async ({
  page,
}) => {
  await page.route("**/api/v1/session", (r) =>
    r.fulfill({ json: { csrf_token: "synthetic" } }),
  );
  await page.route("**/api/v1/ledger", (r) =>
    r.fulfill({ json: { name: "Synthetic", revision: 1 } }),
  );
  const categories = [
    {
      category_id: "dining",
      category_name: "合成餐饮",
      direction: "expense",
      amount_fen: "21000",
      known_fen: "21000",
      historical_fen: "0",
      detail_fen: "21000",
      share_bps: 10000,
    },
    {
      category_id: "salary",
      category_name: "合成工资",
      direction: "income",
      amount_fen: "30000",
      known_fen: "30000",
      historical_fen: "0",
      detail_fen: "30000",
      share_bps: 10000,
    },
  ];
  await page.route("**/api/v1/reports?*", (r) =>
    r.fulfill({
      json: {
        period: "month",
        calendar_end: "2026-01-31",
        current: {
          start: "2026-01-01",
          end: "2026-01-31",
          income_fen: "30000",
          expense_fen: "21000",
          surplus_fen: "9000",
          known_income_fen: "30000",
          known_expense_fen: "21000",
          daily_expense_fen: "677",
          day_count: 31,
          covered_count: 0,
          detail_count: 21,
          historical_count: 0,
          categories,
        },
        previous: null,
        changes: [],
        trend: [],
        history_ranges: [],
      },
    }),
  );
  await page.route("**/api/v1/budgets/*", (r) =>
    r.fulfill({
      json: {
        month: "2026-01",
        ledger_revision: 1,
        as_of: "2026-01-31",
        items: [],
      },
    }),
  );
  let latest = new URLSearchParams();
  await page.route("**/api/v1/reports/entries?*", (r) => {
    latest = new URL(r.request().url()).searchParams;
    const offset = Number(latest.get("offset"));
    const ascending = latest.get("sort_order") === "asc";
    return r.fulfill({
      json: {
        total: 21,
        items: Array.from({ length: offset ? 1 : 20 }, (_, i) => ({
          id: String(offset + i),
          start: "2026-01-10",
          end: "2026-01-10",
          direction: "expense",
          category_id: "dining",
          category_name: "合成餐饮",
          account_name: "合成账户",
          note: `合成记录${offset + i}`,
          source: "逐笔流水",
          amount_fen: ascending ? "100" : "2100",
          counted_fen: ascending ? "100" : "2100",
          status: "included",
        })),
      },
    });
  });
  let exported = new URLSearchParams();
  await page.route("**/api/v1/reports/export?*", (r) => {
    exported = new URL(r.request().url()).searchParams;
    return r.fulfill({ contentType: "text/csv", body: "合成导出" });
  });
  await page.goto("/reports/");
  const section = page.getByRole("region", { name: "报表构成明细" });
  const rows = section.locator("tbody tr");
  await expect(rows).toHaveCount(20);
  const original = section.getByRole("button", { name: "原金额", exact: true });
  const counted = section.getByRole("button", {
    name: "计入金额",
    exact: true,
  });
  await original.click();
  await expect.poll(() => latest.get("sort_order")).toBe("desc");
  expect(latest.get("sort_by")).toBe("amount_fen");
  await expect(
    section.getByRole("columnheader", { name: "原金额", exact: true }),
  ).toHaveAttribute("aria-sort", "descending");
  await section.getByRole("button", { name: "明细下一页" }).click();
  await expect(rows).toHaveCount(1);
  expect(latest.get("offset")).toBe("20");
  expect(latest.get("sort_order")).toBe("desc");
  await original.focus();
  await page.keyboard.press("Enter");
  await expect(rows).toHaveCount(20);
  await expect(rows.first().locator("td").nth(3)).toHaveText("¥1.00");
  expect(latest.get("offset")).toBe("0");
  expect(latest.get("sort_order")).toBe("asc");
  await expect(
    section.getByRole("columnheader", { name: "原金额", exact: true }),
  ).toHaveAttribute("aria-sort", "ascending");
  await counted.click();
  await expect.poll(() => latest.get("sort_by")).toBe("counted_fen");
  expect(latest.get("sort_order")).toBe("desc");
  await section.getByLabel("构成方向").selectOption("expense");
  await section.getByLabel("构成分类").selectOption("dining");
  await expect.poll(() => latest.get("category_id")).toBe("dining");
  expect(latest.get("direction")).toBe("expense");
  expect(latest.get("sort_order")).toBe("desc");
  await counted.focus();
  await page.keyboard.press("Space");
  await expect.poll(() => latest.get("sort_order")).toBe("asc");
  const download = page.waitForEvent("download");
  await section.getByRole("button", { name: "导出当前构成 CSV" }).click();
  const file = await (await download).path();
  expect(await readFile(file!, "utf8")).toBe("合成导出");
  for (const key of [
    "period",
    "anchor",
    "category_id",
    "direction",
    "sort_by",
    "sort_order",
  ]) {
    expect(exported.get(key)).toBe(latest.get(key));
  }
  await expect(
    section.getByRole("columnheader", { name: "计入金额", exact: true }),
  ).toHaveAttribute("aria-sort", "ascending");
  await page.screenshot({
    path: "test-results/report-amount-sort.png",
    fullPage: true,
  });
});
