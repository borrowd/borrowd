/**
 * Reads Django's `csrftoken` cookie at request time, rather than baking a
 * value rendered into the page into a static `hx-headers` attribute, a
 * `{% csrf_token %}` hidden input, or an inline `{{ csrf_token }}`.
 *
 * Any of those goes stale whenever the CSRF cookie rotates after the page
 * was rendered (e.g. django.contrib.auth.login() rotates it on login),
 * because a page left open in another tab or restored from bfcache still
 * carries the pre-rotation token — causing requests from that page to fail
 * CSRF validation. Reading the cookie live self-heals in those cases.
 *
 * Exposed on `window` so inline `fetch()` calls in templates can use it too,
 * since Vite loads this as a module and inline `<script>` tags can't `import`
 * it directly.
 */
function getCookie(name) {
  const match = document.cookie.match(
    '(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)',
  );
  return match ? decodeURIComponent(match[1]) : null;
}

function getCsrfToken() {
  return getCookie('csrftoken');
}
window.getCsrfToken = getCsrfToken;

document.body.addEventListener('htmx:configRequest', (event) => {
  const csrfToken = getCsrfToken();
  if (!csrfToken) {
    return;
  }
  event.detail.headers['X-CSRFToken'] = csrfToken;
  if ('csrfmiddlewaretoken' in event.detail.parameters) {
    event.detail.parameters['csrfmiddlewaretoken'] = csrfToken;
  }
});
