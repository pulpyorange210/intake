import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// The e2e run starts its own API (replay extractor: recorded runs, no API key; CSV sheet; outbox for Slack)
// on a throwaway data directory, plus the Vite dev server pointed at it.
const root = path.resolve(here, "..");
export const DATA_DIR = path.join(here, "test-results", "e2e-data");
const venvPython = path.join(root, ".venv", "bin", "python");
const python = process.env.PYTHON ?? (existsSync(venvPython) ? venvPython : "python3");
const API_PORT = 8765;
const WEB_PORT = 5174;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://localhost:${WEB_PORT}`, viewport: { width: 1440, height: 900 }, trace: "retain-on-failure" },
  webServer: [
    {
      command: `rm -rf "${DATA_DIR}" && "${python}" -m uvicorn server.app:app --port ${API_PORT}`,
      cwd: root,
      env: { INTAKE_DATA_DIR: DATA_DIR, INTAKE_EXTRACTOR: "replay", SLACK_WEBHOOK_URL: "", GOOGLE_SERVICE_ACCOUNT_JSON: "",
             PYTHONWARNINGS: "ignore" },
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      env: { API_TARGET: `http://127.0.0.1:${API_PORT}` },
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
