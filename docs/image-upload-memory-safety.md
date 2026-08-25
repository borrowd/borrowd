# Image upload memory safety

Upsun has previously OOM'd from simultaneous photo uploads combined with
in-memory image resizing. This doc explains the safeguards around that, and
how the numbers were derived, so they can be recomputed if the deployment
changes.

## The core problem

Every photo upload surface (item photos, profile image, group banner) goes
through an `imagekit.ProcessedImageField`, which has Pillow decode the full
image into a raw pixel buffer before resizing it down. A cap on the
*compressed* upload size (`MAX_PHOTO_SIZE_BYTES` in `borrowd/validators.py`)
does not bound that decode buffer: compression ratio varies enormously by
format and content. A solid-color 10000x10000 PNG compresses to a few KB but
still decodes to 100 million pixels. What actually needs bounding is pixel
count, not file size.

## The safeguards

**Client-side resize** (`static/js/image-resize.js`, `window.resizeImageFile`)
downscales a selected image toward its eventual processed size (e.g.
1600x1600) in the browser, before upload, using `<canvas>`. This is a
best-effort optimization: it keeps normal uploads small and reduces upload
bandwidth, but it is not a security boundary. It can be skipped entirely (JS
disabled, a direct API request, a bug in this code), so it must never be the
only thing standing between an upload and the server.

**Server-side pixel cap** (`validate_image_dimensions` /
`MAX_IMAGE_MEGAPIXELS` in `borrowd/validators.py`) is the actual enforcement
point. It's wired into every form that accepts an image upload
(`ItemCreateWithPhotoForm`, `ItemPhotoForm`, `ProfileUpdateForm`,
`BorrowdGroupForm.clean_banner`). Because client-side resize keeps normal
traffic far below this cap, it can be set purely based on what the deployment
can survive, without worrying about rejecting legitimate photos.

**Pillow-level hardening** (`borrowd/config/base.py`) sets
`Image.MAX_IMAGE_PIXELS` to the same value as `MAX_IMAGE_PIXELS` and converts
Pillow's decompression-bomb warning into a hard error. This is what protects
paths that skip our form validators entirely -- notably Django admin, since
`BorrowdGroup`, `Profile`, and `Item`/`ItemPhoto` are all registered with
plain `admin.site.register(...)` (no custom form). The `banner` and `logo`
model fields also carry `FileExtensionValidator` and `validate_image_size`
directly (`borrowd_groups/models.py`), so admin uploads get the same
extension/size checks as the normal form path. `logo` has no form field, view,
or template upload control anywhere in the app today -- the only way to set
it is admin or a shell/fixture -- so this is currently its only protection.

## How MAX_IMAGE_MEGAPIXELS (8) was derived

This is grounded in the actual production plan, checked via `upsun
project:info`, not in typical camera resolution:

- Whole production environment (app + db combined): capped at **666MB total**
  memory (`resources.production.max_memory` on the project's subscription).
- Idle baseline for the app container's own processes -- `uv run gunicorn`
  wrapper, gunicorn master, 2 sync workers (`-w 2` in `.platform.app.yaml`),
  nginx -- measured via `ps aux --sort=-%mem` on the running production
  container: **~110MB RSS**.
- Unverified assumption: the app container gets roughly **~300MB** of the
  666MB total, with the rest reserved for Postgres. No per-container split is
  visible from static config (no `resources`/`container_profile` block in
  `.platform.app.yaml`, and the flexible-resources API isn't enabled for this
  project), so this number should be confirmed against Upsun support or the
  console dashboard rather than trusted outright.
- Available burst headroom on that assumption: 300MB ceiling minus 110MB
  idle baseline = **~190MB**, shared across both gunicorn workers (both can
  be mid-request at once).
- Decode memory model: worst case is a PNG with an alpha channel (4
  bytes/pixel), and Pillow's resize needs roughly 2-3x the decoded buffer
  size transiently (original buffer + resized buffer + library overhead):
  `peak MB ~= pixels * 4 bytes * 3 / 1,000,000`.
- Solving for both workers peaking simultaneously within the ~190MB headroom
  (~95MB each): `95,000,000 / 12 ~= 7.9 million pixels`, rounded to **8
  megapixels**.

### Recomputing this number

If the Upsun plan, container sizing, or `gunicorn` worker count changes,
redo the math above with fresh numbers:

1. `upsun project:info -p <project-id>` for the current plan's `max_memory`.
2. SSH into the app container and run `ps aux --sort=-%mem` to get the
   current idle baseline (cgroup memory limits aren't visible from inside the
   container on this plan -- `/sys/fs/cgroup` and `/proc/meminfo` reflect the
   shared host, not the container's allocation).
3. Update `MAX_IMAGE_MEGAPIXELS` in `borrowd/validators.py` -- it's the single
   source of truth; the Pillow hardening in `borrowd/config/base.py` reads it
   directly.

## What this doesn't cover

- The app-vs-db memory split is an assumption, not a verified number (see
  above). If it turns out to be materially smaller than ~300MB, the 8MP cap
  should be tightened.
- Up to 5 photos can be uploaded in a single item-edit request
  (`borrowd_items/views.py::_process_uploaded_photos`), processed
  sequentially. The math above assumes peak memory is dominated by roughly
  one in-flight decode per worker, not all 5 at once -- true as long as
  CPython frees each processed image's buffers before the next iteration
  starts, but this hasn't been empirically stress-tested.
- No load test has been run against the actual production container. Before
  trusting this cap under real concurrent traffic, upload several
  max-dimension photos concurrently (ideally on staging first) while watching
  `free -h` / `ps aux --sort=-%mem`, to confirm peak RSS stays within budget.
- Resizing still happens synchronously in the request/response cycle --
  there's no async task queue in this codebase. Moving it off the request
  path would remove the concurrency multiplier entirely, but that's a larger
  architectural change, not part of this fix.
