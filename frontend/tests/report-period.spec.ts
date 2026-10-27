import { test, expect } from "@playwright/test";
import { isoWeekValue, weekMonday } from "../src/report-period";

test("周选择遵守跨年 ISO 周和第 53 周规则", () => {
  expect(isoWeekValue("2021-01-01")).toBe("2020-W53");
  expect(isoWeekValue("2021-01-04")).toBe("2021-W01");
  expect(isoWeekValue("2026-10-27")).toBe("2026-W44");
  expect(weekMonday("2020-W53")).toBe("2020-12-28");
  expect(weekMonday("2026-W44")).toBe("2026-10-26");
  expect(weekMonday("2025-W01")).toBe("2024-12-30");
  expect(weekMonday("2021-W53")).toBeNull();
  expect(weekMonday("2026-W00")).toBeNull();
  expect(weekMonday("2026-W54")).toBeNull();
  expect(weekMonday("2026-10-27")).toBeNull();
});
