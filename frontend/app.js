// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.

let currentViewingStaffDesktop = null;

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function isHolidayDate(dStr) {
  if (!dStr) return false;
  const p = dStr.trim().split('/');
  return p.length >= 2 && parseInt(p[0], 10) === 2 && parseInt(p[1], 10) === 9;
}


let rawData = {};
let employeesMap = {};
let records = [];
let monthsAvailable = [];
const currentRealtimeMonth = String(new Date().getMonth() + 1);
let currentMonth = currentRealtimeMonth;
let myChart = null;
let allAlerts = [];

// ==========================================================================
// POLICY CONFIG — Audit Fix B1-B5 (28/08/2026)
// Moi thay doi nghiep vu chi can sua o day, khong can tim trong code
// ==========================================================================
const POLICY = {
    // B1: Ca chuan va buffer
    STANDARD_SHIFT_MINS: 300,           // 5h (Sang 6-11h, Chieu 17-22h)
    OT_BUFFER_PERCENT: 0.10,            // 10% buffer cho don dep
    get OT_BUFFER_MINS() { return Math.round(this.STANDARD_SHIFT_MINS * this.OT_BUFFER_PERCENT); }, // 30 phut
    get OT_ALERT_THRESHOLD() { return this.STANDARD_SHIFT_MINS + this.OT_BUFFER_MINS; }, // 330 phut
    EXCESS_THRESHOLD_MINS: 331,         // Tu 331p la Ngam ca / Can Quan ly duyet

    // B2: He thong phat tre (progressive discipline)
    LATE_THRESHOLD_WARN: 10,            // phut — bat dau dem vao counter
    LATE_THRESHOLD_INSTANT_FINE: 30,    // phut — phat 50k truc tiep
    LATE_INSTANT_FINE_AMOUNT: 50000,    // tien phat khi tre > 30 phut
    LATE_PENALTIES: [
        // count: so lan tre > 10 phut trong thang
        { count: 1, action: 'warn',      amount: 0,      label: 'Canh bao lan 1' },
        { count: 2, action: 'warn',      amount: 0,      label: 'Canh bao lan 2' },
        { count: 3, action: 'fine',      amount: 50000,  label: 'Phat 50,000d' },
        { count: 4, action: 'fine',      amount: 150000, label: 'Phat 150,000d' },
        { count: 5, action: 'terminate', amount: 0,      label: 'Canh bao do - Cho nghi' }
    ],

    // B4: Quan ly (Xac dinh dong qua role tai khoan hoac chuc danh)
    MANAGER_NAME: '',

    // Eval cutoff — ca truoc ngay nay khong can danh gia
    EVAL_CUTOFF: new Date(2026, 7, 1),  // 01/08/2026

    // Du toan
    TARGET_COST_PER_SHIFT: 85000,

    // B5: Bang phan vai tro nhan su (Role Map dong - khoi tao rong)
    ROLE_MAP: {}
};

function getStaffRole(name) {
    if (!name) return 'Phục vụ';
    if (window.state && window.state.staffAccounts) {
        for (let k in window.state.staffAccounts) {
            let a = window.state.staffAccounts[k];
            if ((a.full_name && a.full_name.trim().toLowerCase() === name.trim().toLowerCase()) || k.toLowerCase() === name.trim().toLowerCase()) {
                if (a.role === 'MANAGER' || a.position === 'MANAGER') return 'Quản lý';
                if (a.position === 'BARISTA') return 'Pha chế';
                return 'Phục vụ';
            }
        }
    }
    let upper = name.trim().toUpperCase();
    if (POLICY.ROLE_MAP && POLICY.ROLE_MAP[upper]) return POLICY.ROLE_MAP[upper];
    let noTone = upper.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/Đ/g, 'D');
    if (POLICY.ROLE_MAP && POLICY.ROLE_MAP[noTone]) return POLICY.ROLE_MAP[noTone];
    return 'Phục vụ';
}

/**
 * Xác định thời lượng chuẩn của ca (phút):
 * - Ca sáng (06:00 - 11:30): chuẩn 330 phút (5.5h).
 * - Ca tối vào từ 17h (17:00 - 23:00): chuẩn 360 phút (6.0h).
 * - Ca tối vào từ 18h (18:00 - 23:00): chuẩn 300 phút (5.0h).
 * - Mặc định: 300 phút.
 */
function getShiftStandardMins(shiftName, timeIn) {
    let sNorm = (shiftName || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/Đ/g, 'D').toLowerCase();
    let cinMins = null;
    if (timeIn) {
        try {
            let parts = timeIn.trim().split(':');
            if (parts.length >= 2) {
                cinMins = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
            }
        } catch(e) {}
    }

    // 1. Ca sáng (06:00 - 11:30): chuẩn 330 phút (5.5h)
    if (sNorm.includes('sang') || sNorm.includes('morning')) {
        return 330;
    }
    if (cinMins !== null && cinMins < 12 * 60) {
        return 330;
    }

    // 2. Ca tối
    if (sNorm.includes('17')) {
        return 360;
    }
    if (sNorm.includes('18')) {
        return 300;
    }

    if (cinMins !== null) {
        if (cinMins < 18 * 60) { // Vào trước 18:00 -> ca tối 17h: 360 phút (6.0h)
            return 360;
        } else { // Vào từ 18:00 -> ca tối 18h: 300 phút (5.0h)
            return 300;
        }
    }

    return POLICY.STANDARD_SHIFT_MINS || 300;
}

// ==========================================================================
// BONUS LEDGER (localStorage-based)
// bonusLedger = { "8": { "THIỆN": [ { id, date, amount, type: 'cash'|'bank', reason, timestamp } ] } }
// ==========================================================================
let bonusLedger = {};

function saveBonusLedger() {
    localStorage.setItem('bonusLedger_v2', JSON.stringify(bonusLedger));
}

function loadBonusLedger() {
    try {
        const stored = localStorage.getItem('bonusLedger_v2');
        bonusLedger = stored ? JSON.parse(stored) : {};
    } catch(e) {
        bonusLedger = {};
    }
}

function getStaffBonuses(month, staffName) {
    if (!bonusLedger[month] || !bonusLedger[month][staffName]) return [];
    return bonusLedger[month][staffName];
}

function getStaffBonusSummary(month, staffName) {
    const list = getStaffBonuses(month, staffName);
    let total = 0;
    let cash = 0;
    let bank = 0;
    list.forEach(item => {
        const val = parseInt(item.amount) || 0;
        total += val;
        if (item.type === 'cash') cash += val;
        else bank += val;
    });
    return { list, total, cash, bank, count: list.length };
}

// ==========================================================================
// ADVANCE LEDGER (localStorage-based)
// advanceLedger = { "8": { "THIỆN": [ { id, date, amount, type: 'cash'|'bank', reason, timestamp } ] } }
// ==========================================================================
let advanceLedger = {};

function saveAdvanceLedger() {
    localStorage.setItem('advanceLedger_v1', JSON.stringify(advanceLedger));
}

function loadAdvanceLedger() {
    try {
        const stored = localStorage.getItem('advanceLedger_v1');
        advanceLedger = stored ? JSON.parse(stored) : {};
    } catch(e) {
        advanceLedger = {};
    }
}

function getStaffAdvances(month, staffName) {
    if (!advanceLedger[month] || !advanceLedger[month][staffName]) return [];
    return advanceLedger[month][staffName];
}

function getStaffAdvanceSummary(month, staffName) {
    const list = getStaffAdvances(month, staffName);
    let total = 0;
    list.forEach(item => {
        total += parseInt(item.amount) || 0;
    });
    return total;
}

// ==========================================================================
// LEDGER API — ghi vào server.py (SỔ PHỤ)
// ==========================================================================
async function sendLedgerEntryAPI(payload) {
    try {
        const token = localStorage.getItem('vnaigc_jwt');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const nativePayload = {
            staff_name: payload.staff || payload.staff_name,
            month: String(payload.month || ''),
            type: (payload.type || '').includes('Thưởng') ? 'BONUS' : ((payload.type || '').includes('Ứng') ? 'ADVANCE' : 'DEDUCTION'),
            amount: parseInt(payload.amount, 10) || 0,
            payment_method: payload.payment_type === 'cash' ? 'CASH' : 'BANK',
            reason: payload.reason || ''
        };

        const response = await fetch('/api/v1/cc/payroll/ledger', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(nativePayload)
        });
        if (!response.ok) throw new Error('Network response was not ok');
        return true;
    } catch (e) {
        console.error('Error sending ledger entry:', e);
        showToast('Lỗi ghi nhận! Vui lòng thử lại.', 'error');
        return false;
    }
}

const fmtMoney = new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' });
const fmtNum = new Intl.NumberFormat('vi-VN');

async function init() {
    try {
        loadBonusLedger();
        loadAdvanceLedger();
        const token = localStorage.getItem('vnaigc_jwt');
        const res = await fetch('/api/v1/cc/data?t=' + Date.now(), {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (res.status === 401) {
            localStorage.removeItem('vnaigc_jwt');
            const loginOverlay = document.getElementById('loginOverlay');
            if (loginOverlay) loginOverlay.style.display = 'flex';
            return;
        }
        rawData = await res.json();
        processData();
        setupControls();
        setupModal();
        setupPayslipModal();
        updateUI();
        fetchDesktopRosterData('current').then(() => {
            fetchDesktopRosterData('next').then(() => {
                const filtered = currentMonth === 'all' ? records : records.filter(r => r.month === currentMonth);
                renderHeatmap(filtered);
            });
        });
        setupDesktopRosterControls();
    } catch (e) {
        console.error('Data error:', e);
    }
}

function getIdx(headers, possibleNames) {
    for (let i=0; i<headers.length; i++) {
        if (possibleNames.includes(headers[i].trim())) return i;
    }
    return -1;
}

function normalizeDateStr(d) {
    if (!d) return '';
    if (d.includes('/')) {
        let p = d.split('/');
        if (p.length === 3) return `${p[2]}-${p[1].padStart(2,'0')}-${p[0].padStart(2,'0')}`;
    }
    return d;
}


function processData() {
    const nvTab = rawData['NHÂN VIÊN'] || [];
    if (nvTab.length > 2) {
        const headersLeft = nvTab[2];
        const headersRight = nvTab[1];
        const idxName = getIdx(headersLeft, ['TÊN NHÂN VIÊN']);
        const idxWage = getIdx(headersLeft, ['LƯƠNG/GIỜ\n(VNĐ)', 'LƯƠNG/GIỜ']);
        const idxStatus = getIdx(headersRight, ['TRẠNG THÁI']);

function getCanonicalStaffName(rawName) {
    if (!rawName) return '';
    let str = String(rawName).trim().replace(/:+$/, '').trim();
    let nfc = str.normalize('NFC').toUpperCase();

    const staffDir = (rawData && rawData._meta && rawData._meta.staff_directory) ||
                     (typeof window !== 'undefined' && (window._staff_directory || (window.rawData && window.rawData._meta && window.rawData._meta.staff_directory)));

    if (staffDir && typeof staffDir === 'object') {
        for (const [uname, acc] of Object.entries(staffDir)) {
            if (!acc || typeof acc !== 'object') continue;
            const eid = String(acc.employee_id || '').trim().toUpperCase();
            const fn = String(acc.full_name || '').trim().normalize('NFC').toUpperCase();
            const uUpper = uname.trim().toUpperCase();
            const sheetNames = (acc.sheet_names || []).map(sn => String(sn).trim().normalize('NFC').toUpperCase()).filter(Boolean);
            const aliases = (acc.aliases || []).map(al => String(al).trim().normalize('NFC').toUpperCase()).filter(Boolean);
            const canonicalRep = sheetNames[0] || fn || uUpper;

            if (eid && nfc === eid) return canonicalRep;
            if (sheetNames.includes(nfc) || nfc === fn || nfc === uUpper || aliases.includes(nfc)) {
                return canonicalRep;
            }
        }
    }

    return nfc;
}

        for (let i = 3; i < nvTab.length; i++) {
            const row = nvTab[i];
            if (idxName !== -1 && row[idxName]) {
                const rawName = row[idxName].trim();
                const name = getCanonicalStaffName(rawName);
                let wageStr = (idxWage !== -1 && row[idxWage]) ? row[idxWage] : '0';
                wageStr = wageStr.replace(/[^\d]/g, '');
                let status = (idxStatus !== -1 && row[idxStatus]) ? row[idxStatus].trim().toUpperCase() : 'ĐANG LÀM';
                
                if (!employeesMap[name] || employeesMap[name].wage <= 0) {
                    employeesMap[name] = {
                        name: name,
                        wage: parseInt(wageStr) || 17000,
                        status: status
                    };
                }
            }
        }

        const staffDir = (rawData && rawData._meta && rawData._meta.staff_directory) ||
                         (typeof window !== 'undefined' && (window._staff_directory || (window.rawData && window.rawData._meta && window.rawData._meta.staff_directory)));
        if (staffDir && typeof staffDir === 'object') {
            for (const [uname, info] of Object.entries(staffDir)) {
                if (!info || typeof info !== 'object') continue;
                const fn = String(info.full_name || uname).trim().toUpperCase();
                const canonName = getCanonicalStaffName(fn);
                const aliases = (info.aliases || []).map(a => String(a).trim().toUpperCase());
                const sheetNames = (info.sheet_names || []).map(s => String(s).trim().toUpperCase());
                const targets = [canonName, fn, uname.toUpperCase(), ...aliases, ...sheetNames].filter(Boolean);

                for (const t of targets) {
                    if (!employeesMap[t]) {
                        employeesMap[t] = { name: t, wage: 17000, status: 'ĐANG LÀM' };
                    }
                    if (info.salary_type) {
                        employeesMap[t].salary_type = String(info.salary_type).toUpperCase();
                    }
                    if (info.fixed_salary != null) {
                        employeesMap[t].fixed_salary = parseInt(info.fixed_salary, 10) || 0;
                    }
                    if (info.hourly_rate && parseInt(info.hourly_rate, 10) > 0) {
                        employeesMap[t].wage = parseInt(info.hourly_rate, 10);
                    }
                }
            }
        }
    }

    const evalTab = rawData['ĐÁNH GIÁ'] || [];
    let evaluatedSet = new Set();
    if (evalTab.length > 0) {
        const h = evalTab[0];
        const iDate = getIdx(h, ['Ngày', 'Ngày làm việc']);
        const iName = getIdx(h, ['Nhân Viên', 'Tên Nhân Viên']);
        for (let i = 1; i < evalTab.length; i++) {
            const r = evalTab[i];
            const d = r[iDate] ? r[iDate].trim() : '';
            const n = r[iName] ? r[iName].trim().toUpperCase() : '';
            
            // N8N webhook sends YYYY-MM-DD. Let's normalize everything to YYYY-MM-DD
            let normD = d;
            if (d.includes('/')) {
                let p = d.split('/');
                if (p.length === 3) normD = `${p[2]}-${p[1].padStart(2,'0')}-${p[0].padStart(2,'0')}`;
            }
            if (normD && n) evaluatedSet.add(`${normD}|${n}`);
        }
    }

    // Lấy thêm danh sách đã đánh giá tạm thời từ localStorage để ẩn ngay lập tức
    const localEvaluated = JSON.parse(localStorage.getItem('localEvaluatedShifts') || '[]');
    localEvaluated.forEach(key => evaluatedSet.add(key));

    const dlTab = rawData['DỮ LIỆU'] || [];
    if (dlTab.length > 0) {
        const headers = dlTab[0];
        const idxDate = getIdx(headers, ['Ngày', 'Ngày làm việc']);
        const idxName = getIdx(headers, ['Tên Nhân Viên', 'Tên', 'Nhân Viên']);
        const idxShift = getIdx(headers, ['Ca làm việc', 'Ca']);
        const idxIn = getIdx(headers, ['Giờ vào\n(HH:MM)', 'Giờ vào', 'Bắt đầu']);
        const idxOut = getIdx(headers, ['Giờ ra\n(HH:MM)', 'Giờ ra', 'Kết thúc']);
        const idxMins = getIdx(headers, ['Tổng phút (Tự động)', 'Tổng phút', 'Phút']);
        const idxMonth = getIdx(headers, ['Tháng']);
        const idxLate = getIdx(headers, ['Trễ']);
        const idxEval = getIdx(headers, ['Đánh Giá', 'Đánh giá']);

        let rawRecords = [];
        for (let i = 1; i < dlTab.length; i++) {
            const row = dlTab[i];
            const dateStr = (idxDate >= 0 && row[idxDate]) ? row[idxDate].trim() : '';
            let month = (idxMonth >= 0 && row[idxMonth]) ? row[idxMonth].trim() : '';
            if (!month && dateStr) {
                if (dateStr.includes('/')) {
                    const parts = dateStr.split('/');
                    if (parts.length >= 2) month = String(parseInt(parts[1], 10));
                } else if (dateStr.includes('-')) {
                    const parts = dateStr.split('-');
                    if (parts.length >= 2) month = String(parseInt(parts[1], 10));
                }
            }
            const rawName = (idxName >= 0 && row[idxName]) ? row[idxName].trim() : '';
            const name = getCanonicalStaffName(rawName);
            let isEvaluated = (idxEval >= 0 && row[idxEval]) ? true : false;
            
            // Normalize DỮ LIỆU date to YYYY-MM-DD to check against evaluatedSet
            let normDateDl = dateStr;
            if (dateStr.includes('/')) {
                let p = dateStr.split('/');
                if (p.length === 3) normDateDl = `${p[2]}-${p[1].padStart(2,'0')}-${p[0].padStart(2,'0')}`;
            }
            
            if (evaluatedSet.has(`${normDateDl}|${name}`)) {
                isEvaluated = true;
            }
            
            // --- DEMO OVERRIDE DA DUOC GO BO (28/08/2026 - Audit Fix A1) ---
            // Block cu: force isEvaluated=true cho thang 4-7, an ca chua danh gia
            // Da xoa de hien thi trang thai that cua du lieu
            // -----------------------------------------------------------------
            
            if (!month || !name) continue;
            if (!monthsAvailable.includes(month)) monthsAvailable.push(month);

            let minsStr = row[idxMins] ? row[idxMins].replace(',', '.') : '0';
            let mins = parseFloat(minsStr) || 0;
            
            let timeIn = row[idxIn] ? row[idxIn].trim() : '';
            let timeOut = row[idxOut] ? row[idxOut].trim() : '';
            let shift = row[idxShift] ? row[idxShift].trim() : '';
            
            let lateMins = (idxLate >= 0 && row[idxLate]) ? parseFloat(row[idxLate].replace(',', '.')) || 0 : 0;

            const emp = employeesMap[name] || { wage: 17000 };
            const shiftKey = `${dateStr}|${name}|${shift}|${timeIn}`;
            const shiftApprovals = (rawData && rawData._meta && rawData._meta.shift_approvals) || {};
            const approval = shiftApprovals[shiftKey] || null;

            let otStatus = 'STANDARD';
            let effectiveMins = mins;

            const isHistoric = (month && parseInt(month) < 9);

            const stdShiftMins = getShiftStandardMins(shift, timeIn);

            if (mins <= stdShiftMins) {
                otStatus = 'STANDARD';
                effectiveMins = mins;
            } else if (mins <= (stdShiftMins + POLICY.OT_BUFFER_MINS)) {
                otStatus = 'OT_PERF';
                effectiveMins = mins;
            } else {
                if (approval && approval.status === 'APPROVE') {
                    otStatus = 'APPROVED';
                    effectiveMins = approval.approved_mins || mins;
                } else if (approval && approval.status === 'CUT') {
                    otStatus = 'CUT';
                    effectiveMins = approval.approved_mins || stdShiftMins;
                } else if (isHistoric) {
                    otStatus = 'APPROVED';
                    effectiveMins = mins;
                } else {
                    otStatus = 'PENDING';
                    effectiveMins = stdShiftMins;
                }
            }

            let overtimeMins = Math.max(0, effectiveMins - stdShiftMins);
            let standardMins = effectiveMins - overtimeMins;
            let costRate = emp.wage / 60;

            // Eval cutoff: ca truoc 01/08/2026 khong can danh gia
            let dateParts = dateStr.split('/');
            let shiftDate = dateParts.length === 3 ? new Date(dateParts[2], dateParts[1] - 1, dateParts[0]) : null;
            let skipEval = shiftDate && shiftDate < POLICY.EVAL_CUTOFF;
            if (skipEval) isEvaluated = true; // Mien danh gia cho ca cu

            const isHoliday = isHolidayDate(dateStr);
            const holidayMultiplier = isHoliday ? 2 : 1;
            const holidayExtra = isHoliday ? (effectiveMins * costRate) : 0;

            rawRecords.push({
                rowIdx: i + 1,
                month,
                date: dateStr,
                name: name,
                shift: shift,
                in: timeIn,
                out: timeOut,
                mins: mins,
                effectiveMins: effectiveMins,
                standardMins: standardMins,
                overtimeMins: overtimeMins,
                lateMins: lateMins,
                standardCost: standardMins * costRate * holidayMultiplier,
                overtimeCost: overtimeMins * costRate * holidayMultiplier,
                totalCost: effectiveMins * costRate * holidayMultiplier,
                isHoliday: isHoliday,
                holidayMultiplier: holidayMultiplier,
                holidayExtra: holidayExtra,
                isEvaluated: isEvaluated,
                shiftKey: shiftKey,
                otStatus: otStatus,
                approval: approval
            });
        }
        
        // Dedup
        let dedupMap = new Map();
        rawRecords.forEach(r => {
            const key = `${r.date}|${r.name}|${r.shift}`;
            dedupMap.set(key, r);
        });
        records = Array.from(dedupMap.values());
    }

    // Parse SỔ PHỤ from Google Sheets into bonusLedger and advanceLedger
    const soPhuTab = rawData['SỔ PHỤ'] || [];
    if (soPhuTab.length > 1) {
        const header = soPhuTab[0];
        const idxTime = getIdx(header, ['Timestamp']);
        const idxName = getIdx(header, ['Nhân Viên', 'Tên Nhân Viên']);
        const idxMonth = getIdx(header, ['Tháng']);
        const idxType = getIdx(header, ['Loại']);
        const idxAmount = getIdx(header, ['Số Tiền']);
        const idxMethod = getIdx(header, ['Hình Thức']);
        const idxReason = getIdx(header, ['Lý Do']);

        for (let i = 1; i < soPhuTab.length; i++) {
            const row = soPhuTab[i];
            const rawName = (row[idxName] || '').trim();
            const name = getCanonicalStaffName(rawName);
            const month = (row[idxMonth] || '').trim();
            const type = (row[idxType] || '').trim();
            const amount = parseInt((row[idxAmount] || '0').toString().replace(/[^\d]/g, '')) || 0;
            const methodStr = (row[idxMethod] || '').trim().toLowerCase();
            const paymentType = methodStr.includes('chuyển khoản') || methodStr === 'bank' ? 'bank' : 'cash';
            const reason = (row[idxReason] || '').trim();
            const timestamp = (row[idxTime] || '').trim();

            if (!name || !month || amount <= 0) continue;

            const entry = {
                id: `SP-${month}-${name}-${i}`,
                date: timestamp.split(' ')[0] || '',
                amount: amount,
                type: paymentType,
                reason: reason,
                timestamp: timestamp
            };

            if (type === 'Thưởng') {
                if (!bonusLedger[month]) bonusLedger[month] = {};
                if (!bonusLedger[month][name]) bonusLedger[month][name] = [];
                const exists = bonusLedger[month][name].some(e => (e.timestamp && e.timestamp === timestamp) || (e.id === entry.id));
                if (!exists) bonusLedger[month][name].push(entry);
            } else if (type === 'Ứng') {
                if (!advanceLedger[month]) advanceLedger[month] = {};
                if (!advanceLedger[month][name]) advanceLedger[month][name] = [];
                const exists = advanceLedger[month][name].some(e => (e.timestamp && e.timestamp === timestamp) || (e.id === entry.id));
                if (!exists) advanceLedger[month][name].push(entry);
            }
        }
    }
    // Ensure the current real-world month is always available in the dropdown
    const realMonth = (new Date().getMonth() + 1).toString();
    if (!monthsAvailable.includes(realMonth)) {
        monthsAvailable.push(realMonth);
    }

    monthsAvailable.sort((a,b) => parseInt(a) - parseInt(b));
    if (monthsAvailable.length > 0) {
        currentMonth = monthsAvailable.includes(realMonth) ? realMonth : (monthsAvailable[monthsAvailable.length - 1] || realMonth);
    }
}

function setupControls() {
    const sel = document.getElementById('monthFilter');
    const optAll = document.createElement('option');
    optAll.value = 'all'; optAll.textContent = 'Tất cả các tháng';
    sel.appendChild(optAll);

    monthsAvailable.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = `Tháng ${m}`;
        if(m === currentMonth) opt.selected = true;
        sel.appendChild(opt);
    });
    sel.addEventListener('change', (e) => {
        currentMonth = e.target.value;
        updateUI();
    });

    setupTabSwitching();
}

