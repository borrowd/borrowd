const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadColorScheme(initiallyDark = false) {
  let changeListener;
  const themeColor = {
    content: "",
    dataset: {
      colorSchemeLight: "#ffffff",
      colorSchemeDark: "#0b0907",
    },
  };
  const links = [
    {
      href: "",
      dataset: {
        colorSchemeLight: "/manifest.json?color_scheme=light&v=4",
        colorSchemeDark: "/manifest.json?color_scheme=dark&v=4",
      },
    },
    {
      href: "",
      dataset: {
        colorSchemeLight: "/static/icon-192.png?v=4",
        colorSchemeDark: "/static/icon-dark-192.png?v=4",
      },
    },
  ];
  const mediaQuery = {
    matches: initiallyDark,
    addEventListener: (type, listener) => {
      assert.equal(type, "change");
      changeListener = listener;
    },
  };
  const document = {
    querySelector: () => themeColor,
    querySelectorAll: () => links,
  };
  const window = { matchMedia: () => mediaQuery };
  const source = fs.readFileSync(path.join(__dirname, "color-scheme.js"), "utf8");

  vm.runInNewContext(source, { document, window });
  return {
    changeTo(dark) {
      mediaQuery.matches = dark;
      changeListener();
    },
    links,
    themeColor,
  };
}

test("applies the current display color scheme to browser metadata", () => {
  const { links, themeColor } = loadColorScheme(true);

  assert.equal(themeColor.content, "#0b0907");
  assert.equal(links[0].href, "/manifest.json?color_scheme=dark&v=4");
  assert.equal(links[1].href, "/static/icon-dark-192.png?v=4");
});

test("updates browser metadata when the display color scheme changes", () => {
  const { changeTo, links, themeColor } = loadColorScheme(false);

  assert.equal(themeColor.content, "#ffffff");
  assert.equal(links[0].href, "/manifest.json?color_scheme=light&v=4");
  assert.equal(links[1].href, "/static/icon-192.png?v=4");

  changeTo(true);

  assert.equal(themeColor.content, "#0b0907");
  assert.equal(links[0].href, "/manifest.json?color_scheme=dark&v=4");
  assert.equal(links[1].href, "/static/icon-dark-192.png?v=4");
});
