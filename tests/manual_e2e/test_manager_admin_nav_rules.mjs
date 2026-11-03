import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';

const ARTIFACT_DIR = '/tmp';
const BASE_URL = process.env.TEST_URL || 'http://localhost:8100';

async function run() {
  const tmpProfile = `/tmp/puppeteer_manager_nav_test_${Date.now()}`;
  let browser;

  try {
    browser = await puppeteer.launch({
      executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--no-default-browser-check',
        `--user-data-dir=${tmpProfile}`
      ]
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 412, height: 915, isMobile: true, hasTouch: true });

    console.log('--- TEST 1: MANAGER LOGIN & NAV BAR DOCK VERIFICATION ---');
    await page.goto(`${BASE_URL}/`, { waitUntil: 'networkidle2', timeout: 15000 });

    // Login as Manager (manager / 8888)
    await page.waitForSelector('#loginUser', { timeout: 5000 });
    await page.$eval('#loginUser', el => el.value = '');
    await page.type('#loginUser', 'manager');
    await page.$eval('#loginPass', el => el.value = '');
    await page.type('#loginPass', '8888');
    await page.evaluate(() => {
      const btn = document.getElementById('btnLoginSubmit');
      if (btn) btn.click();
    });

    await page.waitForFunction(() => {
      const gate = document.getElementById('authGateScreen');
      return gate && gate.style.display === 'none';
    }, { timeout: 8000 });
    await new Promise(r => setTimeout(r, 1000));

    // Verify Manager Nav Rules
    const managerNavData = await page.evaluate(() => {
      const nav = document.getElementById('bottomNav');
      const tabs = ['ops', 'roster', 'attendance', 'payslip'];
      const pill = document.getElementById('navSlidingPill');
      const navRect = nav.getBoundingClientRect();
      const attendanceBtn = document.getElementById('navAttendanceBtn');
      const heroSurface = attendanceBtn ? attendanceBtn.querySelector('.hero-action-surface') : null;

      const tabMetrics = tabs.map(t => {
        const btn = document.getElementById(`nav${t.charAt(0).toUpperCase() + t.slice(1)}Btn`);
        const rect = btn ? btn.getBoundingClientRect() : null;
        return {
          tab: t,
          display: btn ? window.getComputedStyle(btn).display : 'missing',
          width: rect ? rect.width : 0,
          left: rect ? rect.left : 0,
          hasHeroClass: btn ? btn.classList.contains('nav-hero-action') : false,
          isActive: btn ? btn.classList.contains('active') : false
        };
      });

      return {
        hasNavCradleMode: nav.classList.contains('nav-cradle-mode'),
        hasStaffNavLayout: nav.classList.contains('staff-nav-layout'),
        tabMetrics,
        navWidth: navRect.width,
        attendanceHasHeroClass: attendanceBtn ? attendanceBtn.classList.contains('nav-hero-action') : false,
        heroSurfaceComputed: heroSurface ? {
          background: window.getComputedStyle(heroSurface).background,
          borderRadius: window.getComputedStyle(heroSurface).borderRadius,
          height: window.getComputedStyle(heroSurface).height,
          boxShadow: window.getComputedStyle(heroSurface).boxShadow
        } : null,
        pillOpacity: pill ? window.getComputedStyle(pill).opacity : 'missing',
        pillWidth: pill ? window.getComputedStyle(pill).width : 'missing',
        pillTransform: pill ? window.getComputedStyle(pill).transform : 'missing'
      };
    });

    console.log('Manager Nav Metrics:');
    console.log('- hasNavCradleMode:', managerNavData.hasNavCradleMode, '(Expected: false)');
    console.log('- hasStaffNavLayout:', managerNavData.hasStaffNavLayout, '(Expected: false)');
    console.log('- attendanceHasHeroClass:', managerNavData.attendanceHasHeroClass, '(Expected: false)');
    console.log('- Tab widths:', managerNavData.tabMetrics.map(t => `${t.tab}: ${t.width.toFixed(1)}px`));
    console.log('- Pill on Ops:', { opacity: managerNavData.pillOpacity, width: managerNavData.pillWidth, transform: managerNavData.pillTransform });

    // Assert Manager rules
    if (managerNavData.hasNavCradleMode) throw new Error('Manager navbar MUST NOT have nav-cradle-mode!');
    if (managerNavData.attendanceHasHeroClass) throw new Error('Manager attendance button MUST NOT have nav-hero-action!');
    
    // Check equal width variance across 4 tabs (< 5px variance)
    const widths = managerNavData.tabMetrics.map(t => t.width);
    const minW = Math.min(...widths);
    const maxW = Math.max(...widths);
    console.log(`- Width variance: ${(maxW - minW).toFixed(2)}px (Expected: < 5px for equal 25% distribution)`);
    if (maxW - minW > 5) throw new Error(`Tabs do not have equal widths! Variance: ${maxW - minW}px`);

    // Screenshot Ops tab
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'manager_dock_ops.png') });

    // Click attendance tab and verify pill transitions to attendance
    console.log('--- Switching Manager to Attendance tab ---');
    await page.evaluate(() => {
      const btn = document.getElementById('navAttendanceBtn');
      if (btn) btn.click();
    });
    await new Promise(r => setTimeout(r, 600));

    const managerAttendanceData = await page.evaluate(() => {
      const pill = document.getElementById('navSlidingPill');
      const attendanceBtn = document.getElementById('navAttendanceBtn');
      return {
        isAttendanceActive: attendanceBtn.classList.contains('active'),
        pillOpacity: pill ? window.getComputedStyle(pill).opacity : 'missing',
        pillWidth: pill ? window.getComputedStyle(pill).width : 'missing',
        pillTransform: pill ? window.getComputedStyle(pill).transform : 'missing'
      };
    });
    console.log('Manager Attendance Tab Metrics:', managerAttendanceData);
    if (!managerAttendanceData.isAttendanceActive) throw new Error('Attendance tab is not active!');
    if (managerAttendanceData.pillOpacity !== '1') throw new Error(`Sliding pill opacity must be 1 on attendance tab for manager! Got: ${managerAttendanceData.pillOpacity}`);

    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'manager_dock_attendance.png') });

    // Switch to dark theme
    await page.evaluate(() => {
      document.documentElement.setAttribute('data-theme', 'dark');
    });
    await new Promise(r => setTimeout(r, 300));
    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'manager_dock_dark.png') });

    // Switch back to light theme
    await page.evaluate(() => {
      document.documentElement.setAttribute('data-theme', 'light');
    });

    // Logout and Test Staff Role
    console.log('--- TEST 2: STAFF LOGIN & CRADLE HERO FAB VERIFICATION ---');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
      location.reload();
    });
    await page.waitForNavigation({ waitUntil: 'networkidle2' });

    await page.waitForSelector('#loginUser', { timeout: 5000 });
    await page.$eval('#loginUser', el => el.value = '');
    await page.type('#loginUser', 'nhanvien');
    await page.$eval('#loginPass', el => el.value = '');
    await page.type('#loginPass', '1111');
    await page.evaluate(() => {
      const btn = document.getElementById('btnLoginSubmit');
      if (btn) btn.click();
    });

    await page.waitForFunction(() => {
      const gate = document.getElementById('authGateScreen');
      return gate && gate.style.display === 'none';
    }, { timeout: 8000 });
    await new Promise(r => setTimeout(r, 1000));

    // Verify Staff Nav Rules
    const staffNavData = await page.evaluate(() => {
      const nav = document.getElementById('bottomNav');
      const tabs = ['ops', 'roster', 'attendance', 'payslip'];
      const pill = document.getElementById('navSlidingPill');
      const attendanceBtn = document.getElementById('navAttendanceBtn');
      const cradlePath = document.getElementById('navCradlePath');

      const tabMetrics = tabs.map(t => {
        const btn = document.getElementById(`nav${t.charAt(0).toUpperCase() + t.slice(1)}Btn`);
        return {
          tab: t,
          display: btn ? window.getComputedStyle(btn).display : 'missing',
          hasHeroClass: btn ? btn.classList.contains('nav-hero-action') : false,
          isActive: btn ? btn.classList.contains('active') : false
        };
      });

      return {
        hasNavCradleMode: nav.classList.contains('nav-cradle-mode'),
        hasStaffNavLayout: nav.classList.contains('staff-nav-layout'),
        attendanceHasHeroClass: attendanceBtn ? attendanceBtn.classList.contains('nav-hero-action') : false,
        tabMetrics,
        cradlePathD: cradlePath ? cradlePath.getAttribute('d') : null,
        pillOpacity: pill ? window.getComputedStyle(pill).opacity : 'missing'
      };
    });

    console.log('Staff Nav Metrics:');
    console.log('- hasNavCradleMode:', staffNavData.hasNavCradleMode, '(Expected: true)');
    console.log('- hasStaffNavLayout:', staffNavData.hasStaffNavLayout, '(Expected: true)');
    console.log('- attendanceHasHeroClass:', staffNavData.attendanceHasHeroClass, '(Expected: true)');
    console.log('- cradlePath exists:', !!staffNavData.cradlePathD);
    console.log('- Pill opacity on staff attendance (Hero FAB):', staffNavData.pillOpacity, '(Expected: 0)');
    console.log('- Visible tabs:', staffNavData.tabMetrics.filter(t => t.display !== 'none').map(t => t.tab));

    if (!staffNavData.hasNavCradleMode) throw new Error('Staff navbar MUST have nav-cradle-mode!');
    if (!staffNavData.attendanceHasHeroClass) throw new Error('Staff attendance button MUST have nav-hero-action!');
    if (staffNavData.pillOpacity !== '0') throw new Error(`Sliding pill opacity must be 0 for staff hero tab! Got: ${staffNavData.pillOpacity}`);

    await page.screenshot({ path: path.join(ARTIFACT_DIR, 'staff_cradle_attendance.png') });

    console.log('=== ALL NAV DOCK TESTS PASSED SUCCESSFULLY! ===');
  } catch (err) {
    console.error('TEST ERROR:', err);
    process.exitCode = 1;
  } finally {
    if (browser) {
      await browser.close();
    }
    try {
      fs.rmSync(tmpProfile, { recursive: true, force: true });
    } catch (e) {}
  }
}

run();
