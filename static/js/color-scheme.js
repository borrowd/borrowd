(() => {
  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const manifestLink = document.querySelector("link[rel='manifest']");
  const updateManifest = () => {
    if (!manifestLink) return;
    const scheme = mediaQuery.matches ? "dark" : "light";
    const dataKey = `colorScheme${scheme[0].toUpperCase()}${scheme.slice(1)}`;
    manifestLink.href = manifestLink.dataset[dataKey];
  };

  updateManifest();
  if (typeof mediaQuery.addEventListener === "function") {
    mediaQuery.addEventListener("change", updateManifest);
  } else {
    mediaQuery.addListener(updateManifest);
  }
})();