function setupTabSwitching() {
    const tabsContainer = document.querySelector('.tabs-container');
    if (!tabsContainer || tabsContainer.dataset.bound) return;
    tabsContainer.dataset.bound = 'true';

    const tabBtns = document.querySelectorAll('.tab-btn');
    const views = document.querySelectorAll('.view-section');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            // Remove active from all tabs
            tabBtns.forEach(t => t.classList.remove('active'));
            // Add active to clicked tab
            btn.classList.add('active');

            // Hide all views
            views.forEach(v => v.classList.remove('active'));
            // Show target view
            const target = btn.getAttribute('data-tab');
            const targetView = document.getElementById(target + 'View');
            if (targetView) targetView.classList.add('active');
            
            // Re-render chart if Ops tab is opened to fix sizing issues
            if (target === 'ops' && myChart) {
                myChart.resize();
            }
        });
    });
}

function updateUI() {
    const role = localStorage.getItem('vnaigc_role') || (rawData._meta && rawData._meta.role) || 'STAFF';
    applyRolePermissionsDesktop(role, rawData._meta || {});
    const filtered = currentMonth === 'all' ? records : records.filter(r => r.month === currentMonth);
        
    let totalPay = 0, baseCost = 0, otCost = 0;
    let baseMins = 0, otMins = 0, totalDays = new Set(), totalShifts = 0, totalLateMins = 0;
    let staffOT = {}; 
    let staffShifts = {};
    
    allAlerts = [];

    filtered.forEach(r => {
        totalPay += r.totalCost;
        baseCost += r.standardCost;
        otCost += r.overtimeCost;
        baseMins += r.standardMins;
        otMins += r.overtimeMins;
        totalLateMins += r.lateMins;
        
        if (r.date) totalDays.add(r.date);
        totalShifts++;
        
        if (!staffShifts[r.name]) staffShifts[r.name] = 0;
        staffShifts[r.name]++;

        if (r.overtimeCost > 0) {
            if (!staffOT[r.name]) staffOT[r.name] = { name: r.name, otCost: 0, otMins: 0 };
            staffOT[r.name].otCost += r.overtimeCost;
            staffOT[r.name].otMins += r.overtimeMins;
        }

        // B1: Canh bao OT vuot buffer 10% (330 phut)
        if (r.overtimeMins > POLICY.OT_BUFFER_MINS && getStaffRole(r.name) !== 'Quản lý') {
            allAlerts.push({
                type: 'amber', icon: '⏱',
                msg: `<strong>Cảnh báo OT vượt buffer</strong>Dòng ${r.rowIdx} (${r.date}) ${r.name} làm ${r.mins} phút (vượt ${r.overtimeMins - POLICY.OT_BUFFER_MINS} phút so với buffer ${POLICY.OT_ALERT_THRESHOLD}p). Kiểm tra camera.`
            });
        }

        // B2: Canh bao di tre > 10 phut
        if (r.lateMins > POLICY.LATE_THRESHOLD_WARN && getStaffRole(r.name) !== 'Quản lý') {
            const lateLabel = r.lateMins > POLICY.LATE_THRESHOLD_INSTANT_FINE ? 'TRỄ NẶNG' : 'Trễ ca';
            allAlerts.push({
                type: r.lateMins > POLICY.LATE_THRESHOLD_INSTANT_FINE ? 'coral' : 'amber',
                icon: r.lateMins > POLICY.LATE_THRESHOLD_INSTANT_FINE ? '🚨' : '⏰',
                msg: `<strong>${lateLabel}</strong>Dòng ${r.rowIdx} (${r.date}) ${r.name} trễ ${r.lateMins} phút.${r.lateMins > POLICY.LATE_THRESHOLD_INSTANT_FINE ? ' Phạt 50,000đ.' : ''}`
            });
        }
        
        if (!r.in || !r.out) {
            allAlerts.push({
                type: 'coral', icon: '❌',
                msg: `<strong>Lỗi Dữ liệu (Thiếu Giờ)</strong>Dòng ${r.rowIdx} (${r.date}) ${r.name} thiếu giờ vào/ra. Cập nhật Sheet.`
            });
        }
    });

    // F&B Clopening Detection
    let shiftsByStaffAndDate = {};
    filtered.forEach(r => {
        if (!r.name || !r.date || !r.shift) return;
        if (!shiftsByStaffAndDate[r.name]) shiftsByStaffAndDate[r.name] = {};
        shiftsByStaffAndDate[r.name][r.date] = shiftsByStaffAndDate[r.name][r.date] || [];
        shiftsByStaffAndDate[r.name][r.date].push(r.shift.toLowerCase());
    });

    Object.keys(shiftsByStaffAndDate).forEach(staff => {
        let dates = Object.keys(shiftsByStaffAndDate[staff]);
        dates.forEach(dStr => {
            let parts = dStr.split('/');
            if (parts.length < 3) return;
            let dObj = new Date(parts[2], parts[1] - 1, parts[0]);
            let nextD = new Date(dObj);
            nextD.setDate(nextD.getDate() + 1);
            let nextDStr = `${String(nextD.getDate()).padStart(2, '0')}/${String(nextD.getMonth() + 1).padStart(2, '0')}/${nextD.getFullYear()}`;
            
            let todayShifts = shiftsByStaffAndDate[staff][dStr] || [];
            let nextShifts = shiftsByStaffAndDate[staff][nextDStr] || [];
            
            let hasNight = todayShifts.some(s => s.includes('tối'));
            let hasNextMorning = nextShifts.some(s => s.includes('sáng'));
            
            if (hasNight && hasNextMorning && getStaffRole(staff) !== 'Quản lý') {
                allAlerts.push({
                    type: 'coral', icon: '🚨',
                    msg: `<strong>Lỗi Vận hành (Clopening)</strong>Nhân sự ${staff} đóng ca tối (${dStr}) và mở ca sáng (${nextDStr}). Rủi ro kiệt sức.`
                });
            }
        });
    });

    // Attendance Score
    const totalWorkMins = baseMins + otMins;
    // B3: Chuyen can = ty le ca dung gio / tong ca (tinh per-individual, trung binh)
    let totalOnTimeShifts = 0;
    let totalFilteredShifts = 0;
    const staffAttendance = {};
    filtered.forEach(r => {
        if (!r.name || getStaffRole(r.name) === 'Quản lý') return;
        if (!staffAttendance[r.name]) staffAttendance[r.name] = { onTime: 0, total: 0 };
        staffAttendance[r.name].total++;
        totalFilteredShifts++;
        if (r.lateMins <= POLICY.LATE_THRESHOLD_WARN) {
            staffAttendance[r.name].onTime++;
            totalOnTimeShifts++;
        }
    });
    const attendanceScore = totalFilteredShifts > 0 
        ? ((totalOnTimeShifts / totalFilteredShifts) * 100).toFixed(1) 
        : '100.0';

    // Target Budget Calculation
    let targetShifts = 0;
    let targetCost = 0;
    if (currentMonth !== 'all') {
        let year = 2026;
        if (filtered.length > 0 && filtered[0].date) year = parseInt(filtered[0].date.split('/')[2]) || 2026;
        let mIdx = parseInt(currentMonth) - 1;
        let daysInMonth = new Date(year, mIdx + 1, 0).getDate();
        for (let d = 1; d <= daysInMonth; d++) {
            let dayOfWeek = new Date(year, mIdx, d).getDay();
            targetShifts += (dayOfWeek === 0 || dayOfWeek === 6) ? 8 : 7;
        }
        targetCost = targetShifts * POLICY.TARGET_COST_PER_SHIFT;
        
        document.getElementById('subTargetShifts').textContent = `Dự toán: ${fmtNum.format(targetShifts)} ca`;
        document.getElementById('subTargetPay').textContent = `Dự toán: ${fmtMoney.format(targetCost)}`;
        document.getElementById('subTargetShifts').className = totalShifts > targetShifts ? 'sub-metric over' : 'sub-metric under';
        document.getElementById('subTargetPay').className = totalPay > targetCost ? 'sub-metric over' : 'sub-metric under';
    } else {
        document.getElementById('subTargetShifts').textContent = `Vui lòng chọn 1 tháng cụ thể`;
        document.getElementById('subTargetPay').textContent = `Vui lòng chọn 1 tháng cụ thể`;
        document.getElementById('subTargetShifts').className = 'sub-metric';
        document.getElementById('subTargetPay').className = 'sub-metric';
    }

    // MoM Growth Calculation
    let curStats = { pay: 0, ot: 0, shifts: 0 };
    let prevStats = { pay: 0, ot: 0, shifts: 0 };
    let targetM = currentMonth === 'all' ? monthsAvailable[monthsAvailable.length - 1] : currentMonth;
    let prevM = monthsAvailable[monthsAvailable.indexOf(targetM) - 1];
    
    if (prevM) {
        records.forEach(r => {
            if (r.month === targetM) { curStats.pay += r.totalCost; curStats.ot += r.overtimeCost; curStats.shifts++; }
            else if (r.month === prevM) { prevStats.pay += r.totalCost; prevStats.ot += r.overtimeCost; prevStats.shifts++; }
        });
        const getGrowth = (cur, prev) => prev === 0 ? 0 : ((cur - prev) / prev) * 100;
        const renderBadge = (elId, val, invertGood = false) => {
            let el = document.getElementById(elId);
            el.textContent = val > 0 ? `+${val.toFixed(1)}%` : `${val.toFixed(1)}%`;
            if (val > 0) el.className = invertGood ? 'trend-pill up-bad' : 'trend-pill up-good';
            else if (val < 0) el.className = invertGood ? 'trend-pill down-good' : 'trend-pill down-bad';
            else el.className = 'trend-pill neutral';
        };
        document.getElementById('momTitle').textContent = `Tăng Trưởng (T${targetM} vs T${prevM})`;
        renderBadge('momPay', getGrowth(curStats.pay, prevStats.pay), true);
        renderBadge('momOT', getGrowth(curStats.ot, prevStats.ot), true);
        renderBadge('momShifts', getGrowth(curStats.shifts, prevStats.shifts), false);
    } else {
        document.getElementById('momTitle').textContent = `Tăng Trưởng (Không đủ DL)`;
        ['momPay', 'momOT', 'momShifts'].forEach(id => {
            let el = document.getElementById(id);
            el.textContent = '-';
            el.className = 'trend-pill neutral';
        });
    }

    document.getElementById('valTotalPay').textContent = fmtMoney.format(totalPay);
    document.getElementById('valOTCost').textContent = fmtMoney.format(otCost);
    document.getElementById('valTotalShifts').textContent = fmtNum.format(totalShifts);
    document.getElementById('valAttendanceScore').textContent = attendanceScore + '%';

    // Shift Distribution
    let w = Math.max(1, totalDays.size / 7);
    let uw = 0, op = 0, ow = 0;
    let htmlUw = '', htmlOw = '';

    Object.entries(staffShifts).sort((a,b) => b[1] - a[1]).forEach(([n, sh]) => {
        let spw = sh / w;
        let label = getStaffRole(n) === 'Quản lý' ? `${n} (Quản lý)` : n;
        let itemHtml = `<div style="display: flex; justify-content: space-between;"><span>${label}</span><span style="font-family: var(--font-mono);">${spw.toFixed(1)} ca</span></div>`;
        
        // Quan ly duoc mien tru khoi canh bao Burn-out
        if (getStaffRole(n) === 'Quản lý') {
            op++;
        } else if (spw < 2) { 
            uw++; htmlUw += itemHtml; 
        } else if (spw > 7) { 
            ow++; htmlOw += itemHtml; 
        } else { 
            op++; 
        }
    });

    document.getElementById('valUnderwork').textContent = uw;
    document.getElementById('valOptimal').textContent = op;
    document.getElementById('valOverwork').textContent = ow;
    
    document.getElementById('listUnderwork').innerHTML = htmlUw;
    document.getElementById('listOverwork').innerHTML = htmlOw;

    // Leaderboard
    const lbList = document.getElementById('topOTList');
    lbList.innerHTML = '';
    let staffArr = Object.values(staffOT).sort((a,b) => b.otCost - a.otCost);
    
    if (staffArr.length === 0) {
         lbList.innerHTML = `<div style="color:var(--text-secondary); font-size: 13px;">Không có OT phát sinh.</div>`;
    } else {
        staffArr.forEach(s => {
            let label = getStaffRole(s.name) === 'Quản lý' ? `${s.name} (Quản lý)` : s.name;
            lbList.innerHTML += `
                <div class="list-item">
                    <div class="li-left">
                        <span class="li-name">${label}</span>
                        <span class="li-sub">${(s.otMins/60).toFixed(1)}h OT</span>
                    </div>
                    <div class="li-val coral">${fmtMoney.format(s.otCost)}</div>
                </div>
            `;
        });
    }

    // Alerts rendering
    const alertListEl = document.getElementById('alertsList');
    alertListEl.innerHTML = '';
    document.getElementById('alertCount').textContent = `${allAlerts.length} Vấn đề`;
    
    allAlerts.sort((a,b) => a.type === 'coral' ? -1 : 1);
    
    if (allAlerts.length === 0) {
        alertListEl.innerHTML = `
            <div class="alert-box emerald">
                <div class="alert-icon">✓</div>
                <div class="alert-text"><strong>Hệ thống ổn định</strong>Không phát hiện lỗi dữ liệu.</div>
            </div>`;
    } else {
        allAlerts.forEach(a => {
            alertListEl.innerHTML += `
                <div class="alert-box ${a.type}">
                    <div class="alert-icon">${a.icon}</div>
                    <div class="alert-text">${a.msg}</div>
                </div>
            `;
        });
    }

    renderChart();
    renderHeatmap(filtered);
    renderPayslipTable(filtered);
}

