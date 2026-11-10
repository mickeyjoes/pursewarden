import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the static build works from any path (GitHub Pages, a file server, IPFS).
export default defineConfig({ plugins: [react()], base: "./", build: { sourcemap: false } });
