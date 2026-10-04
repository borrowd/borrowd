import "vite/modulepreload-polyfill";
import "../css/main.css";
import "./toast.js";
import "./qrcode-render.js";
import "./htmx-csrf.js";
import "./image-resize.js";
import "./read-ack.js";

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch((error) => {
    console.error("Service worker registration failed:", error);
  });
}
