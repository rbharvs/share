import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vitest/config";

// Unit tests cover the pure upload/source-type/API logic (no DOM needed), so a
// node environment is sufficient; component rendering is covered by typecheck +
// production build per the project's frontend-v1 testing policy.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
