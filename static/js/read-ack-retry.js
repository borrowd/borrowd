/**
 * Retries the "mark thread read" request fired by messaging/_message.html
 * (`hx-trigger="load"` on the last rendered message, marked `data-read-ack`)
 * when it is dropped or the server errors. That request only fires once on
 * render, and nothing else re-sends it until another message arrives or the
 * thread is reopened, so a single failure would otherwise leave the thread
 * unread indefinitely.
 */
const MAX_ATTEMPTS = 3;
const BASE_DELAY_MS = 1000;

// null once attempts are exhausted, so the caller gives up instead of retrying forever.
function nextRetryDelayMs(attempts) {
  return attempts < MAX_ATTEMPTS ? BASE_DELAY_MS * 2 ** attempts : null;
}

function retry(target) {
  const attempts = Number(target.dataset.readAckAttempts || '0');
  const delay = nextRetryDelayMs(attempts);
  if (delay === null) {
    return;
  }
  target.dataset.readAckAttempts = String(attempts + 1);
  setTimeout(() => window.htmx?.trigger(target, 'load'), delay);
}

function handleFailure(event) {
  if (event.target.matches('[data-read-ack]')) {
    retry(event.target);
  }
}

if (typeof document !== 'undefined') {
  document.body.addEventListener('htmx:sendError', handleFailure);
  document.body.addEventListener('htmx:responseError', handleFailure);
}

// Exposes the pure, DOM-free backoff math to Node's built-in test runner
// (static/js/read-ack-retry.test.js) without affecting the browser bundle --
// `module` is undefined there.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { nextRetryDelayMs };
}
