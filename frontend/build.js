import * as esbuild from 'esbuild';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const distDir = path.join(__dirname, 'dist');
if (!fs.existsSync(distDir)) {
  fs.mkdirSync(distDir, { recursive: true });
}

const isDev = process.argv.includes('--dev');

async function runBuild() {
  console.log(`--- Starting Frontend ${isDev ? 'DEVELOPMENT' : 'PRODUCTION'} Build Pipeline ---`);
  if (isDev) {
    console.log('Mode: DEVELOPMENT (sourcemap: inline, minify: false - tối ưu debug Tauri/DevTools)');
  } else {
    console.log('Mode: PRODUCTION (sourcemap: false, minify: true - tối ưu bảo mật & dung lượng)');
  }

  // Dọn dẹp chunks và sourcemaps cũ trước khi build để tránh phình dung lượng
  fs.rmSync(path.join(__dirname, 'dist', 'chunks'), { recursive: true, force: true });
  fs.rmSync(path.join(__dirname, 'chunks'), { recursive: true, force: true });
  for (const oldMap of ['mobile.bundle.js.map', 'app.min.js.map']) {
    fs.rmSync(path.join(distDir, oldMap), { force: true });
  }

  const legalBanner = '/*! FnBOps WFM — Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC <hoanh@vnaigc.com>). Licensed under GNU AGPL-3.0-only. Source: https://github.com/nguyendaihoanh/fnbop */';

  // 1. Bundle mobile.js with code-splitting for dynamic i18n
  const mobileResult = await esbuild.build({
    entryPoints: { 'mobile.bundle': path.join(__dirname, 'mobile.js') },
    bundle: true,
    splitting: true,
    minify: !isDev,
    legalComments: 'inline',
    banner: { js: legalBanner },
    sourcemap: isDev ? 'inline' : false,
    target: ['es2020'],
    format: 'esm',
    outdir: distDir,
    chunkNames: 'chunks/[name]-[hash]',
    metafile: true
  });
  console.log('✓ mobile.bundle.js compiled successfully.');

  // 1b. Synchronize chunks to frontend/chunks directory for root static serving
  const distChunks = path.join(distDir, 'chunks');
  const webChunks = path.join(__dirname, 'chunks');
  if (fs.existsSync(distChunks)) {
    if (!fs.existsSync(webChunks)) {
      fs.mkdirSync(webChunks, { recursive: true });
    }
    const chunkFiles = fs.readdirSync(distChunks);
    for (const f of chunkFiles) {
      fs.copyFileSync(path.join(distChunks, f), path.join(webChunks, f));
    }
    console.log(`✓ Synchronized ${chunkFiles.length} chunk files to frontend/chunks.`);
  }

  // 2. Compile app.js
  const appResult = await esbuild.build({
    entryPoints: [path.join(__dirname, 'app.js')],
    bundle: false,
    minify: !isDev,
    legalComments: 'inline',
    banner: { js: legalBanner },
    sourcemap: isDev ? 'inline' : false,
    target: ['es2020'],
    outfile: path.join(distDir, 'app.min.js'),
    metafile: true
  });
  console.log('✓ app.min.js compiled successfully.');

  // 3. Security Audit on Generated Output (Zero-Trust)
  const forbiddenPatterns = [
    /fnbop_secret_fallback/i,
    /cc\.vnaigc\.com/i,
    /CONFIDENTIAL_API_KEY/i,
    /PRIVATE_KEY/i
  ];

  function scanDir(dir) {
    const files = fs.readdirSync(dir);
    for (const f of files) {
      const fullPath = path.join(dir, f);
      if (fs.statSync(fullPath).isDirectory()) {
        scanDir(fullPath);
      } else if (f.endsWith('.js')) {
        const content = fs.readFileSync(fullPath, 'utf-8');
        for (const pattern of forbiddenPatterns) {
          if (pattern.test(content)) {
            throw new Error(`CRITICAL SECURITY FAILURE: Hardcoded secret/forbidden pattern "${pattern}" detected in ${f}!`);
          }
        }
      }
    }
  }
  scanDir(distDir);
  console.log('✓ Zero-Trust Verification passed: 0 secret keys / forbidden strings present in dist artifacts.');
  console.log('--- Frontend Build Completed Successfully ---');
}

runBuild().catch(err => {
  console.error('Build failed:', err);
  process.exit(1);
});
