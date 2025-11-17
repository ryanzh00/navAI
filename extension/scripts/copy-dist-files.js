const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..'); // extension/
const dist = path.join(root, 'dist');
const files = ['manifest.json', 'popup.html'];

if (!fs.existsSync(dist)) {
  console.warn('dist directory does not exist — skipping copy');
  process.exit(0);
}

files.forEach((f) => {
  const src = path.join(root, f);
  const dest = path.join(dist, f);
  try {
    if (!fs.existsSync(src)) {
      console.warn(`Source not found, skipping: ${src}`);
      return;
    }
    fs.copyFileSync(src, dest);
    console.log(`Copied ${f} -> dist/${f}`);
  } catch (err) {
    console.error(`Failed to copy ${f}:`, err);
    process.exitCode = 1;
  }
});
