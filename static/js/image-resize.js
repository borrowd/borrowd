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
window.resizeImageFile = async function resizeImageFile(
  file,
  maxWidth,
  maxHeight,
  quality = 0.85,
) {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxWidth / bitmap.width, maxHeight / bitmap.height);

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
};
