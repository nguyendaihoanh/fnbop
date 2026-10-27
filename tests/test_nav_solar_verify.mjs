import puppeteer from 'puppeteer-core';
import fs from 'fs';

const ARTIFACT_DIR = '/tmp';
const tmpProfile = `/tmp/puppeteer_nav_verify_${Date.now()}`;

let browser;
try {
  browser = await puppeteer.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--no-default-browser-check',
      '--disable-gpu',
      `--user-data-dir=${tmpProfile}`
    ]
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 412, height: 915, isMobile: true });

  // Load page — dùng load thay networkidle2 để tránh treo
  await page.goto('http://localhost:8080', { waitUntil: 'load', timeout: 10000 });
  await new Promise(r => setTimeout(r, 2000));

  // Quick login
  await page.evaluate(() => {
    if (typeof window.quickSwitchAccount === 'function') {
      window.quickSwitchAccount('MANAGER', 'Quản Trị Viên', 'admin');
    }
  });
  await new Promise(r => setTimeout(r, 1000));

  // === LIGHT MODE ===
  await page.evaluate(() => {
    document.documentElement.setAttribute('data-theme', 'light');
    localStorage.setItem('fnbops_theme', 'light');
  });
  await new Promise(r => setTimeout(r, 600));

  // Chụp full screen light
  await page.screenshot({ path: `${ARTIFACT_DIR}/e2e_pulse_nav_light_full.png` });
  console.log('[OK] Light full saved');

  // Chụp nav bar crop: lấy bounding rect rồi screenshot vùng đó
  const navBox = await page.evaluate(() => {
    const nav = document.getElementById('bottomNav');
    if (!nav) return null;
    const r = nav.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  });
  if (navBox) {
    await page.screenshot({
      path: `${ARTIFACT_DIR}/e2e_pulse_nav_light_bar.png`,
      clip: navBox
    });
    console.log('[OK] Light nav bar saved, box:', JSON.stringify(navBox));
  }

  // Kiểm tra iconify-icon trong nav
  const navIcons = await page.evaluate(() => {
    const nav = document.getElementById('bottomNav');
    if (!nav) return [];
    return Array.from(nav.querySelectorAll('iconify-icon')).map(el => ({
      icon: el.getAttribute('icon'),
      rendered: el.shadowRoot ? el.shadowRoot.innerHTML.includes('<svg') : el.innerHTML.includes('<svg'),
      tab: el.closest('[data-tab]')?.getAttribute('data-tab')
    }));
  });
  console.log('[ICONS]', JSON.stringify(navIcons, null, 2));

  // === DARK MODE ===
  try {
    await page.evaluate(() => {
      document.documentElement.setAttribute('data-theme', 'dark');
    });
    await new Promise(r => setTimeout(r, 800));

    await page.screenshot({ path: `${ARTIFACT_DIR}/e2e_pulse_nav_dark_full.png` });
    console.log('[OK] Dark full saved');

    // Reuse navBox từ light mode (fixed nav không đổi vị trí)
    if (navBox) {
      await page.screenshot({
        path: `${ARTIFACT_DIR}/e2e_pulse_nav_dark_bar.png`,
        clip: navBox
      });
      console.log('[OK] Dark nav bar saved');
    }
  } catch (darkErr) {
    console.warn('[WARN] Dark mode skipped:', darkErr.message);
  }

  console.log('[DONE] All screenshots saved.');

} catch (err) {
  console.error('[ERROR]', err.message);
  process.exit(1);
} finally {
  if (browser) await browser.close();
  try { fs.rmSync(tmpProfile, { recursive: true, force: true }); } catch {}
}
