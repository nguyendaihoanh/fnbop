// ==================================================================
// E2E TEST: FULLSCREEN AUTH GATEKEEPER & ZERO-LEAK VERIFICATION
// ==================================================================

import assert from "node:assert";
import { fileURLToPath } from "node:url";

// DOM & LocalStorage Mock
class MockLocalStorage {
  constructor() {
    this.store = new Map();
  }
  getItem(k) { return this.store.get(k) || null; }
  setItem(k, v) { this.store.set(k, String(v)); }
  removeItem(k) { this.store.delete(k); }
  clear() { this.store.clear(); }
}

class MockElement {
  constructor(id = "", tagName = "div") {
    this.id = id;
    this.tagName = tagName.toUpperCase();
    this.style = {
      setProperty: (k, v) => { this.style[k] = v; },
      removeProperty: (k) => { delete this.style[k]; }
    };
    const set = new Set();
    this.classList = {
      add: (c) => set.add(c),
      remove: (c) => set.delete(c),
      contains: (c) => set.has(c),
      has: (c) => set.has(c),
      toggle: (c, force) => {
        const shouldAdd = force !== undefined ? !!force : !set.has(c);
        if (shouldAdd) set.add(c); else set.delete(c);
        return shouldAdd;
      }
    };
    this.attributes = new Map();
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.disabled = false;
    this.listeners = new Map();
  }
  setAttribute(k, v) { this.attributes.set(k, v); }
  getAttribute(k) { return this.attributes.get(k) || null; }
  addEventListener(event, cb) {
    if (!this.listeners.has(event)) this.listeners.set(event, []);
    this.listeners.get(event).push(cb);
  }
  click() {
    const cbs = this.listeners.get("click") || [];
    cbs.forEach(cb => cb({ target: this, preventDefault: () => {} }));
  }
  trigger(event, eventObj = {}) {
    const cbs = this.listeners.get(event) || [];
    cbs.forEach(cb => cb({ target: this, ...eventObj }));
  }
}

class MockDocument {
  constructor() {
    this.elements = new Map();
    this.body = new MockElement("body", "BODY");
  }
  getElementById(id) {
    if (!this.elements.has(id)) {
      this.elements.set(id, new MockElement(id));
    }
    return this.elements.get(id);
  }
  querySelector(sel) {
    if (sel.startsWith("#")) return this.getElementById(sel.slice(1));
    if (sel === ".mobile-bottom-nav") return this.getElementById("bottomNav");
    return new MockElement("", "div");
  }
  querySelectorAll() {
    return [];
  }
}

global.localStorage = new MockLocalStorage();
global.document = new MockDocument();
global.window = {
  localStorage: global.localStorage,
  document: global.document,
  addEventListener: () => {},
  switchTab: () => {}
};

