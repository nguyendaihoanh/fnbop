// ==========================================================================
// TEST SUITE: MANAGER SAFEGUARDS & EVALUATION 2-TAB SPLIT (TASK 2.3)
// Tests:
// 1. Auto-Roster Safeguard Bottom Sheet (#autoRosterConfirmSheet)
// 2. Evaluation Sheet 2-Tab Split (Penalty vs Bonus) & Quick-Amount Pills
// 3. Static Markup (index.html) & CSS Styling (mobile.css)
// 4. Runtime Interaction Logic (rosterModule.js & payslipModule.js)
// ==========================================================================

import assert from "assert";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

console.log("==================================================================");
console.log("STARTING TEST: MANAGER SAFEGUARDS & EVALUATION 2-TAB SPLIT");
console.log("==================================================================");

// --------------------------------------------------------------------------
// 1. VERIFY HTML MARKUP (frontend/index.html)
// --------------------------------------------------------------------------
console.log("\n[TEST 1] Verifying frontend/index.html markup...");
const indexHtml = fs.readFileSync(path.join(rootDir, "frontend/index.html"), "utf-8");

// 1.1 Auto-Roster Safeguard Modal
assert(indexHtml.includes('id="btnAutoRoster"'), "index.html must contain #btnAutoRoster");
assert(indexHtml.includes('id="autoRosterConfirmSheet"'), "index.html must contain #autoRosterConfirmSheet");
assert(indexHtml.includes('id="btnCloseAutoRoster"'), "index.html must contain #btnCloseAutoRoster");
assert(indexHtml.includes('id="btnCancelAutoRoster"'), "index.html must contain #btnCancelAutoRoster");
assert(indexHtml.includes('id="btnConfirmAutoRoster"'), "index.html must contain #btnConfirmAutoRoster");
assert(indexHtml.includes("Xác Nhận Xếp Ca Tự Động") || indexHtml.includes("Xác Nhận Xếp Lịch Tự Động"), "Modal must contain title 'Xác Nhận Xếp Ca Tự Động'");
assert(
  indexHtml.includes("Thao tác này sẽ tự động tính toán lại định biên nhân sự và GHI ĐÈ lịch trực hiện tại của tuần này. Bạn có chắc chắn muốn tiếp tục?") ||
  indexHtml.includes("GHI ĐÈ lịch trực hiện tại của tuần này"),
  "Modal must contain explicit safeguard warning about overwriting roster"
);
assert(indexHtml.includes("Xác Nhận Ghi Đè &amp; Xếp Ca") || indexHtml.includes("Xác Nhận Ghi Đè & Xếp Ca"), "Confirm button must have correct action label");

console.log("   ✓ 1.1 Auto-Roster Safeguard modal markup is complete and correct.");

// 1.2 Evaluation Sheet 2-Tab Split & Quick-Pills
assert(indexHtml.includes('id="evalSheet"'), "index.html must contain #evalSheet");
assert(indexHtml.includes('id="tabEvalPenalty"'), "index.html must contain #tabEvalPenalty");
assert(indexHtml.includes('id="tabEvalBonus"'), "index.html must contain #tabEvalBonus");
assert(indexHtml.includes("VI PHẠM / PHẠT"), "Tab penalty must have text 'VI PHẠM / PHẠT'");
assert(indexHtml.includes("THƯỞNG NÓNG"), "Tab bonus must have text 'THƯỞNG NÓNG'");

// Penalty suggestions
assert(indexHtml.includes('data-incident="Đi trễ không báo trước"'), "Must contain suggestion 'Đi trễ không báo trước'");
assert(indexHtml.includes('data-incident="Không đeo tạp dề / đồng phục"'), "Must contain suggestion 'Không đeo tạp dề / đồng phục'");
assert(indexHtml.includes('data-incident="Quên dọn vệ sinh quầy"'), "Must contain suggestion 'Quên dọn vệ sinh quầy'");
assert(indexHtml.includes('data-incident="Bỏ vị trí trực"'), "Must contain suggestion 'Bỏ vị trí trực'");

