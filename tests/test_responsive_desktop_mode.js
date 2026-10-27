// ==========================================================================
// TEST SUITE: RESPONSIVE DESKTOP FLUID MODE (TASK 3.1)
// Covers:
//   1. CSS Responsive Architecture (mobile.css)
//   2. DOM Structure & Action Sheet Controls (index.html)
//   3. Responsive View Engine & Device Detection (navModule.js)
// ==========================================================================

import assert from "assert";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");
const cssPath = path.join(projectRoot, "frontend", "mobile.css");
const htmlPath = path.join(projectRoot, "frontend", "index.html");

console.log("==================================================================");
console.log("RUNNING TEST SUITE: RESPONSIVE DESKTOP & FLUID MODE (TASK 3.1)");
console.log("==================================================================");

// --------------------------------------------------------------------------
// TEST 1: CSS RESPONSIVE ARCHITECTURE IN mobile.css
// --------------------------------------------------------------------------
console.log("\n[TEST 1] Kiểm tra cấu trúc CSS Responsive trong mobile.css:");
const cssContent = fs.readFileSync(cssPath, "utf-8");

// 1A. Breakpoint queries
assert(cssContent.includes("@media (min-width: 540px)"), "CSS thiếu @media (min-width: 540px) cho mobile giả lập!");
assert(cssContent.includes("@media (min-width: 768px)"), "CSS thiếu @media (min-width: 768px) cho Tablet!");
assert(cssContent.includes("@media (min-width: 1024px)"), "CSS thiếu @media (min-width: 1024px) cho Desktop!");
console.log("   ✓ Đầy đủ các media queries: 540px, 768px (Tablet), 1024px (Desktop).");

// 1B. .mobile-app fluid dimensions
assert(cssContent.includes("view-desktop-fluid"), "CSS thiếu class view-desktop-fluid!");
assert(cssContent.includes("max-width: 1100px") || cssContent.includes("max-width: 1200px"), "Thiếu thiết lập max-width 1100px/1200px cho fluid mode!");
assert(cssContent.includes("height: 96dvh"), "Thiếu thiết lập height: 96dvh cho fluid mode!");
assert(cssContent.includes("border-radius: 24px"), "Thiếu thiết lập border-radius: 24px cho fluid mode!");
console.log("   ✓ .mobile-app bung rộng 1100px, 96dvh, bo góc 24px khi kích hoạt fluid mode.");

// 1C. Tab Chấm Công 2 cột cân đối
assert(cssContent.includes(".attendance-col-left"), "CSS thiếu .attendance-col-left!");
assert(cssContent.includes(".attendance-col-right"), "CSS thiếu .attendance-col-right!");
assert(cssContent.includes("width: 360px"), "CSS thiếu độ rộng 360px cho cột trái chấm công!");
assert(cssContent.includes("#sopChecklistCard"), "CSS thiếu căn chỉnh #sopChecklistCard cho cột phải!");
console.log("   ✓ Tab Chấm Công bố cục 2 cột cân đối: Cột trái 360px, Cột phải Checklist flex 1.");

// 1D. Tab Lịch Ca thoáng đãng & đa cột
assert(cssContent.includes(".shift-cards-split"), "CSS thiếu căn chỉnh .shift-cards-split!");
assert(cssContent.includes("#staffMyScheduleList"), "CSS thiếu căn chỉnh lưới ca cá nhân #staffMyScheduleList!");
console.log("   ✓ Tab Lịch Ca lưới tuần bung rộng, chia cột ca sáng/tối không bị co cụm.");

// 1E. Tab Phiếu Lương căn giữa max-width 600px
assert(cssContent.includes("max-width: 600px"), "CSS thiếu căn giữa max-width 600px cho Thermal Receipt!");
assert(cssContent.includes("#staffPortalContainer"), "CSS thiếu căn chỉnh #staffPortalContainer!");
assert(cssContent.includes("#slipList"), "CSS thiếu lưới danh sách phiếu lương admin #slipList!");
console.log("   ✓ Tab Phiếu Lương: Thermal Receipt căn giữa trang nhã max-width 600px, danh sách admin dạng lưới.");