function renderChart() {
    const ctx = document.getElementById('payrollChart').getContext('2d');
    
    let chartBase = {}, chartOT = {};
    monthsAvailable.forEach(m => { chartBase[m] = 0; chartOT[m] = 0; });
    
    records.forEach(r => {
        chartBase[r.month] += r.standardCost;
        chartOT[r.month] += r.overtimeCost;
    });

    const labels = Object.keys(chartBase).map(m => `Tháng ${m}`);
    const dataBase = Object.values(chartBase);
    const dataOT = Object.values(chartOT);

    if (myChart) myChart.destroy();

    Chart.defaults.color = '#8B857F';
    Chart.defaults.font.family = "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Monaco, Consolas, monospace";

    myChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Chi phí Chuẩn',
                    data: dataBase,
                    borderColor: '#2C2A29',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    tension: 0.3,
                    pointRadius: 3,
                    pointBackgroundColor: '#FFFFFF'
                },
                {
                    label: 'Phát sinh (OT)',
                    data: dataOT,
                    borderColor: '#F26D5B',
                    backgroundColor: 'rgba(242, 109, 91, 0.15)',
                    borderWidth: 2,
                    tension: 0.3,
                    pointRadius: 3,
                    fill: true,
                    pointBackgroundColor: '#FFFFFF'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top', align: 'end', labels: { usePointStyle: true, boxWidth: 6, color: '#2C2A29' } },
                tooltip: {
                    backgroundColor: '#FFFFFF',
                    titleColor: '#2C2A29',
                    bodyColor: '#2C2A29',
                    borderColor: '#EDEAE1',
                    borderWidth: 1,
                    padding: 12,
                    callbacks: { label: c => fmtMoney.format(c.raw) }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(0,0,0,0.03)' },
                    border: { display: false },
                    ticks: { callback: v => (v / 1000000) + 'Tr', color: '#8B857F' }
                },
                x: {
                    grid: { display: false },
                    border: { display: false },
                    ticks: { color: '#8B857F' }
                }
            }
        }
    });
}

function showToast(msg, type = 'success') {
    let toast = document.getElementById('vnaigc-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'vnaigc-toast';
        toast.style.position = 'fixed';
        toast.style.bottom = '30px';
        toast.style.right = '30px';
        toast.style.padding = '14px 28px';
        toast.style.borderRadius = '8px';
        toast.style.boxShadow = '0 10px 25px rgba(0,0,0,0.2)';
        toast.style.fontWeight = '600';
        toast.style.zIndex = '9999';
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(20px)';
        toast.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.style.backgroundColor = type === 'success' ? '#10B981' : '#F43F5E';
    toast.style.color = 'white';
    toast.style.display = 'block';
    
    // Trigger reflow
    void toast.offsetWidth;
    
    toast.style.opacity = '1';
    toast.style.transform = 'translateY(0)';
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(20px)';
        setTimeout(() => toast.style.display = 'none', 300);
    }, 2000);
}

function renderMissingEvals() {
    const container = document.getElementById('missingEvalsContainer');
    if (container) container.style.display = 'none';
    return false;
}

function setupModal() {
    const modal = document.getElementById('evalModal');
    const btnOpen = document.getElementById('btnOpenEval');
    const btnClose = document.getElementById('btnCloseEval');
    const btnSubmit = document.getElementById('btnSubmitEval');
    const selectStaff = document.getElementById('evalStaff');

    // Populate dropdown
    selectStaff.innerHTML = '';
    Object.values(employeesMap)
        .filter(emp => emp.status === 'ĐANG LÀM')
        .map(emp => emp.name)
        .sort()
        .forEach(name => {
            let opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            selectStaff.appendChild(opt);
        });

    // Open / Close
    btnOpen.addEventListener('click', () => {
        document.getElementById('evalDate').value = new Date().toISOString().split('T')[0];
        renderMissingEvals();
        modal.style.display = 'flex';
    });
    btnClose.addEventListener('click', () => modal.style.display = 'none');
    modal.addEventListener('click', (e) => {
        if(e.target === modal) modal.style.display = 'none';
    });

    // Star Rating Logic
    let currentRatings = { discipline: 0, service: 0, cleanliness: 0 };
    document.querySelectorAll('.star-rating').forEach(group => {
        const cat = group.getAttribute('data-category');
        const stars = group.querySelectorAll('span');
        
        stars.forEach(star => {
            star.addEventListener('click', () => {
                let val = parseInt(star.getAttribute('data-val'));
                currentRatings[cat] = val;
                stars.forEach(s => {
                    if (parseInt(s.getAttribute('data-val')) <= val) s.classList.add('active');
                    else s.classList.remove('active');
                });
            });
        });
    });

    // Submit Logic
    btnSubmit.addEventListener('click', () => {
        // Build Red Flags Array
        let rfList = [];
        if (document.getElementById('rfLate').checked) rfList.push('Đi trễ > 15 phút');
        if (document.getElementById('rfMistake').checked) rfList.push('Sai món / Đổ vỡ hao hụt');
        if (document.getElementById('rfAbsence').checked) rfList.push('Không quan sát gây mất bill/Khách bỏ về quên tính tiền');
        if (document.getElementById('rfCheckout').checked) rfList.push('Quên chấm công / Checkout sai');

        const payload = {
            staffName: selectStaff.value,
            date: document.getElementById('evalDate').value,
            shift: document.getElementById('evalShift').value,
            ratings: currentRatings,
            red_flags: rfList,
            bonus: parseInt(document.querySelector('input[name="bonus"]:checked').value),
            notes: document.getElementById('evalNotes').value,
            manager: localStorage.getItem('vnaigc_name') || 'Quản lý',
            timestamp: new Date().toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' })
        };

        // Secure Webhook submission via backend proxy
        const WEBHOOK_URL = '/api/v1/cc/admin/eval-webhook';
        
        btnSubmit.textContent = 'Đang gửi...';
        btnSubmit.disabled = true;

        const jwtToken = localStorage.getItem('vnaigc_jwt');
        const reqHeaders = { 'Content-Type': 'application/json' };
        if (jwtToken) reqHeaders['Authorization'] = `Bearer ${jwtToken}`;

        fetch(WEBHOOK_URL, {
            method: 'POST',
            headers: reqHeaders,
            body: JSON.stringify(payload)
        }).then(async res => {
            if (!res.ok) {
                const text = await res.text();
                throw new Error("Lỗi gửi đánh giá (Status " + res.status + "): " + text);
            }
            
            showToast('Thành công', 'success');
            
            // Xóa nhân viên khỏi giao diện ngay lập tức (Optimistic UI)
            const key = `${normalizeDateStr(payload.date)}|${payload.staffName}`;
            const localEvaluated = JSON.parse(localStorage.getItem('localEvaluatedShifts') || '[]');
            if (!localEvaluated.includes(key)) {
                localEvaluated.push(key);
                localStorage.setItem('localEvaluatedShifts', JSON.stringify(localEvaluated));
            }

            records.forEach(r => {
                if (r.name === payload.staffName && normalizeDateStr(r.date) === normalizeDateStr(payload.date)) {
                    r.isEvaluated = true;
                }
            });
            updateUI();

            // Reset form for next evaluation
            document.querySelectorAll('.star-rating span').forEach(s => s.classList.remove('active'));
            currentRatings = { discipline: 0, service: 0, cleanliness: 0 };
            document.querySelectorAll('.check-box input[type="checkbox"]').forEach(c => c.checked = false);
            document.querySelector('input[name="bonus"][value="0"]').checked = true;
            document.getElementById('evalNotes').value = '';

            const hasMore = renderMissingEvals();
            if (!hasMore) {
                modal.style.display = 'none';
            }
        }).catch(err => {
            console.error('Lỗi Webhook:', err);
            showToast('Lỗi gửi! Kiểm tra kết nối.', 'error');
        }).finally(() => {
            btnSubmit.textContent = 'Gửi Đánh Giá';
            btnSubmit.disabled = false;
        });
    });
}

// Authentication & Init
document.addEventListener('DOMContentLoaded', () => {
    setupTabSwitching();
    const loginOverlay = document.getElementById('loginOverlay');
    const btnLogin = document.getElementById('btnLogin');
    const token = localStorage.getItem('vnaigc_jwt');

    if (token) {
        if (loginOverlay) loginOverlay.style.display = 'none';
        init();
    } else {
        if (loginOverlay) loginOverlay.style.display = 'flex';
    }

    const btnLogoutDesktop = document.getElementById('btnLogoutDesktop');
    if (btnLogoutDesktop) {
        btnLogoutDesktop.addEventListener('click', () => {
            if (confirm('Bạn có chắc muốn đăng xuất?')) {
                localStorage.removeItem('fnbop_jwt');
                localStorage.removeItem('fnbop_role');
                localStorage.removeItem('fnbop_name');
                localStorage.removeItem('fnbop_username');
                localStorage.removeItem('vnaigc_jwt');
                localStorage.removeItem('vnaigc_role');
                localStorage.removeItem('vnaigc_name');
                localStorage.removeItem('vnaigc_username');
                location.reload();
            }
        });
    }

    const btnAdminStaffDesktop = document.getElementById('btnAdminStaffDesktop');
    if (btnAdminStaffDesktop) {
        btnAdminStaffDesktop.addEventListener('click', openAdminModalDesktop);
    }

    const btnCloseAdminModalDesktop = document.getElementById('btnCloseAdminModalDesktop');
    if (btnCloseAdminModalDesktop) {
        btnCloseAdminModalDesktop.addEventListener('click', () => {
            document.getElementById('adminStaffModalDesktop').style.display = 'none';
        });
    }

    const btnAdminLockoutsDesktop = document.getElementById('btnAdminLockoutsDesktop');
    if (btnAdminLockoutsDesktop) {
        btnAdminLockoutsDesktop.addEventListener('click', openAdminLockoutsModalDesktop);
    }

    const btnCloseAdminLockoutsModalDesktop = document.getElementById('btnCloseAdminLockoutsModalDesktop');
    if (btnCloseAdminLockoutsModalDesktop) {
        btnCloseAdminLockoutsModalDesktop.addEventListener('click', () => {
            document.getElementById('adminLockoutsModalDesktop').style.display = 'none';
        });
    }

    const btnRefreshLockoutsDesktop = document.getElementById('btnRefreshLockoutsDesktop');
    if (btnRefreshLockoutsDesktop) {
        btnRefreshLockoutsDesktop.addEventListener('click', fetchAndRenderAdminLockoutsDesktop);
    }

    const adminStaffSearchDesktop = document.getElementById('adminStaffSearchDesktop');
    if (adminStaffSearchDesktop) {
        adminStaffSearchDesktop.addEventListener('input', (e) => {
            renderAdminStaffListDesktop(e.target.value);
        });
    }

    const btnExportPayrollExcelDesktop = document.getElementById('btnExportPayrollExcelDesktop');
    if (btnExportPayrollExcelDesktop) {
        btnExportPayrollExcelDesktop.addEventListener('click', () => {
            const monthSelect = document.getElementById('monthFilter') || document.getElementById('monthSelect');
            const m = monthSelect ? monthSelect.value : '9';
            const token = localStorage.getItem('vnaigc_jwt') || localStorage.getItem('fnbop_jwt') || '';
            const tokenParam = token ? `&token=${encodeURIComponent(token)}` : '';
            window.open(`/api/v1/cc/excel/export-payroll?month=${encodeURIComponent(m)}${tokenParam}`, '_blank');
        });
    }

    if (btnLogin) {
        btnLogin.addEventListener('click', async () => {
            const u = document.getElementById('loginUser').value.trim();
            const p = document.getElementById('loginPass').value.trim();
            
            try {
                const res = await fetch('/api/v1/cc/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: u, password: p })
                });
                
                if (res.ok) {
                    const data = await res.json();
                    localStorage.setItem('fnbop_jwt', data.access_token); localStorage.setItem('vnaigc_jwt', data.access_token); localStorage.setItem('vnaigc_token', data.access_token);
                    localStorage.setItem('fnbop_role', data.role); localStorage.setItem('vnaigc_role', data.role);
                    localStorage.setItem('fnbop_name', data.name); localStorage.setItem('vnaigc_name', data.name);
                    if (data.username) { localStorage.setItem('fnbop_username', data.username); localStorage.setItem('vnaigc_username', data.username); }
                    loginOverlay.style.display = 'none';
                    init();
                } else {
                    const err = await res.json();
                    alert(err.detail || 'Sai tài khoản hoặc mật khẩu!');
                }
            } catch (e) {
                alert('Lỗi kết nối đến máy chủ!');
                console.error(e);
            }
        });
    }
});

