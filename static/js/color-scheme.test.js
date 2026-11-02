const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadColorScheme(initiallyDark = false) {
  let changeListener;
  const manifestLink = {
    href: "",
    dataset: {
      colorSchemeLight: "/manifest.json?color_scheme=light&v=5",
      colorSchemeDark: "/manifest.json?color_scheme=dark&v=5",
    },
  };
  const mediaQuery = {
    matches: initiallyDark,
    addEventListener: (type, listener) => {
      assert.equal(type, "change");
      changeListener = listener;
    },
  };
  const document = {
    querySelector: () => manifestLink,
  };
  const window = { matchMedia: () => mediaQuery };
  const source = fs.readFileSync(path.join(__dirname, "color-scheme.js"), "utf8");

  vm.runInNewContext(source, { document, window });
  return {
    changeTo(dark) {
      mediaQuery.matches = dark;
      changeListener();
    },
    manifestLink,
  };
}

test("applies the current display color scheme to the manifest link", () => {
  const { manifestLink } = loadColorScheme(true);

  assert.equal(manifestLink.href, "/manifest.json?color_scheme=dark&v=5");
});

test("updates the manifest link when the display color scheme changes", () => {
  const { changeTo, manifestLink } = loadColorScheme(false);

  assert.equal(manifestLink.href, "/manifest.json?color_scheme=light&v=5");

  changeTo(true);

  assert.equal(manifestLink.href, "/manifest.json?color_scheme=dark&v=5");
});