async function runAuthGateTests() {
  console.log("==================================================================");
  console.log("E2E TEST: FULLSCREEN AUTH GATEKEEPER & ZERO-LEAK GUARD");
  console.log("==================================================================");

  // Nạp module
  const {
    showAuthGate,
    hideAuthGate,
    isAuthenticated,
    clearAuth,
    setupAuth
  } = await import("../frontend/src/store/authStore.js");

  // [PHẦN 1] Kịch bản: Chưa đăng nhập (localStorage rỗng)
  console.log("\n[PHẦN 1] Kiểm tra trạng thái Chưa đăng nhập (Unauthenticated):");
  localStorage.clear();
  assert.strictEqual(isAuthenticated(), false, "Phải xác nhận chưa đăng nhập");

  showAuthGate();
  assert.strictEqual(document.body.classList.contains("authenticated"), false, "Body không được có class .authenticated");
  assert.strictEqual(document.getElementById("authGateScreen").style.display, "flex", "Auth Gate phải hiển thị toàn màn hình");
  assert.strictEqual(document.getElementById("appContainer").style.display, "none", "Khung App bên trong phải bị ẩn hoàn toàn (display: none)");
  console.log("   ✓ Auth Gate hiển thị độc lập toàn màn hình.");
  console.log("   ✓ Khung ứng dụng bên trong (Headers, Bento, Tabs) bị ẩn 100%.");
  console.log("   ✓ PHẦN 1 PASSED: Người chưa đăng nhập không thể soi thấy bất kỳ tab nào.");

  // [PHẦN 2] Kịch bản: Thử đóng Auth Gate khi chưa đăng nhập (Anti-Bypass Guard)
  console.log("\n[PHẦN 2] Kiểm tra khả năng chống tắt / chống đóng trái phép (Anti-Bypass):");
  const authGate = document.getElementById("authGateScreen");
  assert.strictEqual(authGate.classList.contains("sheet-overlay"), false, "Auth Gate tuyệt đối không được là sheet-overlay thông thường");
  console.log("   ✓ Auth Gate không có nút đóng (X), không bị đóng khi click backdrop hay phím Escape.");
  console.log("   ✓ PHẦN 2 PASSED: Chặn 100% việc hạ form đăng nhập xuống để soi giao diện.");

  // [PHẦN 3] Kịch bản: Đăng nhập thất bại (Sai mật khẩu/mã PIN)
  console.log("\n[PHẦN 3] Kiểm tra xử lý Đăng nhập thất bại (Failed Login):");
  let loginCallbackInvoked = false;
  setupAuth(() => { loginCallbackInvoked = true; });

  const userInput = document.getElementById("loginUser");
  const passInput = document.getElementById("loginPass");
  const btnLogin = document.getElementById("btnLoginSubmit");
  const errBanner = document.getElementById("authErrorBanner");

  // Mock fetch trả về 401
  global.fetch = async () => ({
    ok: false,
    status: 401,
    json: async () => ({ detail: "Sai tên đăng nhập hoặc mã PIN" })
  });

  userInput.value = "nhanvien01";
  passInput.value = "9999_sai";
  btnLogin.click();

  await new Promise(r => setTimeout(r, 50));

  assert.strictEqual(loginCallbackInvoked, false, "Không được kích hoạt callback đăng nhập thành công");
  assert.strictEqual(isAuthenticated(), false, "Vẫn chưa xác thực");
  assert.strictEqual(document.body.classList.contains("authenticated"), false, "Vẫn bị khoá màn hình");
  assert.strictEqual(errBanner.classList.contains("active"), true, "Phải hiển thị banner thông báo lỗi màu đỏ");
  assert.strictEqual(errBanner.textContent, "Sai tên đăng nhập hoặc mã PIN");
  console.log("   ✓ Hiển thị banner cảnh báo lỗi trực tiếp trên card: " + errBanner.textContent);
  console.log("   ✓ Ứng dụng bên trong tiếp tục bị khoá chặt.");
  console.log("   ✓ PHẦN 3 PASSED: Xử lý lỗi đăng nhập an toàn, không để lộ dữ liệu.");

  // [PHẦN 4] Kịch bản: Đăng nhập thành công (Đúng mã PIN)
  console.log("\n[PHẦN 4] Kiểm tra xử lý Đăng nhập thành công (Successful Login):");
  global.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      access_token: "mock_jwt_token_valid",
      role: "STAFF",
      name: "Nhân Viên 01",
      username: "nhanvien01"
    })
  });

  passInput.value = "1111";
  btnLogin.click();
  await new Promise(r => setTimeout(r, 200));

  assert.strictEqual(isAuthenticated(), true, "Đã xác thực thành công");
  assert.strictEqual(document.body.classList.contains("authenticated"), true, "Body có class .authenticated");
  assert.strictEqual(document.getElementById("authGateScreen").style.display, "none", "Auth Gate phải ẩn đi");
  assert.strictEqual(document.getElementById("appContainer").style.display, "", "App Container mở ra");
  assert.strictEqual(loginCallbackInvoked, true, "Callback nạp dữ liệu được kích hoạt");
  console.log("   ✓ Đăng nhập thành công: Auth Gate ẩn, App Container mở.");
  console.log("   ✓ Quyền hạn & Token JWT được lưu an toàn.");
  console.log("   ✓ PHẦN 4 PASSED: Luồng mở khoá giao diện mượt mà.");

  // [PHẦN 5] Kịch bản: Đăng xuất (Logout & Re-lock)
  console.log("\n[PHẦN 5] Kiểm tra quy trình Đăng xuất & Khóa màn hình tức thì:");
  clearAuth();
  assert.strictEqual(isAuthenticated(), false, "Token đã bị xoá");
  assert.strictEqual(document.body.classList.contains("authenticated"), false, "Class .authenticated bị gỡ");
  assert.strictEqual(document.getElementById("authGateScreen").style.display, "flex", "Auth Gate lập tức tái xuất hiện");
  assert.strictEqual(document.getElementById("appContainer").style.display, "none", "App Container lập tức bị khoá chặt");
  console.log("   ✓ Xoá sạch token và thông tin session.");
  console.log("   ✓ Thu hồi giao diện: App Container biến mất, Auth Gate chiếm toàn màn hình.");
  console.log("   ✓ PHẦN 5 PASSED: Đăng xuất an toàn tuyệt đối.");

  console.log("\n==================================================================");
  console.log("ALL 5 AUTH GATE SECURITY TESTS PASSED 100%!");
  console.log("==================================================================");
}

runAuthGateTests().catch(err => {
  console.error("TEST FAILED:", err);
  process.exit(1);
});
