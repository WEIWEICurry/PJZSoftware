import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: "http://127.0.0.1:8765",
    browserName: "chromium",
    channel: process.env.PLAYWRIGHT_CHANNEL,
    viewport: { width: 1440, height: 1080 },
  },
  webServer: {
    command: "uv run python scripts/e2e_server.py",
    cwd: "..",
    url: "http://127.0.0.1:8765/health",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
