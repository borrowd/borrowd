import { defineConfig } from 'vite';
import { resolve } from 'path';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({mode}) => {
  return {
    base: "/static/",
    build: {
      manifest: "manifest.json",
      outDir: resolve("./build"),
      assetsDir: "",
      rollupOptions: {
        input: {
          main: resolve("./static/js/main.js"),
        }
      }
    },
    cacheDir: resolve("./node_modules/.vite"),
    plugins: [
      tailwindcss(),
    ]
  }
});