// Bonus suggestions
assert(indexHtml.includes('data-incident="Hỗ trợ tăng ca đột xuất"'), "Must contain suggestion 'Hỗ trợ tăng ca đột xuất'");
assert(indexHtml.includes('data-incident="Khách hàng khen ngợi"'), "Must contain suggestion 'Khách hàng khen ngợi'");
assert(indexHtml.includes('data-incident="Xử lý sự cố xuất sắc"'), "Must contain suggestion 'Xử lý sự cố xuất sắc'");
assert(indexHtml.includes('data-incident="Doanh thu ca vượt trội"'), "Must contain suggestion 'Doanh thu ca vượt trội'");

// Quick Pills
assert(indexHtml.includes('class="quick-amount-pill" data-amount="20000"'), "Must contain quick pill for 20.000đ");
assert(indexHtml.includes('class="quick-amount-pill" data-amount="50000"'), "Must contain quick pill for 50.000đ");
assert(indexHtml.includes('class="quick-amount-pill" data-amount="100000"'), "Must contain quick pill for 100.000đ");
assert(indexHtml.includes('id="evalAmountInput"'), "Must contain #evalAmountInput");

console.log("   ✓ 1.2 Evaluation sheet 2-tab split and quick-pills markup is verified.");

// --------------------------------------------------------------------------
// 2. VERIFY CSS STYLES (frontend/mobile.css)
// --------------------------------------------------------------------------
console.log("\n[TEST 2] Verifying frontend/mobile.css rules...");
const mobileCss = fs.readFileSync(path.join(rootDir, "frontend/mobile.css"), "utf-8");

assert(mobileCss.includes(".eval-type-tabs"), "Must contain .eval-type-tabs rule");
assert(mobileCss.includes(".eval-tab-btn"), "Must contain .eval-tab-btn rule");
assert(mobileCss.includes(".eval-tab-btn.penalty.active"), "Must contain .eval-tab-btn.penalty.active rule");
assert(mobileCss.includes(".eval-tab-btn.bonus.active"), "Must contain .eval-tab-btn.bonus.active rule");
assert(mobileCss.includes("var(--accent-coral)"), "Penalty active must use --accent-coral");
assert(mobileCss.includes("var(--accent-emerald)"), "Bonus active must use --accent-emerald");
assert(mobileCss.includes(".quick-amount-pills"), "Must contain .quick-amount-pills rule");
assert(mobileCss.includes(".quick-amount-pill"), "Must contain .quick-amount-pill rule");
assert(mobileCss.includes(".quick-amount-pill.active"), "Must contain .quick-amount-pill.active rule");

console.log("   ✓ TEST 2 PASSED: mobile.css contains full styling for eval tabs & quick pills.");

// --------------------------------------------------------------------------
// 3. RUNTIME LOGIC VERIFICATION: AUTO-ROSTER SAFEGUARD
// --------------------------------------------------------------------------
console.log("\n[TEST 3] Verifying Auto-Roster Safeguard runtime interaction...");

// Lightweight Mock DOM
class MockClassList {
  constructor(initial = []) {
    this.classes = new Set(initial);
  }
  add(...names) { names.forEach(n => this.classes.add(n)); }
  remove(...names) { names.forEach(n => this.classes.delete(n)); }
  contains(n) { return this.classes.has(n); }
  toggle(n, force) {
    if (force !== undefined) {
      if (force) this.classes.add(n); else this.classes.delete(n);
      return force;
    }
    if (this.classes.has(n)) { this.classes.delete(n); return false; }
    this.classes.add(n); return true;
  }
}

