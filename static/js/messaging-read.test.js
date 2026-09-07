const test = require('node:test');
const assert = require('node:assert/strict');
const { initializeMessagingReads } = require('./messaging-read.js');

function fixture({ cursor = '10', visible = true, hasThread = true } = {}) {
  const doc = new EventTarget();
  const browser = new EventTarget();
  const frames = [];
  const timers = new Map();
  const requests = [];
  let timerId = 0;
  const messages = {
    dataset: { readUrl: '/messages/1/read/' },
    isConnected: true,
    cursor,
    querySelector: () => messages.cursor ? { id: `message-${messages.cursor}` } : null,
  };
  doc.visibilityState = visible ? 'visible' : 'hidden';
  doc.querySelector = () => hasThread ? messages : null;
  browser.AbortController = AbortController;
  browser.CustomEvent = CustomEvent;
  browser.token = 'csrf-first';
  browser.getCsrfToken = () => browser.token;
  browser.requestAnimationFrame = (callback) => frames.push(callback);
  browser.setTimeout = (callback, delay) => {
    timers.set(++timerId, { callback, delay });
    return timerId;
  };
  browser.clearTimeout = (id) => timers.delete(id);
  browser.fetch = (url, options) => new Promise((resolve, reject) => {
    requests.push({ url, options, resolve, reject });
    options.signal.addEventListener('abort', () => reject(new Error('Aborted')));
  });
  initializeMessagingReads(doc, browser);
  return {
    doc, browser, messages, frames, timers, requests,
    async frame() {
      frames.splice(0).forEach((callback) => callback());
      await Promise.resolve();
    },
    async respond(status = 204) {
      requests.at(-1).resolve({ status });
      await Promise.resolve();
    },
    swap(target = messages) {
      doc.dispatchEvent(new CustomEvent('htmx:afterSwap', { detail: { target } }));
    },
    visibility(visible) {
      doc.visibilityState = visible ? 'visible' : 'hidden';
      doc.dispatchEvent(new Event('visibilitychange'));
    },
    timer(delay) {
      const entry = [...timers].find(([, timer]) => timer.delay === delay);
      assert.ok(entry, `Expected a ${delay}ms timer`);
      timers.delete(entry[0]);
      entry[1].callback();
    },
  };
}

test('initial visible render sends an exact cursor with live CSRF, and success is deduplicated', async () => {
  const f = fixture();
  const events = [];
  f.doc.addEventListener('messaging:read', (event) => events.push(event.detail.through));
  assert.equal(f.requests.length, 0);
  await f.frame();
  const { url, options } = f.requests[0];
  assert.equal(url, '/messages/1/read/');
  assert.equal(options.body.get('through'), '10');
  assert.equal(options.method, 'POST');
  assert.equal(options.credentials, 'same-origin');
  assert.equal(options.redirect, 'error');
  assert.equal(options.headers['X-CSRFToken'], 'csrf-first');
  await f.respond();
  f.swap();
  await f.frame();
  assert.equal(f.requests.length, 1);
  assert.deepEqual(events, ['10']);
  assert.equal(f.timers.size, 0);
});

test('no thread or an empty thread sends nothing', async () => {
  for (const options of [{ hasThread: false }, { cursor: '' }]) {
    const f = fixture(options);
    await f.frame();
    assert.equal(f.requests.length, 0);
  }
});

test('hidden initial page and hidden swaps wait until visible', async () => {
  const f = fixture({ visible: false });
  await f.frame();
  f.messages.cursor = '11';
  f.swap();
  await f.frame();
  assert.equal(f.requests.length, 0);
  f.visibility(true);
  await f.frame();
  assert.equal(f.requests[0].options.body.get('through'), '11');
});

test('hiding between scheduling and the frame prevents acknowledgment', async () => {
  const f = fixture();
  f.visibility(false);
  await f.frame();
  assert.equal(f.requests.length, 0);
});

