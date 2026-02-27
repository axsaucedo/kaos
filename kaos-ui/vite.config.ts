import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  // Base path for GitHub Pages deployment
  // In production: use VITE_BASE env var (e.g., /kaos-ui/dev/, /kaos-ui/v1.0.0/)
  // Falls back to /kaos-ui/ for backward compatibility
  base: mode === "production" 
    ? (process.env.VITE_BASE || "/kaos-ui/") 
    : "/",
  server: {
    host: "::",
    port: 8080,
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
}));
