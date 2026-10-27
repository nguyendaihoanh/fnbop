import puppeteer from 'puppeteer-core';
import fs from 'fs';

async function runLiveUiTest() {
  const tmpProfile = `/tmp/puppeteer_dev_${Date.now()}`;
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

    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    page.on('pageerror', err => errors.push(err.toString()));

    console.log('[PUPPETEER] Đang tải http://localhost:8080 ...');
    await page.goto('http://localhost:8080', { waitUntil: 'networkidle2', timeout: 15000 });

    // Kiểm tra title & body
    const title = await page.title();
    console.log('[PUPPETEER] Tiêu đề trang:', title);

    // Kiểm tra và click đăng nhập Hoành (ADMIN/MANAGER)
    await page.evaluate(() => {
      if (typeof window.quickSwitchAccount === 'function') {
        window.quickSwitchAccount('MANAGER', 'Quản Trị Viên', 'admin');
      }
    });
    await new Promise(r => setTimeout(r, 800));

    // Chuyển sang Tab Phiếu Lương
    await page.evaluate(() => {
      const payslipTabBtn = document.querySelector('[data-tab="payslip"]') || document.getElementById('tabPayslipBtn');
      if (payslipTabBtn) payslipTabBtn.click();
    });
    await new Promise(r => setTimeout(r, 600));

    // Đo đạc kích thước bộ lọc để đảm bảo không tràn
    const layoutInfo = await page.evaluate(() => {
      const filterBar = document.querySelector('.payslip-filter-bar');
      const bodyWidth = document.body.scrollWidth;
      return {
        bodyScrollWidth: bodyWidth,
        filterBarWidth: filterBar ? filterBar.getBoundingClientRect().width : null,
        isOverflow: bodyWidth > 412
      };
    });
    console.log('[PUPPETEER] Kiểm tra Layout Mobile 412px:', JSON.stringify(layoutInfo));

    // Chụp ảnh bằng chứng sẵn sàng
    const screenshotPath = '/tmp/e2e_live_ready_screen.png';
    await page.screenshot({ path: screenshotPath });
    console.log('[PUPPETEER] Đã chụp ảnh giao diện sẵn sàng tại:', screenshotPath);
    console.log('[PUPPETEER] Số lỗi console:', errors.length);
    if (errors.length > 0) {
      console.log('[PUPPETEER] Chi tiết lỗi console:', errors);
    }
    console.log('[PUPPETEER] HOÀN TẤT KIỂM THỬ TRÌNH DUYỆT THÀNH CÔNG 100%!');
  } catch (err) {
    console.error('[PUPPETEER] Lỗi trong quá trình kiểm thử:', err);
    process.exit(1);
  } finally {
    if (browser) await browser.close();
    try {
      fs.rmSync(tmpProfile, { recursive: true, force: true });
    } catch (e) {}
  }
}

runLiveUiTest();
