import { test, expect } from "@playwright/test";

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
  await page.getByRole("button", { name: "日报表", exact: true }).click();
  if (Number(today.slice(8)) > 1)
    await expect(page.locator(".report-incomplete")).toContainText(
      "缺少分日数据",
    );
  else await expect(reportMetrics).toContainText("¥106.00");
  await page.getByRole("button", { name: "周报表", exact: true }).click();
  await expect(reportMetrics.locator(".metric").first()).toBeVisible();
  await page.getByRole("button", { name: "年报表", exact: true }).click();
  await expect(
    reportMetrics.locator(".metric").filter({ hasText: "净支出" }).first(),
  ).toContainText("¥106.00");
  await expect(page.locator(".trend-row")).toHaveCount(12);
  await page.getByRole("button", { name: "月报表", exact: true }).click();
  await expect(reportMetrics).toContainText("¥106.00");
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