test('send and poll swaps coalesce while a read is in flight, without skipping the newer cursor', async () => {
  const f = fixture();
  await f.frame();
  f.messages.cursor = '11';
  f.swap();
  f.messages.cursor = '12';
  f.swap();
  await f.frame();
  assert.equal(f.requests.length, 1);
  await f.respond();
  f.browser.token = 'csrf-rotated';
  await f.frame();
  assert.equal(f.requests.length, 2);
  assert.equal(f.requests[1].options.body.get('through'), '12');
  assert.equal(f.requests[1].options.headers['X-CSRFToken'], 'csrf-rotated');
});

test('unrelated HTMX swaps do not trigger acknowledgment', async () => {
  const f = fixture();
  await f.frame();
  await f.respond();
  await f.frame();
  f.messages.cursor = '11';
  f.swap({ id: 'another-widget' });
  await f.frame();
  assert.equal(f.requests.length, 1);
});

test('failed requests retry without polling or another message, with backoff capped at one minute', async () => {
  const f = fixture();
  await f.frame();
  for (const delay of [4000, 8000, 16000, 32000, 60000, 60000]) {
    await f.respond(503);
    f.swap();
    assert.equal(f.frames.length, 0);
    f.timer(delay);
    await f.frame();
  }
  await f.respond();
  await f.frame();
  assert.equal(f.timers.size, 0);
});

test('network failure and non-204 login HTML do not count as success', async () => {
  const f = fixture();
  const events = [];
  f.doc.addEventListener('messaging:read', (event) => events.push(event));
  await f.frame();
  f.requests[0].reject(new Error('Offline'));
  await Promise.resolve();
  f.timer(4000);
  await f.frame();
  await f.respond(200);
  assert.equal(events.length, 0);
  f.timer(8000);
  await f.frame();
  assert.equal(f.requests.at(-1).options.body.get('through'), '10');
});

test('timeout releases a stuck request and retries', async () => {
  const f = fixture();
  await f.frame();
  f.timer(10000);
  await Promise.resolve();
  assert.equal(f.requests[0].options.signal.aborted, true);
  f.timer(4000);
  await f.frame();
  assert.equal(f.requests.length, 2);
});

test('retry pauses in a hidden tab and resumes when visible', async () => {
  const f = fixture();
  await f.frame();
  await f.respond(403);
  f.visibility(false);
  await f.frame();
  assert.equal(f.timers.size, 0);
  assert.equal(f.requests.length, 1);
  f.visibility(true);
  await f.frame();
  assert.equal(f.requests.length, 2);
});

test('a response to a visible-page acknowledgment cannot acknowledge messages later loaded while hidden', async () => {
  const f = fixture();
  await f.frame();
  f.visibility(false);
  f.messages.cursor = '11';
  f.swap();
  await f.respond();
  await f.frame();
  assert.equal(f.requests.length, 1);
  f.visibility(true);
  await f.frame();
  assert.equal(f.requests.at(-1).options.body.get('through'), '11');
});

test('pagehide aborts requests and pageshow retries on restoration', async () => {
  const f = fixture();
  await f.frame();
  f.browser.dispatchEvent(new Event('pagehide'));
  await Promise.resolve();
  assert.equal(f.timers.size, 0);
  f.browser.dispatchEvent(new Event('pageshow'));
  await f.frame();
  assert.equal(f.requests.length, 2);
});

test('going online retries immediately and rereads the CSRF token', async () => {
  const f = fixture();
  await f.frame();
  await f.respond(403);
  f.browser.token = 'csrf-restored';
  f.browser.dispatchEvent(new Event('online'));
  await f.frame();
  assert.equal(f.requests.length, 2);
  assert.equal(f.requests[1].options.headers['X-CSRFToken'], 'csrf-restored');
});

test('IDs beyond JavaScript safe integers remain exact and distinguishable', async () => {
  const f = fixture({ cursor: '9007199254740992' });
  await f.frame();
  await f.respond();
  f.messages.cursor = '9007199254740993';
  f.swap();
  await f.frame();
  assert.equal(f.requests[1].options.body.get('through'), '9007199254740993');
});

test('detached message lists are not acknowledged', async () => {
  const f = fixture();
  f.messages.isConnected = false;
  await f.frame();
  assert.equal(f.requests.length, 0);
});
