// ==========================================================================
// TEST SUITE: THERMAL RECEIPT DARK GRAPHITE & SWIPE DOWN DISMISS GESTURES
// ==========================================================================

import assert from "assert";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

console.log("==================================================================");
console.log("STARTING TEST: DARK GRAPHITE THERMAL RECEIPT & SWIPE GESTURES");
console.log("==================================================================");

// --------------------------------------------------------------------------
// 1. Verify CSS rules in mobile.css
// --------------------------------------------------------------------------
const mobileCss = fs.readFileSync(path.join(rootDir, "frontend/mobile.css"), "utf-8");

console.log("\n[TEST 1] Verifying mobile.css Dark Graphite Thermal Receipt & Grabber...");

// Grabber enhancements
assert(mobileCss.includes(".sheet-grabber {"), "Must contain .sheet-grabber");
assert(mobileCss.includes("cursor: grab;"), "Must have grab cursor on grabber");
assert(mobileCss.includes("touch-action: none;"), "Must have touch-action: none on grabber");

// Dark theme receipt rules
assert(mobileCss.includes('[data-theme="dark"] .receipt-card-premium') || mobileCss.includes('[data-theme="dark"] .payslip-card'), 
  "Must contain dark theme rules for receipt card");
assert(mobileCss.includes("#1E2638") || mobileCss.includes("#202921"), 
  "Must use dark receipt background");
assert(mobileCss.includes("1px solid rgba(255, 255, 255, 0.1)") || mobileCss.includes("rgba(217, 201, 178, 0.12)"), 
  "Must use subtle 1px border");
assert(mobileCss.includes("#F8FAFC") || mobileCss.includes("#F8F6EE"), 
  "Must use light tone for titles/employee names");
assert(mobileCss.includes("#A8B7CC") || mobileCss.includes("#D9C9B2"), 
  "Must use soft tone for secondary labels");
assert(mobileCss.includes("#FF6D3E") || mobileCss.includes("#F8F6EE") || mobileCss.includes("#E07A57"), 
  "Must style hero amounts");
assert(mobileCss.includes("[data-theme=\"dark\"] .rc-details-table"), 
  "Must style .rc-details-table in dark mode");
assert(mobileCss.includes("background: #252F42") || mobileCss.includes("background: #182119"), 
  "Details table must use dark background in dark mode");
assert(mobileCss.includes("border-radius: 10px") || mobileCss.includes("border-radius: 12px"), 
  "Details table must have border radius");
assert(mobileCss.includes(".rc-serrated-edge"), 
  "Must contain serrated receipt edge style");
assert(mobileCss.includes(".rc-perforated-top"), 
  "Must contain perforated top line style");

console.log("   ✓ TEST 1 PASSED: mobile.css contains full Dark Graphite Thermal Receipt specifications.");

// --------------------------------------------------------------------------
// 2. Verify HTML output of generatePayslipHtml
// --------------------------------------------------------------------------
console.log("\n[TEST 2] Verifying payslipModule generatePayslipHtml markup...");

// Mock localStorage for Node.js test environment
global.localStorage = {
  store: { fnbops_role: "STAFF", fnbops_username: "thuan" },
  getItem(k) { return this.store[k] || null; },
  setItem(k, v) { this.store[k] = String(v); },
  removeItem(k) { delete this.store[k]; }
};

import { generatePayslipHtml } from "../frontend/src/modules/payslipModule.js";
import { state } from "../frontend/src/store/state.js";

// Mock minimal state
state.currentMonth = "9";
state.records = [
  { name: "Nguyễn Văn Thuận", month: "9", mins: 360, standardMins: 300, overtimeMins: 60, standardCost: 85000, overtimeCost: 25500, lateMins: 0, isHoliday: false }
];
state.employeesMap = {
  "Nguyễn Văn Thuận": { wage: 17000, role: "Phục vụ" }
};
state.bonuses = [];
state.advances = [];
state.deductions = [];

const payslipHtml = generatePayslipHtml("Nguyễn Văn Thuận");

