(() => {
  const banner = document.querySelector("[data-install-prompt]");
  if (!banner) return;

  const installButton = banner.querySelector("[data-install-prompt-action]");
  const dismissButton = banner.querySelector("[data-install-prompt-dismiss]");
  const dismissalKey = "borrowd-pwa-install-prompt-dismissed";
  const dismissalDuration = 7 * 24 * 60 * 60 * 1000;
  let deferredPrompt = null;

  const isInstalled = () =>
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true ||
    window.borrowdPlatform.isCapacitorApp();

  const hideBanner = () => {
    banner.hidden = true;
  };

  const isDismissed = () => {
    try {
      const dismissedAt = window.localStorage.getItem(dismissalKey);
      if (dismissedAt === null) return false;

      const elapsed = Date.now() - Number(dismissedAt);
      if (Number.isFinite(elapsed) && elapsed >= 0 && elapsed < dismissalDuration) {
        return true;
      }

      window.localStorage.removeItem(dismissalKey);
    } catch (error) {
      console.error("Unable to read install prompt dismissal:", error);
    }
    return false;
  };

  window.addEventListener("beforeinstallprompt", (event) => {
    if (!window.borrowdPlatform.isMobileBrowser()) return;

    event.preventDefault();

    if (isDismissed() || isInstalled()) return;

    deferredPrompt = event;
    banner.hidden = false;
  });

  installButton.addEventListener("click", async () => {
    if (!deferredPrompt) return;

    const prompt = deferredPrompt;
    deferredPrompt = null;
    installButton.disabled = true;
    hideBanner();

    try {
      await prompt.prompt();
      await prompt.userChoice;
    } catch (error) {
      console.error("Unable to show the install prompt:", error);
    } finally {
      installButton.disabled = false;
    }
  });

  dismissButton.addEventListener("click", () => {
    deferredPrompt = null;
    hideBanner();

    try {
      window.localStorage.setItem(dismissalKey, String(Date.now()));
    } catch (error) {
      console.error("Unable to save install prompt dismissal:", error);
    }
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    hideBanner();
  });
})();
