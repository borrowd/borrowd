const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadInstallPrompt({
  capacitorApp = false,
  installed = false,
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
    navigator: {},
    Capacitor: capacitorApp ? {} : undefined,
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    },
  };
  const document = { querySelector: () => banner };
  const platformSource = fs.readFileSync(path.join(__dirname, 'platform.js'), 'utf8');
  const installPromptSource = fs.readFileSync(path.join(__dirname, 'install-prompt.js'), 'utf8');

  vm.runInNewContext(platformSource, { window });
  vm.runInNewContext(installPromptSource, { document, window, console });
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

test('persists dismissal and does not show the banner again', () => {
  const { banner, dismissListeners, storage, windowListeners } = loadInstallPrompt();

  windowListeners.get('beforeinstallprompt')(createInstallEvent().event);
  dismissListeners.get('click')();

  assert.equal(storage.get('borrowd-pwa-install-prompt-dismissed'), 'true');
  assert.equal(banner.hidden, true);

  const nextLoad = loadInstallPrompt({ storage });
  const nextInstallEvent = createInstallEvent();
  nextLoad.windowListeners.get('beforeinstallprompt')(nextInstallEvent.event);

  assert.equal(nextInstallEvent.wasPrevented(), true);
  assert.equal(nextLoad.banner.hidden, true);
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

test('hides the banner after the app is installed', () => {
  const { banner, windowListeners } = loadInstallPrompt();

  windowListeners.get('beforeinstallprompt')(createInstallEvent().event);
  assert.equal(banner.hidden, false);

  windowListeners.get('appinstalled')();

  assert.equal(banner.hidden, true);
});
