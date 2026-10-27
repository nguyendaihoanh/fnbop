const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: 'new',
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--no-default-browser-check']
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 412, height: 915, isMobile: true });
    
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', err => errors.push(err.toString()));

    await page.goto('http://localhost:8100', { waitUntil: 'networkidle2', timeout: 15000 });
    
    // Kiểm tra các phần tử cốt lõi
    const bodyExists = await page.$('body');
    const headerTitle = await page.evaluate(() => document.title);
    console.log('Page Title:', headerTitle);

    // Chụp ảnh giao diện sẵn sàng
    const outImg = '/tmp/e2e_live_ready_screen.png';
    await page.screenshot({ path: outImg });
    console.log('Saved screenshot to:', outImg);
    console.log('Console errors during load:', errors.length);
    if (errors.length > 0) {
      console.log('Sample error:', errors.slice(0, 3));
    }
  } catch (err) {
    console.error('Puppeteer run error:', err);
    process.exit(1);
  } finally {
    if (browser) await browser.close();
  }
})();
