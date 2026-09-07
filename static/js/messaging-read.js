/**
 * Acknowledge messages present in an open, visible conversation. This is a
 * conversation bookmark, not proof that every bubble entered the viewport.
 * Read requests never share the send/poll lock and never insert message HTML.
 */
function initializeMessagingReads(doc, browser) {
  const messages = doc.querySelector('#chat-messages[data-read-url]');
  if (!messages) return;

  let acknowledged = 0n;
  let inFlight = false;
  let framePending = false;
  let retryTimer = null;
  let retryDelay = 4000;
  let paused = false;
  let controller = null;

  function renderedCursor() {
    const id = messages.querySelector('li:last-child')?.id || '';
    const match = /^message-([0-9]+)$/.exec(id);
    // Keep database bigint IDs exact, including beyond Number.MAX_SAFE_INTEGER.
    return match ? BigInt(match[1]) : 0n;
  }

  function schedule() {
    if (paused || framePending || retryTimer !== null) return;
    framePending = true;
    browser.requestAnimationFrame(() => {
      framePending = false;
      acknowledge();
    });
  }

  async function acknowledge() {
    if (paused || doc.visibilityState !== 'visible' || !messages.isConnected || inFlight) {
      return;
    }
    const through = renderedCursor();
    if (through <= acknowledged) return;

    inFlight = true;
    controller = new browser.AbortController();
    const timeout = browser.setTimeout(() => controller?.abort(), 10000);
    let succeeded = false;
    try {
      const response = await browser.fetch(messages.dataset.readUrl, {
        method: 'POST',
        credentials: 'same-origin',
        redirect: 'error',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': browser.getCsrfToken() || '',
        },
        body: new URLSearchParams({ through: through.toString() }),
        signal: controller.signal,
      });
      // A login page or error response must never count as an acknowledgment.
      if (response.status === 204) {
        acknowledged = through;
        retryDelay = 4000;
        succeeded = true;
        doc.dispatchEvent(
          new browser.CustomEvent('messaging:read', {
            detail: { through: through.toString() },
          }),
        );
      }
    } catch {
      // Retry without another message arriving, even on an archived page.
    } finally {
      browser.clearTimeout(timeout);
      controller = null;
      inFlight = false;
      if (!paused && messages.isConnected) {
        if (succeeded) {
          schedule(); // Pick up messages inserted while this request was running.
        } else if (doc.visibilityState === 'visible') {
          retryTimer = browser.setTimeout(() => {
            retryTimer = null;
            schedule();
          }, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 60000);
        }
      }
    }
  }

  function resume() {
    browser.clearTimeout(retryTimer);
    retryTimer = null;
    schedule();
  }

  doc.addEventListener('htmx:afterSwap', (event) => {
    if (event.detail.target === messages) schedule();
  });
  doc.addEventListener('visibilitychange', resume);
  browser.addEventListener('online', resume);
  browser.addEventListener('pagehide', () => {
    paused = true;
    browser.clearTimeout(retryTimer);
    retryTimer = null;
    controller?.abort();
  });
  browser.addEventListener('pageshow', () => {
    paused = false;
    resume();
  });
  schedule();
}

if (typeof window !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener(
      'DOMContentLoaded',
      () => initializeMessagingReads(document, window),
      { once: true },
    );
  } else {
    initializeMessagingReads(document, window);
  }
}

// The same controller runs in Node tests using a small browser substitute.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { initializeMessagingReads };
}
