import type { CapacitorConfig } from '@capacitor/cli';
import { writeFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * The app is a native shell around the live site: `server.url` points the
 * WebView at a Django deployment instead of a bundled build, so site changes
 * ship on deploy with no store review.
 *
 * Which deployment is chosen when the native projects are synced
 * (`npm run sync:<env>`), and baked into that build.
 */
const SERVER_URLS = {
  // iOS Simulator shares the Mac's network, so localhost reaches runserver.
  dev: 'http://localhost:8000',
  // Cert hostnames rotate per platform.sh environment, so the URL is passed in.
  cert: process.env.BORROWD_CERT_URL,
  prod: 'https://app.borrowd.org',
};

type AppEnv = keyof typeof SERVER_URLS;

// Commands that copy this config into ios/ and android/, so the build gets
// whichever server URL was chosen. Others (e.g. `cap open`) don't need one.
const CONFIG_COPYING_COMMANDS = ['add', 'copy', 'run', 'sync'];

function serverUrl(): { appEnv: AppEnv; url: string } | null {
  const appEnv = process.env.BORROWD_APP_ENV;
  if (!appEnv) {
    const command = process.argv.find((arg) =>
      CONFIG_COPYING_COMMANDS.includes(arg),
    );
    if (!command) {
      return null;
    }
  }
  if (!appEnv || !(appEnv in SERVER_URLS)) {
    throw new Error(
      `Set BORROWD_APP_ENV to one of: ${Object.keys(SERVER_URLS).join(', ')} ` +
        '(use `npm run sync:<env>`).',
    );
  }
  const url = SERVER_URLS[appEnv as AppEnv];
  if (!url) {
    throw new Error('Set BORROWD_CERT_URL to the cert environment URL.');
  }
  return { appEnv: appEnv as AppEnv, url };
}

const server = serverUrl();

if (server) {
  // The offline page's "Try again" needs the site URL, which differs per build.
  writeFileSync(
    join(__dirname, 'www', 'server-url.js'),
    `window.BORROWD_SERVER_URL = ${JSON.stringify(server.url)};\n`,
  );
}

const config: CapacitorConfig = {
  // Must match NATIVE_APP_ID in borrowd/config/base.py.
  appId: 'org.borrowd.app',
  appName: "Borrow'd",
  // Only used for the offline page below; the site itself is loaded from `url`.
  webDir: 'www',
  server: server ? {
    url: server.url,
    cleartext: server.appEnv === 'dev',
    // Shown when the site can't be reached, instead of a blank WebView.
    errorPath: 'offline.html',
  } : undefined,
  ios: {
    // Keep the site's top bar below the status bar and its bottom content
    // above the home indicator, without the site needing safe-area CSS.
    contentInset: 'always',
  },
  plugins: {
    SplashScreen: {
      // static/js/native-app.js hides it as soon as the first page renders;
      // this is the fallback if that never happens.
      launchShowDuration: 3000,
      launchAutoHide: true,
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
};

export default config;