class MockElement {
  constructor(tag, id = "", className = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.className = className;
    this.classList = new MockClassList(className ? className.split(" ").filter(Boolean) : []);
    this.style = {};
    this.attributes = {};
    this.listeners = {};
    this.innerHTML = "";
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.children = [];
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return this.attributes[k] || null; }
  addEventListener(ev, fn) {
    if (!this.listeners[ev]) this.listeners[ev] = [];
    this.listeners[ev].push(fn);
  }
  click() {
    if (typeof this.onclick === "function") this.onclick({ type: "click", target: this });
    const handlers = this.listeners["click"] || [];
    for (const h of handlers) h({ type: "click", target: this });
  }
  input(val) {
    this.value = val;
    const handlers = this.listeners["input"] || [];
    for (const h of handlers) h({ type: "input", target: this });
  }
  appendChild(child) { this.children.push(child); }
  querySelector(sel) { return null; }
}

const mockDoc = {
  body: new MockElement("body"),
  elements: {},
  getElementById(id) {
    return this.elements[id] || null;
  },
  querySelector(selector) {
    if (selector === ".sheet-overlay.active") {
      return Object.values(this.elements).find(e => e.classList.contains("sheet-overlay") && e.classList.contains("active")) || null;
    }
    return null;
  },
  querySelectorAll(selector) {
    if (selector === ".quick-amount-pill") {
      return Object.values(this.elements).filter(e => e.classList.contains("quick-amount-pill"));
    }
    if (selector === ".incident-action-btn") {
      return Object.values(this.elements).filter(e => e.classList.contains("incident-action-btn"));
    }
    return [];
  },
  createElement(tag) {
    return new MockElement(tag);
  }
};

global.document = mockDoc;
global.window = {
  localStorage: {
    store: { fnbops_jwt: "mock_test_token", fnbops_role: "MANAGER", fnbops_name: "Anh Quanh" },
    getItem(k) { return this.store[k] || null; },
    setItem(k, v) { this.store[k] = String(v); },
    removeItem(k) { delete this.store[k]; }
  }
};
global.localStorage = global.window.localStorage;

const fetchHistory = [];
let lastFetchCall = null;
global.fetch = async (url, opts = {}) => {
  const call = { url, opts };
  fetchHistory.push(call);
  lastFetchCall = call;
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, message: "OK Mock Response" })
  };
};

// Setup DOM elements for auto-roster safeguard
const btnAutoRoster = new MockElement("button", "btnAutoRoster");
const autoRosterConfirmSheet = new MockElement("div", "autoRosterConfirmSheet", "sheet-overlay");
const btnCancelAutoRoster = new MockElement("button", "btnCancelAutoRoster");
const btnCloseAutoRoster = new MockElement("button", "btnCloseAutoRoster");
const btnConfirmAutoRoster = new MockElement("button", "btnConfirmAutoRoster");

mockDoc.elements["btnAutoRoster"] = btnAutoRoster;
mockDoc.elements["autoRosterConfirmSheet"] = autoRosterConfirmSheet;
mockDoc.elements["btnCancelAutoRoster"] = btnCancelAutoRoster;
mockDoc.elements["btnCloseAutoRoster"] = btnCloseAutoRoster;
mockDoc.elements["btnConfirmAutoRoster"] = btnConfirmAutoRoster;

import {
  openAutoRosterConfirmModal,
  closeAutoRosterConfirmModal,
  executeRosterAutoFill,
  handleRosterAutoFill,
  setupRosterNav
} from "../frontend/src/modules/rosterModule.js";

// Test modal open & close directly
assert(!autoRosterConfirmSheet.classList.contains("active"), "Modal should initially be inactive");
openAutoRosterConfirmModal();
assert(autoRosterConfirmSheet.classList.contains("active"), "openAutoRosterConfirmModal should add .active");
closeAutoRosterConfirmModal();
assert(!autoRosterConfirmSheet.classList.contains("active"), "closeAutoRosterConfirmModal should remove .active");

// Test click on handleRosterAutoFill
handleRosterAutoFill();
assert(autoRosterConfirmSheet.classList.contains("active"), "handleRosterAutoFill must open confirm sheet");

