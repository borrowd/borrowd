/**
 * Behavior that only applies inside the native app shell (mobile/).
 *
 * The shell is Capacitor loading this live site, and it injects
 * `window.Capacitor` (and its plugins) into every page it loads -- so the site
 * needs no Capacitor dependency of its own, and in a normal browser none of
 * this runs.
 */

function isNativeApp(win) {
  return win.Capacitor?.isNativePlatform?.() === true;
}

// Universal Links / App Links hand the app the full URL that was tapped (e.g.
// in an email). Returns the path to navigate to, or null when the link is for
// another site or is the page already showing.
function inAppPath(url, currentLocation) {
  let target;
  try {
    target = new URL(url);
  } catch {
    return null;
  }
  if (target.origin !== currentLocation.origin) {
    return null;
  }
  const path = target.pathname + target.search + target.hash;
  const currentPath =
    currentLocation.pathname + currentLocation.search + currentLocation.hash;
  return path === currentPath ? null : path;
}

if (typeof window !== 'undefined' && isNativeApp(window)) {
  document.documentElement.dataset.nativeApp = 'true';
  // Held over the first page load (see mobile/capacitor.config.ts).
  window.Capacitor.Plugins.SplashScreen?.hide();

  window.Capacitor.Plugins.App?.addListener('appUrlOpen', ({ url }) => {
    const path = inAppPath(url, window.location);
    if (path) {
      window.location.assign(path);
    }
  });
}

// Exposes the pure helpers to Node's built-in test runner
// (static/js/native-app.test.js) without affecting the browser bundle --
// `module` is undefined there.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { inAppPath, isNativeApp };
}
