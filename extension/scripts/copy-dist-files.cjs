const fs = require('fs');
const path = require('path');

const rootDir = path.resolve(__dirname, '..');
const distDir = path.join(rootDir, 'dist');

// Ensure dist directory exists
if (!fs.existsSync(distDir)) {
  fs.mkdirSync(distDir, { recursive: true });
}

const filesToCopy = [
  { src: 'manifest.json', dest: 'manifest.json' },
  // popup.html is handled by Vite
  // { src: 'src/popup/popup.html', dest: 'popup.html' },
  // popup.css is likely handled by Vite too if imported, but we'll leave it if it's static
  { src: 'src/popup/popup.css', dest: 'popup.css' }
];

filesToCopy.forEach(file => {
  const srcPath = path.join(rootDir, file.src);
  const destPath = path.join(distDir, file.dest);

  if (fs.existsSync(srcPath)) {
    fs.copyFileSync(srcPath, destPath);
    console.log(`Copied ${file.src} -> dist/${file.dest}`);
  } else {
    // Only log if it's not the popup.html we just commented out
    if (!file.src.includes('popup.html')) {
        console.log(`Source not found, skipping: ${srcPath}`);
    }
  }
});