/**
 * Client-side downscale of an image file before upload, so a typical upload
 * already arrives near its eventual processed size instead of relying on the
 * server's pixel-count cap (borrowd.validators.MAX_IMAGE_PIXELS) to reject
 * anything larger.
 *
 * This is never a substitute for that server-side check -- it can be skipped
 * (JS disabled, a bug here, a non-browser client), so the server always
 * re-validates regardless of what this does. Falls back to the original,
 * unresized file if anything about the resize fails; upload should never be
 * blocked by this step.
 */
/**
 * Aspect-ratio-preserving scale factor to fit sourceWidth x sourceHeight
 * within maxWidth x maxHeight, never upscaling (result is always <= 1).
 */
function computeFitScale(sourceWidth, sourceHeight, maxWidth, maxHeight) {
  return Math.min(1, maxWidth / sourceWidth, maxHeight / sourceHeight);
}

async function resizeImageFile(file, maxWidth, maxHeight, quality = 0.85) {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = computeFitScale(bitmap.width, bitmap.height, maxWidth, maxHeight);

    if (scale >= 1) {
      bitmap.close();
      return file; // already within bounds
    }

    const targetWidth = Math.round(bitmap.width * scale);
    const targetHeight = Math.round(bitmap.height * scale);

    const canvas = document.createElement('canvas');
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext('2d');
    // JPEG has no alpha channel. Without an explicit fill, canvas composites
    // transparent source pixels onto black, silently blackening any
    // transparent background (e.g. a logo-style PNG) before upload.
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, targetWidth, targetHeight);
    ctx.drawImage(bitmap, 0, 0, targetWidth, targetHeight);
    bitmap.close();

    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', quality),
    );
    if (!blob) {
      return file;
    }

    const resizedName = file.name.replace(/\.[^.]+$/, '') + '.jpg';
    return new File([blob], resizedName, { type: 'image/jpeg' });
  } catch (err) {
    console.warn('resizeImageFile: falling back to original file', err);
    return file;
  }
}

if (typeof window !== 'undefined') {
  window.resizeImageFile = resizeImageFile;
}

// Exposes the pure, DOM-free math to Node's built-in test runner
// (static/js/image-resize.test.js) without affecting the browser bundle --
// `module` is undefined there.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { computeFitScale };
}
