import { defineConfig } from 'vite';
import { resolve } from 'path';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({mode}) => {
  /* I'm not sure whether this was a bug per se in vite or some
  special interplay between vite and django, but there doesn't
  seem to be a single value that can be used here that works for
  both vite dev and vite build.

  The issue seems to be the `url()` call used in the css to load in
  the font file. If set to "fonts", then dev works, but build can't
  find the target file. If set to "static/fonts" then build works,
  but oddly in dev, the path of the file is translated to
  "/static/static/fonts", which 404s.

  Hence, after much struggling and cursing, simply using the values
  here that work for each mode. */

  let fontspath = "";
  if (mode === "development") {
    fontspath = "fonts";
  }
  else {
    fontspath = "static/fonts";
  }

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
    ],
    resolve: {
      alias: {
        $fonts: resolve(fontspath),
      }
    }
  }
});
