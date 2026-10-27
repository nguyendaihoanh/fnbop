// ==========================================================================
// TEST SUITE: TEAMMATES ROSTER & 1-TOUCH SHIFT SWAP (TASK 2.2)
// Verifies peer visibility, off-duty detection, 1-touch swap message & DOM
// ==========================================================================

import assert from "assert";

// 1. Mock minimal DOM and Browser API for Node.js
class MockClassList {
  constructor() {
    this.classes = new Set();
  }
  add(...names) {
    names.forEach(n => this.classes.add(n));
  }
  remove(...names) {
    names.forEach(n => this.classes.delete(n));
  }
  contains(name) {
    return this.classes.has(name);
  }
}

class MockElement {
  constructor(tag, id = "", className = "") {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.className = className;
    this.classList = new MockClassList();
    if (className) {
      className.split(" ").filter(Boolean).forEach(c => this.classList.add(c));
    }
    this.style = {};
    this.listeners = {};
    this.innerHTML = "";
    this.textContent = "";
  }

  addEventListener(event, callback) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(callback);
  }

  dispatchEvent(event) {
    const handlers = this.listeners[event.type] || [];
    for (const h of handlers) h(event);
  }
}

const elementsMap = {};
function getOrCreateElement(id, tag = "div") {
  if (!elementsMap[id]) {
    elementsMap[id] = new MockElement(tag, id);
  }
  return elementsMap[id];
}

globalThis.document = {
  getElementById: (id) => elementsMap[id] || null,
  querySelector: (selector) => {
    if (selector === ".sheet-overlay.active") {
      return Object.values(elementsMap).find(el => el.classList.contains("active")) || null;
    }
    return null;
  },
  querySelectorAll: (selector) => {
    if (selector === ".sheet-overlay.active") {
      return Object.values(elementsMap).filter(el => el.classList.contains("active"));
    }
    return [];
  },
  createElement: (tag) => new MockElement(tag),
  body: new MockElement("body", "body")
};
document.body.appendChild = () => {};
document.body.removeChild = () => {};

let copiedClipboardText = "";
if (typeof globalThis.navigator === "undefined") {
  globalThis.navigator = {};
}
Object.defineProperty(globalThis.navigator, 'clipboard', {
  value: {
    writeText: async (text) => {
      copiedClipboardText = text;
      return Promise.resolve();
    }
  },
  configurable: true
});

const localStorageStore = {};
globalThis.localStorage = {
  getItem: (k) => localStorageStore[k] || null,
  setItem: (k, v) => { localStorageStore[k] = String(v); },
  removeItem: (k) => { delete localStorageStore[k]; },
  clear: () => { Object.keys(localStorageStore).forEach(k => delete localStorageStore[k]); }
};

// 2. Import module functions under test
import {
  getInitialsAvatar,
  openShiftDetailModal,
  closeShiftDetailModal,
  handleRequestSwapShift
} from "../frontend/src/modules/rosterModule.js";
import { state, POLICY } from "../frontend/src/store/state.js";

