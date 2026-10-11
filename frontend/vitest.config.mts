import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// A fixed non-UTC timezone, so tests can prove that days are split by local time.
process.env.TZ = "Asia/Kolkata";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
