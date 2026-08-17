/**
 * Attaches the CSRF token to every htmx request by reading Django's
 * `csrftoken` cookie at request time, rather than baking a value rendered
 * into the page into a static `hx-headers` attribute or a `{% csrf_token %}`
 * hidden input.
 *
 * Either of those goes stale whenever the CSRF cookie rotates after the page
 * was rendered (e.g. django.contrib.auth.login() rotates it on login),
 * because a page left open in another tab or restored from bfcache still
 * carries the pre-rotation token — causing htmx requests from that page to
 * fail CSRF validation. Reading the cookie live self-heals in those cases.
 * The `csrfmiddlewaretoken` form field is refreshed too, since Django's
 * CsrfViewMiddleware prefers a token in the request body over the header
 * when a form submits both.
 */
function getCookie(name) {
  const match = document.cookie.match(
    '(?:^|; )' + name.replace(/([.$?*|{}()[\]\\/+^])/g, '\\$1') + '=([^;]*)',
  );
  return match ? decodeURIComponent(match[1]) : null;
}

document.body.addEventListener('htmx:configRequest', (event) => {
  const csrfToken = getCookie('csrftoken');
  if (!csrfToken) {
    return;
  }
  event.detail.headers['X-CSRFToken'] = csrfToken;
  if ('csrfmiddlewaretoken' in event.detail.parameters) {
    event.detail.parameters['csrfmiddlewaretoken'] = csrfToken;
  }
});
