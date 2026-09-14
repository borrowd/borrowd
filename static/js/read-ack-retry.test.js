const test = require('node:test');
const assert = require('node:assert/strict');
const { nextRetryDelayMs } = require('./read-ack-retry.js');

test('nextRetryDelayMs backs off exponentially from the base delay', () => {
  assert.equal(nextRetryDelayMs(0), 1000);
  assert.equal(nextRetryDelayMs(1), 2000);
  assert.equal(nextRetryDelayMs(2), 4000);
});

test('nextRetryDelayMs returns null once attempts are exhausted', () => {
  assert.equal(nextRetryDelayMs(3), null);
  assert.equal(nextRetryDelayMs(4), null);
});
