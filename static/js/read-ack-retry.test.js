const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  READ_ACK_SEND_EVENT,
  isRetryableFailure,
  nextRetryDelayMs,
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
