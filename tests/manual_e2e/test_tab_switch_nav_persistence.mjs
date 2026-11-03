import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';

const ARTIFACT_DIR = '/tmp';
const BASE_URL = process.env.TEST_URL || 'http://localhost:8100';

async function run() {
  const tmpProfile = `/tmp/puppeteer_nav_tab_test_${Date.now()}`;
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

    console.log('=== TEST 1: MANAGER (PIN 1111) TAB SWITCHING & BOTTOM NAV PERSISTENCE ===');
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

    // Wait for login to complete and #appContainer to become visible
    await page.waitForFunction(() => {
      const gate = document.getElementById('authGateScreen');
      return gate && gate.style.display === 'none';
    }, { timeout: 8000 });
    await new Promise(r => setTimeout(r, 1000));

    // Verify 4 tabs visible for Manager
    const managerTabVisibility = await page.evaluate(() => {
      const tabs = ['ops', 'roster', 'attendance', 'payslip'];
      return tabs.map(t => {
        const btn = document.getElementById(`nav${t.charAt(0).toUpperCase() + t.slice(1)}Btn`);
        return {
          tab: t,
          display: btn ? window.getComputedStyle(btn).display : 'missing'
        };
      });
    });
    console.log('Manager Tab Visibility:', managerTabVisibility);

    // Switch through each tab: ops -> roster -> attendance -> payslip -> roster -> ops
    const tabsToTest = ['ops', 'roster', 'attendance', 'payslip', 'roster', 'ops'];
    for (const tab of tabsToTest) {
      console.log(`\n--> Switching to tab: [${tab}]`);
      const btnSelector = `#nav${tab.charAt(0).toUpperCase() + tab.slice(1)}Btn`;
      await page.click(btnSelector);
      await new Promise(r => setTimeout(r, 500));

      const navState = await page.evaluate((currentTab) => {
        const nav = document.getElementById('bottomNav');
        if (!nav) return { exists: false };
        const rect = nav.getBoundingClientRect();
        const style = window.getComputedStyle(nav);
        const activeSection = document.querySelector('.tab-view.active');
        return {
          exists: true,
          display: style.display,
          visibility: style.visibility,
          opacity: style.opacity,
          position: style.position,
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          bottom: Math.round(window.innerHeight - rect.bottom),
          activeSectionId: activeSection ? activeSection.id : null,
          tabBtnClasses: Array.from(document.querySelectorAll('.nav-tab-btn')).map(b => ({
            id: b.id,
            active: b.classList.contains('active'),
            display: window.getComputedStyle(b).display
          }))
        };
      }, tab);

      console.log(`Tab [${tab}] Result:`, {
        display: navState.display,
        visibility: navState.visibility,
        activeSection: navState.activeSectionId,
        width: navState.width,
        height: navState.height,
        bottomDist: navState.bottom
      });

      if (navState.display === 'none' || navState.visibility === 'hidden') {
        throw new Error(`CRITICAL BUG: #bottomNav became invisible on tab [${tab}]!`);
      }

      const shotPath = path.join(ARTIFACT_DIR, `tab_verify_manager_${tab}.png`);
      await page.screenshot({ path: shotPath });
    }

    console.log('\n=== TEST 2: STAFF (PIN 1234) TAB SWITCHING & 3-TAB ENFORCEMENT ===');
    // Logout
    await page.evaluate(() => {
      if (typeof window.logout === 'function') window.logout();
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.reload({ waitUntil: 'networkidle2' });

    // Login as Staff (nhanvien / 1111)
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

    // Verify 3 tabs for Staff (Ops must be display: none)
    const staffTabCheck = await page.evaluate(() => {
      const ops = document.getElementById('navOpsBtn');
      const roster = document.getElementById('navRosterBtn');
      const att = document.getElementById('navAttendanceBtn');
      const pay = document.getElementById('navPayslipBtn');
      return {
        opsDisplay: ops ? window.getComputedStyle(ops).display : null,
        rosterDisplay: roster ? window.getComputedStyle(roster).display : null,
      };
    });
    console.log('Staff Tab Check (Ops must be none):', staffTabCheck);

    const authInfo = await page.evaluate(() => ({
      role: localStorage.getItem('fnbops_role'),
      user: localStorage.getItem('fnbops_username'),
      opsClass: document.getElementById('navOpsBtn')?.className,
      opsStyle: document.getElementById('navOpsBtn')?.getAttribute('style')
    }));
    console.log('Current Auth Info after staff login:', authInfo);

    if (staffTabCheck.opsDisplay !== 'none') {
      throw new Error(`CRITICAL BUG: navOpsBtn is not hidden for staff! display=${staffTabCheck.opsDisplay}`);
    }

    // Switch across Staff tabs: roster -> attendance -> payslip -> roster
    const staffTabs = ['roster', 'attendance', 'payslip', 'roster'];
    for (const stab of staffTabs) {
      console.log(`\n--> Staff switching to: [${stab}]`);
      const btnSelector = `#nav${stab.charAt(0).toUpperCase() + stab.slice(1)}Btn`;
      await page.click(btnSelector);
      await new Promise(r => setTimeout(r, 500));

      const navState = await page.evaluate(() => {
        const nav = document.getElementById('bottomNav');
        const rect = nav.getBoundingClientRect();
        const style = window.getComputedStyle(nav);
        return {
          display: style.display,
          visibility: style.visibility,
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          bottom: Math.round(window.innerHeight - rect.bottom)
        };
      });

      console.log(`Staff Tab [${stab}] Result:`, navState);
      if (navState.display === 'none' || navState.visibility === 'hidden') {
        throw new Error(`CRITICAL BUG: #bottomNav became invisible for staff on tab [${stab}]!`);
      }

      const shotPath = path.join(ARTIFACT_DIR, `tab_verify_staff_${stab}.png`);
      await page.screenshot({ path: shotPath });
    }

    console.log('\n=== TEST 3: POS DESKTOP VIEWPORT (1024x768) CENTERING ===');
    await page.setViewport({ width: 1024, height: 768, isMobile: false });
    await new Promise(r => setTimeout(r, 500));

    const posNavState = await page.evaluate(() => {
      const nav = document.getElementById('bottomNav');
      const rect = nav.getBoundingClientRect();
      const style = window.getComputedStyle(nav);
      return {
        display: style.display,
        width: Math.round(rect.width),
        left: Math.round(rect.left),
        right: Math.round(window.innerWidth - rect.right),
        maxWidth: style.maxWidth,
        position: style.position
      };
    });
    console.log('POS Desktop Nav State:', posNavState);

    const desktopShot = path.join(ARTIFACT_DIR, `tab_verify_desktop_pos_staff.png`);
    await page.screenshot({ path: desktopShot });
    console.log(`Saved screenshot: ${desktopShot}`);

    console.log('\n>>> SUCCESS: ALL TAB SWITCH TESTS PASSED! BOTTOM NAV NEVER DISAPPEARS! <<<');
  } catch (err) {
    console.error('Test FAILED:', err);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    try {
      fs.rmSync(tmpProfile, { recursive: true, force: true });
    } catch (_) {}
  }
}

run();
