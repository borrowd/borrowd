(() => {
  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const themeColor = document.querySelector('meta[name="theme-color"]');
  const colorSchemeLinks = document.querySelectorAll(
    "link[data-color-scheme-light][data-color-scheme-dark]",
  );
  const capitalize = (value) => value[0].toUpperCase() + value.slice(1);

  const updateColorScheme = () => {
    const scheme = mediaQuery.matches ? "dark" : "light";
    if (themeColor) {
      themeColor.content = themeColor.dataset[`colorScheme${capitalize(scheme)}`];
    }

    colorSchemeLinks.forEach((link) => {
      link.href = link.dataset[`colorScheme${capitalize(scheme)}`];
    });
  };

  updateColorScheme();
  if (typeof mediaQuery.addEventListener === "function") {
    mediaQuery.addEventListener("change", updateColorScheme);
  } else {
    mediaQuery.addListener(updateColorScheme);
  }
})();