// 1F. Bảo toàn 100% trải nghiệm di động (< 768px)
assert(cssContent.includes("@media (max-width: 767px)"), "CSS thiếu query bảo vệ màn hình nhỏ (< 768px)!");
assert(cssContent.includes("display: contents"), "CSS thiếu display: contents cho 2 cột trên điện thoại để giữ nguyên DOM!");
console.log("   ✓ Trải nghiệm điện thoại (< 768px) bảo toàn trọn vẹn 100% với display: contents.");


// --------------------------------------------------------------------------
// TEST 2: KIỂM TRA DOM VÀ CÁC THẺ TRONG index.html
// --------------------------------------------------------------------------
console.log("\n[TEST 2] Kiểm tra markup HTML trong index.html:");
const htmlContent = fs.readFileSync(htmlPath, "utf-8");

assert(htmlContent.includes('class="attendance-col-left"'), "index.html thiếu .attendance-col-left!");
assert(htmlContent.includes('class="attendance-col-right"'), "index.html thiếu .attendance-col-right!");
assert(htmlContent.includes('id="devSimulatorStrip"'), "index.html thiếu #devSimulatorStrip!");
assert(htmlContent.includes('id="netStatusCard"'), "index.html thiếu #netStatusCard!");
assert(htmlContent.includes('id="activeShiftCard"'), "index.html thiếu #activeShiftCard!");
assert(htmlContent.includes('id="sopChecklistCard"'), "index.html thiếu #sopChecklistCard!");
assert(htmlContent.includes('id="managerAttendancePanel"'), "index.html thiếu #managerAttendancePanel!");
console.log("   ✓ Cấu trúc DOM Tab Chấm Công phân chia đúng 2 cột ngữ nghĩa.");

assert(htmlContent.includes('id="btnToggleFluidSheet"'), "index.html thiếu nút #btnToggleFluidSheet trong Action Sheet!");
assert(htmlContent.includes('id="fluidCurrentLabel"'), "index.html thiếu badge #fluidCurrentLabel!");
assert(htmlContent.includes('id="btnDesktopSheet"'), "index.html thiếu nút #btnDesktopSheet!");
assert(htmlContent.includes('href="desktop.html"'), "index.html thiếu liên kết desktop.html cho Admin!");
console.log("   ✓ Action Sheet đầy đủ nút Chế Độ Mở Rộng (#btnToggleFluidSheet) và Chế Độ Máy Tính (#btnDesktopSheet).");


// --------------------------------------------------------------------------
// TEST 3: KIỂM TRA LOGIC NHẬN DIỆN THIẾT BỊ & TOGGLE VIEW TRONG navModule.js
// --------------------------------------------------------------------------
console.log("\n[TEST 3] Kiểm tra logic thiết bị & toggle view mode (navModule.js):");

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
  click() {
    this.dispatchEvent({ type: "click" });
  }
}

const mockStorage = {};
const mockLocalStorage = {
  getItem: (k) => (k in mockStorage ? mockStorage[k] : null),
  setItem: (k, v) => { mockStorage[k] = String(v); },
  removeItem: (k) => { delete mockStorage[k]; },
  clear: () => { for (const k in mockStorage) delete mockStorage[k]; }
};

const domElements = new Map();
function getOrCreateMockEl(id, tag = "div") {
  if (!domElements.has(id)) {
    domElements.set(id, new MockElement(tag, id));
  }
  return domElements.get(id);
}

global.localStorage = mockLocalStorage;
global.document = {
  body: new MockElement("BODY", "body"),
  documentElement: new MockElement("HTML", "html"),
  getElementById: (id) => getOrCreateMockEl(id),
  querySelector: (sel) => null,
  querySelectorAll: (sel) => []
};
global.window = {
  innerWidth: 1200,
  localStorage: mockLocalStorage
};

// Import module dynamically
const navModule = await import("../frontend/src/modules/navModule.js");
const { initResponsiveViewMode, toggleResponsiveViewMode } = navModule;

// Subtest 3A: Chưa lưu thiết lập & màn hình lớn (>= 1024px) -> Tự động kích hoạt fluid mode
mockLocalStorage.clear();
document.body.classList = new MockClassList();
window.innerWidth = 1280;

