import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort = process.env.VOLUNDR_E2E_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 650,
    rollupOptions: {
      output: {
        manualChunks: {
          monaco: ["@monaco-editor/react"],
          three: ["three", "three/examples/jsm/loaders/STLLoader.js"]
        }
      }
    }
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": `http://localhost:${apiPort}`
    }
  }
});
