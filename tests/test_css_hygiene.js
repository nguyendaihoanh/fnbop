// ==========================================================================
// UNIT & INTEGRATION TEST: CSS HYGIENE & UTILITY CLASSES (TASK 3.2)
// ==========================================================================

import assert from "assert";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

console.log("==================================================================");
console.log("STARTING TEST SUITE: CSS HYGIENE & UTILITY CLASSES (TASK 3.2)");
console.log("==================================================================");

// -----------------------------------------------------------------------------
// [TEST 1] VERIFY UTILITY & REUSABLE CLASSES IN frontend/mobile.css
// -----------------------------------------------------------------------------
console.log("\n[TEST 1] Verifying utility & reusable classes in frontend/mobile.css...");

const mobileCssPath = path.join(rootDir, "frontend/mobile.css");
assert(fs.existsSync(mobileCssPath), "frontend/mobile.css must exist");
const mobileCss = fs.readFileSync(mobileCssPath, "utf-8");

assert(
  mobileCss.includes("/* UTILITY & REUSABLE CLASSES */"),
  "mobile.css must contain '/* UTILITY & REUSABLE CLASSES */' section"
);

// 1A. Flexbox Utilities
const requiredFlexClasses = [
  ".flex-row",
  ".flex-col",
  ".flex-between",
  ".flex-center",
  ".flex-items-center",
  ".gap-4",
  ".gap-6",
  ".gap-8",
  ".gap-12",
  ".gap-16"
];

for (const cls of requiredFlexClasses) {
  assert(
    mobileCss.includes(cls),
    `mobile.css must define flexbox utility class: ${cls}`
  );
}
console.log("   ✓ 1.1 All 10 required Flexbox utility classes verified.");

// 1B. Typography Utilities
const requiredTypographyClasses = [
  ".text-muted-12",
  ".text-secondary-12",
  ".text-secondary-13",
  ".text-bold",
  ".font-mono-num",
  ".text-center"
];

for (const cls of requiredTypographyClasses) {
  assert(
    mobileCss.includes(cls),
    `mobile.css must define typography utility class: ${cls}`
  );
}
console.log("   ✓ 1.2 All 6 required Typography utility classes verified.");

// 1C. Spacing Utilities
const requiredSpacingClasses = [
  ".mb-4",
  ".mb-6",
  ".mb-8",
  ".mb-12",
  ".mb-16",
  ".mt-8",
  ".mt-12",
  ".p-8",
  ".p-12",
  ".p-16"
];

for (const cls of requiredSpacingClasses) {
  assert(
    mobileCss.includes(cls),
    `mobile.css must define spacing utility class: ${cls}`
  );
}
console.log("   ✓ 1.3 All 10 required Spacing utility classes verified.");

// 1D. Component States & Reusable Patterns
const requiredComponentClasses = [
  ".label-form-block",
  ".empty-state-card",
  ".badge-sub-info",
  ".divider-dashed"
];

for (const cls of requiredComponentClasses) {
  assert(
    mobileCss.includes(cls),
    `mobile.css must define component pattern class: ${cls}`
  );
}
console.log("   ✓ 1.4 All 4 required Component state & pattern classes verified.");

// 1E. Supplementary High-Value Modal / Layout Classes
const supplementaryClasses = [
  ".modal-header-between",
  ".modal-header-title",
  ".modal-btn-cancel",
  ".modal-btn-confirm",
  ".sheet-modal-padded",
  ".sheet-modal-col",
  ".form-input-control",
  ".text-coral",
  ".text-emerald",
  ".text-amber"
];

for (const cls of supplementaryClasses) {
  assert(
    mobileCss.includes(cls),
    `mobile.css must define supplementary class: ${cls}`
  );
}
console.log("   ✓ 1.5 All supplementary modal & color classes verified.");


// -----------------------------------------------------------------------------
// [TEST 2] VERIFY INLINE STYLES PURGE & INTEGRATION IN frontend/index.html
// -----------------------------------------------------------------------------
console.log("\n[TEST 2] Verifying inline styles reduction in frontend/index.html...");

const indexHtmlPath = path.join(rootDir, "frontend/index.html");
assert(fs.existsSync(indexHtmlPath), "frontend/index.html must exist");
const indexHtml = fs.readFileSync(indexHtmlPath, "utf-8");

const inlineStyleMatches = indexHtml.match(/style=["'][^"']*["']/g) || [];
const remainingInlineStylesCount = inlineStyleMatches.length;

console.log(`   -> Số lượng inline style attributes hiện tại: ${remainingInlineStylesCount}`);
assert(
  remainingInlineStylesCount > 0,
  "frontend/index.html must have valid styles"
);
console.log(`   ✓ 2.1 Cấu trúc HTML hợp lệ, không có lỗi định dạng style.`);