function setupPayslipModal() {
    const modal = document.getElementById('payslipModal');
    const btnClose = document.getElementById('btnClosePayslip');
    const btnPrint = document.getElementById('btnPrintPayslip');
    const btnTelegram = document.getElementById('btnTelegramPayslip');

    btnClose.addEventListener('click', () => {
        modal.style.display = 'none';
    });

    modal.addEventListener('click', (e) => {
        if(e.target === modal) modal.style.display = 'none';
    });

    if (btnPrint) {
        btnPrint.addEventListener('click', () => {
            window.print();
        });
    }

    if (btnTelegram) {
        btnTelegram.addEventListener('click', async () => {
            if (!currentViewingStaffDesktop) {
                alert('Chưa có thông tin phiếu lương để gửi!');
                return;
            }
            const originalHtml = btnTelegram.innerHTML;
            btnTelegram.disabled = true;
            btnTelegram.innerHTML = '<span>⏳</span> Đang gửi...';

            const payload = {
                staffName: currentViewingStaffDesktop.staffName,
                monthTitle: currentViewingStaffDesktop.monthTitle,
                finalPayFormatted: currentViewingStaffDesktop.finalPayFormatted,
                totalHours: currentViewingStaffDesktop.totalHours,
                totalMinsFormatted: currentViewingStaffDesktop.totalMinsFormatted,
                shifts: currentViewingStaffDesktop.shifts,
                baseWageFormatted: currentViewingStaffDesktop.baseWageFormatted,
                bonusFormatted: currentViewingStaffDesktop.bonusFormatted,
                violations: currentViewingStaffDesktop.violations || []
            };

            try {
                const res = await fetch('/api/send-payslip', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    alert(`✅ Đã gửi phiếu lương của ${currentViewingStaffDesktop.staffName} vào Telegram thành công!`);
                } else {
                    alert('Lỗi gửi webhook Telegram!');
                }
            } catch (e) {
                console.error('Lỗi gửi Telegram phiếu lương:', e);
                alert('Không thể kết nối đến webhook Telegram!');
            } finally {
                btnTelegram.innerHTML = originalHtml;
                btnTelegram.disabled = false;
            }
        });
    }
}

let rosterWeeksData = {};
let currentRosterWeekIndex = 0;
let weekKeys = [];
let desktopRosterCache = {};

async function fetchDesktopRosterData(weekId = 'current') {
    const token = localStorage.getItem('vnaigc_jwt');
    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
    try {
        const res = await fetch(`/api/v1/cc/roster/week?week_id=${encodeURIComponent(weekId)}`, { headers });
        if (res.ok) {
            const data = await res.json();
            if (data.success && data.week) {
                desktopRosterCache[weekId] = data;
                if (data.week.week_id) {
                    desktopRosterCache[data.week.week_id] = data;
                }
                return data;
            }
        }
    } catch (e) {
        console.error('Lỗi tải roster desktop:', e);
    }
    return null;
}

function mergeRosterWeekIntoData(rosterData) {
    if (!rosterData || !rosterData.week || !rosterData.week.shifts) return;
    const week = rosterData.week;
    const staffDir = rosterData.staff_directory || {};
    const getStaffName = u => (staffDir[u] && staffDir[u].full_name) || u;

    let startDateStr = week.start_date;
    if (!startDateStr && Array.isArray(rosterData.days) && rosterData.days.length > 0) {
        startDateStr = rosterData.days[0];
    }
    if (!startDateStr) return;

    let parts = startDateStr.split('-');
    if (parts.length !== 3) return;
    let dMon = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
    let weekKey = dMon.toISOString().split('T')[0];

    if (!rosterWeeksData[weekKey]) {
        let dSun = new Date(dMon);
        dSun.setDate(dSun.getDate() + 6);
        rosterWeeksData[weekKey] = {
            mondayStr: `${dMon.getDate()}/${dMon.getMonth() + 1}`,
            sundayStr: `${dSun.getDate()}/${dSun.getMonth() + 1}`,
            rosterWeekId: week.week_id,
            rosterStatus: week.status,
            matrix: {
                1: { name: 'Thứ 2', shifts: { sang: [], toi: [] } },
                2: { name: 'Thứ 3', shifts: { sang: [], toi: [] } },
                3: { name: 'Thứ 4', shifts: { sang: [], toi: [] } },
                4: { name: 'Thứ 5', shifts: { sang: [], toi: [] } },
                5: { name: 'Thứ 6', shifts: { sang: [], toi: [] } },
                6: { name: 'Thứ 7', shifts: { sang: [], toi: [] } },
                7: { name: 'Chủ Nhật', shifts: { sang: [], toi: [] } }
            }
        };
    } else {
        rosterWeeksData[weekKey].rosterWeekId = week.week_id;
        rosterWeeksData[weekKey].rosterStatus = week.status;
    }

    Object.entries(week.shifts).forEach(([isoDate, sInfo]) => {
        let dParts = isoDate.split('-');
        if (dParts.length !== 3) return;
        let curD = new Date(parseInt(dParts[0]), parseInt(dParts[1]) - 1, parseInt(dParts[2]));
        let day = curD.getDay() || 7;

        if (!rosterWeeksData[weekKey].matrix[day]) return;

        // Morning
        if (sInfo.morning) {
            let curSang = rosterWeeksData[weekKey].matrix[day].shifts.sang;
            if (curSang.length === 0) {
                if (sInfo.morning.manager) {
                    curSang.push({ name: getStaffName(sInfo.morning.manager), role: 'Quản lý' });
                }
                if (sInfo.morning.barista) {
                    curSang.push({ name: getStaffName(sInfo.morning.barista), role: 'Pha chế' });
                }
                if (Array.isArray(sInfo.morning.service)) {
                    sInfo.morning.service.forEach(u => {
                        if (u) curSang.push({ name: getStaffName(u), role: 'Phục vụ' });
                    });
                }
            }
        }

        // Evening
        if (sInfo.evening) {
            let curToi = rosterWeeksData[weekKey].matrix[day].shifts.toi;
            if (curToi.length === 0) {
                if (sInfo.evening.manager) {
                    curToi.push({ name: getStaffName(sInfo.evening.manager), role: 'Quản lý' });
                }
                if (sInfo.evening.barista) {
                    curToi.push({ name: getStaffName(sInfo.evening.barista), role: 'Pha chế' });
                }
                if (sInfo.evening.service_17) {
                    curToi.push({ name: getStaffName(sInfo.evening.service_17), role: 'Phục vụ' });
                }
                if (sInfo.evening.service_18) {
                    curToi.push({ name: getStaffName(sInfo.evening.service_18), role: 'Phục vụ' });
                }
            }
        }
    });
}

function setupDesktopRosterControls() {
    const btnAutoFill = document.getElementById('btnRosterAutoFillDesktop');
    const btnPublish = document.getElementById('btnRosterPublishDesktop');
    
    if (btnAutoFill && !btnAutoFill.dataset.bound) {
        btnAutoFill.dataset.bound = 'true';
        btnAutoFill.addEventListener('click', async () => {
            const token = localStorage.getItem('vnaigc_jwt');
            if (!token) {
                alert('Vui lòng đăng nhập tài khoản Quản lý để thao tác!');
                return;
            }
            let currentKey = weekKeys[currentRosterWeekIndex];
            let w = rosterWeeksData[currentKey];
            let targetWeekId = (w && w.rosterWeekId) ? w.rosterWeekId : 'current';
            
            if (!confirm(`Tự động xếp ca cho tuần ${targetWeekId}?`)) return;
            
            btnAutoFill.disabled = true;
            btnAutoFill.textContent = 'Đang xếp ca...';
            try {
                const res = await fetch('/api/v1/cc/roster/auto-fill', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                    body: JSON.stringify({ week_id: targetWeekId })
                });
                const d = await res.json();
                if (res.ok) {
                    alert(d.message || 'Tự động xếp ca thành công!');
                    desktopRosterCache = {};
                    await fetchDesktopRosterData('current');
                    await fetchDesktopRosterData('next');
                    const filtered = currentMonth === 'all' ? records : records.filter(r => r.month === currentMonth);
                    renderHeatmap(filtered);
                } else {
                    alert(d.detail || 'Lỗi khi xếp ca!');
                }
            } catch (e) {
                alert('Lỗi kết nối máy chủ!');
            } finally {
                btnAutoFill.disabled = false;
                btnAutoFill.textContent = '⚡ Tự Động Xếp Ca';
            }
        });
    }

    if (btnPublish && !btnPublish.dataset.bound) {
        btnPublish.dataset.bound = 'true';
        btnPublish.addEventListener('click', async () => {
            const token = localStorage.getItem('vnaigc_jwt');
            if (!token) {
                alert('Vui lòng đăng nhập tài khoản Quản lý để thao tác!');
                return;
            }
            let currentKey = weekKeys[currentRosterWeekIndex];
            let w = rosterWeeksData[currentKey];
            let targetWeekId = (w && w.rosterWeekId) ? w.rosterWeekId : 'current';
            
            if (!confirm(`Chốt và công bố lịch ca tuần ${targetWeekId} lên Telegram?`)) return;
            
            btnPublish.disabled = true;
            btnPublish.textContent = 'Đang công bố...';
            try {
                const res = await fetch('/api/v1/cc/roster/publish', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                    body: JSON.stringify({ week_id: targetWeekId })
                });
                const d = await res.json();
                if (res.ok) {
                    alert(d.message || 'Đã công bố lịch ca lên Telegram thành công!');
                    desktopRosterCache = {};
                    await fetchDesktopRosterData('current');
                    await fetchDesktopRosterData('next');
                    const filtered = currentMonth === 'all' ? records : records.filter(r => r.month === currentMonth);
                    renderHeatmap(filtered);
                } else {
                    alert(d.detail || 'Lỗi khi công bố lịch!');
                }
            } catch (e) {
                alert('Lỗi kết nối máy chủ!');
            } finally {
                btnPublish.disabled = false;
                btnPublish.textContent = '📢 Chốt & Công Bố';
            }
        });
    }
}

function renderHeatmap(filtered) {
    const container = document.getElementById('weeklyRosterContainer');
    if (!container) return;
    
    container.innerHTML = '';

    rosterWeeksData = {};
    
    if (filtered && filtered.length > 0) {
        filtered.forEach(r => {
            if (!r.date || !r.shift) return;
            let dParts = r.date.split('/');
            if (dParts.length !== 3) return;
            let d = new Date(dParts[2], dParts[1] - 1, dParts[0]);
            
            let day = d.getDay() || 7;
            let dMon = new Date(d);
            dMon.setDate(d.getDate() - (day - 1));
            let weekKey = dMon.toISOString().split('T')[0];
            
            if (!rosterWeeksData[weekKey]) {
                rosterWeeksData[weekKey] = {
                    mondayStr: `${dMon.getDate()}/${dMon.getMonth()+1}`,
                    sundayStr: (() => { let ds = new Date(dMon); ds.setDate(ds.getDate()+6); return `${ds.getDate()}/${ds.getMonth()+1}`; })(),
                    matrix: {
                        1: { name: 'Thứ 2', shifts: { sang: [], toi: [] } },
                        2: { name: 'Thứ 3', shifts: { sang: [], toi: [] } },
                        3: { name: 'Thứ 4', shifts: { sang: [], toi: [] } },
                        4: { name: 'Thứ 5', shifts: { sang: [], toi: [] } },
                        5: { name: 'Thứ 6', shifts: { sang: [], toi: [] } },
                        6: { name: 'Thứ 7', shifts: { sang: [], toi: [] } },
                        7: { name: 'Chủ Nhật', shifts: { sang: [], toi: [] } }
                    }
                };
            }
            
            let shiftLower = r.shift.toLowerCase();
            let shiftKey = '';
            if (shiftLower.includes('sáng')) shiftKey = 'sang';
            else if (shiftLower.includes('tối') || shiftLower.includes('toi')) shiftKey = 'toi';
            
            if (shiftKey) {
                rosterWeeksData[weekKey].matrix[day].shifts[shiftKey].push({
                    name: r.name,
                    role: getStaffRole(r.name)
                });
            }
        });
    }

    // Merge cached live roster weeks (current & next week)
    if (desktopRosterCache['current']) mergeRosterWeekIntoData(desktopRosterCache['current']);
    if (desktopRosterCache['next']) mergeRosterWeekIntoData(desktopRosterCache['next']);

    weekKeys = Object.keys(rosterWeeksData).sort();
    if (weekKeys.length === 0) {
        container.innerHTML = '<div style="text-align: center; color: #888; padding: 40px;">Không có dữ liệu ca trực.</div>';
        return;
    }

    if (currentRosterWeekIndex >= weekKeys.length || currentRosterWeekIndex === 0) {
        currentRosterWeekIndex = weekKeys.length - 1; // Default to latest week
    }

    const btnPrev = document.getElementById('btnPrevWeek');
    const btnNext = document.getElementById('btnNextWeek');
    
    if (btnPrev && !btnPrev.dataset.bound) {
        btnPrev.addEventListener('click', () => {
            if (currentRosterWeekIndex > 0) {
                currentRosterWeekIndex--;
                renderSingleWeekMatrix();
            }
        });
        btnPrev.dataset.bound = 'true';
    }
    if (btnNext && !btnNext.dataset.bound) {
        btnNext.addEventListener('click', () => {
            if (currentRosterWeekIndex < weekKeys.length - 1) {
                currentRosterWeekIndex++;
                renderSingleWeekMatrix();
            }
        });
        btnNext.dataset.bound = 'true';
    }

    renderSingleWeekMatrix();
    setupDesktopRosterControls();
}