// Test cancel button closes modal
closeAutoRosterConfirmModal();
assert(!autoRosterConfirmSheet.classList.contains("active"), "Cancel should safely dismiss modal without executing API");

// Test executeRosterAutoFill triggers API and closes modal
fetchHistory.length = 0;
openAutoRosterConfirmModal();
assert(autoRosterConfirmSheet.classList.contains("active"), "Modal must be active before confirm");

await executeRosterAutoFill();
assert(!autoRosterConfirmSheet.classList.contains("active"), "executeRosterAutoFill must close the modal");
const autoFillCall = fetchHistory.find(c => c.url.includes("/api/v1/cc/roster/auto-fill"));
assert(autoFillCall !== undefined, "executeRosterAutoFill must call fetch /api/v1/cc/roster/auto-fill");
assert(autoFillCall.opts.method === "POST", "fetch method must be POST");

console.log("   ✓ TEST 3 PASSED: Auto-Roster Safeguard prevents accidental overwrite and executes on confirmation.");

// --------------------------------------------------------------------------
// 4. RUNTIME LOGIC VERIFICATION: EVALUATION 2-TAB & QUICK PILLS
// --------------------------------------------------------------------------
console.log("\n[TEST 4] Verifying Evaluation 2-Tab Split & Quick Pills runtime interaction...");

// Setup DOM elements for eval sheet
const modalEval = new MockElement("div", "evalSheet", "sheet-overlay");
const btnOpenEval = new MockElement("button", "btnOpenEval");
const btnCloseEval = new MockElement("button", "btnCloseEval");
const staffSelect = new MockElement("select", "evalStaffSelect");
const shiftSelect = new MockElement("select", "evalShiftSelect");
const dateInput = new MockElement("input", "evalDateInput");
const notesInput = new MockElement("input", "evalNotesInput");
const amountInput = new MockElement("input", "evalAmountInput");
const typeSelect = new MockElement("select", "evalTypeSelect");
const btnSubmitCustomEval = new MockElement("button", "btnSubmitCustomEval");

const tabEvalPenalty = new MockElement("button", "tabEvalPenalty", "eval-tab-btn penalty active");
tabEvalPenalty.setAttribute("data-type", "Phạt");
const tabEvalBonus = new MockElement("button", "tabEvalBonus", "eval-tab-btn bonus");
tabEvalBonus.setAttribute("data-type", "Thưởng");

const evalPenaltyContainer = new MockElement("div", "evalPenaltyContainer", "eval-tab-content active");
const evalBonusContainer = new MockElement("div", "evalBonusContainer", "eval-tab-content");
evalBonusContainer.style.display = "none";

const pill20k = new MockElement("button", "pill20k", "quick-amount-pill");
pill20k.setAttribute("data-amount", "20000");
const pill50k = new MockElement("button", "pill50k", "quick-amount-pill");
pill50k.setAttribute("data-amount", "50000");
const pill100k = new MockElement("button", "pill100k", "quick-amount-pill");
pill100k.setAttribute("data-amount", "100000");

const incidentPenaltyBtn = new MockElement("button", "incBtn1", "incident-action-btn mistake");
incidentPenaltyBtn.setAttribute("data-incident", "Quên dọn vệ sinh quầy");
incidentPenaltyBtn.setAttribute("data-amount", "50000");
incidentPenaltyBtn.setAttribute("data-type", "Phạt");

const incidentBonusBtn = new MockElement("button", "incBtn2", "incident-action-btn bonus");
incidentBonusBtn.setAttribute("data-incident", "Xử lý sự cố xuất sắc");
incidentBonusBtn.setAttribute("data-amount", "100000");
incidentBonusBtn.setAttribute("data-type", "Thưởng");

