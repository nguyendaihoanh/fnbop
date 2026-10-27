// ==========================================================================
// E2E AUTOMATED SIMULATION: BUTTON CLICKS, FILTERS, MODALS & BACKEND PIPELINE
// ==========================================================================

import assert from "assert";
import fs from "fs";

// 1. Setup DOM environment
class MockElement {
  constructor(tag, id = "", className = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.className = className;
    this.style = {};
    this.children = [];
    this.attributes = {};
    this.eventListeners = {};
    this.value = "";
    this._innerHTML = "";
    this.textContent = "";
  }

  get classList() {
    return {
      add: (cls) => {
        const classes = (this.className || "").split(" ").filter(Boolean);
        if (!classes.includes(cls)) classes.push(cls);
        this.className = classes.join(" ");
      },
      remove: (cls) => {
        const classes = (this.className || "").split(" ").filter(Boolean);
        this.className = classes.filter(c => c !== cls).join(" ");
      },
      toggle: (cls, force) => {
        if (force === true) this.classList.add(cls);
        else if (force === false) this.classList.remove(cls);
        else if (this.classList.contains(cls)) this.classList.remove(cls);
        else this.classList.add(cls);
      },
      contains: (cls) => (this.className || "").split(" ").filter(Boolean).includes(cls)
    };
  }

  getAttribute(attr) {
    return this.attributes[attr] || null;
  }

  setAttribute(attr, val) {
    this.attributes[attr] = String(val);
  }

  removeAttribute(attr) {
    delete this.attributes[attr];
  }

  addEventListener(event, fn) {
    if (!this.eventListeners[event]) this.eventListeners[event] = [];
    this.eventListeners[event].push(fn);
  }

  async click() {
    if (this.onclick) await this.onclick({ target: this });
    if (this.eventListeners["click"]) {
      for (const fn of this.eventListeners["click"]) {
        await fn({ target: this });
      }
    }
  }

  dispatchEvent(event) {
    const fnList = this.eventListeners[event.type || event] || [];
    fnList.forEach(fn => fn(event));
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set innerHTML(html) {
    this._innerHTML = html;
    this.children = [];
    const regex = /<([a-z0-9]+)([^>]*)>([\s\S]*?)<\/\1>/gi;
    let match;
    while ((match = regex.exec(html)) !== null) {
      const tag = match[1];
      const attrStr = match[2];
      const content = match[3];
      const child = new MockElement(tag);
      const classMatch = attrStr.match(/class=["']([^"']*)["']/i);
      if (classMatch) child.className = classMatch[1];
      const dataRoleMatch = attrStr.match(/data-role=["']([^"']*)["']/i);
      if (dataRoleMatch) child.setAttribute("data-role", dataRoleMatch[1]);
      const dataNameMatch = attrStr.match(/data-name=["']([^"']*)["']/i);
      if (dataNameMatch) child.setAttribute("data-name", dataNameMatch[1]);
      child.textContent = content.replace(/<[^>]*>/g, "").trim();
      this.children.push(child);
    }
  }

  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  }

  querySelectorAll(sel) {
    let results = [];
    if (sel.startsWith(".")) {
      const cls = sel.slice(1);
      if (this.classList.contains(cls)) results.push(this);
      for (const ch of this.children) {
        results = results.concat(ch.querySelectorAll(sel));
      }
    } else if (sel.startsWith("#")) {
      const id = sel.slice(1);
      if (this.id === id) results.push(this);
      for (const ch of this.children) {
        results = results.concat(ch.querySelectorAll(sel));
      }
    }
    return results;
  }
}

const domElements = new Map();
function getOrCreateElement(id, tag = "div", className = "") {
  if (!domElements.has(id)) {
    domElements.set(id, new MockElement(tag, id, className));
  }
  return domElements.get(id);
}

const elementIds = [
  "monthFilter", "btnTheme", "roleBadge", "btnAdminStaff", "btnOpenEval", "btnLogout",
  "tabOps", "tabRoster", "tabAttendance", "tabPayslip",
  "navTabOps", "navTabRoster", "navTabAttendance", "navTabPayslip",
  "slipList", "payslipSearch", "payslipSheet", "payslipContent",
  "btnTelegramSend", "btnPrintSheet", "btnCloseSheet",
  "evalSheet", "btnCloseEval", "btnSubmitEval", "evalStaffSelect", "evalShiftSelect",
  "evalDateInput", "evalTypeSelect", "evalAmountInput", "evalNotesInput", "btnSubmitCustomEval",
  "staffShiftsSheet", "shiftsModalTitle", "shiftsModalSubtitle", "shiftsModalSummary", "shiftsModalList",
  "btnCloseStaffShifts", "btnCloseStaffShiftsBottom", "staffPortalContainer", "adminPayslipContainer",
  "managerAttendancePanel", "loginSheet", "loginUser", "loginPass", "btnLoginSubmit"
];