assert(payslipHtml.includes('class="receipt-card-premium payslip-card"'), "Receipt card must have payslip-card class");
assert(payslipHtml.includes('class="rc-perforated-top"'), "Must include perforated top line");
assert(payslipHtml.includes('class="rc-serrated-edge"'), "Must include serrated bottom edge");
assert(payslipHtml.includes('class="rc-details-table"'), "Must include rc-details-table");
assert(payslipHtml.includes('class="rc-hero-amount tabular-nums"'), "Hero amount must use tabular-nums");
assert(payslipHtml.includes('tabular-nums'), "Details values must use tabular-nums");
assert(payslipHtml.includes('class="sheet-btn secondary rc-btn-detail"'), "Detail button must use rc-btn-detail class");

console.log("   ✓ TEST 2 PASSED: generatePayslipHtml generates semantic Dark Graphite thermal receipt structure.");

// --------------------------------------------------------------------------
// 3. Verify Swipe Down to Dismiss Gestures in DOM Environment
// --------------------------------------------------------------------------
console.log("\n[TEST 3] Verifying Swipe Down Dismiss Gestures in DOM environment...");

class MockElement {
  constructor(tag, id = "", className = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.className = className;
    this.style = {};
    this.dataset = {};
    this.children = [];
    this.parentElement = null;
    this.eventListeners = {};
    this.scrollTop = 0;
    this.scrollHeight = 100;
    this.clientHeight = 100;
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
      contains: (cls) => (this.className || "").split(" ").filter(Boolean).includes(cls)
    };
  }

  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
    return child;
  }

  addEventListener(event, fn) {
    if (!this.eventListeners[event]) this.eventListeners[event] = [];
    this.eventListeners[event].push(fn);
  }

  dispatchEvent(event) {
    event.target = event.target || this;
    const fnList = this.eventListeners[event.type] || [];
    fnList.forEach(fn => fn(event));
  }

  closest(selector) {
    let curr = this;
    while (curr) {
      if (selector.startsWith(".") && curr.classList.contains(selector.slice(1))) return curr;
      if (selector.startsWith("#") && curr.id === selector.slice(1)) return curr;
      if (selector.toUpperCase() === curr.tagName) return curr;
      if (selector.includes(",")) {
        const parts = selector.split(",").map(p => p.trim());
        for (const p of parts) {
          if (curr.closest(p)) return curr;
        }
      }
      curr = curr.parentElement;
    }
    return null;
  }

  querySelector(sel) {
    return this.querySelectorAll(sel)[0] || null;
  }

  querySelectorAll(sel) {
    let results = [];
    if (sel.startsWith(".")) {
      const cls = sel.slice(1);
      if (this.classList.contains(cls)) results.push(this);
      for (const ch of this.children) results = results.concat(ch.querySelectorAll(sel));
    } else if (sel.startsWith("#")) {
      const id = sel.slice(1);
      if (this.id === id) results.push(this);
      for (const ch of this.children) results = results.concat(ch.querySelectorAll(sel));
    }
    return results;
  }
}

const mockDoc = {
  body: new MockElement("body"),
  querySelector: (sel) => mockDoc.body.querySelector(sel),
  querySelectorAll: (sel) => mockDoc.body.querySelectorAll(sel),
  getElementById: (id) => mockDoc.body.querySelector("#" + id)
};

global.document = mockDoc;
global.window = {
  addEventListener: () => {}
};

// Build Mock DOM hierarchy:
// body -> sheetOverlay (#payslipSheet.sheet-overlay.active) -> sheetModal (.sheet-modal) -> [grabber, header, innerContent]
const sheetOverlay = new MockElement("div", "payslipSheet", "sheet-overlay active");
const sheetModal = new MockElement("div", "", "sheet-modal");
const grabber = new MockElement("div", "", "sheet-grabber");
const header = new MockElement("div", "", "sheet-header");
const innerContent = new MockElement("div", "scrollContent", "scroll-box");