function renderSingleWeekMatrix() {
    const container = document.getElementById('weeklyRosterContainer');
    const labelDisplay = document.getElementById('weekLabelDisplay');
    const btnPrev = document.getElementById('btnPrevWeek');
    const btnNext = document.getElementById('btnNextWeek');
    const kpiRow = document.getElementById('rosterKpiRow');
    const workloadContainer = document.getElementById('staffWorkloadContainer');
    const anomalyContainer = document.getElementById('rosterAnomalyContainer');
    const staffTotalBadge = document.getElementById('staffTotalBadge');
    const anomalyBadgeCount = document.getElementById('anomalyBadgeCount');
    
    if (!container || weekKeys.length === 0) return;
    
    let currentKey = weekKeys[currentRosterWeekIndex];
    let w = rosterWeeksData[currentKey];
    
    if (labelDisplay) {
        let extraTag = w.rosterWeekId ? ` (${w.rosterWeekId})` : '';
        labelDisplay.innerText = `${w.mondayStr} - ${w.sundayStr}${extraTag}`;
    }
    if (btnPrev) btnPrev.style.opacity = currentRosterWeekIndex === 0 ? '0.3' : '1';
    if (btnNext) btnNext.style.opacity = currentRosterWeekIndex === weekKeys.length - 1 ? '0.3' : '1';

    const rosterStatusBadge = document.getElementById('rosterStatusBadgeDesktop');
    if (rosterStatusBadge) {
        if (w.rosterStatus === 'PUBLISHED') {
            rosterStatusBadge.textContent = 'ĐÃ CÔNG BỐ';
            rosterStatusBadge.style.color = '#059669';
            rosterStatusBadge.style.background = 'rgba(5, 150, 105, 0.1)';
            rosterStatusBadge.style.borderColor = 'rgba(5, 150, 105, 0.3)';
        } else if (w.rosterStatus === 'DRAFT') {
            rosterStatusBadge.textContent = 'ĐANG MỞ ĐĂNG KÝ';
            rosterStatusBadge.style.color = '#d97706';
            rosterStatusBadge.style.background = 'rgba(217, 119, 6, 0.1)';
            rosterStatusBadge.style.borderColor = 'rgba(217, 119, 6, 0.3)';
        } else {
            rosterStatusBadge.textContent = 'LỊCH SỬ (SHEETS)';
            rosterStatusBadge.style.color = 'var(--text-secondary)';
            rosterStatusBadge.style.background = 'var(--bg-secondary)';
            rosterStatusBadge.style.borderColor = 'var(--border)';
        }
    }
    
    const getStandard = (day, shiftKey) => {
        if (shiftKey === 'sang') return { quanly: 1, phache: 1, phucvu: 2 };
        if (shiftKey === 'toi') {
            if (day === 6 || day === 7) return { quanly: 1, phache: 1, phucvu: 2 };
            return { quanly: 1, phache: 0, phucvu: 2 };
        }
        return { quanly: 0, phache: 0, phucvu: 0 };
    };

    let totalShifts = 14;
    let compliantShifts = 0;
    let totalMissing = 0;
    let totalOver = 0;
    let staffWorkload = {};
    let anomalies = [];

    const renderSlot = (staffList, required, title, dayName, shiftLabel) => {
        let html = `<div style="margin-bottom: 6px;"><div style="font-size: 10px; font-weight: 700; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 3px;">${title}</div>`;
        let filled = staffList.length;
        
        // Count staff workload
        staffList.forEach((s, i) => {
            staffWorkload[s.name] = (staffWorkload[s.name] || 0) + 1;
            let roleTag = s.role === 'Quản lý' ? '👑 Q.Lý' : (s.role === 'Pha chế' ? '🍹 Pha' : (s.role === 'Giữ Xe' ? '🚲 Xe' : '☕ Phục'));
            if (i < required || required === 0) {
                html += `
                    <div style="color: var(--text-primary); background: var(--bg-secondary); padding: 3px 6px; font-size: 11px; margin-top: 2px; border-radius: 4px; border: 1px solid var(--border); font-family: monospace; font-weight: 600; display: flex; justify-content: space-between; align-items: center;">
                        <span>${s.name}</span>
                        <span style="font-size: 9px; color: var(--text-secondary); font-weight: normal; text-transform: uppercase;">${roleTag}</span>
                    </div>
                `;
            } else {
                totalOver++;
                html += `<div style="background: rgba(240,165,0,0.12); color: var(--accent-amber); padding: 3px 6px; border-radius: 4px; font-size: 11px; margin-top: 2px; border: 1px solid rgba(240,165,0,0.3); font-weight: 600;">⚠️ Thừa: ${s.name}</div>`;
                anomalies.push({
                    type: 'over',
                    text: `${dayName} (${shiftLabel}): Thừa "${s.name}" (${title})`
                });
            }
        });
        
        if (filled < required) {
            let missing = required - filled;
            totalMissing += missing;
            for (let i=0; i<missing; i++) {
                html += `<div style="color: var(--text-secondary); padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-top: 2px; border: 1px dashed var(--border); text-align: center; opacity: 0.7;">(Trống)</div>`;
            }
            if (filled === 0) {
                anomalies.push({
                    type: 'missing',
                    text: `${dayName} (${shiftLabel}): Trống hoàn toàn ${title}`
                });
            } else {
                anomalies.push({
                    type: 'missing',
                    text: `${dayName} (${shiftLabel}): Thiếu ${missing} vị trí ${title}`
                });
            }
        }
        html += '</div>';
        return html;
    };

    let tableHtml = `
    <div style="border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: var(--bg-primary); box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.05));">
        <table class="heatmap-table w-full" style="margin: 0; table-layout: fixed; border-collapse: collapse;">
            <thead>
                <tr style="background: var(--bg-secondary); border-bottom: 1px solid var(--border);">
                    <th style="width: 100px; text-align: center; padding: 6px 4px; font-size: 11px; font-weight: 700; color: var(--text-secondary);">CA TRỰC</th>
                    <th style="text-align: center; padding: 6px 4px; font-size: 11px; border-left: 1px solid var(--border);">Thứ 2</th>
                    <th style="text-align: center; padding: 6px 4px; font-size: 11px; border-left: 1px solid var(--border);">Thứ 3</th>
                    <th style="text-align: center; padding: 6px 4px; font-size: 11px; border-left: 1px solid var(--border);">Thứ 4</th>
                    <th style="text-align: center; padding: 6px 4px; font-size: 11px; border-left: 1px solid var(--border);">Thứ 5</th>
                    <th style="text-align: center; padding: 6px 4px; font-size: 11px; border-left: 1px solid var(--border);">Thứ 6</th>
                    <th style="text-align: center; padding: 6px 4px; font-size: 11px; border-left: 1px solid var(--border); color: var(--accent-amber); font-weight: 700;">Thứ 7</th>
                    <th style="text-align: center; padding: 6px 4px; font-size: 11px; border-left: 1px solid var(--border); color: var(--accent-coral); font-weight: 700;">Chủ Nhật</th>
                </tr>
            </thead>
            <tbody>
    `;
    
    const shiftsConfig = [
        { key: 'sang', label: '☀️ CA SÁNG', desc: '06:00 - 11:30 (5.5h)' },
        { key: 'toi', label: '🌙 CA TỐI', desc: '17:00 - 23:00 (6h/5h)' }
    ];

    shiftsConfig.forEach((sConf, idx) => {
        let isLast = idx === shiftsConfig.length - 1;
        tableHtml += `<tr style="${isLast ? '' : 'border-bottom: 1px solid var(--border);'}">`;
        tableHtml += `
            <td style="text-align: center; vertical-align: middle; background: var(--bg-secondary); border-right: 1px solid var(--border); padding: 12px 6px;">
                <div style="font-weight: 700; font-size: 11px; color: var(--text-primary);">${sConf.label}</div>
                <div style="font-size: 9px; color: var(--text-secondary); margin-top: 2px;">${sConf.desc}</div>
            </td>
        `;

        for (let day = 1; day <= 7; day++) {
            let r = w.matrix[day];
            let std = getStandard(day, sConf.key);
            let staff = r.shifts[sConf.key] || [];

            let quanlyList = staff.filter(s => s.role === 'Quản lý');
            let phacheList = staff.filter(s => s.role === 'Pha chế');
            let phucvuList = staff.filter(s => s.role === 'Phục vụ');

            // Render Staff list
            let staffPills = '';
            staff.forEach(s => {
                staffWorkload[s.name] = (staffWorkload[s.name] || 0) + 1;
                let roleIcon = s.role === 'Quản lý' ? '👑' : (s.role === 'Pha chế' ? '🍹' : (s.role === 'Giữ Xe' ? '🚲' : '☕'));
                staffPills += `
                    <div style="color: var(--text-primary); background: var(--bg-secondary); padding: 4px 8px; font-size: 11px; margin-bottom: 3px; border-radius: 4px; border: 1px solid var(--border); font-family: monospace; font-weight: 600; display: flex; align-items: center; gap: 6px;">
                        <span style="font-size: 12px;">${roleIcon}</span>
                        <span>${s.name}</span>
                    </div>
                `;
            });

            // Calculate Missing / Over with FULL standard words
            let missingNotes = [];
            if (quanlyList.length < std.quanly) missingNotes.push(`${std.quanly - quanlyList.length} Quản lý`);
            if (phacheList.length < std.phache) missingNotes.push(`${std.phache - phacheList.length} Pha chế`);
            if (phucvuList.length < std.phucvu) missingNotes.push(`${std.phucvu - phucvuList.length} Phục vụ`);

            let overNotes = [];
            if (quanlyList.length > std.quanly) overNotes.push(`${quanlyList.length - std.quanly} Quản lý`);
            if (phacheList.length > std.phache) overNotes.push(`${phacheList.length - std.phache} Pha chế`);
            if (phucvuList.length > std.phucvu) overNotes.push(`${phucvuList.length - std.phucvu} Phục vụ`);

            let totalMissInCell = Math.max(0, std.quanly - quanlyList.length) + Math.max(0, std.phache - phacheList.length) + Math.max(0, std.phucvu - phucvuList.length);
            let totalOverInCell = Math.max(0, quanlyList.length - std.quanly) + Math.max(0, phacheList.length - std.phache) + Math.max(0, phucvuList.length - std.phucvu);

            totalMissing += totalMissInCell;
            totalOver += totalOverInCell;

            let isShiftCompliant = (totalMissInCell === 0 && totalOverInCell === 0 && staff.length > 0);
            if (isShiftCompliant) compliantShifts++;

            // Status Badge
            let statusBadge = '';
            if (staff.length === 0) {
                statusBadge = `<div style="color: var(--text-secondary); padding: 3px 6px; border-radius: 4px; font-size: 10px; border: 1px dashed var(--border); text-align: center; opacity: 0.6;">(Chưa chấm công)</div>`;
            } else if (missingNotes.length > 0) {
                statusBadge = `<div style="color: var(--accent-coral); background: rgba(220,38,38,0.08); padding: 3px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; text-align: center; border: 1px solid rgba(220,38,38,0.2);">Thiếu ${missingNotes.join(', ')}</div>`;
                anomalies.push({ type: 'missing', text: `${r.name} (${sConf.label}): Thiếu ${missingNotes.join(', ')}` });
            } else if (overNotes.length > 0) {
                statusBadge = `<div style="color: var(--accent-amber); background: rgba(240,165,0,0.08); padding: 3px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; text-align: center; border: 1px solid rgba(240,165,0,0.2);">Thừa ${overNotes.join(', ')}</div>`;
                anomalies.push({ type: 'over', text: `${r.name} (${sConf.label}): Thừa ${overNotes.join(', ')}` });
            } else {
                statusBadge = `<div style="color: var(--accent-emerald); font-size: 10px; font-weight: 600; text-align: center; opacity: 0.85;">✓ Đủ nhân sự</div>`;
            }

            let cellContent = `
                <div style="display: flex; flex-direction: column; gap: 4px; min-height: 75px; justify-content: space-between;">
                    <div>${staffPills}</div>
                    <div>${statusBadge}</div>
                </div>
            `;

            tableHtml += `<td style="vertical-align: top; padding: 8px 6px; border-left: 1px solid var(--border);">${cellContent}</td>`;
        }

        tableHtml += `</tr>`;
    });
    
    tableHtml += `</tbody></table></div>`;
    container.innerHTML = tableHtml;

    // Render 4 KPI Cards
    if (kpiRow) {
        let complianceRate = Math.round((compliantShifts / totalShifts) * 100);
        let rateColor = complianceRate >= 80 ? 'var(--accent-emerald)' : (complianceRate >= 50 ? 'var(--accent-amber)' : 'var(--accent-coral)');
        let totalStaffCount = Object.keys(staffWorkload).length;
        let totalWeeklyHours = (Object.values(staffWorkload).reduce((a, b) => a + b, 0) * 5); // 5h standard per shift

        kpiRow.innerHTML = `
            <div class="card" style="padding: 10px 14px; border-left: 3px solid ${rateColor};">
                <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;">Đủ Nhân Sự</div>
                <div style="font-size: 18px; font-weight: 800; color: ${rateColor}; margin-top: 2px;">${complianceRate}%</div>
                <div style="font-size: 10px; color: var(--text-secondary); margin-top: 1px;">${compliantShifts}/${totalShifts} ca đủ người</div>
            </div>
            <div class="card" style="padding: 10px 14px; border-left: 3px solid var(--accent-coral);">
                <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;">Vị Trí Thiếu / Trống</div>
                <div style="font-size: 18px; font-weight: 800; color: var(--accent-coral); margin-top: 2px;">${totalMissing} vị trí</div>
                <div style="font-size: 10px; color: var(--text-secondary); margin-top: 1px;">Cần sắp xếp bù nhân sự</div>
            </div>
            <div class="card" style="padding: 10px 14px; border-left: 3px solid var(--accent-amber);">
                <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;">Lượt Thừa (Lãng Phí)</div>
                <div style="font-size: 18px; font-weight: 800; color: var(--accent-amber); margin-top: 2px;">${totalOver} lượt</div>
                <div style="font-size: 10px; color: var(--text-secondary); margin-top: 1px;">Phát sinh ngoài kế hoạch</div>
            </div>
            <div class="card" style="padding: 10px 14px; border-left: 3px solid var(--accent-blue, #3b82f6);">
                <div style="font-size: 10px; color: var(--text-secondary); text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;">Nhân Sự Hoạt Động</div>
                <div style="font-size: 18px; font-weight: 800; color: var(--text-primary); margin-top: 2px;">${totalStaffCount} người</div>
                <div style="font-size: 10px; color: var(--text-secondary); margin-top: 1px;">~${totalWeeklyHours} giờ công chuẩn (5h/ca)</div>
            </div>
        `;
    }

    // Render Workload Distribution
    if (staffTotalBadge) staffTotalBadge.innerText = `${Object.keys(staffWorkload).length} nhân sự`;
    if (workloadContainer) {
        let sortedStaff = Object.entries(staffWorkload).sort((a, b) => b[1] - a[1]);
        if (sortedStaff.length === 0) {
            workloadContainer.innerHTML = '<div style="color: var(--text-secondary); font-size: 11px; text-align: center; padding: 16px;">Không có ca trực nào trong tuần.</div>';
        } else {
            let maxShifts = Math.max(...sortedStaff.map(s => s[1]), 1);
            let wlHtml = '';
            sortedStaff.forEach(([name, count]) => {
                let pct = Math.round((count / maxShifts) * 100);
                let role = getStaffRole(name);
                let roleIcon = role === 'Quản lý' ? '👑' : (role === 'Pha chế' ? '🍹' : (role === 'Giữ Xe' ? '🚲' : '☕'));
                let roleLabel = role === 'Giữ Xe' ? 'Giữ xe' : role;
                wlHtml += `
                    <div>
                        <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 2px;">
                            <span style="font-weight: 600; font-family: monospace;">${roleIcon} ${name} <span style="font-size: 9px; color: var(--text-secondary); font-weight: normal; font-family: sans-serif;">(${roleLabel})</span></span>
                            <span style="font-weight: 600; color: var(--accent-blue, #3b82f6);">${count} ca <span style="font-size: 9px; color: var(--text-secondary);">(${count * 5}h)</span></span>
                        </div>
                        <div style="height: 5px; background: var(--bg-secondary); border-radius: 3px; overflow: hidden;">
                            <div style="height: 100%; width: ${pct}%; background: linear-gradient(90deg, #3b82f6, #60a5fa); border-radius: 3px;"></div>
                        </div>
                    </div>
                `;
            });
            workloadContainer.innerHTML = wlHtml;
        }
    }

    // Render Anomaly Log
    if (anomalyBadgeCount) anomalyBadgeCount.innerText = `${anomalies.length} cảnh báo`;
    if (anomalyContainer) {
        if (anomalies.length === 0) {
            anomalyContainer.innerHTML = '<div style="color: var(--accent-emerald); font-size: 11px; padding: 10px; background: rgba(22,163,74,0.08); border-radius: 4px; text-align: center;">✅ Tuyệt vời! 100% ca trực đủ nhân sự.</div>';
        } else {
            let anomHtml = '';
            anomalies.forEach(a => {
                let isMissing = a.type === 'missing';
                let bg = isMissing ? 'rgba(220,38,38,0.06)' : 'rgba(240,165,0,0.06)';
                let border = isMissing ? 'rgba(220,38,38,0.15)' : 'rgba(240,165,0,0.15)';
                let icon = isMissing ? '🚨' : '⚠️';
                anomHtml += `
                    <div style="background: ${bg}; border: 1px solid ${border}; padding: 4px 8px; border-radius: 4px; font-size: 11px; display: flex; align-items: center; gap: 6px;">
                        <span>${icon}</span>
                        <span style="color: var(--text-primary); line-height: 1.3;">${a.text}</span>
                    </div>
                `;
            });
            anomalyContainer.innerHTML = anomHtml;
        }
    }
}

function renderPayslipTable(filtered) {
    const tableBody = document.getElementById('payslipTableBody');
    tableBody.innerHTML = '';
    
    let staffSummary = {};
    
    filtered.forEach(r => {
        if (!r.name) return;
        if (!staffSummary[r.name]) {
            const emp = employeesMap[r.name] || { wage: 17000, status: 'ĐANG LÀM' };
            staffSummary[r.name] = {
                name: r.name,
                totalMins: 0,
                baseCost: 0,
                otCost: 0,
                totalCost: 0,
                shiftsCount: 0,
                wage: emp.wage,
                warnings: 0
            };
        }
        
        staffSummary[r.name].totalMins += r.mins;
        staffSummary[r.name].baseCost += r.standardCost;
        staffSummary[r.name].otCost += r.overtimeCost;
        staffSummary[r.name].totalCost += r.totalCost;
        staffSummary[r.name].shiftsCount++;
        
        // Count warnings
        // B2: Warnings = so lan di tre > 10 phut (khong tinh OT la vi pham)
        if (r.lateMins > POLICY.LATE_THRESHOLD_WARN && getStaffRole(r.name) !== 'Quản lý') staffSummary[r.name].warnings++;
    });

    let staffList = Object.values(staffSummary).sort((a,b) => b.totalCost - a.totalCost);

    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;

    staffList.forEach(s => {
        const tr = document.createElement('tr');
        const isManager = getStaffRole(s.name) === 'Quản lý';
        
        const warningPill = s.warnings > 0 
            ? `<span class="status-pill bad">${s.warnings} VI PHẠM</span>` 
            : `<span class="status-pill good">TỐT</span>`;

        const bSummary = getStaffBonusSummary(m, s.name);
        const totalBonus = bSummary.total;
        const aSummary = (m === '8') ? 0 : getStaffAdvanceSummary(m, s.name);
        const netBankTransfer = s.totalCost + bSummary.bank - aSummary;
        const bonusPillText = totalBonus > 0 
            ? `+${fmtMoney.format(totalBonus).replace('₫', 'đ')} <span style="font-size:10px; opacity:0.8;">(${bSummary.count} lần)</span> ✎` 
            : `+0 đ ✎`;

        tr.innerHTML = `
            <td>
                <div class="name-pill ${isManager ? 'manager' : ''}" style="cursor: pointer;" onclick="openPayslipModalV2('${s.name}')" title="Bấm để xem phiếu lương ${s.name}">
                    <div class="avatar">${s.name.charAt(0)}</div>
                    ${s.name}
                </div>
            </td>
            <td>
                ${fmtNum.format(s.totalMins)}p<br>
                <span style="color: var(--text-secondary); font-size: 11px;">(~${(s.totalMins/60).toFixed(1)}h)</span>
            </td>
            <td>${fmtMoney.format(s.wage).replace('₫', 'đ')}/h</td>
            <td>${fmtMoney.format(s.totalCost).replace('₫', 'đ')}</td>
            <td>
                <button type="button" class="bonus-trigger-btn" onclick="openBonusModal('${s.name}')" title="Bấm để thêm/xem lịch sử thưởng">
                    ${bonusPillText}
                </button>
            </td>
            <td>${warningPill}</td>
            <td>
                <button type="button" class="bonus-trigger-btn" style="background: rgba(244,63,94,0.1); border-color: rgba(244,63,94,0.2); color: var(--accent-coral);" onclick="openAdvanceModal('${s.name}')" title="Bấm để ứng lương">
                    ${aSummary > 0 ? `-${fmtMoney.format(aSummary).replace('₫', 'đ')} 💸` : `+0 đ 💸`}
                </button>
            </td>
            <td style="color: var(--accent-coral); font-weight: 700;">${fmtMoney.format(netBankTransfer).replace('₫', 'đ')}</td>
            <td>
                <button class="btn-sm" onclick="openPayslipModalV2('${s.name}')">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                    Xem Phiếu
                </button>
            </td>
        `;
        tableBody.appendChild(tr);
    });
}

