import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort = process.env.VOLUNDR_E2E_PORT ?? "8000";
const host = process.env.VOLUNDR_VITE_HOST ?? "127.0.0.1";
const port = Number(process.env.VOLUNDR_VITE_PORT ?? "5173");

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
    host,
    port,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${apiPort}`,
        configure(proxy) {
          proxy.on("proxyReq", (proxyRequest) => {
            proxyRequest.setHeader("X-Volundr-Internal-Actor", "volundr-single-user");
            proxyRequest.setHeader("X-Volundr-Actor-Id", "");
            proxyRequest.setHeader("Authorization", "");
            proxyRequest.setHeader("X-Volundr-Direct-Access", "");
          });
        },
      },
    }
  }
});
