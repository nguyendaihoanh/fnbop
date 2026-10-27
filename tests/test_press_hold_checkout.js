// ==========================================================================
// UNIT & INTEGRATION TEST: PRESS-AND-HOLD CHECKOUT INTERACTION (TASK 2.1)
// ==========================================================================

import assert from "assert";

// Mock minimal DOM environment for Node.js
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
  toString() {
    return Array.from(this.classes).join(" ");
  }
}

class MockElement {
  constructor(tag, id, className = "") {
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
    this.disabled = false;
  }

  addEventListener(event, callback) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(callback);
  }

  removeEventListener(event, callback) {
    if (!this.listeners[event]) return;
    this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
  }

  dispatchEvent(event) {
    const handlers = this.listeners[event.type] || [];
    for (const h of handlers) {
      h(event);
    }
  }

  click() {
    if (typeof this.onclick === "function") {
      this.onclick();
    }
    this.dispatchEvent({ type: "click", preventDefault: () => {} });
  }
}

const domElements = new Map();
function getOrCreateElement(tag, id, className = "") {
  if (!domElements.has(id)) {
    domElements.set(id, new MockElement(tag, id, className));
  }
  return domElements.get(id);
}

// Setup global mock document
const elementIds = [
  "btnPressHoldCheckout", "pressHoldProgressBar", "pressHoldBtnText",
  "btnCheckinPrimary", "checkinActionArea", "checkinResultStrip",
  "completedShiftCard", "completedShiftDetails", "completedShiftNextNotice",
  "earlyCheckoutModal", "earlyMinsCount", "btnCancelEarlyCheckout", "btnConfirmEarlyCheckout"
];

elementIds.forEach(id => {
  let tag = "div";
  if (id.startsWith("btn")) tag = "button";
  else if (id.endsWith("Text")) tag = "span";
  getOrCreateElement(tag, id);
});

globalThis.document = {
  getElementById: (id) => domElements.get(id) || null,
  querySelector: (sel) => {
    if (sel.startsWith("#")) return domElements.get(sel.slice(1)) || null;
    return null;
  },
  querySelectorAll: () => [],
  createElement: (tag) => new MockElement(tag, "", ""),
  body: {
    appendChild: () => {},
    removeChild: () => {}
  }
};

globalThis.window = {
  location: { hostname: "localhost" }
};

// Mock navigator.vibrate
let vibrateCall = null;
if (typeof globalThis.navigator === "undefined") {
  globalThis.navigator = {};
}
Object.defineProperty(globalThis.navigator, 'vibrate', {
  value: (pattern) => {
    vibrateCall = pattern;
    return true;
  },
  configurable: true,
  writable: true
});

// Mock localStorage
const storage = new Map();
storage.set("fnbops_username", "thuan");
storage.set("fnbops_jwt", "mock_jwt_token");
globalThis.localStorage = {
  getItem: (k) => storage.get(k) || null,
  setItem: (k, v) => storage.set(k, v),
  removeItem: (k) => storage.delete(k)
};

// Mock fetch
let checkoutApiCalled = false;
let checkoutConfirmEarly = null;
let isShiftCheckedOut = false;
globalThis.fetch = async (url, opts = {}) => {
  if (url.includes("/api/v1/cc/attendance/checkout")) {
    checkoutApiCalled = true;
    isShiftCheckedOut = true;
    const body = JSON.parse(opts.body || "{}");
    checkoutConfirmEarly = body.confirm_early;
    return {
      ok: true,
      status: 200,
      json: async () => ({ message: "Check-out thành công!" })
    };
  }
  if (url.includes("/api/v1/cc/attendance/status")) {
    if (isShiftCheckedOut) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          shift_state: "COMPLETED",
          last_closed_record: {
            checkin_time: "07:00",
            checkout_time: "08:30",
            total_mins: 90,
            shift_key: "sang"
          }
        })
      };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({
        shift_state: "IN_PROGRESS",
        is_cafe_wifi: true,
        user_record: {
          checkin_time: "07:00",
          checkout_time: null,
          is_late: false,
          late_mins: 0,
          created_at: new Date(Date.now() - 90 * 60000).toISOString() // 90 minutes ago
        }
      })
    };
  }
  return { ok: true, json: async () => ({}) };
};

