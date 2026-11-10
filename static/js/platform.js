window.borrowdPlatform = Object.freeze({
  isCapacitorApp: () => Boolean(window.Capacitor),
  isMobileBrowser: () => {
    const userAgentDataMobile = window.navigator.userAgentData?.mobile;
    if (typeof userAgentDataMobile === "boolean") return userAgentDataMobile;

    const userAgent = window.navigator.userAgent ?? "";
    const isIPad = window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1;
    return isIPad || /Android|iPhone|iPad|iPod|Mobile|IEMobile|Windows Phone/i.test(userAgent);
  },
});
