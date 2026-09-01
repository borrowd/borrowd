const test = require('node:test');
const assert = require('node:assert/strict');
const { computeFitScale } = require('./image-resize.js');

test('computeFitScale downscales when both dimensions exceed the bounds', () => {
  // 4000x3000 fit into 1600x1600: width-bound (1600/4000) is the tighter ratio.
  const scale = computeFitScale(4000, 3000, 1600, 1600);
  assert.equal(scale, 1600 / 4000);
});

test('computeFitScale never upscales an already-small image', () => {
  const scale = computeFitScale(100, 100, 1600, 1600);
  assert.equal(scale, 1);
});

test('computeFitScale returns exactly 1 at the exact boundary', () => {
  const scale = computeFitScale(1600, 1600, 1600, 1600);
  assert.equal(scale, 1);
});

test('computeFitScale picks the more restrictive dimension for a non-square target (banner)', () => {
  // A 1600x1600 source into a 1600x400 banner box: height is the binding constraint.
  const scale = computeFitScale(1600, 1600, 1600, 400);
  assert.equal(scale, 400 / 1600);
});

test('computeFitScale preserves aspect ratio for a wide source fit into a wide target', () => {
  // 3200x800 source (4:1, same aspect as the 1600x400 banner box) should hit
  // both bounds at the same scale.
  const scale = computeFitScale(3200, 800, 1600, 400);
  assert.equal(scale, 0.5);
  assert.equal(1600 * scale, 800);
  assert.equal(800 * scale, 400);
});
