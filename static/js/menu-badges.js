document.addEventListener("DOMContentLoaded", () => {
  const getCookie = (name) => {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  };

  const drawerToggle = document.getElementById("main-drawer");
  if (!drawerToggle) return;

  drawerToggle.addEventListener("change", async () => {
    if (!drawerToggle.checked) return;

    const dot = document.querySelector("[data-menu-hamburger-dot]");
    if (dot) dot.remove();

    let csrfToken = "";
    const hxHeadersAttr = document.body.getAttribute("hx-headers");
    if (hxHeadersAttr) {
      try {
        const hxHeaders = JSON.parse(hxHeadersAttr);
        csrfToken = hxHeaders["X-CSRFToken"] || "";
      } catch (_) {
        csrfToken = "";
      }
    }

    if (!csrfToken) {
      csrfToken = getCookie("csrftoken");
    }

    try {
      await fetch("/profile/menu-badges/drawer-open/", {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: {
          "X-CSRFToken": csrfToken,
          "X-Requested-With": "XMLHttpRequest",
        },
      });
    } catch (_) {}
  });
});