mockDoc.elements["evalSheet"] = modalEval;
mockDoc.elements["btnOpenEval"] = btnOpenEval;
mockDoc.elements["btnCloseEval"] = btnCloseEval;
mockDoc.elements["evalStaffSelect"] = staffSelect;
mockDoc.elements["evalShiftSelect"] = shiftSelect;
mockDoc.elements["evalDateInput"] = dateInput;
mockDoc.elements["evalNotesInput"] = notesInput;
mockDoc.elements["evalAmountInput"] = amountInput;
mockDoc.elements["evalTypeSelect"] = typeSelect;
mockDoc.elements["btnSubmitCustomEval"] = btnSubmitCustomEval;
mockDoc.elements["tabEvalPenalty"] = tabEvalPenalty;
mockDoc.elements["tabEvalBonus"] = tabEvalBonus;
mockDoc.elements["evalPenaltyContainer"] = evalPenaltyContainer;
mockDoc.elements["evalBonusContainer"] = evalBonusContainer;
mockDoc.elements["pill20k"] = pill20k;
mockDoc.elements["pill50k"] = pill50k;
mockDoc.elements["pill100k"] = pill100k;
mockDoc.elements["incBtn1"] = incidentPenaltyBtn;
mockDoc.elements["incBtn2"] = incidentBonusBtn;

import { setupEvalModal } from "../frontend/src/modules/payslipModule.js";
import { state, POLICY } from "../frontend/src/store/state.js";

state.employeesMap = {
  "E1": { name: "Nguyễn Văn A", status: "ĐANG LÀM" },
  "E2": { name: "Trần Thị B", status: "ĐANG LÀM" },
  "M1": { name: POLICY.MANAGER_NAME, status: "ĐANG LÀM" }
};

// Initialize listeners
setupEvalModal();

// 4.1 Test tab switching to Bonus
tabEvalBonus.click();
assert(tabEvalBonus.classList.contains("active"), "tabEvalBonus should be active after click");
assert(!tabEvalPenalty.classList.contains("active"), "tabEvalPenalty should be inactive after bonus click");
assert(evalBonusContainer.style.display === "block", "evalBonusContainer must be displayed");
assert(evalPenaltyContainer.style.display === "none", "evalPenaltyContainer must be hidden");
assert(typeSelect.value === "Thưởng", "evalTypeSelect should be synchronized to Thưởng");
assert(btnSubmitCustomEval.textContent.includes("Thưởng"), "Submit button text should reflect Thưởng");
assert(btnSubmitCustomEval.style.background === "var(--accent-emerald)", "Submit button background must use --accent-emerald");

// 4.2 Test tab switching back to Penalty
tabEvalPenalty.click();
assert(tabEvalPenalty.classList.contains("active"), "tabEvalPenalty should be active after click");
assert(!tabEvalBonus.classList.contains("active"), "tabEvalBonus should be inactive after penalty click");
assert(evalPenaltyContainer.style.display === "block", "evalPenaltyContainer must be displayed");
assert(evalBonusContainer.style.display === "none", "evalBonusContainer must be hidden");
assert(typeSelect.value === "Phạt", "evalTypeSelect should be synchronized to Phạt");
assert(btnSubmitCustomEval.textContent.includes("Phạt"), "Submit button text should reflect Phạt");
assert(btnSubmitCustomEval.style.background === "var(--accent-coral)", "Submit button background must use --accent-coral");

console.log("   ✓ 4.1 & 4.2 Tab switching between Penalty and Bonus operates flawlessly.");

// 4.3 Test Quick Amount Pills click & two-way sync
pill50k.click();
assert(pill50k.classList.contains("active"), "Pill 50k should be active after click");
assert(!pill20k.classList.contains("active"), "Pill 20k should be inactive");
assert(!pill100k.classList.contains("active"), "Pill 100k should be inactive");
assert(amountInput.value == 50000, "amountInput must be set to 50000 when clicking 50k pill");

pill100k.click();
assert(pill100k.classList.contains("active"), "Pill 100k should be active after click");
assert(!pill50k.classList.contains("active"), "Pill 50k should be inactive");
assert(amountInput.value == 100000, "amountInput must be set to 100000 when clicking 100k pill");

