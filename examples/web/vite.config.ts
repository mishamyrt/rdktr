import { defineConfig } from "vite";

import { serviceWorker } from "./vite-plugin-sw.ts";

export default defineConfig({
  plugins: [serviceWorker()],
  server: {
    fs: {
      // Add the name of the folder where your file lives
      allow: ['..', '../../bindings/js']
    }
  }
})
