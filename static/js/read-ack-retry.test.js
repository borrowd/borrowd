const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  READ_ACK_SEND_EVENT,
  isRetryableFailure,
  newestUnsentReadAck,
  nextRetryDelayMs,
  readAckAllowed,
} = require('./read-ack-retry.js');

test('nextRetryDelayMs backs off exponentially from the base delay', () => {
  assert.equal(nextRetryDelayMs(0), 1000);
  assert.equal(nextRetryDelayMs(1), 2000);
  assert.equal(nextRetryDelayMs(2), 4000);
});

test('nextRetryDelayMs returns null once attempts are exhausted', () => {
  assert.equal(nextRetryDelayMs(3), null);
  assert.equal(nextRetryDelayMs(4), null);
});

test('isRetryableFailure retries dropped requests and server errors only', () => {
  assert.equal(isRetryableFailure('htmx:sendError', 0), true);
  assert.equal(isRetryableFailure('htmx:responseError', 502), true);
  assert.equal(isRetryableFailure('htmx:responseError', 400), false);
  assert.equal(isRetryableFailure('htmx:responseError', 403), false);
});

test('readAckAllowed only while the page is visible and focused', () => {
  const page = (visibilityState, focused) => ({
    visibilityState,
    hasFocus: () => focused,
  });

  assert.equal(readAckAllowed(page('visible', true)), true);
  assert.equal(readAckAllowed(page('visible', false)), false);
  assert.equal(readAckAllowed(page('hidden', true)), false);
  assert.equal(readAckAllowed(page('hidden', false)), false);
});

test('newestUnsentReadAck picks the newest ack only while it is unsent', () => {
  const older = { dataset: {} };
  const newest = { dataset: {} };

  assert.equal(newestUnsentReadAck([older, newest]), newest);
  newest.dataset.readAckSent = 'true';
  assert.equal(newestUnsentReadAck([older, newest]), null);
  assert.equal(newestUnsentReadAck([]), null);
});

// htmx runs a `load` trigger once, so a retry only sends if the element listens for its event.
test('every read-ack element listens for the event a retry fires', () => {
  const template = fs.readFileSync(
    path.join(__dirname, '..', '..', 'templates', 'messaging', '_message.html'),
    'utf8',
  );
  const triggers = [
    ...template.matchAll(/data-read-ack[^>]*?hx-trigger="([^"]*)"/g),
  ].map((match) => match[1]);

  assert.equal(triggers.length, 2);
  for (const trigger of triggers) {
    const events = trigger.split(',').map((spec) => spec.trim().split('[')[0]);
    assert.ok(events.includes(READ_ACK_SEND_EVENT), trigger);
  }
});