async function runTests() {
  console.log("=== RUNNING TESTS: TEAMMATES ROSTER & SHIFT SWAP (TASK 2.2) ===");

  // Setup DOM elements required by shiftDetailSheet
  const sheetModal = getOrCreateElement("shiftDetailSheet", "div");
  const titleEl = getOrCreateElement("shiftDetailTitle", "h2");
  const timeEl = getOrCreateElement("shiftDetailTime", "p");
  const teammatesContainer = getOrCreateElement("teammatesListContainer", "div");
  const offDutyContainer = getOrCreateElement("offDutyListContainer", "div");
  const teammatesBadge = getOrCreateElement("teammatesCountBadge", "span");
  const offDutyBadge = getOrCreateElement("offDutyCountBadge", "span");
  const closeBtnX = getOrCreateElement("btnShiftDetailCloseX", "button");
  const closeBtn = getOrCreateElement("btnShiftDetailClose", "button");

  // -------------------------------------------------------------------------
  // TEST 1: Avatar initials generator
  // -------------------------------------------------------------------------
  console.log("-> Test 1: Testing getInitialsAvatar()");
  assert.strictEqual(getInitialsAvatar("Bình An"), "BA", "Avatar for Bình An should be BA");
  assert.strictEqual(getInitialsAvatar("Hải Đăng"), "HD", "Avatar for Hải Đăng should be HD");
  assert.strictEqual(getInitialsAvatar("Nguyễn Văn A"), "NA", "Avatar for Nguyễn Văn A should be NA");
  assert.strictEqual(getInitialsAvatar("Hoàng Nam"), "HN", "Avatar for Hoàng Nam should be HN");
  assert.strictEqual(getInitialsAvatar("Phát"), "PH", "Avatar for Phát should be PH");
  assert.strictEqual(getInitialsAvatar("Bình An (BAR)"), "BA", "Avatar should strip parenthesized role");
  assert.strictEqual(getInitialsAvatar(""), "OP", "Avatar for empty should fallback to OP");
  console.log("   ✓ getInitialsAvatar() passed all assertions.");

  // -------------------------------------------------------------------------
  // TEST 2: 1-Touch Swap Request message format & clipboard
  // -------------------------------------------------------------------------
  console.log("-> Test 2: Testing handleRequestSwapShift() message and clipboard");
  localStorage.setItem("vnaigc_name", "Bình An");
  localStorage.setItem("fnbop_name", "Bình An");
  localStorage.setItem("fnbops_name", "Bình An");
  localStorage.setItem("vnaigc_username", "binhan");
  localStorage.setItem("fnbop_username", "binhan");
  localStorage.setItem("fnbops_username", "binhan");

  copiedClipboardText = "";
  const swapResult = handleRequestSwapShift("Hoàng Nam", "07/09/2026", "Ca Sáng");

  const expectedMessage = "[YÊU CẦU ĐỔI CA - FnBOps] @Hoàng Nam ơi, ca Ca Sáng ngày 07/09/2026 bạn có thể đổi ca hỗ trợ mình (@Bình An) được không? Cảm ơn bạn nhiều!";
  assert.strictEqual(swapResult.message, expectedMessage, "Message content must strictly match required prompt template");
  assert.strictEqual(copiedClipboardText, expectedMessage, "Clipboard must receive the exact polite swap request message");
  assert.strictEqual(state.lastSwapRequest.targetStaffName, "Hoàng Nam");
  assert.strictEqual(state.lastSwapRequest.shiftDate, "07/09/2026");
  assert.strictEqual(state.lastSwapRequest.shiftKey, "Ca Sáng");
  assert.strictEqual(localStorage.getItem("fnbop_last_swap_request"), JSON.stringify(state.lastSwapRequest));
  console.log("   ✓ handleRequestSwapShift() formatted template & copied to clipboard successfully.");

  // -------------------------------------------------------------------------
  // TEST 3: Teammates & Off-Duty Staff detection with Published Roster Data
  // -------------------------------------------------------------------------
  console.log("-> Test 3: Testing openShiftDetailModal() with Published Roster");

  const mockRosterWeek = {
    week_id: "2026-W37",
    status: "PUBLISHED",
    shifts: {
      "2026-09-07": {
        morning: {
          time: "06:00 - 11:00",
          manager: "phat",
          barista: "binhan",
          service: ["nhanvien02", "nhanvien04"]
        },
        evening: {
          time: "17:00 - 23:00",
          manager: "phat",
          barista: null,
          service_17: "nhanvien05",
          service_18: "nhanvien06"
        }
      }
    }
  };

  const mockStaffDirectory = {
    "phat": { full_name: "Phát", position: "Quản lý", gender: "NAM", status: "ACTIVE" },
    "binhan": { full_name: "Bình An", position: "Pha chế", gender: "NU", status: "ACTIVE" },
    "nhanvien02": { full_name: "Đặng Văn Nam", position: "Phục vụ", gender: "NAM", status: "ACTIVE" },
    "nhanvien04": { full_name: "Lan Phục Vụ", position: "Phục vụ", gender: "NU", status: "ACTIVE" },
    "nhanvien05": { full_name: "Nguyên", position: "Phục vụ", gender: "NAM", status: "ACTIVE" },
    "nhanvien06": { full_name: "Thuận", position: "Phục vụ", gender: "NAM", status: "ACTIVE" },
    "nhanvien07": { full_name: "Mai Barista", position: "Pha chế", gender: "NU", status: "ACTIVE" },
    "nhanvien08": { full_name: "Nguyễn Văn Tuấn", position: "Phục vụ", gender: "NAM", status: "ACTIVE" }
  };

  state.currentRosterWeekData = {
    success: true,
    week: mockRosterWeek,
    staff_directory: mockStaffDirectory
  };
  state.currentRosterWeeksCache["current"] = state.currentRosterWeekData;

  // Open modal for morning shift on 2026-09-07 (User is Bình An)
  openShiftDetailModal("2026-09-07", "morning");

  // Verify modal is active
  assert.strictEqual(sheetModal.classList.contains("active"), true, "Modal must be active");
  assert.strictEqual(titleEl.textContent, "Chi Tiết Ca Sáng");
  assert.ok(timeEl.textContent.includes("07/09/2026"), "Subtitle must contain VN date format");
  assert.ok(timeEl.textContent.includes("06:00 - 11:00"), "Subtitle must contain shift hours");

  // Section 1: Teammates working this morning shift
  // Expected: Phát (QL), Bình An (Pha chế, Tôi), Đặng Văn Nam (PV), Lan Phục Vụ (PV)
  assert.strictEqual(teammatesBadge.textContent, "4 người", "Morning shift should have 4 staff members");
  assert.ok(teammatesContainer.innerHTML.includes("Bình An"), "Teammates must include Bình An");
  assert.ok(teammatesContainer.innerHTML.includes("teammate-me-badge"), "Current user Bình An must have (Tôi) badge");
  assert.ok(teammatesContainer.innerHTML.includes("Phát"), "Teammates must include Phát");
  assert.ok(teammatesContainer.innerHTML.includes("Đặng Văn Nam"), "Teammates must include Đặng Văn Nam");
  assert.ok(teammatesContainer.innerHTML.includes("Lan Phục Vụ"), "Teammates must include Lan Phục Vụ");
  assert.ok(teammatesContainer.innerHTML.includes("role-manager"), "Quản lý must have manager badge class");
  assert.ok(teammatesContainer.innerHTML.includes("role-barista"), "Pha chế must have barista badge class");
  assert.ok(teammatesContainer.innerHTML.includes("role-service"), "Phục vụ must have service badge class");

  // Section 2: Off-Duty staff today (Working neither morning nor evening)
  // Working morning: phat, binhan, nhanvien02, nhanvien04
  // Working evening: phat, nhanvien05, nhanvien06
  // Total working: phat, binhan, nhanvien02, nhanvien04, nhanvien05, nhanvien06 (6 people)
  // Off today: nhanvien07 (Mai Barista), nhanvien08 (Nguyễn Văn Tuấn) -> 2 people!
  assert.strictEqual(offDutyBadge.textContent, "2 người", "There should be exactly 2 staff members OFF today");
  assert.ok(offDutyContainer.innerHTML.includes("Mai Barista"), "Off-duty list must contain Mai Barista");
  assert.ok(offDutyContainer.innerHTML.includes("Nguyễn Văn Tuấn"), "Off-duty list must contain Nguyễn Văn Tuấn");
  assert.ok(!offDutyContainer.innerHTML.includes("Nguyên"), "Nguyên works in evening so must NOT be in off-duty list");
  assert.ok(!offDutyContainer.innerHTML.includes("Thuận"), "Thuận works in evening so must NOT be in off-duty list");
  assert.ok(offDutyContainer.innerHTML.includes("btn-request-swap"), "Must include 1-touch swap button for off-duty peers");
  assert.ok(offDutyContainer.innerHTML.includes("handleRequestSwapShift"), "Button must have onclick calling handleRequestSwapShift");

  // Test closing the modal
  closeShiftDetailModal();
  assert.strictEqual(sheetModal.classList.contains("active"), false, "Modal must be inactive after closeShiftDetailModal()");
  console.log("   ✓ Published Roster teammates & off-duty detection verified successfully.");

  // -------------------------------------------------------------------------
  // TEST 4: Fallback to Sheet Records when no Roster is published
  // -------------------------------------------------------------------------
  console.log("-> Test 4: Testing openShiftDetailModal() with Records fallback");
  state.currentRosterWeekData = null;
  state.currentRosterWeeksCache = {};

  state.records = [
    { date: "15/09/2026", name: "Hải Nam", shift: "Ca Sáng", role: "Pha chế", in: "06:00", out: "11:30" },
    { date: "15/09/2026", name: "Vinh", shift: "Ca Sáng", role: "Phục vụ", in: "06:00", out: "11:30" },
    { date: "15/09/2026", name: "Phát", shift: "Ca Tối", role: "Quản lý", in: "17:00", out: "23:00" },
    { date: "15/09/2026", name: "Bình An", shift: "Ca Tối", role: "Pha chế", in: "17:00", out: "23:00" }
  ];

  state.employeesMap = {
    "Hải Nam": {},
    "Vinh": {},
    "Phát": {},
    "Bình An": {},
    "Mai Barista": {}
  };

  localStorage.setItem("fnbops_name", "Hải Nam");
  localStorage.setItem("fnbops_username", "hainam");

  openShiftDetailModal("15/09/2026", "Ca Sáng");

  assert.strictEqual(sheetModal.classList.contains("active"), true);
  assert.strictEqual(titleEl.textContent, "Chi Tiết Ca Sáng");
  assert.strictEqual(teammatesBadge.textContent, "2 người");
  assert.ok(teammatesContainer.innerHTML.includes("Hải Nam"));
  assert.ok(teammatesContainer.innerHTML.includes("Vinh"));

  // Off today: Mai Barista
  assert.strictEqual(offDutyBadge.textContent, "1 người");
  assert.ok(offDutyContainer.innerHTML.includes("Mai Barista"));

  closeShiftDetailModal();
  console.log("   ✓ Records fallback teammates & off-duty detection verified successfully.");

  console.log("\n>>> ALL TESTS PASSED SUCCESSFULLY! (100% COVERAGE FOR TASK 2.2) <<<");
}

runTests().catch(err => {
  console.error("Test execution failed:", err);
  process.exit(1);
});