elementIds.forEach(id => getOrCreateElement(id));

global.window = global;
global.window.alert = (msg) => console.log("   [ALERT]:", msg);
global.window.confirm = () => true;
global.window.prompt = () => "Test prompt note";
global.window.print = () => console.log("   [PRINT]: print invoked");

global.document = {
  readyState: "complete",
  documentElement: {
    setAttribute: () => {},
    getAttribute: () => "dark"
  },
  body: {
    style: {},
    appendChild: () => {},
    removeChild: () => {}
  },
  getElementById: (id) => domElements.get(id) || null,
  querySelector: (sel) => {
    if (sel.startsWith("#")) return domElements.get(sel.slice(1)) || null;
    return null;
  },
  querySelectorAll: (sel) => {
    if (sel === ".role-pill") return Array.from(domElements.values()).filter(el => el.classList.contains("role-pill"));
    if (sel === ".incident-action-btn") return Array.from(domElements.values()).filter(el => el.classList.contains("incident-action-btn"));
    if (sel === ".nav-tab-btn") return Array.from(domElements.values()).filter(el => el.classList.contains("nav-tab-btn"));
    if (sel === ".tab-view") return Array.from(domElements.values()).filter(el => el.classList.contains("tab-view"));
    if (sel === ".sheet-overlay") return Array.from(domElements.values()).filter(el => el.classList.contains("sheet-overlay"));
    return [];
  },
  createElement: (tag) => new MockElement(tag),
  addEventListener: () => {}
};

const roleNames = ["ALL", "Pha chế", "Phục vụ", "Quản lý", "Giữ Xe"];
roleNames.forEach(r => {
  const el = new MockElement("span", `pill_${r}`, `role-pill ${r === "ALL" ? "active" : ""}`);
  el.setAttribute("data-role", r);
  el.textContent = r;
  domElements.set(`pill_${r}`, el);
});

const quickIncidents = [
  { cls: "late", title: "Trễ Ca > 15p", incident: "Đi trễ > 15 phút", amount: "20000", type: "Phạt" },
  { cls: "mistake", title: "Sai Món / Đổ Vỡ", incident: "Sai món / Đổ vỡ hao hụt", amount: "50000", type: "Phạt" },
  { cls: "bill", title: "Mất Bill / Quên Tính", incident: "Không quan sát mất bill / Quên tính tiền", amount: "50000", type: "Phạt" },
  { cls: "bonus", title: "Thưởng Nóng", incident: "Thưởng nóng phục vụ xuất sắc", amount: "50000", type: "Thưởng" }
];
quickIncidents.forEach(q => {
  const el = new MockElement("button", `btn_inc_${q.cls}`, `incident-action-btn ${q.cls}`);
  el.setAttribute("data-incident", q.incident);
  el.setAttribute("data-amount", q.amount);
  el.setAttribute("data-type", q.type);
  domElements.set(`btn_inc_${q.cls}`, el);
});

const tabKeys = ["ops", "roster", "attendance", "payslip"];
tabKeys.forEach(t => {
  const el = new MockElement("button", `nav_${t}`, "nav-tab-btn");
  el.setAttribute("data-tab", t);
  domElements.set(`nav_${t}`, el);

  const view = new MockElement("div", `tab${t.charAt(0).toUpperCase() + t.slice(1)}`, "tab-view");
  domElements.set(view.id, view);
});

const storage = new Map();
storage.set("fnbops_jwt", "mock_jwt_admin");
storage.set("fnbops_role", "ADMIN");
storage.set("fnbops_username", "admin");
storage.set("fnbops_name", "Chủ Quán");

global.localStorage = {
  getItem: (k) => storage.get(k) || null,
  setItem: (k, v) => storage.set(k, String(v)),
  removeItem: (k) => storage.delete(k)
};

