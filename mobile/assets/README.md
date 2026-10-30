# App icon and splash screen sources

The PNGs here are rendered from `static/icon.svg` and are the inputs
[`@capacitor/assets`](https://github.com/ionic-team/capacitor-assets) turns
into every icon and splash size under `ios/` and `android/`.

| File | Used for |
| --- | --- |
| `icon-only.png` | iOS app icon (opaque, 1024×1024) |
| `icon-foreground.png`, `icon-background.png` | Android adaptive icon layers |
| `splash.png`, `splash-dark.png` | Launch screen, light and dark mode (2732×2732, cropped to the screen) |

To regenerate after the logo changes, from `mobile/`:

```bash
# Run from a scratch directory rather than adding these tools to package.json:
# @capacitor/assets 3.x pins old sharp/tar releases that npm audit flags.
npm install --prefix /tmp/assetgen @capacitor/assets@3.0.5
NODE_PATH=/tmp/assetgen/node_modules node assets/render-sources.js ../static/icon.svg assets
/tmp/assetgen/node_modules/.bin/capacitor-assets generate --ios --android \
    --iconBackgroundColor '#ffffff' --iconBackgroundColorDark '#0b0907' \
    --splashBackgroundColor '#ffffff' --splashBackgroundColorDark '#0b0907'
```

The generator also rewrites files it shouldn't; discard those changes:

```bash
git checkout android/app/src/main/AndroidManifest.xml \
    android/app/src/main/res/mipmap-anydpi-v26/
rm android/app/src/main/res/mipmap-*/ic_launcher_background.png
```

(Its adaptive icon insets the background layer too, leaving a ring the
launcher fills with its own theme color.)