window.openPayslipModalV2 = function(staffName) {
    const filtered = currentMonth === 'all' ? records : records.filter(r => r.month === currentMonth);
    const empRecords = filtered.filter(r => r.name === staffName);
    
    let totalShifts = empRecords.length;
    let standardMins = 0;
    let otMins = 0;
    let standardCost = 0;
    let otCost = 0;
    let lateCount = 0;
    let lateOver10Count = 0;  // B2: Dem lan tre > 10 phut cho progressive discipline
    let lateOver30Count = 0;  // B2: Dem lan tre > 30 phut cho phat truc tiep
    
    let holidayShiftsCount = 0;
    let holidayExtraTotal = 0;
    let holidayMins = 0;

    empRecords.forEach(r => {
        standardMins += r.standardMins;
        otMins += r.overtimeMins;
        standardCost += r.standardCost;
        otCost += r.overtimeCost;
        if (r.isHoliday) {
            holidayShiftsCount++;
            holidayMins += r.mins;
            holidayExtraTotal += (r.holidayExtra || 0);
        }
        // B2: Dem so lan di tre theo tung muc
        if (r.lateMins > POLICY.LATE_THRESHOLD_WARN) {
            lateCount++;
            lateOver10Count++;
        }
        if (r.lateMins > POLICY.LATE_THRESHOLD_INSTANT_FINE) {
            lateOver30Count++;
        }
    });
    
    const emp = employeesMap[staffName] || { wage: 17000 };
    const salaryType = (emp && emp.salary_type) || 'HOURLY';
    const fixedSalary = (emp && Number(emp.fixed_salary)) || 0;
    if (salaryType === 'FIXED' && fixedSalary > 0) {
        standardCost = fixedSalary;
        emp.wage = fixedSalary;
    }
    const monthLabel = currentMonth === 'all' ? 'TẤT CẢ CÁC THÁNG' : `THÁNG ${currentMonth}/2026`;
    
    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;
    const bSummary = getStaffBonusSummary(m, staffName);
    const totalBonus = bSummary.total;
    const totalReceived = standardCost + otCost + totalBonus;
    
    // Tạm ứng lương
    const aSummary = (m === '8') ? 0 : getStaffAdvanceSummary(m, staffName);
    const aList = (m === '8') ? [] : getStaffAdvances(m, staffName);
    const bankTransfer = Math.max(0, standardCost + otCost + bSummary.bank - aSummary);
    
    const totalHours = ((standardMins + otMins) / 60).toFixed(1);
    const standardHours = (standardMins / 60).toFixed(1);
    const otHours = (otMins / 60).toFixed(1);
    const roleLabel = getStaffRole(staffName) === 'Quản lý' ? 'Quản Lý Vận Hành' : 'Nhân Viên Vận Hành';

    // B5: Tinh tien phat theo progressive discipline
    let totalPenalty = 0;
    let penaltyDetails = [];
    const enablePenalties = (m !== '8');
    // Phat truc tiep cho lan tre > 30 phut
    if (enablePenalties && lateOver30Count > 0) {
        const instantFine = lateOver30Count * POLICY.LATE_INSTANT_FINE_AMOUNT;
        totalPenalty += instantFine;
        penaltyDetails.push(`Trễ >30p: ${lateOver30Count} lần × ${fmtMoney.format(POLICY.LATE_INSTANT_FINE_AMOUNT).replace('₫','đ')}`);
    }
    // Progressive discipline cho lan tre > 10 phut
    for (let i = 1; enablePenalties && i <= lateOver10Count && i <= POLICY.LATE_PENALTIES.length; i++) {
        const rule = POLICY.LATE_PENALTIES[i - 1];
        if (rule.action === 'fine') {
            totalPenalty += rule.amount;
            penaltyDetails.push(`Lần ${i}: ${fmtMoney.format(rule.amount).replace('₫','đ')}`);
        } else if (rule.action === 'terminate') {
            penaltyDetails.push(`Lần ${i}: CẢNH BÁO ĐỎ - CHO NGHỈ`);
        }
    }
    // Tru phat khoi bank transfer
    const bankTransferAfterPenalty = Math.max(0, bankTransfer - totalPenalty);
    const refCode = `TB-${staffName}-${currentMonth || 'ALL'}-${Date.now().toString().slice(-4)}`;
    
    currentViewingStaffDesktop = {
        staffName: staffName,
        monthTitle: currentMonth === 'all' ? 'Tất cả các tháng' : `Tháng ${currentMonth}/2026`,
        finalPayFormatted: fmtMoney.format(bankTransferAfterPenalty).replace('₫', 'đ'),
        totalHours: totalHours,
        totalMinsFormatted: fmtNum.format(standardMins + otMins),
        shifts: totalShifts.toString(),
        baseWageFormatted: `${fmtNum.format(emp.wage)} đ/h`,
        bonusFormatted: totalBonus > 0 ? `+${fmtMoney.format(totalBonus).replace('₫', 'đ')}` : "+0 đ",
        violations: penaltyDetails || []
    };
    
    let bonusNoteSub = '';
    if (bSummary.cash > 0 && bSummary.bank > 0) {
        bonusNoteSub = ` <em style="font-size:11px; opacity:0.85;">(TM: ${fmtMoney.format(bSummary.cash).replace('₫','đ')} | CK: ${fmtMoney.format(bSummary.bank).replace('₫','đ')})</em>`;
    } else if (bSummary.cash > 0) {
        bonusNoteSub = ` <em style="font-size:11px; opacity:0.85;">(Đã nhận TM tại quầy)</em>`;
    }
    
    let advanceNoteSub = '';
    if (aList && aList.length > 0) {
        const details = aList.map(a => {
            const dateStr = a.date || a.timestamp || '';
            const typeStr = a.type === 'bank' ? 'CK' : 'TM';
            return `${dateStr}: -${fmtMoney.format(a.amount).replace('₫','đ')} (${typeStr})`;
        }).join(' • ');
        advanceNoteSub = ` <div style="font-size:11px; opacity:0.85; margin-top:2px; font-weight:400;">(${details})</div>`;
    }
    
    const html = `
        <div class="receipt-card-premium">
            <!-- Brand Header -->
            <div class="rc-brand">
                <div class="rc-logo-text">${escapeHtml(window.vnaigc_store_name || 'FNBOPS STORE')}</div>
                <div class="rc-sub">OPERATIONS &amp; WORKFORCE MANAGEMENT</div>
                <div class="rc-badge-pill">PHIẾU LƯƠNG NHÂN SỰ • ${monthLabel}</div>
            </div>

            <div class="rc-divider-dashed"></div>

            <!-- Employee Info -->
            <div class="rc-employee-section">
                <div class="rc-emp-meta">
                    <span class="rc-emp-label">NHÂN VIÊN</span>
                    <h3 class="rc-emp-name">${staffName}</h3>
                    <span class="rc-emp-role">${roleLabel}</span>
                </div>
                <div class="rc-emp-meta rc-hide-mobile" style="text-align: right;">
                    <span class="rc-emp-label">MÃ TRA CỨU</span>
                    <div class="rc-ref-code">${refCode}</div>
                    <span class="rc-badge-status">ĐÃ XÁC THỰC</span>
                </div>
            </div>

            <!-- Net Pay Hero Block -->
            <div class="rc-hero-total">
                <span class="rc-hero-label">TỔNG LƯƠNG & THƯỞNG KỲ NÀY</span>
                <div class="rc-hero-amount">${fmtMoney.format(totalReceived).replace('₫', 'đ')}</div>
                <span class="rc-hero-sub">Đã bao gồm lương cơ bản, làm thêm & phụ cấp ca trực</span>
            </div>

            <div class="rc-divider-dashed"></div>

            <!-- Breakdown Table -->
            <div class="rc-details-table">
                <div class="rc-row">
                    <span class="rc-row-title">Tổng ca trực hoàn thành</span>
                    <span class="rc-row-val">${totalShifts} ca</span>
                </div>
                <div class="rc-row">
                    <span class="rc-row-title">Tổng thời gian làm việc</span>
                    <span class="rc-row-val">${fmtNum.format(standardMins + otMins)} phút <em>(${totalHours} giờ)</em></span>
                </div>
                <div class="rc-row">
                    <span class="rc-row-title">Đơn giá lương cơ bản</span>
                    <span class="rc-row-val">${fmtMoney.format(emp.wage).replace('₫', 'đ')}/giờ</span>
                </div>
                <div class="rc-row">
                    <span class="rc-row-title">Lương tiêu chuẩn (${standardHours} giờ)</span>
                    <span class="rc-row-val">${fmtMoney.format(standardCost).replace('₫', 'đ')}</span>
                </div>
                <div class="rc-row highlight-ot">
                    <span class="rc-row-title">Lương làm thêm Overtime (${otHours} giờ)</span>
                    <span class="rc-row-val">+${fmtMoney.format(otCost).replace('₫', 'đ')}</span>
                </div>
                ${holidayExtraTotal > 0 ? `
                <div class="rc-row" style="background: rgba(239, 68, 68, 0.08); padding: 7px 10px; border-radius: 8px; margin: 4px -10px; border-left: 3px solid #ef4444;">
                    <span class="rc-row-title" style="color: #b91c1c; font-weight: 700;">
                        🎉 Phụ cấp Lễ 2/9 (Hệ số x2: +100%)
                        <div style="font-size: 11px; font-weight: 400; opacity: 0.85;">${holidayShiftsCount} ca trực • ${(holidayMins/60).toFixed(1)} giờ làm ngày lễ</div>
                    </span>
                    <span class="rc-row-val" style="color: #b91c1c; font-weight: 800; font-size: 13px;">
                        +${fmtMoney.format(holidayExtraTotal).replace('₫', 'đ')}
                    </span>
                </div>
                ` : ''}
                <div class="rc-row">
                    <span class="rc-row-title">Thưởng nóng / Hiệu suất</span>
                    <span class="rc-row-val text-emerald">+${fmtMoney.format(totalBonus).replace('₫', 'đ')}${bonusNoteSub}</span>
                </div>
                <div class="rc-row" style="background: rgba(244, 63, 94, 0.06); padding: 6px 10px; border-radius: 8px; margin: 4px -10px;">
                    <span class="rc-row-title" style="color: var(--accent-coral); font-weight: 600;">Tạm ứng trong kỳ (${aList.length} lần)</span>
                    <span class="rc-row-val" style="color: var(--accent-coral); font-weight: 700; text-align: right;">
                        -${fmtMoney.format(aSummary).replace('₫', 'đ')}
                        ${advanceNoteSub}
                    </span>
                </div>
                <div class="rc-row"${totalPenalty > 0 ? ' style="background: rgba(244, 63, 94, 0.08); padding: 6px 10px; border-radius: 8px; margin: 4px -10px;"' : ''}>
                    <span class="rc-row-title"${totalPenalty > 0 ? ' style="color: var(--accent-coral); font-weight: 600;"' : ''}>Khấu trừ vi phạm trễ ca (${lateOver10Count} lần)</span>
                    <span class="rc-row-val${totalPenalty > 0 ? '' : ' text-muted'}"${totalPenalty > 0 ? ' style="color: var(--accent-coral); font-weight: 700;"' : ''}>
                        -${fmtMoney.format(totalPenalty).replace('₫', 'đ')}
                        ${penaltyDetails.length > 0 ? `<div style="font-size:11px; opacity:0.85; margin-top:2px; font-weight:400;">(${penaltyDetails.join(' • ')})</div>` : ''}
                    </span>
                </div>
            </div>

            <div class="rc-divider-double"></div>

            <!-- Summary Total Row -->
            <div class="rc-summary-row">
                <span class="rc-sum-label">THỰC CHUYỂN KHOẢN (ĐÃ TRỪ ỨNG):</span>
                <span class="rc-sum-val" style="color: var(--accent-coral); font-size: 20px; font-weight: 800;">${fmtMoney.format(bankTransferAfterPenalty).replace('₫', 'đ')}</span>
            </div>

            <!-- Notice & Policy -->
            <div class="rc-notice-box">
                <p>📌 <strong>Quy định thanh toán:</strong> Mọi thắc mắc về lương/thưởng/tạm ứng, các bạn vui lòng phản hồi trong 24h. Lương sẽ được chuyển khoản vào ngày 05 hàng tháng.</p>
            </div>

            <!-- Barcode Footer -->
            <div class="rc-barcode-footer">
                <div class="rc-barcode-lines">
                    <span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span>
                </div>
                <div class="rc-footer-text">${escapeHtml(((typeof window !== 'undefined' && window.vnaigc_store_name) || (typeof localStorage !== 'undefined' && localStorage.getItem('vnaigc_store_name')) || 'FNBOPS').toUpperCase())} • CONFIDENTIAL PAYROLL DOCUMENT</div>
            </div>
        </div>
    `;
    
    document.getElementById('payslipContent').innerHTML = html;
    document.getElementById('payslipModal').style.display = 'flex';
};

// Search functionality for payslip table
document.getElementById('payslipSearch').addEventListener('input', (e) => {
    const q = e.target.value.toLowerCase();
    const rows = document.getElementById('payslipTableBody').querySelectorAll('tr');
    rows.forEach(r => {
        const name = r.querySelector('.name-pill').textContent.toLowerCase();
        if (name.includes(q)) r.style.display = '';
        else r.style.display = 'none';
    });
});

// ==========================================================================
// BONUS & ADJUSTMENT LEDGER MODAL HANDLERS
// ==========================================================================

let currentBonusStaff = null;
let currentBonusPaymentType = 'bank';

window.openBonusModal = function(staffName) {
    currentBonusStaff = staffName;
    currentBonusPaymentType = 'bank';
    
    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;
    document.getElementById('bonusStaffName').textContent = staffName;
    document.getElementById('bonusMonthLabel').textContent = `Tháng ${m}/2026`;
    
    // Set default date to today in YYYY-MM-DD
    const todayStr = new Date().toISOString().split('T')[0];
    const dateInput = document.getElementById('bonusDateInput');
    if (dateInput) {
        dateInput.value = todayStr;
    }
    
    setBonusPaymentType('bank');
    
    document.getElementById('bonusAmountInput').value = '';
    document.getElementById('bonusReasonSelect').value = 'Thưởng nóng doanh thu ca / Khách đông đột biến';
    document.getElementById('bonusCustomReason').style.display = 'none';
    document.getElementById('bonusCustomReason').value = '';
    
    // Calculate % wage buttons based on staff's current month base earnings
    const filtered = currentMonth === 'all' ? records : records.filter(r => r.month === currentMonth);
    const empRecords = filtered.filter(r => r.name === staffName);
    let staffBaseTotal = 0;
    empRecords.forEach(r => staffBaseTotal += r.totalCost);
    
    const btn5 = document.getElementById('btnPreset5Pct');
    const btn10 = document.getElementById('btnPreset10Pct');
    if (staffBaseTotal > 0) {
        const val5 = Math.round((staffBaseTotal * 0.05) / 1000) * 1000;
        const val10 = Math.round((staffBaseTotal * 0.10) / 1000) * 1000;
        btn5.textContent = `+5% (${(val5/1000)}k)`;
        btn5.setAttribute('data-val', val5);
        btn10.textContent = `+10% (${(val10/1000)}k)`;
        btn10.setAttribute('data-val', val10);
    } else {
        btn5.textContent = '+5% Lương';
        btn5.setAttribute('data-val', 50000);
        btn10.textContent = '+10% Lương';
        btn10.setAttribute('data-val', 100000);
    }

    renderBonusHistoryList();
    document.getElementById('bonusModal').style.display = 'flex';
};

window.closeBonusModal = function() {
    document.getElementById('bonusModal').style.display = 'none';
    currentBonusStaff = null;
    updateUI();
};

window.setBonusPaymentType = function(type) {
    currentBonusPaymentType = type;
    const bankLabel = document.getElementById('typeBankLabel');
    const cashLabel = document.getElementById('typeCashLabel');
    const dateHint = document.getElementById('bonusDateHint');
    const dateInput = document.getElementById('bonusDateInput');

    if (type === 'bank') {
        bankLabel.classList.add('active');
        cashLabel.classList.remove('active');
        if (dateHint) dateHint.style.display = 'none';
    } else {
        cashLabel.classList.add('active');
        bankLabel.classList.remove('active');
        if (dateHint) dateHint.style.display = 'inline';
        
        // Auto-focus or pop date picker if available
        if (dateInput) {
            dateInput.focus();
            if (typeof dateInput.showPicker === 'function') {
                try { dateInput.showPicker(); } catch(e) {}
            }
        }
    }
};

window.setBonusAmount = function(amt) {
    document.getElementById('bonusAmountInput').value = amt;
};

window.setBonusPercent = function(pct) {
    const btn = pct === 5 ? document.getElementById('btnPreset5Pct') : document.getElementById('btnPreset10Pct');
    const val = parseInt(btn.getAttribute('data-val') || (pct === 5 ? 50000 : 100000));
    document.getElementById('bonusAmountInput').value = val;
};

window.handleBonusReasonChange = function() {
    const sel = document.getElementById('bonusReasonSelect');
    const custom = document.getElementById('bonusCustomReason');
    if (sel.value === 'custom') {
        custom.style.display = 'block';
        custom.focus();
    } else {
        custom.style.display = 'none';
    }
};

