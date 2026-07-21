self.addEventListener("push", (event) => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(
    self.registration.showNotification(data.title ?? "Borrow'd", {
      body: data.body ?? "",
      // Paths here resolve against the service worker's own scope (`/`,
      // since sw.js is served from the root), not `/static/` — so these
      // must be absolute, not relative, to reach the real icon location.
      icon: data.icon ?? "/static/icon.svg",
      badge: "/static/icon.svg",
      data: { url: data.url ?? "/notifications/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