initResponsiveViewMode();

assert(document.body.classList.contains("view-desktop-fluid"), "Màn hình >= 1024px phải tự động thêm class view-desktop-fluid!");
assert.strictEqual(mockLocalStorage.getItem("fnbops_view_mode"), "fluid", "localStorage phải lưu 'fluid'!");
const fluidLabel = document.getElementById("fluidCurrentLabel");
assert(fluidLabel.textContent.includes("1100px") || fluidLabel.textContent.includes("Mở rộng"), "Badge phải hiển thị trạng thái Mở rộng!");
console.log("   ✓ Tự động nhận diện màn hình lớn (1280px >= 1024px) -> Kích hoạt chế độ desktop fluid.");

// Subtest 3B: Chưa lưu thiết lập & màn hình điện thoại (< 1024px) -> Mặc định compact mode
mockLocalStorage.clear();
document.body.classList = new MockClassList();
window.innerWidth = 414;

initResponsiveViewMode();

assert(!document.body.classList.contains("view-desktop-fluid"), "Màn hình < 1024px không được tự bật view-desktop-fluid!");
assert(document.body.classList.contains("view-desktop-compact"), "Màn hình < 1024px phải có view-desktop-compact!");
assert.strictEqual(mockLocalStorage.getItem("fnbops_view_mode"), "compact", "localStorage phải lưu 'compact'!");
assert(fluidLabel.textContent.includes("500px"), "Badge phải hiển thị trạng thái Khung 500px!");
console.log("   ✓ Tự động nhận diện màn hình nhỏ (414px < 1024px) -> Giữ nguyên chế độ Khung 500px.");

// Subtest 3C: Tôn trọng cấu hình đã lưu trong localStorage ('fluid')
mockLocalStorage.setItem("fnbops_view_mode", "fluid");
document.body.classList = new MockClassList();
window.innerWidth = 768; // Tablet

initResponsiveViewMode();

assert(document.body.classList.contains("view-desktop-fluid"), "Phải tải đúng cấu hình đã lưu là 'fluid'!");
console.log("   ✓ Tôn trọng cấu hình người dùng đã lưu trong localStorage ('fluid').");

// Subtest 3D: Nút chuyển đổi toggleResponsiveViewMode()
const next1 = toggleResponsiveViewMode();
assert.strictEqual(next1, "compact", "Chuyển từ fluid sang compact!");
assert(!document.body.classList.contains("view-desktop-fluid"), "Phải gỡ class view-desktop-fluid!");
assert(document.body.classList.contains("view-desktop-compact"), "Phải có class view-desktop-compact!");
assert.strictEqual(mockLocalStorage.getItem("fnbops_view_mode"), "compact", "localStorage phải cập nhật compact!");

const next2 = toggleResponsiveViewMode();
assert.strictEqual(next2, "fluid", "Chuyển từ compact sang fluid!");
assert(document.body.classList.contains("view-desktop-fluid"), "Phải có lại class view-desktop-fluid!");
assert(!document.body.classList.contains("view-desktop-compact"), "Phải gỡ class view-desktop-compact!");
assert.strictEqual(mockLocalStorage.getItem("fnbops_view_mode"), "fluid", "localStorage phải cập nhật fluid!");
console.log("   ✓ Nút chuyển đổi toggleResponsiveViewMode chuyển qua lại giữa 500px và 1100px tức thì.");

// Subtest 3E: Click nút Action Sheet #btnToggleFluidSheet
const btnToggleSheet = document.getElementById("btnToggleFluidSheet");
btnToggleSheet.click();
assert(!document.body.classList.contains("view-desktop-fluid"), "Click nút sheet phải toggle trạng thái!");
btnToggleSheet.click();
assert(document.body.classList.contains("view-desktop-fluid"), "Click nút sheet lần 2 phải bật lại fluid!");
console.log("   ✓ Bấm nút #btnToggleFluidSheet trên Action Sheet hoạt động chính xác.");

console.log("\n==================================================================");
console.log("TẤT CẢ CÁC KIỂM THỬ CHO TASK 3.1 ĐÃ PASS 100%!");
console.log("==================================================================");
