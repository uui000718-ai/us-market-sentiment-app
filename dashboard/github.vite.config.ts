import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  root: "github", base: "./", publicDir: "../public", plugins: [react()],
  css: { postcss: process.cwd() },
  build: { outDir: "../dist/github", emptyOutDir: true },
});