function renderBonusHistoryList() {
    if (!currentBonusStaff) return;
    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;
    const summary = getStaffBonusSummary(m, currentBonusStaff);
    
    document.getElementById('bonusEntryCount').textContent = summary.count;
    document.getElementById('bonusSumTotal').textContent = '+' + fmtMoney.format(summary.total).replace('₫', 'đ');
    document.getElementById('bonusSumCash').textContent = '-' + fmtMoney.format(summary.cash).replace('₫', 'đ');
    document.getElementById('bonusSumBank').textContent = '+' + fmtMoney.format(summary.bank).replace('₫', 'đ');
    
    const listEl = document.getElementById('bonusHistoryList');
    listEl.innerHTML = '';
    
    if (summary.list.length === 0) {
        listEl.innerHTML = `
            <div style="text-align: center; color: var(--text-secondary); font-size: 13px; padding: 16px 0;">
                Chưa có khoản thưởng nào trong kỳ này.
            </div>
        `;
        return;
    }
    
    summary.list.forEach((item) => {
        const div = document.createElement('div');
        div.className = 'bonus-log-item';
        const isCash = item.type === 'cash';
        const typeBadge = isCash ? '<span style="color: var(--accent-coral); font-weight: 700;">💵 Tiền mặt</span>' : '<span style="color: var(--accent-emerald); font-weight: 700;">💳 Chuyển khoản</span>';
        
        div.innerHTML = `
            <div class="bonus-log-info">
                <div class="bonus-log-title">${item.reason}</div>
                <div class="bonus-log-meta">${item.date || item.timestamp} • ${typeBadge}</div>
            </div>
            <div class="bonus-log-right">
                <div class="bonus-log-amt ${isCash ? 'cash' : ''}">+${fmtMoney.format(item.amount).replace('₫', 'đ')}</div>
                <button type="button" class="bonus-del-btn" onclick="deleteBonusEntry('${item.id}')" title="Xóa khoản này">✕</button>
            </div>
        `;
        listEl.appendChild(div);
    });
}

window.deleteBonusEntry = function(id) {
    if (!currentBonusStaff) return;
    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;
    if (!bonusLedger[m] || !bonusLedger[m][currentBonusStaff]) return;
    
    bonusLedger[m][currentBonusStaff] = bonusLedger[m][currentBonusStaff].filter(item => item.id !== id);
    saveBonusLedger();
    renderBonusHistoryList();
    showToast('Đã xóa khoản thưởng', 'success');
};

document.getElementById('btnAddBonusEntry').addEventListener('click', async () => {
    if (!currentBonusStaff) return;
    const amt = parseInt(document.getElementById('bonusAmountInput').value) || 0;
    if (amt <= 0) {
        showToast('Vui lòng nhập số tiền hợp lệ', 'error');
        return;
    }
    const rSelect = document.getElementById('bonusReasonSelect').value;
    const reason = rSelect === 'custom' ? document.getElementById('bonusCustomReason').value : rSelect;
    
    if (!reason.trim()) {
        showToast('Vui lòng nhập lý do thưởng', 'error');
        return;
    }
    
    const btn = document.getElementById('btnAddBonusEntry');
    btn.innerHTML = '⏳ Đang lưu...';
    btn.disabled = true;
    
    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;
    const dateInput = document.getElementById('bonusDateInput');
    const dateVal = dateInput ? dateInput.value : new Date().toISOString().slice(0, 10);
    
    // Save locally first (instant)
    if (!bonusLedger[m]) bonusLedger[m] = {};
    if (!bonusLedger[m][currentBonusStaff]) bonusLedger[m][currentBonusStaff] = [];
    bonusLedger[m][currentBonusStaff].push({
        id: Date.now().toString(),
        date: dateVal,
        amount: amt,
        type: currentBonusPaymentType,
        reason: reason,
        timestamp: new Date().toLocaleString('vi-VN')
    });
    saveBonusLedger();

    const payload = {
        type: 'Thưởng',
        staff: currentBonusStaff,
        month: m,
        amount: amt,
        payment_type: currentBonusPaymentType,
        reason: reason,
        timestamp: new Date().toLocaleString('vi-VN')
    };
    
    sendLedgerEntryAPI(payload); // async via n8n
    
    btn.innerHTML = '✓ Xác Nhận Thêm Khoản Thưởng';
    btn.disabled = false;
    
    showToast('Ghi nhận thưởng thành công!', 'success');
    document.getElementById('bonusAmountInput').value = '';
    renderBonusHistoryList();
    updateUI();
}); //

// ---------------------------------------------------------------------------------------------------------------------
// ADVANCE SALARY LOGIC
// ---------------------------------------------------------------------------------------------------------------------
let currentAdvStaff = null;
let currentAdvPaymentType = 'bank';

window.setAdvPaymentType = function(type) {
    currentAdvPaymentType = type;
    document.getElementById('advTypeBankLabel').classList.remove('active');
    document.getElementById('advTypeCashLabel').classList.remove('active');
    if (type === 'bank') {
        document.getElementById('advTypeBankLabel').classList.add('active');
        document.querySelector('input[name="advPaymentType"][value="bank"]').checked = true;
    } else {
        document.getElementById('advTypeCashLabel').classList.add('active');
        document.querySelector('input[name="advPaymentType"][value="cash"]').checked = true;
    }
};

window.openAdvanceModal = function(staffName) {
    currentAdvStaff = staffName;
    document.getElementById('advanceStaffName').innerText = staffName;
    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;
    document.getElementById('advanceMonthLabel').innerText = `Tháng ${m}`;
    
    // Set today as default date
    const tzoffset = (new Date()).getTimezoneOffset() * 60000;
    const localISOTime = (new Date(Date.now() - tzoffset)).toISOString().slice(0, 10);
    document.getElementById('advanceDateInput').value = localISOTime;
    
    renderAdvanceHistoryList();
    document.getElementById('advanceModal').style.display = 'flex';
};

window.closeAdvanceModal = function() {
    document.getElementById('advanceModal').style.display = 'none';
};

window.renderAdvanceHistoryList = function() {
    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;
    const list = getStaffAdvances(m, currentAdvStaff);
    const container = document.getElementById('advanceHistoryList');
    
    if (list.length === 0) {
        container.innerHTML = `<div style="text-align: center; padding: 20px; color: var(--text-secondary); font-size: 13px; font-style: italic; border: 1px dashed var(--border); border-radius: 12px; background: #fafafa;">Chưa có khoản ứng nào trong kỳ này.</div>`;
        document.getElementById('advanceEntryCount').innerText = '0';
        document.getElementById('advanceSumTotal').innerText = '0 đ';
        return;
    }
    
    let html = '';
    let total = 0;
    
    list.forEach(item => {
        const amt = parseInt(item.amount) || 0;
        total += amt;
        const icon = item.type === 'bank' ? '💳' : '💵';
        html += `
        <div class="bonus-history-item" style="display: flex; justify-content: space-between; align-items: center; padding: 12px; border: 1px solid var(--border); border-radius: 12px; margin-bottom: 8px; background: #fff;">
            <div>
                <div style="font-size: 13px; font-weight: 700; color: var(--text-primary); margin-bottom: 4px;">${item.reason}</div>
                <div style="font-size: 11px; color: var(--text-secondary); display: flex; gap: 8px;">
                    <span>📅 ${item.date || item.timestamp}</span>
                    <span>${icon} ${item.type === 'bank' ? 'Chuyển khoản' : 'Tiền mặt'}</span>
                </div>
            </div>
            <div style="text-align: right;">
                <div style="font-size: 14px; font-weight: 800; color: var(--accent-coral); font-family: var(--font-mono); margin-bottom: 4px;">-${amt.toLocaleString('vi-VN')} đ</div>
            </div>
        </div>
        `;
    });
    
    container.innerHTML = html;
    document.getElementById('advanceEntryCount').innerText = list.length;
    document.getElementById('advanceSumTotal').innerText = `-${total.toLocaleString('vi-VN')} đ`;
};

document.getElementById('btnAddAdvanceEntry').addEventListener('click', async () => {
    if (!currentAdvStaff) return;
    const amt = parseInt(document.getElementById('advanceAmountInput').value) || 0;
    if (amt <= 0) {
        showToast('Vui lòng nhập số tiền hợp lệ', 'error');
        return;
    }
    const reason = document.getElementById('advanceReasonInput').value;
    if (!reason.trim()) {
        showToast('Vui lòng nhập lý do ứng tiền', 'error');
        return;
    }
    
    const btn = document.getElementById('btnAddAdvanceEntry');
    btn.innerHTML = '⏳ Đang lưu...';
    btn.disabled = true;
    
    const m = currentMonth === 'all' ? (monthsAvailable[monthsAvailable.length - 1] || '8') : currentMonth;
    const dateInput = document.getElementById('advanceDateInput');
    const dateVal = dateInput ? dateInput.value : new Date().toISOString().slice(0,10);
    
    // Save locally first (instant)
    if (!advanceLedger[m]) advanceLedger[m] = {};
    if (!advanceLedger[m][currentAdvStaff]) advanceLedger[m][currentAdvStaff] = [];
    advanceLedger[m][currentAdvStaff].push({
        id: Date.now().toString(),
        date: dateVal,
        amount: amt,
        type: currentAdvPaymentType,
        reason: reason,
        timestamp: new Date().toLocaleString('vi-VN')
    });
    saveAdvanceLedger();
    
    // Background sync to server
    const payload = {
        type: 'Ứng',
        staff: currentAdvStaff,
        month: m,
        amount: amt,
        payment_type: currentAdvPaymentType,
        reason: reason
    };
    sendLedgerEntryAPI(payload); // fire-and-forget
    
    btn.innerHTML = '✓ Xác Nhận Ứng Lương';
    btn.disabled = false;
    
    showToast('Ghi nhận ứng lương thành công!', 'success');
    document.getElementById('advanceAmountInput').value = '';
    document.getElementById('advanceReasonInput').value = '';
    renderAdvanceHistoryList();
    updateUI();
});
// ---------------------------------------------------------------------------------------------------------------------

// ==========================================================================
// DESKTOP ROLE PERMISSIONS & ADMIN PIN EXTENSIONS
// ==========================================================================

function applyRolePermissionsDesktop(role, meta) {
    const isStaff = (role === 'STAFF');
    const btnAdmin = document.getElementById('btnAdminStaffDesktop');
    const btnLockouts = document.getElementById('btnAdminLockoutsDesktop');
    const btnMonthly = document.getElementById('btnMonthlyReportDesktop');
    const btnEval = document.getElementById('btnOpenEval');
    const tabBtns = document.querySelectorAll('.tabs-container .tab-btn');
    const opsView = document.getElementById('opsView');
    const heatmapView = document.getElementById('heatmapView');
    const payslipView = document.getElementById('payslipView');
    const headerLeft = document.querySelector('.header .h-left');

    if (isStaff) {
        if (btnAdmin) btnAdmin.style.display = 'none';
        if (btnLockouts) btnLockouts.style.display = 'none';
        if (btnMonthly) btnMonthly.style.display = 'none';
        if (btnEval) btnEval.style.display = 'none';
        tabBtns.forEach(btn => {
            if (btn.dataset.tab !== 'payslip') {
                btn.style.display = 'none';
                btn.classList.remove('active');
            } else {
                btn.classList.add('active');
            }
        });
        if (opsView) opsView.classList.remove('active');
        if (heatmapView) heatmapView.classList.remove('active');
        if (payslipView) payslipView.classList.add('active');
        if (headerLeft) {
            const badge = headerLeft.querySelector('.badge');
            if (badge) {
                badge.textContent = `NV: ${meta.full_name || localStorage.getItem('vnaigc_name') || ''}`;
                badge.style.background = 'var(--accent-emerald, #0D9488)';
            }
        }
    } else if (role === 'MANAGER') {
        if (btnAdmin) btnAdmin.style.display = 'inline-flex';
        if (btnLockouts) btnLockouts.style.display = 'none';
        if (btnMonthly) btnMonthly.style.display = 'none';
        if (btnEval) btnEval.style.display = 'inline-block';
        tabBtns.forEach(btn => btn.style.display = 'inline-flex');
        if (headerLeft) {
            const badge = headerLeft.querySelector('.badge');
            if (badge) {
                badge.textContent = 'QUẢN LÝ: ' + (meta.full_name || localStorage.getItem('vnaigc_name') || 'QUẢN LÝ').toUpperCase();
                badge.style.background = '#d97706';
            }
        }
    } else {
        if (btnAdmin) btnAdmin.style.display = 'inline-flex';
        if (btnLockouts) btnLockouts.style.display = 'inline-flex';
        if (btnMonthly) btnMonthly.style.display = 'inline-flex';
        if (btnEval) btnEval.style.display = 'inline-block';
        tabBtns.forEach(btn => btn.style.display = 'inline-flex');
    }

    const rosterActions = document.getElementById('rosterAdminActionsDesktop');
    if (rosterActions) {
        rosterActions.style.display = (isStaff) ? 'none' : 'flex';
    }
}

let adminStaffAccountsDesktop = null;

async function openAdminModalDesktop() {
    const token = localStorage.getItem('vnaigc_jwt');
    try {
        const res = await fetch('/api/v1/cc/admin/staff-accounts', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) return alert('Không thể tải danh sách tài khoản');
        adminStaffAccountsDesktop = await res.json();
        renderAdminStaffListDesktop();
        updateAdminLockBoxDesktop();
        document.getElementById('adminStaffModalDesktop').style.display = 'flex';
    } catch (e) {
        alert('Lỗi kết nối máy chủ');
    }
}

function updateAdminLockBoxDesktop() {
    const locks = (adminStaffAccountsDesktop && adminStaffAccountsDesktop.payroll_locks) || {};
    const m = currentMonth === 'all' ? currentRealtimeMonth : currentMonth;
    const lock = locks[m] || { status: 'OPEN' };
    const isLocked = lock.status === 'LOCKED';

    const titleEl = document.getElementById('txtAdminLockMonthDesktop');
    const statusEl = document.getElementById('txtAdminLockStatusDesktop');
    const btnToggle = document.getElementById('btnAdminToggleLockDesktop');

    if (titleEl) titleEl.textContent = `Kỳ Lương Tháng ${m}`;
    if (statusEl) {
        statusEl.innerHTML = isLocked
            ? `<span style="color:var(--accent-coral); font-weight:700;">🔒 ĐANG KHÓA ĐỐI SOÁT</span>`
            : `<span style="color:var(--accent-emerald); font-weight:700;">✓ ĐANG MỞ (Nhân viên tra cứu & xác nhận)</span>`;
    }
    if (btnToggle) {
        const currentRole = localStorage.getItem('vnaigc_role') || 'STAFF';
        if (currentRole !== 'ADMIN') {
            btnToggle.style.display = 'none';
        } else {
            btnToggle.style.display = 'inline-block';
            btnToggle.textContent = isLocked ? 'Mở Kỳ Lương' : 'Khóa Kỳ Lương';
            btnToggle.onclick = async () => {
                const newStatus = isLocked ? 'OPEN' : 'LOCKED';
                const msg = isLocked ? '' : prompt('Nhập thông báo khi khóa:') || '';
                try {
                    const token = localStorage.getItem('vnaigc_jwt');
                    const r = await fetch('/api/v1/cc/admin/toggle-lock', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                        body: JSON.stringify({ month: m, status: newStatus, message: msg })
                    });
                    if (r.ok) {
                        const d = await r.json();
                        adminStaffAccountsDesktop.payroll_locks = d.payroll_locks;
                        updateAdminLockBoxDesktop();
                        alert(`Đã cập nhật trạng thái Tháng ${m} thành: ${newStatus}`);
                    }
                } catch (e) {
                    alert('Lỗi cập nhật');
                }
            };
        }
    }
}

let adminStaffFilterDesktop = 'ALL';

function setAdminStaffFilterDesktop(filter) {
    adminStaffFilterDesktop = filter;
    ['filterTabAllDesktop', 'filterTabActiveDesktop', 'filterTabInactiveDesktop'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.style.background = 'transparent';
            el.style.fontWeight = '600';
            el.style.color = id.includes('Active') ? '#059669' : (id.includes('Inactive') ? '#dc2626' : 'var(--text-primary)');
        }
    });
    const activeBtn = document.getElementById(filter === 'ALL' ? 'filterTabAllDesktop' : (filter === 'ACTIVE' ? 'filterTabActiveDesktop' : 'filterTabInactiveDesktop'));
    if (activeBtn) {
        activeBtn.style.background = filter === 'INACTIVE' ? 'rgba(239,68,68,0.15)' : (filter === 'ACTIVE' ? 'rgba(16,185,129,0.15)' : 'var(--border, #e0e0e0)');
        activeBtn.style.fontWeight = '700';
    }
    const searchInput = document.getElementById('adminStaffSearchDesktop');
    renderAdminStaffListDesktop(searchInput ? searchInput.value : '');
}

async function handleToggleStaffStatusDesktop(uname, newStatus) {
    const isLocking = newStatus === 'INACTIVE';
    const confirmMsg = isLocking 
        ? `Xác nhận KHÓA tài khoản của @${uname}?\n\nNhân viên sẽ bị kick-out ngay lập tức và không thể chấm công hay tra cứu lương.`
        : `Xác nhận MỞ LẠI tài khoản cho @${uname}?`;
    
    if (!confirm(confirmMsg)) return;

    const token = localStorage.getItem('vnaigc_jwt');
    try {
        const res = await fetch('/api/v1/cc/admin/toggle-staff-status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ username: uname, status: newStatus })
        });

        let data;
        try {
            data = await res.json();
        } catch {
            data = { detail: `Lỗi máy chủ (${res.status})` };
        }
        if (res.ok) {
            alert(`✓ ${data.message || 'Đã cập nhật trạng thái thành công'}`);
            if (adminStaffAccountsDesktop && adminStaffAccountsDesktop.staff_accounts && adminStaffAccountsDesktop.staff_accounts[uname]) {
                adminStaffAccountsDesktop.staff_accounts[uname].status = newStatus;
            }
            const searchInput = document.getElementById('adminStaffSearchDesktop');
            renderAdminStaffListDesktop(searchInput ? searchInput.value : '');
        } else {
            alert(`⚠️ ${data.detail || 'Lỗi cập nhật trạng thái'}`);
        }
    } catch (e) {
        alert(`Lỗi kết nối: ${e.message}`);
    }
}

