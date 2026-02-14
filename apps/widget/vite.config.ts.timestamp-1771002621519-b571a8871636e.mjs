// vite.config.ts
import { defineConfig } from "file:///G:/fractics/agentbuilder/apps/widget/node_modules/vite/dist/node/index.js";
import react from "file:///G:/fractics/agentbuilder/apps/widget/node_modules/@vitejs/plugin-react/dist/index.js";
var vite_config_default = defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    strictPort: true,
    fs: {
      strict: false
    },
    watch: {
      usePolling: false
    }
  },
  optimizeDeps: {
    include: ["react", "react-dom"]
  }
});
export {
  vite_config_default as default
};

