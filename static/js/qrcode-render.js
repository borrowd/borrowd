import QRCode from "qrcode";

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("canvas[data-qr-value]").forEach((canvas) => {
    const value = canvas.dataset.qrValue;
    if (value) {
      QRCode.toCanvas(canvas, value, { width: 200, margin: 2 });
    }
  });

  // Vector output for print: the SVG scales to its container without blurring.
  document.querySelectorAll("[data-qr-svg-value]").forEach((container) => {
    const value = container.dataset.qrSvgValue;
    if (value) {
      // Until this resolves, and if it fails, the container keeps its own
      // fallback content.
      QRCode.toString(value, { type: "svg", margin: 0 })
        .then((svg) => {
          container.innerHTML = svg;
        })
        .catch((err) => {
          console.error("Failed to render QR code: ", err);
        });
    }
  });
});