sheetModal.appendChild(grabber);
sheetModal.appendChild(header);
sheetModal.appendChild(innerContent);
sheetOverlay.appendChild(sheetModal);
mockDoc.body.appendChild(sheetOverlay);

// Import authStore
import { setupSheetSwipeGestures } from "../frontend/src/store/authStore.js";

setupSheetSwipeGestures();

// Helper to simulate touch events
function triggerTouch(type, clientX, clientY, target) {
  const touch = { clientX, clientY };
  const event = {
    type,
    target,
    touches: type === "touchend" || type === "touchcancel" ? [] : [touch],
    changedTouches: [touch],
    cancelable: true,
    preventDefault: () => {}
  };
  sheetModal.dispatchEvent(event);
  return event;
}

// 3A. Swipe down on grabber (> 75px) should dismiss modal
console.log("   - Subtest 3A: Pull down on grabber by 100px (> 75px threshold)...");
triggerTouch("touchstart", 100, 50, grabber);
triggerTouch("touchmove", 100, 150, grabber); // deltaY = 100px

assert(sheetModal.style.transform === "translateY(100px)", 
  `Modal should follow finger to translateY(100px), got: ${sheetModal.style.transform}`);
assert(Number(sheetOverlay.style.opacity) < 1, 
  `Backdrop opacity should reduce when dragging, got: ${sheetOverlay.style.opacity}`);

// End touch
triggerTouch("touchend", 100, 150, grabber);

// After dismissal transition, active class should be removed
await new Promise(r => setTimeout(r, 260));
assert.strictEqual(sheetOverlay.classList.contains("active"), false, "Sheet should be closed after pulling > 75px");
console.log("   ✓ Subtest 3A passed: Sheet dismissed on pull down > 75px.");

// 3B. Reopen sheet, pull down slightly (< 75px), should snap back elastically
console.log("   - Subtest 3B: Pull down on grabber by 40px (< 75px threshold, slow)...");
sheetOverlay.classList.add("active");
sheetModal.style.transform = "";

triggerTouch("touchstart", 100, 50, grabber);
// Wait a bit to simulate slow movement (low velocity)
await new Promise(r => setTimeout(r, 120));
triggerTouch("touchmove", 100, 90, grabber); // deltaY = 40px

assert(sheetModal.style.transform === "translateY(40px)", 
  `Modal should follow finger to translateY(40px), got: ${sheetModal.style.transform}`);

triggerTouch("touchend", 100, 90, grabber);

// Should snap back with cubic-bezier transition and keep active
assert(sheetModal.style.transition.includes("cubic-bezier(0.2, 0.8, 0.2, 1)"), 
  `Modal should snap back with elastic bezier, got: ${sheetModal.style.transition}`);
assert.strictEqual(sheetModal.style.transform, "", "Modal transform should be reset to empty");
assert.strictEqual(sheetOverlay.classList.contains("active"), true, "Sheet should remain active when pull < 75px");
console.log("   ✓ Subtest 3B passed: Sheet snaps back elastically when deltaY < 75px.");

// 3C. When inner list is scrolled down (scrollTop > 0), dragging list content down does NOT dismiss sheet
console.log("   - Subtest 3C: List scrolled down (scrollTop > 0), pulling content down should NOT drag modal...");
sheetModal.style.transform = "";
sheetModal.scrollTop = 150; // Scrolled down

triggerTouch("touchstart", 100, 150, innerContent);
triggerTouch("touchmove", 100, 220, innerContent);

assert.strictEqual(sheetModal.style.transform, "", "Modal must NOT translate when scrolling inside non-top list");
triggerTouch("touchend", 100, 220, innerContent);
assert.strictEqual(sheetOverlay.classList.contains("active"), true, "Sheet must remain active without interruption to list scrolling");
console.log("   ✓ Subtest 3C passed: Inner scrolling is preserved smoothly without interrupting list interaction.");

console.log("\n==================================================================");
console.log("ALL THERMAL RECEIPT & SWIPE GESTURE TESTS PASSED 100%!");
console.log("==================================================================");
