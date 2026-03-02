/**
 * showToast(message, variant)
 *
 * Programmatically shows a floating DaisyUI alert toast.
 * Mirrors the markup and dismiss behaviour of templates/includes/messages.html.
 * Auto-dismiss is handled by Alpine.js (x-init) — no manual setTimeout needed.
 *
 * Used only for AJAX responses (e.g. avatar delete) where a page reload is
 * intentionally avoided. All other toasts go through Django messages.
 *
 * @param {string} message           - Text to display.
 * @param {string} [variant='success'] - DaisyUI alert variant:
 *   'success' | 'error' | 'warning' | 'info'
 */
window.showToast = function showToast(message, variant = 'success') {
  const wrapper = document.createElement('div');
  wrapper.className = 'toast toast-center z-50';
  wrapper.setAttribute('x-data', '');
  wrapper.setAttribute(
    'x-init',
    "setTimeout(() => { $el.style.transition = 'opacity 0.3s ease-out'; $el.style.opacity = '0'; setTimeout(() => $el.remove(), 300); }, 5000)",
  );
  wrapper.innerHTML = `
    <div role="alert"
         class="alert alert-${variant} w-72 flex items-center gap-4 px-4 py-3 rounded-2xl shadow-[0px_4px_3px_-2px_rgba(0,0,0,0.08)] font-bold">
      <!-- icon: static/icons/info-circle.svg -->
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"
           stroke-width="1.5" stroke="currentColor" class="size-6 shrink-0">
        <path stroke-linecap="round" stroke-linejoin="round"
              d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
      </svg>
      <span class="text-sm leading-6">${message}</span>
    </div>
  `;
  document.body.appendChild(wrapper);
  // Initialise Alpine on the newly-injected element so x-init fires.
  Alpine.initTree(wrapper);
};
