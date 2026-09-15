/**
 * Retries the "mark thread read" request fired by messaging/_message.html
 * (on the last rendered message, marked `data-read-ack`) when it is dropped or
 * the server errors. That request only fires once on render, and nothing else
 * re-sends it until another message arrives or the thread is reopened, so a
 * single failure would otherwise leave the thread unread indefinitely.
 */
const MAX_ATTEMPTS = 3;
const BASE_DELAY_MS = 1000;
// The ack element listens for this; htmx never re-runs a `load` trigger.
const READ_ACK_SEND_EVENT = 'read-ack:send';

// null once attempts are exhausted, so the caller gives up instead of retrying forever.
function nextRetryDelayMs(attempts) {
  return attempts < MAX_ATTEMPTS ? BASE_DELAY_MS * 2 ** attempts : null;
}

// A 4xx (bad cursor, expired CSRF token) would fail the same way again.
function isRetryableFailure(eventType, status) {
  return eventType === 'htmx:sendError' || status >= 500;
}

function retry(target) {
  const attempts = Number(target.dataset.readAckAttempts || '0');
  const delay = nextRetryDelayMs(attempts);
  if (delay === null) {
    return;
  }
  target.dataset.readAckAttempts = String(attempts + 1);
  setTimeout(() => window.htmx?.trigger(target, READ_ACK_SEND_EVENT), delay);
}

function handleFailure(event) {
  if (
    event.target.matches('[data-read-ack]') &&
    isRetryableFailure(event.type, event.detail?.xhr?.status ?? 0)
  ) {
    retry(event.target);
  }
}

if (typeof document !== 'undefined') {
  document.body.addEventListener('htmx:sendError', handleFailure);
  document.body.addEventListener('htmx:responseError', handleFailure);
}

// Exposes the pure, DOM-free helpers to Node's built-in test runner
// (static/js/read-ack-retry.test.js) without affecting the browser bundle --
// `module` is undefined there.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { READ_ACK_SEND_EVENT, isRetryableFailure, nextRetryDelayMs };
}
