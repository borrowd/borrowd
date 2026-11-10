const test = require('node:test');
const assert = require('node:assert/strict');
const { inAppPath, isNativeApp } = require('./native-app.js');

const here = new URL('https://app.borrowd.org/items/');

test('isNativeApp is true only when Capacitor reports a native platform', () => {
  assert.equal(isNativeApp({}), false);
  assert.equal(isNativeApp({ Capacitor: { isNativePlatform: () => false } }), false);
  assert.equal(isNativeApp({ Capacitor: { isNativePlatform: () => true } }), true);
});

test('inAppPath keeps the path, query and fragment of a same-site link', () => {
  assert.equal(
    inAppPath('https://app.borrowd.org/groups/12/?tab=items#top', here),
    '/groups/12/?tab=items#top',
  );
});

test('inAppPath ignores links to other sites', () => {
  assert.equal(inAppPath('https://example.com/groups/12/', here), null);
  assert.equal(inAppPath('http://app.borrowd.org/groups/12/', here), null);
});

test('inAppPath ignores the page already showing', () => {
  assert.equal(inAppPath('https://app.borrowd.org/items/', here), null);
});

test('inAppPath ignores malformed URLs', () => {
  assert.equal(inAppPath('not a url', here), null);
});
