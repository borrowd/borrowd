# Borrow'd iOS and Android apps

A [Capacitor](https://capacitorjs.com/) shell: a native app whose WebView
loads the live Django site (`server.url` in `capacitor.config.ts`). Site
changes reach app users on deploy, with no store review; only changes in
this folder need a new app build.

- `ios/`, `android/` — the native projects (open them in Xcode / Android Studio)
- `capacitor.config.ts` — app ID, which site to load, plugin settings
- `offline.html` — shown when the site can't be reached; copied into `www/`
  with the site URL filled in on every sync
- `assets/` — app icon and splash sources (see `assets/README.md`)

The site side lives outside this folder: `static/js/native-app.js` (runs only
inside the app) and the Universal Links / App Links files served at
`/.well-known/` (`borrowd_web/views.py`).

## Setup

You need [Xcode](https://developer.apple.com/xcode/) for iOS and
[Android Studio](https://developer.android.com/studio) for Android, with
**Java 21** as Android Studio's Gradle JDK (Settings → Build, Execution,
Deployment → Build Tools → Gradle → Gradle JDK). Newer Java versions fail
with "Unsupported class file major version".

```bash
cd mobile
npm install
```

## Running against your local site

Start the site as usual (`npm run dev` and `uv run manage.py runserver` from
the repo root), then from `mobile/`:

```bash
npm run sync:dev       # point the apps at http://localhost:8000
npm run open:ios       # then pick an iPhone simulator and press ⌘R
npm run open:android   # then start an emulator and press Run
```

On Android, `localhost` inside the emulator is the emulator itself. Forward
the site's ports to your Mac after each emulator start:

```bash
adb reverse tcp:8000 tcp:8000   # Django
adb reverse tcp:5173 tcp:5173   # Vite
```

(`adb` is in `~/Library/Android/sdk/platform-tools/` on macOS.)

Re-run `npm run sync:<env>` after changing anything in this folder.

## Environments

| Command | Loads |
| --- | --- |
| `npm run sync:dev` | `http://localhost:8000` |
| `BORROWD_CERT_URL=https://… npm run sync:cert` | a cert environment (its URL changes per deploy) |
| `npm run sync:prod` | `https://app.borrowd.org` |

The synced URL is baked into the next build, so sync the right environment
before building for testers or the stores.

## Universal Links / App Links

Links to `app.borrowd.org` (e.g. in emails) open in the app on prod only.
They need these set on the prod environment, otherwise the `/.well-known/`
files return 404:

- `APPLE_TEAM_ID` — from the Apple Developer account
- `ANDROID_CERT_SHA256_FINGERPRINTS` — comma-separated; use the app signing
  key's fingerprint from Play Console's App signing page
