// Renders mobile/assets/*.png (capacitor-assets inputs) from static/icon.svg.
const sharp = require('sharp');
const fs = require('fs');
const [svgPath, outDir] = process.argv.slice(2);
const svg = fs.readFileSync(svgPath, 'utf8')
  .replace(/@media\(prefers-color-scheme:dark\)\{[^}]*\}\}/, '');
const INK = '#0b0907', PAPER = '#ffffff';

async function bee(color, size) {
  const src = Buffer.from(svg.replace(/fill:#0b0907/, `fill:${color}`));
  const trimmed = await sharp(src, { density: 600 }).trim().png().toBuffer();
  return sharp(trimmed).resize(size, size, { fit: 'contain', background: '#0000' }).png().toBuffer();
}
async function canvas(size, bg, mark, markSize) {
  const base = sharp({ create: { width: size, height: size, channels: 4, background: bg } });
  return base.composite([{ input: await bee(mark, markSize), gravity: 'center' }]).png();
}
(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  // iOS icon: opaque, no transparency allowed by the App Store.
  await (await canvas(1024, PAPER, INK, 660)).flatten({ background: PAPER }).toFile(`${outDir}/icon-only.png`);
  // Android adaptive icon: capacitor-assets insets this into the launcher safe zone.
  await (await canvas(1024, '#0000', INK, 720)).toFile(`${outDir}/icon-foreground.png`);
  await sharp({ create: { width: 1024, height: 1024, channels: 4, background: PAPER } }).png().toFile(`${outDir}/icon-background.png`);
  // Splash: 2732 square, cropped to the screen shape, so the bee sits small in the middle.
  await (await canvas(2732, PAPER, INK, 520)).flatten({ background: PAPER }).toFile(`${outDir}/splash.png`);
  await (await canvas(2732, INK, PAPER, 520)).flatten({ background: INK }).toFile(`${outDir}/splash-dark.png`);
})();