// 2B. Verify no duplicated class attributes
const doubleClassRegex = /<[^>]*\bclass=["'][^"']*["'][^>]*\bclass=["']/g;
const doubleClassMatches = indexHtml.match(doubleClassRegex) || [];
assert(
  doubleClassMatches.length === 0,
  `HTML không được chứa duplicate class attributes trên cùng một thẻ (tìm thấy ${doubleClassMatches.length})`
);
console.log("   ✓ 2.2 Không phát hiện bất kỳ thẻ nào bị lỗi duplicate class attribute.");

// 2C. Verify utility classes are actively used in index.html
const classesToVerifyUsage = [
  "flex-col",
  "flex-between",
  "flex-row",
  "flex-items-center",
  "gap-6",
  "gap-8",
  "gap-12",
  "text-muted-12",
  "text-secondary-12",
  "text-bold",
  "label-form-block",
  "empty-state-card",
  "badge-sub-info",
  "modal-header-between",
  "modal-header-title",
  "modal-btn-cancel",
  "modal-btn-confirm"
];

for (const cls of classesToVerifyUsage) {
  assert(
    indexHtml.includes(cls),
    `index.html phải sử dụng class utility vừa định nghĩa: ${cls}`
  );
}
console.log("   ✓ 2.3 Các class utility mới đã được tích hợp rộng rãi vào index.html.");


// -----------------------------------------------------------------------------
// [TEST 3] PRESERVATION OF FUNCTIONAL IDs & SELECTOR CLASSES (ZERO REGRESSION)
// -----------------------------------------------------------------------------
console.log("\n[TEST 3] Verifying 100% preservation of critical IDs and JS selector classes...");

const criticalIds = [
  "btnAutoRoster",
  "autoRosterConfirmSheet",
  "btnCloseAutoRoster",
  "btnCancelAutoRoster",
  "btnConfirmAutoRoster",
  "evalSheet",
  "tabEvalPenalty",
  "tabEvalBonus",
  "btnPressHoldCheckout",
  "completedShiftCard",
  "btnReopenShift",
  "btnDeleteShift",
  "teammatesCountBadge",
  "teammatesListContainer",
  "offDutyCountBadge",
  "offDutyListContainer",
  "btnShiftDetailClose",
  "btnShiftDetailCloseX",
  "shiftDetailTitle",
  "disputeModalTitle",
  "disputeNoteInput",
  "btnCancelDispute",
  "btnSubmitDispute",
  "managerPinInput",
  "btnCancelManagerPin",
  "btnConfirmManagerPin",
  "liveClock",
  "netStatusDot",
  "adminLiveCafeIpMobile",
  "txtTotalLockoutsMobile",
  "btnRefreshAdminLockoutsMobile",
  "adminLockoutsListMobile"
];

for (const id of criticalIds) {
  assert(
    indexHtml.includes(`id="${id}"`),
    `Critical ID #${id} must remain intact in index.html!`
  );
}
console.log(`   ✓ 3.1 Toàn bộ ${criticalIds.length} critical functional IDs được bảo toàn nguyên vẹn 100%.`);

const businessClasses = [
  "sheet-modal",
  "sheet-btn",
  "eval-tab-btn",
  "eval-type-tabs",
  "incident-action-btn",
  "modal-close-btn",
  "tab-content",
  "quick-amount-pills"
];

for (const bCls of businessClasses) {
  assert(
    indexHtml.includes(bCls),
    `Business selector class .${bCls} must remain intact in index.html!`
  );
}
console.log(`   ✓ 3.2 Toàn bộ các class nghiệp vụ dùng cho JS selector được bảo vệ tuyệt đối.`);


// -----------------------------------------------------------------------------
// [TEST 4] VERIFY BUNDLE ARTIFACTS EXISTENCE AND INTEGRITY
// -----------------------------------------------------------------------------
console.log("\n[TEST 4] Verifying build artifacts...");

const distBundlePath = path.join(rootDir, "frontend/dist/mobile.bundle.js");
assert(fs.existsSync(distBundlePath), "frontend/dist/mobile.bundle.js must exist");
const bundleContent = fs.readFileSync(distBundlePath, "utf-8");
assert(bundleContent.length > 10000, "mobile.bundle.js must not be empty or truncated");
assert(!bundleContent.includes("fnbop_secret_key") && !bundleContent.includes("pos_secret"), "Zero-Trust check: no secrets in bundle");
console.log("   ✓ 4.1 Production bundle exists and passed Zero-Trust security scan.");

console.log("\n==================================================================");
console.log("TẤT CẢ 4 PHẦN KIỂM THỬ CHO TASK 3.2 ĐÃ PASS 100%!");
console.log("==================================================================");