// 4.4 Test typing into amountInput activates corresponding pill
amountInput.input("20000");
assert(pill20k.classList.contains("active"), "Pill 20k should become active when 20000 is typed");
assert(!pill100k.classList.contains("active"), "Pill 100k should become inactive");

amountInput.input("35000"); // Custom amount not in pills
assert(!pill20k.classList.contains("active"), "No pill should be active for custom amount 35000");
assert(!pill50k.classList.contains("active"), "No pill should be active for custom amount 35000");
assert(!pill100k.classList.contains("active"), "No pill should be active for custom amount 35000");

console.log("   ✓ 4.3 & 4.4 Quick Amount Pills click and two-way sync with amount input tested successfully.");

// 4.5 Test 1-Tap Incident Button (Penalty)
staffSelect.value = "Nguyễn Văn A";
lastFetchCall = null;
incidentPenaltyBtn.click();
assert(amountInput.value == 50000, "Incident button should prefill amount 50000");
assert.strictEqual(notesInput.value, "Quên dọn vệ sinh quầy", "Incident button should prefill reason");
btnSubmitCustomEval.click();
// Give async fetch a tick
await new Promise(r => setTimeout(r, 10));

assert(lastFetchCall !== null, "Submitting incident action must call staff evaluation API");
const penaltyPayload = JSON.parse(lastFetchCall.opts.body);
assert(penaltyPayload.staff_name === "Nguyễn Văn A", "Payload staff_name must match");
assert(penaltyPayload.type === "Phạt", "Penalty button must have type 'Phạt'");
assert(penaltyPayload.amount === 50000, "Penalty amount must be 50000");
assert(penaltyPayload.reason === "Quên dọn vệ sinh quầy", "Reason must match incident attribute");

// 4.6 Test 1-Tap Incident Button (Bonus)
lastFetchCall = null;
incidentBonusBtn.click();
assert(amountInput.value == 100000, "Bonus incident button should prefill amount 100000");
assert.strictEqual(notesInput.value, "Xử lý sự cố xuất sắc", "Bonus incident button should prefill reason");
btnSubmitCustomEval.click();
await new Promise(r => setTimeout(r, 10));

assert(lastFetchCall !== null, "Submitting bonus action must call staff evaluation API");
const bonusPayload = JSON.parse(lastFetchCall.opts.body);
assert(bonusPayload.staff_name === "Nguyễn Văn A", "Payload staff_name must match");
assert(bonusPayload.type === "Thưởng", "Bonus button must have type 'Thưởng'");
assert(bonusPayload.amount === 100000, "Bonus amount must be 100000");
assert(bonusPayload.reason === "Xử lý sự cố xuất sắc", "Reason must match incident attribute");

// 4.7 Test Custom Eval Submit
tabEvalBonus.click();
notesInput.value = "Khen ngợi hỗ trợ khách hàng vip";
amountInput.value = "75000";
lastFetchCall = null;
btnSubmitCustomEval.click();
await new Promise(r => setTimeout(r, 10));

assert(lastFetchCall !== null, "Custom eval submit must call API");
const customPayload = JSON.parse(lastFetchCall.opts.body);
assert(customPayload.staff_name === "Nguyễn Văn A", "Custom payload staff_name must match");
assert(customPayload.type === "Thưởng", "Custom payload must take active tab type 'Thưởng'");
assert(customPayload.amount === 75000, "Custom payload amount must match input value");
assert(customPayload.notes === "Khen ngợi hỗ trợ khách hàng vip", "Custom notes must match input");

console.log("   ✓ 4.5, 4.6 & 4.7 1-Tap buttons and custom eval submission properly verified with live payload assertions.");

console.log("\n==================================================================");
console.log("ALL UNIT & INTEGRATION TESTS PASSED SUCCESSFULLY! (100% OK)");
console.log("==================================================================");
