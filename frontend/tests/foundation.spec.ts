import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import { isoWeekValue } from "../src/report-period";

test("本地连接、日常账务、幂等重试和备份恢复，页面无出站请求", async ({
  page,
}) => {
  const external: string[] = [];
  page.on("request", (request) => {
    if (!request.url().startsWith("http://127.0.0.1:8765"))
      external.push(request.url());
  });
  await page.goto("/#bootstrap=synthetic-browser-bootstrap");
  await expect(page.getByText("已连接本机服务")).toBeVisible();
  await expect(page).toHaveURL("http://127.0.0.1:8765/");
  await page.screenshot({ path: "test-results/overview.png", fullPage: true });
  await page.getByRole("button", { name: "数据管理", exact: true }).click();
  await page.getByLabel("账本名称").fill("Synthetic browser ledger");
  await page.getByRole("button", { name: "保存名称" }).click();
  await expect(page.getByRole("status")).toContainText("已保存");
  await page.reload();
  await page.getByRole("button", { name: "数据管理", exact: true }).click();
  await expect(page.getByLabel("账本名称")).toHaveValue(
    "Synthetic browser ledger",
  );
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载本地备份" }).click();
  const download = await downloadEvent;
  const backupPath = await download.path();
  expect(backupPath).toBeTruthy();
  await page.getByLabel("选择 .pjzbackup 备份").setInputFiles(backupPath!);
  await expect(page.getByText("备份验证通过")).toBeVisible();
  await page.getByRole("button", { name: "确认恢复到新目录" }).click();
  await expect(page.getByRole("status")).toContainText("恢复成功");
  await page.screenshot({ path: "test-results/data.png", fullPage: true });
  await page.getByRole("button", { name: "账户", exact: true }).click();
  await page.getByLabel("账户名称").fill("Synthetic bank");
  await page.getByLabel("期初余额（元）").fill("1000.00");
  // The server commits, but the browser loses the response. Retrying must not duplicate.
  let loseResponse = true;
  await page.route("**/api/v1/accounts", async (route) => {
    if (route.request().method() === "POST" && loseResponse) {
      loseResponse = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "添加账户", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "fetch" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "添加账户", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("账户已保存");
  await expect(
    page.getByRole("heading", { name: "Synthetic bank", exact: true }),
  ).toHaveCount(1);
  await page.unroute("**/api/v1/accounts");
  await page.getByLabel("账户名称").fill("Synthetic cash");
  await page.getByLabel("账户类型").selectOption("cash");
  await page.getByLabel("期初余额（元）").fill("0");
  await page.getByRole("button", { name: "添加账户", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Synthetic cash", exact: true }),
  ).toBeVisible();
  await page.getByLabel("账户名称").fill("Synthetic archived");
  await page.getByRole("button", { name: "添加账户", exact: true }).click();
  const archivedCard = page
    .locator(".account-card")
    .filter({ hasText: "Synthetic archived" });
  await expect(archivedCard).toBeVisible();
  await archivedCard
    .getByRole("button", { name: "归档账户", exact: true })
    .click();
  const archiveToggle = page.getByRole("button", { name: /已归档账户（1）/ });
  await expect(archiveToggle).toHaveAttribute("aria-expanded", "false");
  await expect(archivedCard).toBeHidden();
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.screenshot({
    path: "test-results/accounts-collapsed.png",
    fullPage: true,
  });
  await archiveToggle.focus();
  await page.keyboard.press("Enter");
  await expect(archiveToggle).toHaveAttribute("aria-expanded", "true");
  await expect(archivedCard).toBeVisible();
  await archiveToggle.click();
  await expect(archivedCard).toBeHidden();
  await archiveToggle.click();
  await archivedCard
    .getByRole("button", { name: "恢复账户", exact: true })
    .click();
  await expect(page.getByRole("button", { name: /已归档账户/ })).toHaveCount(0);
  await expect(archivedCard).toBeVisible();
  await archivedCard
    .getByRole("button", { name: "归档账户", exact: true })
    .click();
  await expect(archiveToggle).toHaveAttribute("aria-expanded", "false");
  await expect(archivedCard).toBeHidden();
  await archiveToggle.click();
  await page.reload();
  await page.getByRole("button", { name: "账户", exact: true }).click();
  await expect(archiveToggle).toHaveAttribute("aria-expanded", "false");
  await expect(archivedCard).toBeHidden();
  await archiveToggle.click();
  await archivedCard
    .getByRole("button", { name: "彻底删除", exact: true })
    .click();
  const deleteDialog = page.getByRole("dialog");
  await expect(deleteDialog).toContainText("1 条相关流水");
  await expect(
    deleteDialog.getByRole("button", { name: "确认彻底删除" }),
  ).toBeDisabled();
  await deleteDialog.getByLabel("输入账户名称以确认").fill("wrong name");
  await expect(
    deleteDialog.getByRole("button", { name: "确认彻底删除" }),
  ).toBeDisabled();
  await deleteDialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(deleteDialog).not.toBeVisible();
  await expect(archivedCard).toBeVisible();
  await archivedCard
    .getByRole("button", { name: "彻底删除", exact: true })
    .click();
  await deleteDialog
    .getByLabel("输入账户名称以确认")
    .fill("Synthetic archived");
  await page.screenshot({
    path: "test-results/delete-confirmation.png",
    fullPage: true,
  });
  let loseDeleteResponse = true;
  await page.route("**/api/v1/accounts/*/delete", async (route) => {
    if (loseDeleteResponse) {
      loseDeleteResponse = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await deleteDialog.getByRole("button", { name: "确认彻底删除" }).click();
  await expect(
    deleteDialog.getByRole("alert").filter({ hasText: "fetch" }),
  ).toBeVisible();
  await deleteDialog.getByRole("button", { name: "确认彻底删除" }).click();
  await expect(deleteDialog).not.toBeVisible();
  await expect(archivedCard).toHaveCount(0);
  await expect(page.getByRole("button", { name: /已归档账户/ })).toHaveCount(0);
  await expect(page.getByRole("status")).toContainText("已删除");
  await page.unroute("**/api/v1/accounts/*/delete");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "日常账本", exact: true }).click();
  await expect(page.getByLabel("金额（元）", { exact: true })).toBeVisible();
  expect(
    await page
      .getByLabel("金额（元）", { exact: true })
      .evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
  ).toBeGreaterThanOrEqual(16);

  await page.getByLabel("金额（元）", { exact: true }).fill("30.25");
  await page.getByLabel("备注", { exact: true }).fill("Synthetic expense");
  await page.getByRole("button", { name: "保存流水", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("流水已保存");
  const commonNotes = page.getByRole("group", {
    name: "常用备注",
    exact: true,
  });
  await expect(
    commonNotes.getByRole("button", { name: "Synthetic expense", exact: true }),
  ).toBeVisible();
  await page.getByLabel("金额（元）", { exact: true }).fill("1.00");
  await page.getByLabel("备注", { exact: true }).fill("manual draft");
  const rowsBeforeSuggestion = await page.locator("tbody tr").count();
  await commonNotes
    .getByRole("button", { name: "Synthetic expense", exact: true })
    .click();
  await expect(page.getByLabel("备注", { exact: true })).toHaveValue(
    "Synthetic expense",
  );
  await expect(page.locator("tbody tr")).toHaveCount(rowsBeforeSuggestion);

  await page
    .getByRole("combobox", { name: "类型", exact: true })
    .selectOption("income");
  await expect(
    commonNotes.getByRole("button", { name: "Synthetic expense", exact: true }),
  ).not.toBeVisible();
  await page.getByLabel("备注", { exact: true }).fill("Synthetic income");
  await page.getByLabel("金额（元）", { exact: true }).fill("200.00");
  await page.getByRole("button", { name: "保存流水", exact: true }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "¥200.00" }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "类型", exact: true })
    .selectOption("transfer");
  await page.getByLabel("转账本金（元）").fill("100");
  await page.getByLabel("转入账户").selectOption({ label: "Synthetic cash" });
  await page.getByLabel("手续费（元）").fill("1");
  await page.getByRole("button", { name: "保存流水", exact: true }).click();
  await expect(
    page.getByRole("row").filter({ hasText: "手续费 ¥1.00" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "总览", exact: true }).click();
  await expect(
    page.locator(".metric").filter({ hasText: "本月支出" }),
  ).toContainText("¥31.25");
  await expect(page.locator(".asset-strip")).toContainText("¥1,168.75");
  await page.screenshot({
    path: "test-results/daily-overview.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "日常账本", exact: true }).click();
  const expenseRow = page
    .getByRole("row")
    .filter({ hasText: "Synthetic expense" });
  await expenseRow.getByRole("button", { name: "退款", exact: true }).click();
  await page.getByLabel("金额（元）", { exact: true }).fill("10");
  await page.getByRole("button", { name: "保存流水", exact: true }).click();
  const refundRow = page
    .getByRole("row")
    .filter({ hasText: "退款" })
    .filter({ hasText: "¥10.00" });
  await expect(refundRow).toBeVisible();
  await expenseRow.getByRole("button", { name: "修改", exact: true }).click();
  await page.getByLabel("金额（元）", { exact: true }).fill("40.25");
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await expect(expenseRow).toContainText("¥40.25");
  await refundRow.getByRole("button", { name: "作废", exact: true }).click();
  await page.getByRole("button", { name: "确认作废", exact: true }).click();
  await expect(refundRow).toContainText("已作废");
  await page.reload();
  await page.getByRole("button", { name: "总览", exact: true }).click();
  await expect(
    page.locator(".metric").filter({ hasText: "本月支出" }),
  ).toContainText("¥41.25");
  await page.getByRole("button", { name: "日常账本", exact: true }).click();
  for (const width of [1280, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator("#entry-form")).toBeVisible();
    const form = await page.locator("#entry-form").boundingBox();
    expect(form!.height).toBeLessThan(360);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(
      await page
        .locator("tbody td")
        .first()
        .evaluate((el) => parseFloat(getComputedStyle(el).fontSize)),
    ).toBeGreaterThanOrEqual(15);
    await page.screenshot({
      path: "test-results/journal-" + width + ".png",
      fullPage: true,
    });
  }

  await page
    .getByRole("combobox", { name: "类型", exact: true })
    .selectOption("loan");
  await page.getByLabel("对方姓名").fill("Synthetic lender");
  await page.getByLabel("本金（元）").fill("1000");
  let loseLoanResponse = true;
  await page.route("**/api/v1/loans", async (route) => {
    if (route.request().method() === "POST" && loseLoanResponse) {
      loseLoanResponse = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "保存我借入", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "fetch" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "保存我借入", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("借还款已保存");
  await page.unroute("**/api/v1/loans");
  await page.getByRole("button", { name: "账户", exact: true }).click();
  const debtCard = page
    .locator(".account-card")
    .filter({ hasText: "Synthetic lender" });
  await expect(debtCard).toContainText("¥1,000.00");
  await debtCard.getByRole("button", { name: "还钱", exact: true }).click();
  await page.getByLabel("本金（元）").fill("300");
  await page.getByRole("button", { name: "保存我还钱", exact: true }).click();
  await expect(debtCard).toContainText("¥700.00");
  await page.getByRole("button", { name: "我借出", exact: true }).click();
  await page.getByLabel("对方姓名").fill("Synthetic borrower");
  await page.getByLabel("本金（元）").fill("500");
  await page.getByRole("button", { name: "保存我借出", exact: true }).click();
  const lentCard = page
    .locator(".account-card")
    .filter({ hasText: "Synthetic borrower" });
  await expect(lentCard).toContainText("¥500.00");
  await lentCard.getByRole("button", { name: "收回", exact: true }).click();
  await page.getByLabel("本金（元）").fill("501");
  await page.getByRole("button", { name: "保存收回借款", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "剩余本金" }),
  ).toBeVisible();
  await expect(lentCard).toContainText("¥500.00");
  await page.getByLabel("本金（元）").fill("200");
  await page.getByRole("button", { name: "保存收回借款", exact: true }).click();
  await expect(lentCard).toContainText("¥300.00");
  await page.screenshot({ path: "test-results/loans.png", fullPage: true });
  await lentCard.getByRole("button", { name: "收回", exact: true }).click();
  await page.getByLabel("本金（元）").fill("300");
  await page.getByRole("button", { name: "保存收回借款", exact: true }).click();
  await expect(lentCard).toBeHidden();
  await page.getByRole("button", { name: /已结清（1）/ }).click();
  await expect(lentCard).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "账户", exact: true }).click();
  await expect(lentCard).toBeHidden();
  await expect(debtCard).toContainText("¥700.00");

  await page.getByRole("button", { name: "日常账本", exact: true }).click();
  const lendingRow = page.getByRole("row").filter({ hasText: "我借出" });
  await lendingRow.getByRole("button", { name: "修改", exact: true }).click();
  await expect(page.getByLabel("本金（元）")).toHaveValue("500.00");
  await page.getByLabel("备注（选填）").fill("Synthetic edited lending");
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await expect(lendingRow).toContainText("Synthetic edited lending");

  await page.getByRole("button", { name: "数据管理", exact: true }).click();
  const history = page.getByRole("region", {
    name: "历史汇总导入",
    exact: true,
  });
  const today = await page.evaluate(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  });
  const source = {
    schema_version: 1,
    currency: "CNY",
    amount_unit: "fen",
    record_type: "monthly_category_expense_summary",
    periods: [
      {
        start_date: today.slice(0, 7) + "-01",
        end_date: today,
        displayed_total_fen: 10500,
        source_images: ["synthetic-browser-source.png"],
        categories: [
          { category: "餐饮", amount_fen: 10000 },
          { category: "Synthetic mapped", amount_fen: 500 },
        ],
      },
    ],
  };
  await page.getByLabel("选择历史汇总 JSON（最多 512 KB）").setInputFiles({
    name: "synthetic-history.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(source)),
  });
  await expect(history.getByText("待映射", { exact: true })).toBeVisible();
  await expect(
    history.getByRole("button", { name: "确认导入历史汇总", exact: true }),
  ).toBeDisabled();
  await history
    .getByRole("combobox", {
      name: "映射 Synthetic mapped expense",
      exact: true,
    })
    .selectOption({ label: "日用" });
  await history
    .getByRole("button", { name: "按当前分类重新预览", exact: true })
    .click();
  await expect(history.locator(".history-period-totals")).toContainText(
    "¥105.00",
  );
  await history.getByLabel("我已核对期间、金额及明细覆盖规则").check();
  let loseImportResponse = true;
  await page.route("**/api/v1/history/commit", async (route) => {
    if (loseImportResponse) {
      loseImportResponse = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await history
    .getByRole("button", { name: "确认导入历史汇总", exact: true })
    .click();
  await expect(
    history.getByRole("alert").filter({ hasText: "fetch" }),
  ).toBeVisible();
  await history
    .getByRole("button", { name: "确认导入历史汇总", exact: true })
    .click();
  await expect(history.getByRole("status")).toContainText("历史汇总已导入");
  await page.unroute("**/api/v1/history/commit");
  await expect(history.locator(".history-batch")).toHaveCount(1);
  await page.getByRole("button", { name: "总览", exact: true }).click();
  await expect(
    page.locator(".metric").filter({ hasText: "本月支出" }),
  ).toContainText("¥106.00");
  await expect(page.locator(".history-coverage")).toContainText("历史分类汇总");
  await page.getByRole("button", { name: "报表与预算", exact: true }).click();
  const reportMetrics = page.locator(".report-metrics");
  const budgetPanel = page.getByRole("region", {
    name: "可选分类预算",
    exact: true,
  });
  await expect(
    reportMetrics.locator(".metric").filter({ hasText: "净支出" }).first(),
  ).toContainText("¥106.00");
  await expect(budgetPanel.locator(".budget-card")).toHaveCount(0);
  await expect(budgetPanel.locator(".budget-numbers")).toHaveCount(0);
  await expect(page.getByLabel("选择月份", { exact: true })).toHaveAttribute(
    "type",
    "month",
  );
  await page.getByRole("button", { name: "日报表", exact: true }).click();
  await expect(page.getByLabel("选择日期", { exact: true })).toHaveAttribute(
    "type",
    "date",
  );
  if (Number(today.slice(8)) > 1)
    await expect(page.locator(".report-incomplete")).toContainText(
      "缺少分日数据",
    );
  else await expect(reportMetrics).toContainText("¥106.00");
  await expect(
    page.getByRole("region", { name: "收支趋势", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "周报表", exact: true }).click();
  await expect(page.getByLabel("选择周", { exact: true })).toHaveAttribute(
    "type",
    "week",
  );
  await page.getByLabel("选择周", { exact: true }).fill("2020-W53");
  await expect(page.locator(".report-range")).toContainText(
    "2020-12-28 ～ 2021-01-03",
  );
  await expect(page.locator(".trend-row")).toHaveCount(7);
  const firstWeekBar = await page.locator(".trend-row").nth(0).boundingBox();
  const secondWeekBar = await page.locator(".trend-row").nth(1).boundingBox();
  expect(secondWeekBar!.x).toBeGreaterThan(firstWeekBar!.x);
  expect(secondWeekBar!.y).toBe(firstWeekBar!.y);
  await page.getByLabel("选择周", { exact: true }).fill(isoWeekValue(today));
  await expect(reportMetrics.locator(".metric").first()).toBeVisible();
  await page.getByRole("button", { name: "年报表", exact: true }).click();
  await page.getByLabel("选择年份", { exact: true }).selectOption("2024");
  await expect(page.locator(".report-range")).toContainText(
    "2024-01-01 ～ 2024-12-31",
  );
  await expect(page.locator(".trend-row")).toHaveCount(12);
  await page.getByRole("button", { name: "返回当前年", exact: true }).click();
  await expect(
    reportMetrics.locator(".metric").filter({ hasText: "净支出" }).first(),
  ).toContainText("¥106.00");
  await expect(page.locator(".trend-row")).toHaveCount(12);
  await page.getByRole("button", { name: "月报表", exact: true }).click();
  await page.getByLabel("选择月份", { exact: true }).fill("2024-02");
  await expect(page.locator(".report-range")).toContainText(
    "2024-02-01 ～ 2024-02-29",
  );
  await expect(page.locator(".trend-row")).toHaveCount(29);
  await page.getByRole("button", { name: "返回当前月", exact: true }).click();
  await expect(reportMetrics).toContainText("¥106.00");
  const firstDay = page.locator(".trend-row").first();
  await firstDay.focus();
  await expect(firstDay).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".trend-detail")).toContainText(
    today.slice(0, 7) + "-01",
  );
  // Exercise below-zero rendering with synthetic chart samples.
  await page.route("**/api/v1/reports?*", async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    result.trend[0] = {
      ...result.trend[0],
      income_fen: "10000",
      expense_fen: "-30000",
      surplus_fen: "40000",
      status: "recorded",
    };
    await route.fulfill({ response, json: result });
  });
  await page.getByRole("button", { name: "刷新报表", exact: true }).click();
  const negativeBar = page.locator(".expense-bar.negative");
  await expect(negativeBar).toHaveCount(1);
  const negativeBox = await negativeBar.boundingBox();
  const plotBox = await page.locator(".trend-plot").boundingBox();
  const positiveBox = await page
    .locator(".income-bar.positive")
    .first()
    .boundingBox();
  expect(negativeBox!.y).toBeCloseTo(plotBox!.y + 100, 0);
  expect(positiveBox!.y + positiveBox!.height).toBeLessThanOrEqual(
    negativeBox!.y + 1,
  );
  await page.locator(".trend-row").first().focus();
  await expect(page.locator(".trend-detail")).toContainText("¥-300.00");
  await page.unroute("**/api/v1/reports?*");
  await page.getByRole("button", { name: "刷新报表", exact: true }).click();
  await expect(negativeBar).toHaveCount(0);
  const csvDownloadEvent = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "导出当前构成 CSV", exact: true })
    .click();
  const csvPath = await (await csvDownloadEvent).path();
  const csvContents = await (
    await import("node:fs/promises")
  ).readFile(csvPath!, "utf8");
  expect(csvContents).toContain("原金额（元）");
  expect(csvContents).toContain("历史汇总");
  await budgetPanel
    .getByRole("button", { name: "设置分类预算", exact: true })
    .click();
  await budgetPanel.getByLabel("月预算（元）").fill("50");
  let loseBudgetResponse = true;
  await page.route("**/api/v1/budgets/*/*", async (route) => {
    if (route.request().method() === "PUT" && loseBudgetResponse) {
      loseBudgetResponse = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await budgetPanel
    .getByRole("button", { name: "保存分类预算", exact: true })
    .click();
  await expect(
    budgetPanel.getByRole("alert").filter({ hasText: "fetch" }),
  ).toBeVisible();
  await budgetPanel
    .getByRole("button", { name: "保存分类预算", exact: true })
    .click();
  await page.unroute("**/api/v1/budgets/*/*");
  await expect(budgetPanel.locator(".budget-card")).toHaveCount(1);
  await expect(budgetPanel.locator(".budget-card")).toContainText("已超支");
  await budgetPanel
    .getByRole("button", { name: "刷新预算", exact: true })
    .click();
  await expect(budgetPanel.locator(".budget-numbers")).toContainText("¥100.00");
  await budgetPanel
    .getByRole("button", { name: "调整额度", exact: true })
    .click();
  await budgetPanel.getByLabel("月预算（元）").fill("200");
  await budgetPanel
    .getByRole("button", { name: "保存分类预算", exact: true })
    .click();
  await expect(budgetPanel.locator(".budget-card")).toContainText("剩余");
  await expect(budgetPanel.locator(".budget-card.over")).toHaveCount(0);
  await budgetPanel
    .getByRole("button", { name: "移除餐饮预算", exact: true })
    .click();
  await expect(budgetPanel.locator(".budget-card")).toHaveCount(0);
  await expect(budgetPanel.locator(".budget-numbers")).toHaveCount(0);
  await budgetPanel.getByLabel("月预算（元）").fill("200");
  await budgetPanel
    .getByRole("button", { name: "保存分类预算", exact: true })
    .click();
  await expect(budgetPanel.locator(".budget-card")).toHaveCount(1);
  const nextBudgetMonth = await page.evaluate(() => {
    const date = new Date();
    date.setDate(1);
    date.setMonth(date.getMonth() + 1);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  });
  await budgetPanel.getByLabel("预算月份").fill(nextBudgetMonth);
  await expect(budgetPanel.locator(".budget-empty")).toBeVisible();
  await budgetPanel
    .getByRole("button", { name: "沿用上月预算", exact: true })
    .click();
  await expect(budgetPanel.locator(".budget-card")).toContainText("计划中");
  await expect(budgetPanel.locator(".budget-numbers")).toHaveCount(0);
  await budgetPanel.getByLabel("预算月份").fill(today.slice(0, 7));
  await expect(budgetPanel.locator(".budget-card")).toContainText("¥200.00");
  for (const width of [1440, 900]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    if (width === 900) {
      const scroll = page.locator(".trend-scroller");
      expect(
        await scroll.evaluate((el) => el.scrollWidth > el.clientWidth),
      ).toBe(true);
      await page.locator(".trend-row").last().focus();
      expect(await scroll.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({
    path: "test-results/reports-and-budgets.png",
    fullPage: true,
  });
  await page.reload();
  await page.getByRole("button", { name: "报表与预算", exact: true }).click();
  await expect(budgetPanel.locator(".budget-card")).toContainText("¥200.00");
  await page.getByRole("button", { name: "日常账本", exact: true }).click();
  await expect(page.getByText(/历史汇总已覆盖统计/)).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "数据管理", exact: true }).click();
  await history.getByRole("button", { name: "查看明细", exact: true }).click();
  await expect(history.locator(".history-detail")).toContainText(
    "synthetic-browser-source.png",
  );
  await page.screenshot({
    path: "test-results/history-import.png",
    fullPage: true,
  });
  source.periods[0].categories.reverse();
  await page.getByLabel("选择历史汇总 JSON（最多 512 KB）").setInputFiles({
    name: "renamed-history.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(source, null, 2)),
  });
  await expect(history.getByText("重复，已导入", { exact: true })).toHaveCount(
    2,
  );
  await expect(
    history.getByRole("button", { name: "确认导入历史汇总", exact: true }),
  ).toBeDisabled();
  await history.getByRole("button", { name: "取消预览", exact: true }).click();
  await history.getByRole("button", { name: "预览撤销", exact: true }).click();
  await expect(
    history.getByRole("heading", { name: /撤销影响预览/ }),
  ).toBeVisible();
  await history.getByLabel("我已核对期间、金额及明细覆盖规则").check();
  await history
    .getByRole("button", { name: "确认撤销此批次", exact: true })
    .click();
  await expect(history.getByRole("status")).toContainText("批次已撤销");
  await page.getByRole("button", { name: "总览", exact: true }).click();
  await expect(
    page.locator(".metric").filter({ hasText: "本月支出" }),
  ).toContainText("¥41.25");

  // M3.1: real browser entry, lost response, exact cost, valuations and historical rollback.
  await page.getByRole("button", { name: "账户", exact: true }).click();
  await page.getByLabel("账户名称").fill("Synthetic investment cash");
  await page.getByLabel("账户类型").selectOption("securities");
  await page.getByLabel("期初余额（元）").fill("10000");
  await page.getByRole("button", { name: "添加账户", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Synthetic investment cash",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "投资", exact: true }).click();
  const investmentAccountFilter = page
    .locator(".investment-filters")
    .getByRole("combobox", { name: "账户筛选", exact: true });
  await expect(
    investmentAccountFilter
      .locator("option")
      .filter({ hasText: "Synthetic investment cash" }),
  ).toHaveCount(1);
  await expect(
    investmentAccountFilter
      .locator("option")
      .filter({ hasText: /我欠|欠我|Synthetic borrower/ }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "投资记录", exact: true }).click();
  await expect(
    investmentAccountFilter
      .locator("option")
      .filter({ hasText: /我欠|欠我|Synthetic borrower/ }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "标的与估值", exact: true }).click();
  await page.getByLabel("六位代码").fill("600001");
  await page.getByLabel("标的名称").fill("Synthetic stock");
  await page.getByRole("button", { name: "添加标的", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("投资标的已添加");
  await page.getByRole("button", { name: "记一笔投资", exact: true }).click();
  const investmentForm = page.getByRole("region", { name: "投资记录表单" });
  await investmentForm
    .getByLabel("资金账户")
    .selectOption({ label: "Synthetic investment cash · ¥10,000.00" });
  await investmentForm
    .getByLabel("投资标的")
    .selectOption({ label: "Synthetic stock · 600001" });
  await investmentForm.getByLabel("数量（份／股）").fill("100");
  await investmentForm
    .getByLabel("成交金额（元）", { exact: true })
    .fill("1000");
  await investmentForm.getByText("费用（选填）", { exact: true }).click();
  await investmentForm.getByLabel("费用合计（元）").fill("5");
  await expect(investmentForm).toContainText("本次扣款 ¥1,005.00");
  let loseInvestment = true;
  await page.route("**/api/v1/investments/trades", async (route) => {
    if (route.request().method() === "POST" && loseInvestment) {
      loseInvestment = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await investmentForm.getByRole("button", { name: "保存投资记录" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "fetch" }),
  ).toBeVisible();
  await investmentForm.getByRole("button", { name: "保存投资记录" }).click();
  await expect(page.getByRole("status")).toContainText("投资记录已保存");
  await page.unroute("**/api/v1/investments/trades");
  async function investmentTrade(
    action: string,
    quantity: string,
    value: string,
    fee: string,
    mode = "gross",
  ) {
    await page.getByRole("button", { name: "记一笔投资", exact: true }).click();
    await investmentForm
      .getByRole("combobox", { name: "操作", exact: true })
      .selectOption(action);
    await investmentForm
      .getByLabel("资金账户")
      .selectOption(
        (await investmentForm
          .getByLabel("资金账户")
          .locator("option")
          .filter({ hasText: "Synthetic investment cash" })
          .getAttribute("value")) as string,
      );
    await investmentForm
      .getByLabel("投资标的")
      .selectOption({ label: "Synthetic stock · 600001" });
    await investmentForm.getByLabel("数量（份／股）").fill(quantity);
    await investmentForm.getByLabel("金额口径").selectOption(mode);
    await investmentForm
      .getByLabel(mode === "gross" ? "成交金额（元）" : "实际到账（元）", {
        exact: true,
      })
      .fill(value);
    await investmentForm.getByText("费用（选填）", { exact: true }).click();
    await investmentForm.getByLabel("费用合计（元）").fill(fee);
    await investmentForm.getByRole("button", { name: "保存投资记录" }).click();
    await expect(page.getByRole("status")).toContainText("投资记录已保存");
  }
  await investmentTrade("buy", "100", "1200", "5");
  await investmentTrade("sell", "50", "648", "2", "net");
  const stockPrice = page
    .locator(".investment-price-row")
    .filter({ hasText: "Synthetic stock" });
  await stockPrice.getByLabel("Synthetic stock价格").fill("13");
  await stockPrice
    .getByRole("button", { name: "保存价格", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("手动价格已保存");
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  const holdingRow = page
    .locator(".investment-table tbody tr")
    .filter({ hasText: "Synthetic stock" });
  await expect(holdingRow).toHaveCount(1);
  await expect(holdingRow).toContainText("150");
  await expect(holdingRow).toContainText("¥1,657.50");
  await expect(holdingRow).toContainText("¥1,950.00");
  await expect(holdingRow).toContainText("¥292.50");
  await expect(
    page.locator(".metric").filter({ hasText: "累计投资盈亏" }),
  ).toContainText("¥388.00");
  await page.screenshot({
    path: "test-results/investments.png",
    fullPage: true,
  });
  await holdingRow.getByRole("button", { name: "查看明细" }).click();
  await expect(page.locator(".investment-table tbody tr")).toHaveCount(3);
  const firstBuy = page
    .locator(".investment-table tbody tr")
    .filter({ hasText: "¥1,000.00" });
  await firstBuy.getByRole("button", { name: "修改", exact: true }).click();
  await investmentForm.getByLabel("数量（份／股）").fill("10");
  // The other 100 shares still cover a 50 share sale, so use zero whole shares to test validation.
  await investmentForm.getByLabel("数量（份／股）").fill("0");
  await investmentForm.getByRole("button", { name: "保存投资记录" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: /份额|填写内容/ }),
  ).toBeVisible();
  await investmentForm.getByRole("button", { name: "取消编辑" }).click();
  await page.getByRole("button", { name: "标的与估值", exact: true }).click();
  await stockPrice.getByRole("button", { name: "作废该日价格" }).click();
  await expect(page.getByRole("status")).toContainText("价格已作废");
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  await expect(holdingRow).toContainText("待估值");
  await page.reload();
  await page.getByRole("button", { name: "投资", exact: true }).click();
  await expect(holdingRow).toContainText("¥1,657.50");
  await page.getByRole("button", { name: "标的与估值", exact: true }).click();
  await stockPrice.getByLabel("Synthetic stock价格").fill("13");
  await stockPrice
    .getByRole("button", { name: "保存价格", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("手动价格已保存");
  await page.getByRole("button", { name: "总览", exact: true }).click();
  await expect(page.locator(".investment-assets")).toContainText("¥1,950.00");
  // M3.2 uses only synthetic fund data; every distribution stays outside daily income.
  await page.getByRole("button", { name: "投资", exact: true }).click();
  await page.getByRole("button", { name: "标的与估值", exact: true }).click();
  await page.getByLabel("标的类型").selectOption("fund");
  await page.getByLabel("六位代码").fill("000001");
  await page.getByLabel("标的名称").fill("Synthetic distribution fund");
  await page.getByRole("button", { name: "添加标的", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("投资标的已添加");
  async function beginFundEvent(action: string) {
    await page.getByRole("button", { name: "记一笔投资", exact: true }).click();
    await investmentForm
      .getByRole("combobox", { name: "操作", exact: true })
      .selectOption(action);
    await investmentForm
      .getByRole("combobox", { name: "资金账户", exact: true })
      .selectOption(
        (await investmentForm
          .getByRole("combobox", { name: "资金账户", exact: true })
          .locator("option")
          .filter({ hasText: "Synthetic investment cash" })
          .getAttribute("value")) as string,
      );
    await investmentForm
      .getByLabel("投资标的")
      .selectOption({ label: "Synthetic distribution fund · 000001" });
  }
  async function saveFundEvent() {
    await investmentForm.getByRole("button", { name: "保存投资记录" }).click();
    await expect(page.getByRole("status")).toContainText("投资记录已保存");
  }
  await beginFundEvent("opening");
  await investmentForm.getByLabel("数量（份／股）").fill("1000");
  await investmentForm.getByLabel("剩余总成本（元，选填）").fill("2100");
  await saveFundEvent();
  const fundPrice = page
    .locator(".investment-price-row")
    .filter({ hasText: "Synthetic distribution fund" });
  const previousPriceDay = await page.evaluate(() => {
    const day = new Date();
    day.setDate(day.getDate() - 1);
    return [
      day.getFullYear(),
      String(day.getMonth() + 1).padStart(2, "0"),
      String(day.getDate()).padStart(2, "0"),
    ].join("-");
  });
  await page.getByLabel("价格／净值日期").fill(previousPriceDay);
  await fundPrice.getByLabel("Synthetic distribution fund价格").fill("2.1");
  await fundPrice
    .getByRole("button", { name: "保存价格", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("手动价格已保存");
  await beginFundEvent("cash_dividend");
  await investmentForm.getByLabel("实际净到账（元）").fill("100");
  await expect(investmentForm.getByLabel("数量（份／股）")).toHaveCount(0);
  let loseDividend = true;
  await page.route("**/api/v1/investments/trades", async (route) => {
    if (
      route.request().method() === "POST" &&
      route.request().postDataJSON().action === "cash_dividend" &&
      loseDividend
    ) {
      loseDividend = false;
      await route.fetch();
      await route.abort("failed");
    } else await route.continue();
  });
  await investmentForm.getByRole("button", { name: "保存投资记录" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "fetch" }),
  ).toBeVisible();
  await saveFundEvent();
  await page.unroute("**/api/v1/investments/trades");
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  const fundHolding = page
    .locator(".investment-table tbody tr")
    .filter({ hasText: "Synthetic distribution fund" });
  await expect(fundHolding).toContainText("事件后待更新");
  await expect(fundHolding).toContainText("待估值");
  async function updateFundPrice(value: string) {
    await page.getByRole("button", { name: "标的与估值", exact: true }).click();
    await page.getByLabel("价格／净值日期").fill(today);
    await fundPrice.getByLabel("Synthetic distribution fund价格").fill(value);
    await fundPrice
      .getByRole("button", { name: "保存价格", exact: true })
      .click();
    await expect(page.getByRole("status")).toContainText("手动价格已保存");
    await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  }
  await updateFundPrice("2");
  await expect(fundHolding).toContainText("¥2,000.00");
  await expect(
    page.locator(".metric").filter({ hasText: "累计投资盈亏" }),
  ).toContainText("¥388.00");
  await fundHolding.getByRole("button", { name: "查看明细" }).click();
  const dividendRow = page
    .locator(".investment-table tbody tr")
    .filter({ hasText: "现金分红" });
  await expect(dividendRow).toHaveCount(1);
  await dividendRow.getByRole("button", { name: "作废", exact: true }).click();
  await page.getByRole("button", { name: "确认作废投资", exact: true }).click();
  await expect(dividendRow).toContainText("已作废");
  await beginFundEvent("reinvest");
  await investmentForm.getByLabel("新增份额（份）").fill("50");
  await investmentForm.getByLabel("再投分红金额（元）").fill("100");
  await investmentForm.getByText("费用（选填）", { exact: true }).click();
  await investmentForm.getByLabel("另付费用（元）").fill("2");
  await saveFundEvent();
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  await expect(fundHolding).toContainText("1050");
  await expect(fundHolding).toContainText("¥2,202.00");
  await expect(fundHolding).toContainText("事件后待更新");
  await updateFundPrice("2");
  await expect(
    page.locator(".metric").filter({ hasText: "累计投资盈亏" }),
  ).toContainText("¥386.00");
  await fundHolding.getByRole("button", { name: "查看明细" }).click();
  const reinvestRow = page
    .locator(".investment-table tbody tr")
    .filter({ hasText: "基金分红再投" });
  await reinvestRow.getByRole("button", { name: "修改", exact: true }).click();
  await expect(investmentForm.getByLabel("新增份额（份）")).toHaveValue("50");
  await investmentForm
    .getByLabel("备注", { exact: true })
    .fill("Synthetic confirmed reinvestment");
  await saveFundEvent();
  await expect(reinvestRow).toContainText("Synthetic confirmed reinvestment");
  await beginFundEvent("split");
  await expect(investmentForm.getByLabel("折算前份额（份／股）")).toHaveValue(
    "1050",
  );
  await investmentForm.getByLabel("折算后份额（份／股）").fill("2100");
  await investmentForm
    .getByLabel("折算依据（必填）")
    .fill("Synthetic confirmed 2:1 split");
  await saveFundEvent();
  await page.getByRole("button", { name: "我的持仓", exact: true }).click();
  await expect(fundHolding).toContainText("2100");
  await expect(fundHolding).toContainText("事件后待更新");
  await updateFundPrice("1");
  await expect(fundHolding).toContainText("¥2,100.00");
  await expect(fundHolding).toContainText("¥2,202.00");
  await expect(
    page.locator(".metric").filter({ hasText: "累计投资盈亏" }),
  ).toContainText("¥386.00");
  await page.screenshot({
    path: "test-results/investment-distributions.png",
    fullPage: true,
  });
  await fundHolding.getByRole("button", { name: "查看明细" }).click();
  await expect(
    page.locator(".investment-table tbody tr").filter({ hasText: "份额折算" }),
  ).toContainText("1050 → 2100");
  await reinvestRow.getByRole("button", { name: "作废", exact: true }).click();
  await page.getByRole("button", { name: "确认作废投资", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "折算前份额" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "取消作废", exact: true }).click();
  // NAV requests are simulated; the browser never calls an external provider.
  await page.getByRole("button", { name: "标的与估值", exact: true }).click();
  const navPanel = page.getByRole("region", { name: "联网基金净值" });
  await expect(navPanel.getByRole("checkbox")).not.toBeChecked();
  await page.route("**/api/v1/fund-nav/preview", (route) =>
    route.fulfill({
      json: {
        token: "synthetic-preview",
        source: "Synthetic source",
        fetched_at: "2026-01-01T00:00:00Z",
        rows: [{ price_date: "2026-01-20", price: "1.2345", exists: false }],
      },
    }),
  );
  await page.route("**/api/v1/fund-nav/import", (route) =>
    route.fulfill({ json: { imported: 1, skipped: 0 } }),
  );
  await navPanel.getByRole("checkbox").check();
  await navPanel
    .getByLabel("查询基金")
    .selectOption({ label: "Synthetic distribution fund · 000001" });
  await navPanel.getByRole("button", { name: "获取净值预览" }).click();
  await expect(navPanel.getByRole("table")).toContainText("1.2345");
  await navPanel.getByRole("button", { name: "确认导入净值" }).click();
  await expect(navPanel).toContainText("已导入 1 条");
  await navPanel.getByRole("checkbox").uncheck();
  // M3.3: actual investment reports and allocation are read-only, with four scoped CSVs.
  await page.getByRole("button", { name: "投资报表", exact: true }).click();
  const performance = page.getByRole("region", {
    name: "期间总盈亏与边界持仓",
  });
  await expect(
    performance.getByRole("heading", { name: "期间总盈亏" }),
  ).toBeVisible();
  await expect(performance).toContainText("期初持仓记录");
  await expect(performance).toContainText("期末持仓");

  const investmentReports = page.locator(".investment-report-page");
  await expect(
    investmentReports.locator(".metric").filter({ hasText: "买入实际扣款" }),
  ).toContainText("¥2,210.00");
  await expect(
    investmentReports.locator(".metric").filter({ hasText: "卖出净到账" }),
  ).toContainText("¥648.00");
  await expect(
    investmentReports.locator(".metric").filter({ hasText: "已实现卖出盈亏" }),
  ).toContainText("¥95.50");
  await expect(
    investmentReports.locator(".metric").filter({ hasText: "再投净分红" }),
  ).toContainText("¥100.00");
  await expect(
    investmentReports.locator(".metric").filter({ hasText: "已计入费用" }),
  ).toContainText("¥14.00");
  await expect(
    investmentReports
      .getByRole("table", { name: "投资事件明细", exact: true })
      .locator("tbody tr"),
  ).toHaveCount(6);
  await investmentReports.getByLabel("包含作废记录").check();
  await expect(
    investmentReports
      .getByRole("table", { name: "投资事件明细", exact: true })
      .locator("tbody tr"),
  ).toHaveCount(7);
  const allocation = investmentReports.getByRole("region", {
    name: "当前资产配置",
    exact: true,
  });
  await expect(allocation).toContainText("不是所选期间的期末快照");
  await allocation.getByRole("button", { name: "按账户", exact: true }).click();
  await expect(allocation.getByRole("table").locator("tbody tr")).toHaveCount(
    1,
  );
  await expect(allocation.getByRole("table")).toContainText("¥4,050.00");
  await allocation.getByRole("button", { name: "按类型", exact: true }).click();
  await expect(allocation.getByRole("table").locator("tbody tr")).toHaveCount(
    2,
  );
  await investmentReports
    .getByRole("button", { name: "年报", exact: true })
    .click();
  await investmentReports.getByLabel("选择年份").selectOption("2025");
  await expect(
    investmentReports.locator(".metric").filter({ hasText: "买入实际扣款" }),
  ).toContainText("¥0.00");
  await expect(allocation).toContainText("¥4,050.00");
  await investmentReports
    .getByRole("button", { name: "自选期间", exact: true })
    .click();
  await investmentReports.getByLabel("开始日期", { exact: true }).fill(today);
  await investmentReports.getByLabel("结束日期", { exact: true }).fill(today);
  await expect(
    investmentReports.locator(".metric").filter({ hasText: "买入实际扣款" }),
  ).toContainText("¥2,210.00");
  await expect(
    investmentReports
      .getByRole("combobox", { name: "持仓账户筛选", exact: true })
      .locator("option")
      .filter({ hasText: /欠我|我欠|Synthetic borrower/ }),
  ).toHaveCount(0);
  await investmentReports
    .getByRole("combobox", { name: "投资标的筛选", exact: true })
    .selectOption({ label: "Synthetic distribution fund · 000001" });
  await expect(
    investmentReports.locator(".metric").filter({ hasText: "已计入费用" }),
  ).toContainText("¥2.00");
  await expect(allocation.getByRole("table")).toContainText("51.85%");
  await investmentReports
    .getByRole("combobox", { name: "投资标的筛选", exact: true })
    .selectOption({ label: "Synthetic stock · 600001" });
  await expect(
    performance.locator(".metric").filter({ hasText: "期间总盈亏" }),
  ).toContainText("¥388.00");
  await expect(
    performance.getByRole("table", { name: "期末边界持仓" }),
  ).toContainText("150");
  await investmentReports
    .getByRole("combobox", { name: "投资标的筛选", exact: true })
    .selectOption({ label: "Synthetic distribution fund · 000001" });
  for (const label of [
    "期间报表 CSV",
    "投资记录 CSV",
    "当前持仓 CSV",
    "手动估值 CSV（含作废）",
  ]) {
    const downloaded = page.waitForEvent("download");
    await investmentReports
      .getByRole("button", { name: label, exact: true })
      .click();
    const file = await (await downloaded).path();
    const bytes = await readFile(file!);
    expect(bytes.subarray(0, 3)).toEqual(Buffer.from([0xef, 0xbb, 0xbf]));
    expect(bytes.toString("utf8")).toContain("账本版本");
    expect(bytes.toString("utf8")).toContain("000001");
  }
  await page.screenshot({
    path: "test-results/investment-reports.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "数据管理", exact: true }).click();
  const businessDownloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载本地备份" }).click();
  const businessBackup = await (await businessDownloadEvent).path();
  await page.getByLabel("选择 .pjzbackup 备份").setInputFiles(businessBackup!);
  await expect(page.getByText("备份验证通过")).toBeVisible();
  await page.getByRole("button", { name: "确认恢复到新目录" }).click();
  await expect(page.getByRole("status")).toContainText("恢复成功");
  expect(external).toEqual([]);
  await page.context().clearCookies();
  await page.reload();
  await expect(
    page.getByRole("alert").filter({ hasText: "会话未连接" }),
  ).toContainText("会话未连接");
});
