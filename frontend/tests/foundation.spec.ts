import { test, expect } from "@playwright/test";

test("本地连接、刷新、名称持久化和备份恢复，页面无出站请求", async ({
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
  expect(external).toEqual([]);
  await page.context().clearCookies();
  await page.reload();
  await expect(
    page.getByRole("alert").filter({ hasText: "会话未连接" }),
  ).toContainText("会话未连接");
});
