(() => {
  const banner = document.querySelector("[data-install-prompt]");
  if (!banner) return;

  const installButton = banner.querySelector("[data-install-prompt-action]");
  const dismissButton = banner.querySelector("[data-install-prompt-dismiss]");
  const dismissalKey = "borrowd-pwa-install-prompt-dismissed";
  let deferredPrompt = null;

  const isInstalled = () =>
    window.matchMedia("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;

  const hideBanner = () => {
    banner.hidden = true;
  };

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();

    let dismissed = false;
    try {
      dismissed = window.localStorage.getItem(dismissalKey) === "true";
    } catch (error) {
      console.error("Unable to read install prompt dismissal:", error);
    }

    if (dismissed || isInstalled()) return;

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
      window.localStorage.setItem(dismissalKey, "true");
    } catch (error) {
      console.error("Unable to save install prompt dismissal:", error);
    }
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    hideBanner();
  });
})();
