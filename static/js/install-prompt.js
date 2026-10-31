(() => {
  const banner = document.querySelector("[data-install-prompt]");
  if (!banner) return;

  const installButton = banner.querySelector("[data-install-prompt-action]");
  const dismissButton = banner.querySelector("[data-install-prompt-dismiss]");
  const dismissalKey = "borrowd-pwa-install-prompt-dismissed";
  const installedKey = "borrowd-pwa-installed";
  let deferredPrompt = null;

  const isInstalled = () =>
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true ||
    window.borrowdPlatform.isCapacitorApp();

  const hideBanner = () => {
    banner.hidden = true;
  };

  const markInstalled = () => {
    try {
      window.localStorage.setItem(installedKey, "true");
    } catch (error) {
      console.error("Unable to save installed app status:", error);
    }
  };

  window.addEventListener("beforeinstallprompt", (event) => {
    if (!window.borrowdPlatform.isMobileBrowser()) return;

    event.preventDefault();

    let dismissed = false;
    let installed = false;
    try {
      dismissed = window.localStorage.getItem(dismissalKey) === "true";
      installed = window.localStorage.getItem(installedKey) === "true";
    } catch (error) {
      console.error("Unable to read install prompt status:", error);
    }

    if (dismissed || installed || isInstalled()) return;

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
      const choice = await prompt.userChoice;
      if (choice.outcome === "accepted") markInstalled();
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
      window.localStorage.setItem(dismissalKey, "true");
    } catch (error) {
      console.error("Unable to save install prompt dismissal:", error);
    }
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    markInstalled();
    hideBanner();
  });
})();
