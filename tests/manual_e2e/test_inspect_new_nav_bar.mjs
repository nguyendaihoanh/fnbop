import puppeteer from 'puppeteer-core';
import fs from 'fs';

async function captureNewPulseNavbar() {
  const tmpProfile = `/tmp/puppeteer_nav_${Date.now()}`;
  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--no-default-browser-check',
        `--user-data-dir=${tmpProfile}`
      ]
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 412, height: 915, isMobile: true });

    await page.goto('http://localhost:8080', { waitUntil: 'networkidle2', timeout: 15000 });

    // Đăng nhập Hoành
    await page.evaluate(() => {
      if (typeof window.quickSwitchAccount === 'function') {
        window.quickSwitchAccount('MANAGER', 'Quản Trị Viên', 'admin');
      }
    });
    await new Promise(r => setTimeout(r, 800));

    // 1. LIGHT MODE
    await page.evaluate(() => {
      document.documentElement.setAttribute('data-theme', 'light');
      localStorage.setItem('fnbops_theme', 'light');
    });
    await new Promise(r => setTimeout(r, 500));

    // Crop Bottom Bar Light
    const navElLight = await page.$('#bottomNav');
    const barImgLight = '/tmp/e2e_pulse_nav_light_bar.png';
    if (navElLight) {
      await navElLight.screenshot({ path: barImgLight });
      console.log('[PUPPETEER] Đã lưu:', barImgLight);
    }

    // 2. DARK MODE
    await page.evaluate(() => {
      document.documentElement.setAttribute('data-theme', 'dark');
      localStorage.setItem('fnbops_theme', 'dark');
    });
    await new Promise(r => setTimeout(r, 500));

    // Crop Bottom Bar Dark
    const navElDark = await page.$('#bottomNav');
    const barImgDark = '/tmp/e2e_pulse_nav_dark_bar.png';
    if (navElDark) {
      await navElDark.screenshot({ path: barImgDark });
      console.log('[PUPPETEER] Đã lưu:', barImgDark);
    }

    // Full screen Dark Mode
    const fullImgDark = '/tmp/e2e_pulse_nav_dark_full.png';
    await page.screenshot({ path: fullImgDark });
    console.log('[PUPPETEER] Đã lưu:', fullImgDark);

    console.log('[PUPPETEER] HOÀN TẤT!');
  } catch (err) {
    console.error('[PUPPETEER] Lỗi:', err);
    process.exit(1);
  } finally {
    if (browser) await browser.close();
    try {
      fs.rmSync(tmpProfile, { recursive: true, force: true });
    } catch (e) {}
  }
}

captureNewPulseNavbar();