// Import attendance module and state
const { state } = await import("../frontend/src/store/state.js");
const {
  initPressHoldCheckout,
  resetPressHoldCheckout,
  getActiveShiftElapsedMinutes,
  openEarlyCheckoutModal,
  executeStaffCheckout,
  loadAttendanceTab
} = await import("../frontend/src/modules/attendanceModule.js");

async function runTests() {
  console.log("==================================================================");
  console.log("RUNNING VERIFICATION: PRESS-AND-HOLD CHECKOUT (TASK 2.1)");
  console.log("==================================================================");

  const btn = domElements.get("btnPressHoldCheckout");
  const bar = domElements.get("pressHoldProgressBar");
  const text = domElements.get("pressHoldBtnText");
  const earlyModal = domElements.get("earlyCheckoutModal");

  // TEST 1: Initialization and Bindings
  console.log("\n[TEST 1] Khởi tạo nút Press-and-Hold & trạng thái ban đầu:");
  initPressHoldCheckout();
  assert(text.textContent === "GIỮ 1.2 GIÂY ĐỂ KẾT THÚC CA" || text.textContent === "Nhấn giữ để Tan Ca", "Text ban đầu phải đúng");
  assert.strictEqual(bar.style.width, "0%", "Thanh tiến trình ban đầu phải ở 0%");
  assert(!btn.classList.contains("holding"), "Không có class holding khi chưa nhấn");
  console.log("   ✓ Trạng thái khởi tạo chính xác: 0%, text sẵn sàng.");

  // TEST 2: Early release (< 1.2s) resets progress smoothly
  console.log("\n[TEST 2] Nhả tay sớm (< 1.2s) - Reset thanh tiến trình về 0% mượt mà:");
  btn.dispatchEvent({ type: "pointerdown", button: 0 });
  assert(btn.classList.contains("holding"), "Khi nhấn giữ, class holding phải được thêm vào");
  assert.strictEqual(bar.style.transition, "none", "Transition phải là none trong khi giữ để 60fps");

  // Release early
  btn.dispatchEvent({ type: "pointerup" });
  assert(!btn.classList.contains("holding"), "Khi nhả tay, class holding phải bị gỡ");
  assert.strictEqual(bar.style.transition, "width 0.2s ease", "Khi nhả tay trước 1.2s, transition phải là 0.2s ease");
  assert.strictEqual(bar.style.width, "0%", "Thanh tiến trình phải lập tức reset về 0%");
  console.log("   ✓ Nhả tay sớm (< 1.2s) hủy hold và reset width về 0% với transition: width 0.2s ease.");

  // TEST 3: Early Checkout Warning (< 60 minutes)
  console.log("\n[TEST 3] Kịch bản ra ca sớm (< 60 phút) - Nhấn giữ 1.2s & Mở modal cảnh báo:");
  state.currentActiveAttendance = {
    checkin_time: "07:00",
    checkout_time: null,
    created_at: new Date(Date.now() - 35 * 60000).toISOString() // 35 minutes ago (< 60 min)
  };

  vibrateCall = null;
  checkoutApiCalled = false;
  btn.dispatchEvent({ type: "pointerdown", button: 0 });

  // Wait 1300ms to allow full hold cycle to complete
  await new Promise(r => setTimeout(r, 1300));

  assert(vibrateCall !== null, "Phải kích hoạt navigator.vibrate khi giữ đủ 1.2s");
  assert.deepStrictEqual(vibrateCall, [30, 50, 30], "Mẫu rung haptic phải là [30, 50, 30]");
  assert.strictEqual(text.textContent, "ĐANG XÁC NHẬN TAN CA...", "Text phải đổi thành ĐANG XÁC NHẬN TAN CA...");
  assert.strictEqual(bar.style.width, "100%", "Thanh tiến trình đạt 100%");
  assert(earlyModal.classList.contains("active"), "Modal cảnh báo kết thúc sớm phải mở");
  assert.strictEqual(domElements.get("earlyMinsCount").textContent, 35, "Số phút hiển thị phải là 35");
  assert(!checkoutApiCalled, "Không được tự động gọi checkout API khi ca < 60p mà chưa xác nhận");
  console.log("   ✓ Haptic feedback [30, 50, 30] rung thành công.");
  console.log("   ✓ Text chuyển thành 'ĐANG XÁC NHẬN TAN CA...'.");
  console.log("   ✓ Modal cảnh báo ra ca sớm đã mở với số phút 35.");

  // Test cancel early checkout
  const btnCancelEarly = domElements.get("btnCancelEarlyCheckout");
  btnCancelEarly.click();
  assert(!earlyModal.classList.contains("active"), "Modal phải đóng khi bấm Hủy");
  assert.strictEqual(bar.style.width, "0%", "Thanh tiến trình reset về 0%");
  assert(text.textContent === "GIỮ 1.2 GIÂY ĐỂ KẾT THÚC CA" || text.textContent === "Nhấn giữ để Tan Ca", "Text reset về ban đầu");
  console.log("   ✓ Bấm Hủy đóng modal và reset trạng thái nút về ban đầu.");

  // TEST 4: Full 1.2s Hold triggering checkout (>= 60 minutes)
  console.log("\n[TEST 4] Nhấn giữ đủ 1.2s khi ca >= 60 phút - Kích hoạt Check-out thành công:");
  state.currentActiveAttendance = {
    checkin_time: "07:00",
    checkout_time: null,
    created_at: new Date(Date.now() - 90 * 60000).toISOString() // 90 mins (>= 60 min)
  };

  vibrateCall = null;
  checkoutApiCalled = false;
  btn.dispatchEvent({ type: "pointerdown", button: 0 });

  // Wait 1300ms to allow full hold cycle to complete
  await new Promise(r => setTimeout(r, 1300));

  assert(vibrateCall !== null, "Phải kích hoạt navigator.vibrate khi giữ đủ 1.2s");
  assert(
    JSON.stringify(vibrateCall) === JSON.stringify([30, 50, 30]) ||
    JSON.stringify(vibrateCall) === JSON.stringify([12, 35]),
    "Mẫu rung haptic phải hợp lệ"
  );
  assert(checkoutApiCalled, "Hàm executeStaffCheckout phải được gọi khi ca >= 60 phút");
  assert.strictEqual(checkoutConfirmEarly, false, "confirm_early phải là false cho ca bình thường");
  assert.strictEqual(btn.style.display, "none", "Nút Press-and-Hold phải ẩn khi ca đã hoàn tất");
  assert.strictEqual(domElements.get("completedShiftCard").style.display, "block", "Thẻ hoàn tất ca phải hiển thị");
  console.log("   ✓ Check-out API được kích hoạt thành công (ca >= 60p).");
  console.log("   ✓ Nút Press-and-Hold tự động ẩn đi và Thẻ hoàn tất ca hiển thị.");

  // TEST 5: Integration with loadAttendanceTab
  console.log("\n[TEST 5] Tích hợp với loadAttendanceTab (Hiển thị/Ẩn đúng trạng thái):");
  isShiftCheckedOut = false; // Reset back to in-progress for tab reload test
  await loadAttendanceTab();
  assert.strictEqual(btn.style.display, "flex", "Nút Press-and-Hold phải hiển thị (display: flex) khi đang trong ca");
  assert.strictEqual(domElements.get("btnCheckinPrimary").style.display, "none", "Nút Check-in 1-tap phải ẩn khi đang trong ca");
  console.log("   ✓ loadAttendanceTab tự động kích hoạt và hiển thị nút Press-and-Hold khi có ca trực.");

  console.log("\n==================================================================");
  console.log("TẤT CẢ 5 KIỂM THỬ CHO TASK 2.1 ĐÃ PASS 100%!");
  console.log("==================================================================");
}

runTests()
  .then(() => process.exit(0))
  .catch(err => {
    console.error("Test execution failed:", err);
    process.exit(1);
  });
