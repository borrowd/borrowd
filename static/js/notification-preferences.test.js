const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function createPushPermissionCta(permission, subscription = null) {
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
  const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
  let registrationLookups = 0;
  const notificationApi = { permission };
  const permissionStatus = {};
  const context = {
    Notification: notificationApi,
    navigator: {
      serviceWorker: {
        getRegistration: async () => {
          registrationLookups += 1;
          return subscription
            ? { pushManager: { getSubscription: async () => subscription } }
            : null;
        },
      },
      permissions: {
        query: async () => permissionStatus,
      },
    },
    window: { Notification: notificationApi, PushManager: {} },
    console,
  };

  vm.runInNewContext(script, context);
  return {
    cta: vm.runInNewContext('pushPermissionCta()', context),
    registrationLookups: () => registrationLookups,
    setPermission: (value) => {
      notificationApi.permission = value;
    },
    permissionStatus,
  };
}

test('granting browser permission while the page is open hides the CTA', async () => {
  const { cta, registrationLookups, setPermission, permissionStatus } =
    createPushPermissionCta('default');

  await cta.init();
  assert.equal(cta.show, true);

  setPermission('granted');
  await permissionStatus.onchange();

  assert.equal(cta.show, false);
  assert.equal(cta.permissionDenied, false);
  assert.equal(registrationLookups(), 1);
});

test('denied permission shows the warning and default permission checks subscription', async () => {
  const denied = createPushPermissionCta('denied');
  await denied.cta._refresh();
  assert.equal(denied.cta.show, true);
  assert.equal(denied.cta.permissionDenied, true);
  assert.equal(denied.registrationLookups(), 0);

  const defaultPermission = createPushPermissionCta('default');
  await defaultPermission.cta._refresh();
  assert.equal(defaultPermission.cta.show, true);
  assert.equal(defaultPermission.cta.permissionDenied, false);
  assert.equal(defaultPermission.registrationLookups(), 1);
});

test('a denied subscription attempt preserves the account push preference', async () => {
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
  const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
  const events = [];
  const notificationApi = {
    permission: 'denied',
    requestPermission: async () => 'denied',
  };
  const context = {
    Notification: notificationApi,
    CustomEvent: class {
      constructor(type) {
        this.type = type;
      }
    },
    document: {
      getElementById: () => ({
        textContent: JSON.stringify({
          example: { push: true, is_mandatory: false, category: 'general' },
        }),
      }),
    },
    navigator: {
      serviceWorker: {
        register: async () => ({
          pushManager: { getSubscription: async () => null },
        }),
      },
    },
    window: {
      Notification: notificationApi,
      PushManager: {},
      dispatchEvent: (event) => events.push(event),
    },
    console,
  };
  vm.runInNewContext(script, context);
  const preferences = vm.runInNewContext('notificationPrefs()', context);

  await preferences._ensurePushSubscribed();

  assert.equal(preferences.prefs.example.push, true);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'push-permission-changed');
});
