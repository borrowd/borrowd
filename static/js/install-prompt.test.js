const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadInstallPrompt({
  capacitorApp = false,
  installed = false,
  mobile = true,
  now = 1_000_000,
  storage = new Map(),
} = {}) {
  const windowListeners = new Map();
  const installListeners = new Map();
  const dismissListeners = new Map();
  const installButton = { addEventListener: (type, listener) => installListeners.set(type, listener) };
  const dismissButton = { addEventListener: (type, listener) => dismissListeners.set(type, listener) };
  const banner = {
    hidden: true,
    querySelector: (selector) => {
      if (selector === '[data-install-prompt-action]') return installButton;
      if (selector === '[data-install-prompt-dismiss]') return dismissButton;
      return null;
    },
  };
  const window = {
    addEventListener: (type, listener) => windowListeners.set(type, listener),
    matchMedia: () => ({ matches: installed }),
    navigator: {
      userAgentData: { mobile },
    },
    Capacitor: capacitorApp ? {} : undefined,
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
  };
  const document = { querySelector: () => banner };
  const platformSource = fs.readFileSync(path.join(__dirname, 'platform.js'), 'utf8');
  const installPromptSource = fs.readFileSync(path.join(__dirname, 'install-prompt.js'), 'utf8');

  vm.runInNewContext(platformSource, { window });
  vm.runInNewContext(installPromptSource, {
    Date: { now: () => now },
    document,
    window,
    console,
  });
  return { banner, installListeners, dismissListeners, windowListeners, storage };
}

function createInstallEvent(outcome = 'accepted') {
  let prevented = false;
  let prompted = false;
  return {
    event: {
      preventDefault: () => {
        prevented = true;
      },
      prompt: async () => {
        prompted = true;
      },
      userChoice: Promise.resolve({ outcome }),
    },
    wasPrevented: () => prevented,
    wasPrompted: () => prompted,
  };
}

test('captures the install event and prompts only after the user chooses', async () => {
  const { banner, installListeners, windowListeners } = loadInstallPrompt();
  const installEvent = createInstallEvent();

  windowListeners.get('beforeinstallprompt')(installEvent.event);

  assert.equal(installEvent.wasPrevented(), true);
  assert.equal(banner.hidden, false);
  assert.equal(installEvent.wasPrompted(), false);

  await installListeners.get('click')();

  assert.equal(installEvent.wasPrompted(), true);
  assert.equal(banner.hidden, true);
});

test('does not persist dismissal of the browser install dialog', async () => {
  const { banner, installListeners, storage, windowListeners } = loadInstallPrompt();

  windowListeners.get('beforeinstallprompt')(createInstallEvent('dismissed').event);
  await installListeners.get('click')();

  assert.equal(storage.has('borrowd-pwa-install-prompt-dismissed'), false);
  assert.equal(banner.hidden, true);
});

test('does not persist installed state after accepting the browser prompt', async () => {
  const firstLoad = loadInstallPrompt();
  const installEvent = createInstallEvent('accepted');
  firstLoad.windowListeners.get('beforeinstallprompt')(installEvent.event);
  await firstLoad.installListeners.get('click')();

  assert.equal(firstLoad.storage.has('borrowd-pwa-installed'), false);

  const nextLoad = loadInstallPrompt({ storage: firstLoad.storage });
  const nextInstallEvent = createInstallEvent();
  nextLoad.windowListeners.get('beforeinstallprompt')(nextInstallEvent.event);

  assert.equal(nextInstallEvent.wasPrevented(), true);
  assert.equal(nextLoad.banner.hidden, false);
});

test('persists dismissal and does not show the banner again', () => {
  const { banner, dismissListeners, storage, windowListeners } = loadInstallPrompt();

  windowListeners.get('beforeinstallprompt')(createInstallEvent().event);
  dismissListeners.get('click')();

  assert.equal(storage.get('borrowd-pwa-install-prompt-dismissed'), '1000000');
  assert.equal(banner.hidden, true);

  const nextLoad = loadInstallPrompt({ storage });
  const nextInstallEvent = createInstallEvent();
  nextLoad.windowListeners.get('beforeinstallprompt')(nextInstallEvent.event);

  assert.equal(nextInstallEvent.wasPrevented(), true);
  assert.equal(nextLoad.banner.hidden, true);
});

test('shows the banner again after a dismissal expires', () => {
  const firstLoad = loadInstallPrompt();
  firstLoad.dismissListeners.get('click')();

  const nowAfterExpiry = 1_000_000 + 8 * 24 * 60 * 60 * 1000;
  const nextLoad = loadInstallPrompt({ now: nowAfterExpiry, storage: firstLoad.storage });
  const installEvent = createInstallEvent();
  nextLoad.windowListeners.get('beforeinstallprompt')(installEvent.event);

  assert.equal(nextLoad.banner.hidden, false);
  assert.equal(firstLoad.storage.has('borrowd-pwa-install-prompt-dismissed'), false);
});

test('does not show the banner when the app is already installed', () => {
  const { banner, windowListeners } = loadInstallPrompt({ installed: true });
  const installEvent = createInstallEvent();

  windowListeners.get('beforeinstallprompt')(installEvent.event);

  assert.equal(installEvent.wasPrevented(), true);
  assert.equal(banner.hidden, true);
});

test('does not show the banner inside a Capacitor app', () => {
  const { banner, windowListeners } = loadInstallPrompt({ capacitorApp: true });
  const installEvent = createInstallEvent();

  windowListeners.get('beforeinstallprompt')(installEvent.event);

  assert.equal(installEvent.wasPrevented(), true);
  assert.equal(banner.hidden, true);
});

test('does not intercept or show the install prompt on desktop browsers', () => {
  const { banner, windowListeners } = loadInstallPrompt({ mobile: false });
  let prevented = false;
  const installEvent = {
    preventDefault: () => {
      prevented = true;
    },
  };

  windowListeners.get('beforeinstallprompt')(installEvent);

  assert.equal(prevented, false);
  assert.equal(banner.hidden, true);
});

test('hides the banner after the app is installed', () => {
  const { banner, windowListeners, storage } = loadInstallPrompt();

  windowListeners.get('beforeinstallprompt')(createInstallEvent().event);
  assert.equal(banner.hidden, false);

  windowListeners.get('appinstalled')();

  assert.equal(storage.has('borrowd-pwa-installed'), false);
  assert.equal(banner.hidden, true);
});
