self.addEventListener("push", (event) => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil(
    self.registration.showNotification(data.title ?? "Borrow'd", {
      body: data.body ?? "",
      icon: data.icon ?? "../icon.svg",
      badge: '../icon.svg',
      data: { url: data.url ?? "/notifications/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