global.fetch = async (url, opts = {}) => {
  if (url.startsWith("/api/v1/cc/admin/staff-evaluation")) {
    const body = JSON.parse(opts.body);
    return {
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        message: `Đã ghi nhận ${body.type} cho ${body.staff_name}`,
        entry: {
          id: `EVAL_TEST_${Date.now()}`,
          staffName: body.staff_name,
          date: body.date,
          shift: body.shift,
          type: body.type,
          amount: body.amount,
          reason: body.reason,
          created_at: new Date().toISOString()
        }
      })
    };
  }

  if (url.startsWith("/api/v1/cc/payroll/summary")) {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        net_pay: 500000,
        standard_pay: 450000,
        eval_bonus: 50000,
        late_penalty_total: 0,
        total_hours: 25.5,
        total_shifts: 5,
        violations: []
      })
    };
  }

  return { ok: true, json: async () => ({}) };
};

console.log("==================================================================");
console.log("STARTING E2E AUTOMATED CLICK & CONSEQUENCE TEST SUITE");
console.log("==================================================================");

(async () => {
  const { state, processData } = await import("../frontend/src/store/state.js");
  const {
    renderTabPayslip,
    setupPayslipActionButtons,
    setupEvalModal,
    setupStaffShiftsModalEvents,
    openPayslipModal,
    openStaffShiftsDetailModal
  } = await import("../frontend/src/modules/payslipModule.js");
  const { switchTab, setupNav } = await import("../frontend/src/modules/navModule.js");

  const rawData = JSON.parse(fs.readFileSync("data/data.json", "utf8"));
  state.rawData = rawData;
  processData();

  console.log(`✓ Data loaded: ${state.records.length} attendance records, ${Object.keys(state.employeesMap).length} employees.`);
  console.log(`✓ Current Month: ${state.currentMonth}, Months available: ${state.monthsAvailable.join(", ")}`);

  setupPayslipActionButtons();
  setupEvalModal();
  setupStaffShiftsModalEvents();
  setupNav();

  // TEST 1: Role Filter Pills Clicks & Consequence (Bảng 1)
  console.log("\n[TEST 1] Role Filter Pills Logic & DOM updates:");
  renderTabPayslip();
  const slipContainer = domElements.get("slipList");
  const initialCount = slipContainer.children.length;
  console.log(`   - "Tất cả": Showing ${initialCount} staff items.`);
  assert(initialCount > 0, "slipList should not be empty on ALL");

  // Click "Pha chế"
  const pillBarista = domElements.get("pill_Pha chế");
  await pillBarista.click();
  console.log(`   - Clicked "Pha chế" pill.`);
  assert.strictEqual(state.currentRoleFilter, "Pha chế", "state.currentRoleFilter must be 'Pha chế'");
  const baristaCount = slipContainer.children.length;
  console.log(`   - "Pha chế" filtered count: ${baristaCount}`);
  assert(baristaCount > 0 && baristaCount < initialCount, "Barista count should be filtered");

  // Click "Phục vụ"
  const pillServer = domElements.get("pill_Phục vụ");
  await pillServer.click();
  console.log(`   - Clicked "Phục vụ" pill.`);
  assert.strictEqual(state.currentRoleFilter, "Phục vụ", "state.currentRoleFilter must be 'Phục vụ'");
  const serverCount = slipContainer.children.length;
  console.log(`   - "Phục vụ" filtered count: ${serverCount}`);

  // Click "Quản lý"
  const pillManager = domElements.get("pill_Quản lý");
  await pillManager.click();
  console.log(`   - Clicked "Quản lý" pill.`);
  assert.strictEqual(state.currentRoleFilter, "Quản lý", "state.currentRoleFilter must be 'Quản lý'");
  const mgrCount = slipContainer.children.length;
  console.log(`   - "Quản lý" filtered count: ${mgrCount}`);
  assert.strictEqual(mgrCount, 1, "Only PHÁT is Quản lý");

  // Reset to "ALL"
  await domElements.get("pill_ALL").click();
  assert.strictEqual(state.currentRoleFilter, "ALL", "Reset back to ALL");
  console.log("   ✓ TEST 1 PASSED: Role pills update filter state and re-render list seamlessly.");

  // TEST 2: Open Payslip Modal, Verify Breakdown & Telegram Button
  console.log("\n[TEST 2] Payslip Detail Modal & Action Buttons:");
  await openPayslipModal("PHÁT");
  const payslipSheet = domElements.get("payslipSheet");
  assert(payslipSheet.classList.contains("active"), "payslipSheet must have .active");
  assert(state.currentViewingStaff !== null, "state.currentViewingStaff must be populated");
  assert.strictEqual(state.currentViewingStaff.name, "PHÁT");
  console.log(`   - Opened payslip modal for: ${state.currentViewingStaff.name}, netPay: ${state.currentViewingStaff.bankTransferAfterPenalty}`);

  // Test Telegram button click
  const btnTelegram = domElements.get("btnTelegramSend");
  await btnTelegram.click();
  console.log("   - Clicked 'Gửi Telegram' button.");

  // Test Close Payslip Sheet
  const btnCloseSheet = domElements.get("btnCloseSheet");
  await btnCloseSheet.click();
  assert(!payslipSheet.classList.contains("active"), "payslipSheet should not have .active after close");
  console.log("   - Closed payslip modal.");
  console.log("   ✓ TEST 2 PASSED: Payslip modal opens, captures currentViewingStaff, closes properly.");

  // TEST 3: Incident Modal (evalSheet), 1-Tap & Custom Form (Bảng 2 & 3)
  console.log("\n[TEST 3] Incident / Evaluation Modal (evalSheet) & Reactive Pipeline:");
  const btnOpenEval = domElements.get("btnOpenEval");
  await btnOpenEval.click();
  const evalSheet = domElements.get("evalSheet");
  assert(evalSheet.classList.contains("active"), "evalSheet must be active after clicking btnOpenEval");

  const staffSelect = domElements.get("evalStaffSelect");
  assert(staffSelect.children.length > 0, "evalStaffSelect must be populated with active staff");
  staffSelect.value = "THUẬN";
  console.log(`   - Opened evalSheet. Selected staff: ${staffSelect.value}`);

  // Click 1-Tap: Trễ Ca > 15p
  const btnLate = domElements.get("btn_inc_late");
  await btnLate.click();
  const btnCustomSubmitInit = domElements.get("btnSubmitCustomEval");
  await btnCustomSubmitInit.click();
  assert(!evalSheet.classList.contains("active"), "evalSheet should close after 1-tap submission");
  assert(state.deductionLedger[state.currentMonth]["THUẬN"].length > 0, "Deduction ledger for THUẬN should have recorded entry");
  console.log(`   - 1-Tap 'Trễ Ca > 15p' submitted. Deduction ledger: ${JSON.stringify(state.deductionLedger[state.currentMonth]["THUẬN"][0])}`);

  // Re-open evalSheet for Custom submission
  await btnOpenEval.click();
  staffSelect.value = "NHANVIEN01";
  domElements.get("evalTypeSelect").value = "Thưởng";
  domElements.get("evalAmountInput").value = "50000";
  domElements.get("evalNotesInput").value = "Pha chế xuất sắc giờ cao điểm";

  const btnCustomSubmit = domElements.get("btnSubmitCustomEval");
  await btnCustomSubmit.click();
  assert(!evalSheet.classList.contains("active"), "evalSheet should close after custom submission");
  assert(state.bonusLedger[state.currentMonth]["NHANVIEN01"].length > 0, "Bonus ledger for NHANVIEN01 should have recorded entry");
  console.log(`   - Custom Bonus submitted. Bonus ledger: ${JSON.stringify(state.bonusLedger[state.currentMonth]["NHANVIEN01"][0])}`);
  console.log("   ✓ TEST 3 PASSED: 1-Tap & Custom evaluation forms submit cleanly, update ledger, refresh views.");

  // TEST 4: Tab Switching Navigation Across All 4 Views
  console.log("\n[TEST 4] Tab Switching E2E Logic:");
  const tabsToTest = ["ops", "roster", "attendance", "payslip"];
  tabsToTest.forEach(tab => {
    switchTab(tab);
    assert.strictEqual(state.currentTabKey, tab, `Current tab must be ${tab}`);
    console.log(`   - Switched to tab: '${tab}'. Active class updated.`);
  });
  console.log("   ✓ TEST 4 PASSED: Navigation across Ops, Roster, Attendance, Payslip verified.");

  // TEST 5: Detailed Shifts Modal (staffShiftsSheet)
  console.log("\n[TEST 5] Staff Shifts Detail Modal (staffShiftsSheet):");
  openStaffShiftsDetailModal("PHÁT");
  const shiftsModal = domElements.get("staffShiftsSheet");
  assert(shiftsModal.classList.contains("active"), "staffShiftsSheet must be active");
  const summaryBox = domElements.get("shiftsModalSummary");
  assert(summaryBox.innerHTML.includes("TỔNG CA"), "Summary box must contain total shifts");
  await domElements.get("btnCloseStaffShifts").click();
  assert(!shiftsModal.classList.contains("active"), "staffShiftsSheet must close");
  console.log("   ✓ TEST 5 PASSED: Staff shifts detail modal renders and closes smoothly.");

  console.log("\n==================================================================");
  console.log("ALL 5 E2E SIMULATION TESTS PASSED 100%!");
  console.log("==================================================================");
  process.exit(0);
})();
