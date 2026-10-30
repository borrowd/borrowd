const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const template = fs.readFileSync(
  path.join(
    __dirname,
    '..',
    '..',
    'templates',
    'notifications',
    'preferences.html',
  ),
  'utf8',
);
const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)?.[1];
assert.ok(script, 'notification preferences template has an inline script');

function createNotificationSettings({
  permission,
  subscription = null,
  prefs = {},
  nativeApp = false,
}) {
  let registrationLookups = 0;
  let fetches = 0;
  const events = [];
  const notificationApi = {
    permission,
    requestPermission: async () => notificationApi.permission,
  };
  const registration = {
    pushManager: {
      getSubscription: async () => subscription,
      subscribe: async () => subscription,
    },
  };
  const permissionStatus = { state: permission };
  const context = {
    Notification: notificationApi,
    CustomEvent: class {
      constructor(type) {
        this.type = type;
      }
    },
    document: {
      getElementById: () => ({ textContent: JSON.stringify(prefs) }),
    },
    navigator: {
      serviceWorker: {
        getRegistration: async () => {
          registrationLookups += 1;
          return registration;
        },
        register: async () => registration,
      },
      permissions: {
        query: async () => permissionStatus,
      },
    },
    window: {
      Notification: notificationApi,
      PushManager: {},
      dispatchEvent: (event) => events.push(event),
      getCsrfToken: () => 'csrf-token',
      ...(nativeApp && { Capacitor: { isNativePlatform: () => true } }),
    },
    fetch: async () => {
      fetches += 1;
      return { ok: true };
    },
    console,
  };

  vm.runInNewContext(script, context);
  return {
    cta: vm.runInNewContext('pushPermissionCta()', context),
    preferences: vm.runInNewContext('notificationPrefs()', context),
    events,
    permissionStatus,
    registrationLookups: () => registrationLookups,
    fetches: () => fetches,
    setPermission(value) {
      notificationApi.permission = value;
      permissionStatus.state = value;
    },
  };
}

test('granted permission keeps the CTA visible until this browser has a subscription', async () => {
  const withoutSubscription = createNotificationSettings({
    permission: 'granted',
  });
  await withoutSubscription.cta._refresh();

  assert.equal(withoutSubscription.cta.show, true);
  assert.equal(withoutSubscription.cta.permissionDenied, false);
  assert.equal(withoutSubscription.registrationLookups(), 1);

  const withSubscription = createNotificationSettings({
    permission: 'granted',
    subscription: { endpoint: 'https://push.example/subscription' },
  });
  await withSubscription.cta._refresh();

  assert.equal(withSubscription.cta.show, false);
});

test('changing permission from denied to granted refreshes the CTA subscription state', async () => {
  const settings = createNotificationSettings({ permission: 'denied' });
  await settings.cta.init();
  assert.equal(settings.cta.show, true);
  assert.equal(settings.cta.permissionDenied, true);

  settings.setPermission('granted');
  await settings.permissionStatus.onchange();

  assert.equal(settings.cta.show, true);
  assert.equal(settings.cta.permissionDenied, false);
  assert.equal(settings.registrationLookups(), 1);
});

test('a denied subscription attempt preserves preferences and refreshes the blocked banner', async () => {
  const settings = createNotificationSettings({
    permission: 'denied',
    prefs: {
      example: { push: true, is_mandatory: false, category: 'general' },
    },
  });

  await settings.preferences._ensurePushSubscribed();
  assert.equal(settings.preferences.prefs.example.push, true);
  assert.equal(settings.events.length, 1);
  assert.equal(settings.events[0].type, 'push-permission-changed');
  assert.match(
    template,
    /@push-permission-changed\.window="_refresh\(\)"/,
  );

  await settings.cta._refresh();
  assert.equal(settings.cta.show, true);
  assert.equal(settings.cta.permissionDenied, true);
});

test('inside the native app the web-push CTA stays hidden and nothing subscribes', async () => {
  const settings = createNotificationSettings({
    permission: 'default',
    nativeApp: true,
    prefs: {
      example: { push: true, is_mandatory: false, category: 'general' },
    },
  });

  await settings.cta.init();
  assert.equal(settings.cta.show, false);

  await settings.preferences._ensurePushSubscribed();
  await settings.preferences._dropPushSubscription();
  assert.equal(settings.registrationLookups(), 0);
  assert.equal(settings.fetches(), 0);
  assert.equal(settings.events.length, 0);
});
