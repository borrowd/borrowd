/**
 * Backs up the "mark thread read" request that messaging/_message.html puts on
 * the last rendered message (marked `data-read-ack`):
 * - retries it when it is dropped or the server errors, since nothing else
 *   re-sends it until another message arrives or the thread is reopened;
 * - sends it when the window regains focus, if its `load` trigger was skipped
 *   because the window was hidden or unfocused.
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

// Same condition as the `load` filter in messaging/_message.html.
function readAckAllowed(doc) {
  return doc.visibilityState === 'visible' && doc.hasFocus();
}

// The newest ack covers every older message, so it's the only one worth sending.
function newestUnsentReadAck(targets) {
  const newest = targets[targets.length - 1];
  return newest && !newest.dataset.readAckSent ? newest : null;
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

function markSent(event) {
  if (event.target.matches('[data-read-ack]')) {
    event.target.dataset.readAckSent = 'true';
  }
}

function handleFailure(event) {
  const target = event.target;
  if (
    target.matches('[data-read-ack]') &&
    isRetryableFailure(event.type, event.detail?.xhr?.status ?? 0)
  ) {
    delete target.dataset.readAckSent;
    retry(target);
  }
}

function sendSkippedReadAck() {
  if (!readAckAllowed(document)) {
    return;
  }
  const target = newestUnsentReadAck(document.querySelectorAll('[data-read-ack]'));
  if (target) {
    window.htmx?.trigger(target, READ_ACK_SEND_EVENT);
  }
}

if (typeof document !== 'undefined') {
  document.body.addEventListener('htmx:beforeRequest', markSent);
  document.body.addEventListener('htmx:sendError', handleFailure);
  document.body.addEventListener('htmx:responseError', handleFailure);
  document.addEventListener('visibilitychange', sendSkippedReadAck);
  window.addEventListener('focus', sendSkippedReadAck);
}

// Exposes the pure, DOM-free helpers to Node's built-in test runner
// (static/js/read-ack-retry.test.js) without affecting the browser bundle --
// `module` is undefined there.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    READ_ACK_SEND_EVENT,
    isRetryableFailure,
    newestUnsentReadAck,
    nextRetryDelayMs,
    readAckAllowed,
  };
}