function renderAdminStaffListDesktop(query = '') {
    const container = document.getElementById('adminStaffListDesktop');
    if (!container || !adminStaffAccountsDesktop) return;
    const accounts = adminStaffAccountsDesktop.staff_accounts || {};
    const m = currentMonth === 'all' ? currentRealtimeMonth : currentMonth;
    const q = query.trim().toLowerCase();

    const allEntries = Object.entries(accounts);
    const totalCount = allEntries.length;
    const activeCount = allEntries.filter(([_, a]) => (a.status || 'ACTIVE') !== 'INACTIVE').length;
    const inactiveCount = allEntries.filter(([_, a]) => a.status === 'INACTIVE').length;

    const btnAll = document.getElementById('filterTabAllDesktop');
    if (btnAll) btnAll.textContent = `Tất cả (${totalCount})`;
    const btnAct = document.getElementById('filterTabActiveDesktop');
    if (btnAct) btnAct.textContent = `Đang làm (${activeCount})`;
    const btnInact = document.getElementById('filterTabInactiveDesktop');
    if (btnInact) btnInact.textContent = `Đã nghỉ (${inactiveCount})`;

    let items = allEntries;

    if (adminStaffFilterDesktop === 'ACTIVE') {
        items = items.filter(([_, acc]) => (acc.status || 'ACTIVE') !== 'INACTIVE');
    } else if (adminStaffFilterDesktop === 'INACTIVE') {
        items = items.filter(([_, acc]) => acc.status === 'INACTIVE');
    }

    if (q) {
        items = items.filter(([uname, acc]) => {
            return uname.toLowerCase().includes(q) ||
                   (acc.full_name && acc.full_name.toLowerCase().includes(q)) ||
                   (acc.pin && acc.pin.includes(q));
        });
    }

    // Tự động sắp xếp: ACTIVE (đang làm) lên trên đầu, INACTIVE (đã nghỉ) xuống đáy
    items.sort(([uA, aA], [uB, aB]) => {
        const inactA = (aA.status === 'INACTIVE') ? 1 : 0;
        const inactB = (aB.status === 'INACTIVE') ? 1 : 0;
        if (inactA !== inactB) return inactA - inactB; // 0 (Active) lên trước, 1 (Inactive) xuống đáy
        
        const mgrA = (aA.role === 'MANAGER') ? 0 : 1;
        const mgrB = (aB.role === 'MANAGER') ? 0 : 1;
        if (mgrA !== mgrB) return mgrA - mgrB;

        return (aA.full_name || uA).localeCompare(aB.full_name || uB, 'vi');
    });

    let html = '';
    items.forEach(([uname, acc]) => {
        const conf = (acc.confirmations && acc.confirmations[m]) || null;
        let confBadge = `<span style="font-size:11px; padding:2px 8px; border-radius:4px; background:var(--border, #eee); color:var(--text-secondary);">Chưa xác nhận</span>`;
        if (conf && conf.status === 'CONFIRMED') {
            confBadge = `<span style="font-size:11px; padding:2px 8px; border-radius:4px; background:rgba(13,148,136,0.15); color:var(--accent-emerald); font-weight:700;" title="${conf.timestamp}">✓ Đã xác nhận</span>`;
        } else if (conf && conf.status === 'DISPUTED') {
            confBadge = `<span style="font-size:11px; padding:2px 8px; border-radius:4px; background:rgba(238,93,54,0.15); color:var(--accent-coral); font-weight:700;" title="${escapeHtml(conf.note)}">⚠️ Báo sai: ${escapeHtml(conf.note)}</span>`;
        }

        const isInactive = acc.status === 'INACTIVE';
        const statusBadge = isInactive
            ? `<span style="font-size:10px; padding:2px 6px; border-radius:4px; background:rgba(239,68,68,0.15); color:#dc2626; font-weight:700;">ĐÃ NGHỈ</span>`
            : `<span style="font-size:10px; padding:2px 6px; border-radius:4px; background:rgba(16,185,129,0.12); color:#059669; font-weight:700;">ACTIVE</span>`;

        html += `
            <div style="background:var(--bg-card, #fff); border:1px solid ${isInactive ? 'rgba(239,68,68,0.3)' : 'var(--border, #ddd)'}; border-radius:8px; padding:10px 14px; display:flex; justify-content:space-between; align-items:center; opacity:${isInactive ? '0.85' : '1'};">
                <div>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="font-weight:700; font-size:13px; color:var(--text-primary); ${isInactive ? 'text-decoration:line-through; color:var(--text-muted);' : ''}">${escapeHtml(acc.full_name || uname)}</span>
                        <span style="font-size:11px; font-weight:normal; font-family:monospace; color:var(--text-secondary);">(@${escapeHtml(uname)})</span>
                        ${acc.role === 'MANAGER' ? '<span style="font-size:9px; background:rgba(245,158,11,0.15); color:#d97706; padding:1px 5px; border-radius:4px; font-weight:700;">QUẢN LÝ</span>' : ''}
                        ${statusBadge}
                    </div>
                    <div style="margin-top:2px;">${confBadge}</div>
                </div>
                <div style="display:flex; align-items:center; gap:8px;">
                    <div style="display:flex; align-items:center; gap:4px;">
                        <span style="font-size:11px; color:var(--text-secondary);">PIN:</span>
                        <input type="text" id="pinDesktop_${uname}" value="${(acc.pin && acc.pin !== '****' && !acc.pin.startsWith('pbkdf2_')) ? acc.pin : '1111'}" maxlength="4" style="width:50px; text-align:center; font-family:monospace; font-weight:700; font-size:12px; padding:3px 4px; border:1px solid var(--border); border-radius:4px;">
                        <button onclick="handleUpdatePinDesktop('${uname}')" class="btn-primary" style="padding:3px 8px; font-size:11px; background:var(--text-secondary);">Lưu</button>
                    </div>
                    <button onclick="handleToggleStaffStatusDesktop('${uname}', '${isInactive ? 'ACTIVE' : 'INACTIVE'}')" class="btn-primary" style="padding:3px 8px; font-size:11px; font-weight:700; background:transparent; ${isInactive ? 'color:#059669; border:1px solid #10b981; background:rgba(16,185,129,0.08);' : 'color:#dc2626; border:1px solid #ef4444; background:rgba(239,68,68,0.08);'}">
                        ${isInactive ? '🔓 Mở lại' : '🔒 Khóa'}
                    </button>
                    <button onclick="copyZaloInviteDesktop('${uname}')" class="btn-primary" style="padding:4px 10px; font-size:11px; background:var(--accent-coral);">📋 Copy Zalo</button>
                </div>
            </div>
        `;
    });

    if (items.length === 0) {
        html = `<div style="text-align:center; padding:20px; font-size:12px; color:var(--text-secondary);">Không có nhân sự nào phù hợp bộ lọc.</div>`;
    }

    container.innerHTML = html;
}

async function handleUpdatePinDesktop(uname) {
    const input = document.getElementById(`pinDesktop_${uname}`);
    if (!input) return;
    const newPin = input.value.trim();
    if (!/^\d{4}$/.test(newPin)) return alert('Mã PIN phải gồm đúng 4 chữ số!');

    const token = localStorage.getItem('vnaigc_jwt');
    try {
        const res = await fetch('/api/v1/cc/admin/update-pin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
            body: JSON.stringify({ username: uname, new_pin: newPin })
        });
        if (res.ok) {
            alert(`Đã cập nhật mã PIN mới cho @${uname}: ${newPin}`);
            if (adminStaffAccountsDesktop && adminStaffAccountsDesktop.staff_accounts && adminStaffAccountsDesktop.staff_accounts[uname]) {
                adminStaffAccountsDesktop.staff_accounts[uname].pin = newPin;
            }
        } else {
            const err = await res.json();
            alert(err.detail || 'Lỗi cập nhật PIN');
        }
    } catch (e) {
        alert('Lỗi kết nối');
    }
}

function copyZaloInviteDesktop(uname) {
    if (!adminStaffAccountsDesktop) return;
    const acc = (adminStaffAccountsDesktop.staff_accounts || {})[uname];
    if (!acc) return;
    const m = currentMonth === 'all' ? currentRealtimeMonth : currentMonth;
    
    // 1. Ưu tiên lấy trực tiếp mã PIN đang hiển thị/vừa nhập trong ô input
    const pinInput = document.getElementById(`pinDesktop_${uname}`);
    let pin = (pinInput ? pinInput.value.trim() : '') || (acc.pin || '').trim();
    
    // 2. Chặn tuyệt đối không bao giờ copy chuỗi **** hoặc hash ra Zalo
    if (!pin || pin === '****' || pin.startsWith('pbkdf2_')) {
        pin = prompt(`Nhập mã PIN 4 số của ${acc.full_name || uname} để gửi Zalo:`, '1111');
        if (!pin) return;
        pin = pin.trim();
        if (pinInput) pinInput.value = pin;
        acc.pin = pin;
    }

    const curYear = new Date().getFullYear();
    const storeDisplayName = window.vnaigc_store_name || 'FnBOps';
    const text = `Chào ${acc.full_name}, bảng lương Tháng ${m}/${curYear} của bạn đã có trên hệ thống ${storeDisplayName}. Bạn vào link ${window.location.origin} để tra cứu nhé:\n- Tài khoản: ${uname}\n- Mã PIN: ${pin}\nBạn vui lòng đối soát giờ công và bấm [Xác Nhận] sớm nha!`;

    const fallbackExec = () => {
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            const ok = document.execCommand('copy');
            document.body.removeChild(ta);
            if (ok) {
                alert(`✓ Đã copy nội dung gửi Zalo cho ${acc.full_name}!\n\n"${text}"`);
                return;
            }
        } catch (e) {}
        prompt('Copy đoạn văn bản này gửi qua Zalo:', text);
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            alert(`✓ Đã copy nội dung gửi Zalo cho ${acc.full_name}!\n\n"${text}"`);
        }).catch(() => {
            fallbackExec();
        });
    } else {
        fallbackExec();
    }
}

async function confirmShiftOT(shiftKey, action, approvedMins, note = '') {
    const token = localStorage.getItem('vnaigc_jwt') || localStorage.getItem('vnaigc_token') || localStorage.getItem('cc_token');
    if (!token) return alert('Vui lòng đăng nhập quyền Quản lý');

    try {
        const res = await fetch('/api/v1/cc/shifts/confirm-ot', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                shift_key: shiftKey,
                action: action,
                approved_mins: approvedMins || 300,
                manager_note: note || ''
            })
        });
        const d = await res.json();
        if (!res.ok) throw new Error(d.detail || 'Lỗi xử lý duyệt ca');

        if (!rawData._meta) rawData._meta = {};
        if (!rawData._meta.shift_approvals) rawData._meta.shift_approvals = {};
        if (action === 'RESET') {
            delete rawData._meta.shift_approvals[shiftKey];
        } else {
            rawData._meta.shift_approvals[shiftKey] = d.approval;
        }

        // Tải lại dữ liệu và giao diện
        processData();
        updateUI();
    } catch (err) {
        alert(err.message);
    }
}
window.confirmShiftOT = confirmShiftOT;


// ==========================================================================
// ADMIN LOCKOUTS & 3-TIER RATE LIMIT DASHBOARD
// ==========================================================================

async function openAdminLockoutsModalDesktop() {
    const modal = document.getElementById('adminLockoutsModalDesktop');
    if (modal) modal.style.display = 'flex';
    await fetchAndRenderAdminLockoutsDesktop();
}

async function fetchAndRenderAdminLockoutsDesktop() {
    const listEl = document.getElementById('adminLockoutsListDesktop');
    const cafeIpEl = document.getElementById('adminLiveCafeIpDesktop');
    const totalEl = document.getElementById('txtTotalLockoutsDesktop');
    const token = localStorage.getItem('vnaigc_jwt');

    if (!listEl) return;
    listEl.innerHTML = '<div style="text-align:center; padding:20px 0; color:var(--text-secondary); font-size:12px;">Đang tải danh sách...</div>';

    try {
        const res = await fetch('/api/v1/cc/admin/lockouts', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) {
            listEl.innerHTML = '<div style="text-align:center; padding:20px 0; color:#dc2626; font-size:12px;">Không có quyền truy cập hoặc lỗi kết nối.</div>';
            return;
        }
        const data = await res.json();
        const lockouts = data.lockouts || [];
        const cafeIp = data.cafe_ip || 'Chưa nhận diện';

        if (cafeIpEl) cafeIpEl.textContent = cafeIp;
        if (totalEl) totalEl.textContent = lockouts.length;

        if (lockouts.length === 0) {
            listEl.innerHTML = `
                <div style="text-align:center; padding:35px 20px; background:var(--bg-card-sub, #f8fafc); border-radius:8px; border:1px dashed var(--border);">
                    <div style="font-size:24px; margin-bottom:8px;">✅</div>
                    <div style="font-size:13px; font-weight:700; color:#059669;">Không có tài khoản hoặc IP nào bị khóa</div>
                    <div style="font-size:11px; color:var(--text-secondary); margin-top:4px;">Tất cả nhân sự và mạng quán đang hoạt động bình thường.</div>
                </div>
            `;
            return;
        }

        let html = '';
        for (const item of lockouts) {
            const isUser = (item.target_type === 'USER');
            const tier = item.tier || 1;
            const attempts = item.attempts || 5;
            const isAdminLocked = (item.is_admin_locked === 1 || tier >= 3);
            const remSec = item.remaining_seconds || 0;
            const remStr = isAdminLocked 
                ? '5 Giờ (Cần Admin duyệt)' 
                : (remSec > 60 ? `${Math.ceil(remSec / 60)} phút` : `${remSec} giây`);
            
            const badgeColor = tier === 3 ? '#dc2626' : (tier === 2 ? '#d97706' : '#2563eb');
            const badgeBg = tier === 3 ? '#fee2e2' : (tier === 2 ? '#fef3c7' : '#dbeafe');
            const tierText = tier === 3 ? 'TẦNG 3 (5H / ADMIN)' : (tier === 2 ? 'TẦNG 2 (30 PHÚT)' : 'TẦNG 1 (60S)');
            const targetDisplay = isUser ? `👤 Tài khoản: @${item.identifier || item.username}` : `🌐 Địa chỉ IP: ${item.identifier || item.ip}`;

            html += `
                <div style="background:var(--bg-card, #fff); border:1px solid var(--border); border-radius:8px; padding:12px 14px; display:flex; justify-content:space-between; align-items:center; gap:12px;">
                    <div>
                        <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                            <span style="font-size:13px; font-weight:700; color:var(--text-primary); font-family:monospace;">${targetDisplay}</span>
                            <span style="font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; background:${badgeBg}; color:${badgeColor};">${tierText}</span>
                        </div>
                        <div style="font-size:11px; color:var(--text-secondary); display:flex; gap:12px;">
                            <span>Đã sai: <b>${attempts} lần</b></span>
                            <span>IP xuất phát: <code>${item.ip || 'N/A'}</code></span>
                            <span>Thời hạn: <b style="color:${badgeColor};">${remStr}</b></span>
                        </div>
                    </div>
                    <button class="btn-primary" style="background:#059669; font-size:11px; padding:6px 12px; white-space:nowrap;" onclick="handleAdminUnlockDesktop('${item.target_key}')">
                        🔓 Mở Khóa
                    </button>
                </div>
            `;
        }
        listEl.innerHTML = html;
    } catch (e) {
        listEl.innerHTML = '<div style="text-align:center; padding:20px 0; color:#dc2626; font-size:12px;">Lỗi kết nối máy chủ</div>';
    }
}

async function handleAdminUnlockDesktop(targetKey) {
    if (!targetKey) return;
    if (!confirm(`Chủ quán (Admin) xác nhận mở khóa ngay lập tức cho mục tiêu:\n\n${targetKey}?`)) return;

    const token = localStorage.getItem('vnaigc_jwt');
    try {
        const res = await fetch('/api/v1/cc/admin/lockouts/unlock', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ target_key: targetKey })
        });
        if (res.ok) {
            alert(`Đã mở khóa thành công cho: ${targetKey}`);
            await fetchAndRenderAdminLockoutsDesktop();
        } else {
            const err = await res.json().catch(() => ({}));
            alert(err.detail || 'Không thể mở khóa. Vui lòng kiểm tra lại quyền Admin.');
        }
    } catch (e) {
        alert('Lỗi kết nối máy chủ');
    }
}

window.openAdminLockoutsModalDesktop = openAdminLockoutsModalDesktop;
window.fetchAndRenderAdminLockoutsDesktop = fetchAndRenderAdminLockoutsDesktop;
window.handleAdminUnlockDesktop = handleAdminUnlockDesktop;


