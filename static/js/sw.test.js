const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadServiceWorker() {
  const listeners = new Map();
  const notifications = [];
  const openedWindows = [];
  const self = {
    registration: {
      showNotification: async (title, options) => {
        notifications.push({ title, options });
      },
    },
    addEventListener: (type, listener) => listeners.set(type, listener),
  };
  const context = {
    self,
    clients: { openWindow: async (url) => openedWindows.push(url) },
  };
  const source = fs.readFileSync(path.join(__dirname, 'sw.js'), 'utf8');

  vm.runInNewContext(source, context);
  return { listeners, notifications, openedWindows };
}

test('push handler displays the notification payload', async () => {
  const { listeners, notifications } = loadServiceWorker();
  let pending;

  listeners.get('push')({
    data: {
      json: () => ({
        title: "Borrow'd test",
        body: 'Push handler works',
        url: '/notifications/',
      }),
    },
    waitUntil: (promise) => {
      pending = promise;
    },
  });
  await pending;

  assert.equal(notifications.length, 1);
  assert.equal(notifications[0].title, "Borrow'd test");
  assert.equal(notifications[0].options.body, 'Push handler works');
  assert.equal(notifications[0].options.data.url, '/notifications/');
});

test('notification click closes the notification and opens its URL', async () => {
  const { listeners, openedWindows } = loadServiceWorker();
  let closed = false;
  let pending;

  listeners.get('notificationclick')({
    notification: {
      close: () => {
        closed = true;
      },
      data: { url: '/notifications/' },
    },
    waitUntil: (promise) => {
      pending = promise;
    },
  });
  await pending;

  assert.equal(closed, true);
  assert.deepEqual(openedWindows, ['/notifications/']);
});
