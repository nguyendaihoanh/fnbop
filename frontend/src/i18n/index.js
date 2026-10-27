// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Nguyen Dai Hoanh (VNAIGC) <hoanh@vnaigc.com>
// Additional terms under AGPL-3.0 Section 7 apply; see NOTICE.
// ==========================================================================
// WFM PAYROLL & OPS — CORE I18N ENGINE V4.0 (MODULAR PER-LANGUAGE DESIGN)
// ==========================================================================
// Architecture:
//   src/i18n/index.js             -> Pure Language-Agnostic Runtime & DOM Engine
//   src/i18n/locales/<lang>/      -> 100% Self-Contained Language Packages:
//     ├── meta.js                 -> Language metadata (code, native, flag, bcp47)
//     ├── common.js               -> Navigation, Topbar, Auth, Common UI
//     ├── ops.js                  -> Tab 1: Operations, KPIs, OT, Performance
//     ├── roster.js               -> Tab 2: Roster Matrix, Availability, Quotas
//     ├── attendance.js           -> Tab 3: Clock-in/out, WiFi/4G, SOP Checklist
//     ├── payslip.js              -> Tab 4: Payroll Summary, Payslip Receipt, QR
//     ├── admin.js                -> Admin Modals, Staff Accounts, IP Lockout
//     ├── patterns.js             -> Domain Tokens & Dynamic Regex Templates
//     ├── domMap.js               -> Full Exact DOM Phrase Dictionary
//     └── index.js                -> Barrel export for the language folder
// ==========================================================================

import * as viPkg from './locales/vi/index.js';
import { META as viMeta } from './locales/vi/meta.js';
import { META as enMeta } from './locales/en/meta.js';
import { META as thMeta } from './locales/th/meta.js';
import { META as zhMeta } from './locales/zh/meta.js';
import { META as ruMeta } from './locales/ru/meta.js';

export const SUPPORTED_LANGUAGES = [viMeta, enMeta, thMeta, zhMeta, ruMeta];

export const LOCALE_PACKAGES = {
  vi: viPkg
};

export const LOCALE_LOADERS = {
  vi: () => Promise.resolve(viPkg),
  en: () => import('./locales/en/index.js'),
  th: () => import('./locales/th/index.js'),
  zh: () => import('./locales/zh/index.js'),
  ru: () => import('./locales/ru/index.js')
};

const loadingPromises = {};

export async function ensureLocaleLoaded(langCode) {
  if (LOCALE_PACKAGES[langCode]) {
    return LOCALE_PACKAGES[langCode];
  }
  const loader = LOCALE_LOADERS[langCode];
  if (!loader) {
    console.warn(`[i18n] No loader found for locale: ${langCode}, falling back to vi`);
    return LOCALE_PACKAGES.vi;
  }
  if (!loadingPromises[langCode]) {
    loadingPromises[langCode] = loader().then(mod => {
      LOCALE_PACKAGES[langCode] = mod;
      delete loadingPromises[langCode];
      return mod;
    }).catch(err => {
      delete loadingPromises[langCode];
      console.error(`[i18n] Failed to load locale package for ${langCode}:`, err);
      return LOCALE_PACKAGES.vi;
    });
  }
  return loadingPromises[langCode];
}

const STORAGE_KEY = 'wfm_lang';
const LEGACY_STORAGE_KEY = 'fnbops_lang';
const VNAIGC_STORAGE_KEY = 'vnaigc_lang';

let currentLang = 'vi';
const listeners = new Set();

// WeakMaps preserve original Vietnamese source text & attributes on every DOM node
const originalNodeTextMap = new WeakMap();
const lastTranslatedTextMap = new WeakMap();
const originalAttrMap = new WeakMap();
let domObserver = null;
let isApplyingDOM = false;

export function getLanguage() {
  if (typeof localStorage !== 'undefined') {
    const saved = localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY);
    if (saved && (LOCALE_PACKAGES[saved] || LOCALE_LOADERS[saved])) {
      currentLang = saved;
    }
  }
  return currentLang;
}

export function t(key, paramsOrFallback = null, maybeParams = null) {
  const lang = getLanguage();
  const pkg = LOCALE_PACKAGES[lang] || LOCALE_PACKAGES.vi;
  const fallbackPkg = LOCALE_PACKAGES.vi;

  let actualFallback = null;
  let actualParams = null;

  if (typeof paramsOrFallback === 'string') {
    actualFallback = paramsOrFallback;
    actualParams = maybeParams;
  } else if (paramsOrFallback && typeof paramsOrFallback === 'object') {
    actualParams = paramsOrFallback;
  }

  let str = pkg.dictionary[key];
  if (str === undefined) {
    str = fallbackPkg.dictionary[key];
  }
  if (str === undefined && pkg.EXACT_PHRASE_MAP && pkg.EXACT_PHRASE_MAP[key]) {
    str = pkg.EXACT_PHRASE_MAP[key];
  }
  if (str === undefined) {
    str = (typeof actualFallback === 'string' && actualFallback.length > 0) ? actualFallback : key;
  }

  if (actualParams && typeof actualParams === 'object') {
    Object.keys(actualParams).forEach(k => {
      str = String(str).replace(new RegExp(`\\{${k}\\}`, 'g'), actualParams[k]);
    });
  }

  return str;
}

export function onLanguageChanged(callback) {
  if (typeof callback === 'function') {
    listeners.add(callback);
  }
  return () => {
    listeners.delete(callback);
  };
}

/**
 * Translates any static or dynamic Vietnamese string into the target language
 * using that language folder's own EXACT_PHRASE_MAP and PATTERNS.
 */
export function translateDynamicString(rawVi, lang = getLanguage()) {
  if (!rawVi || lang === 'vi') return rawVi;
  const trimmed = rawVi.trim();
  if (!trimmed) return rawVi;

  const pkg = LOCALE_PACKAGES[lang];
  if (!pkg) return rawVi;

  const exactDict = pkg.EXACT_PHRASE_MAP;
  if (exactDict && exactDict[trimmed]) {
    return rawVi.replace(trimmed, exactDict[trimmed]);
  }

  const norm = trimmed.replace(/\s+/g, ' ');
  if (exactDict && exactDict[norm]) {
    return exactDict[norm];
  }

  const patterns = pkg.PATTERNS || [];
  for (const rule of patterns) {
    const match = norm.match(rule.re);
    if (match) {
      if (typeof rule.fn === 'function') {
        return rule.fn(match, norm);
      }
      if (typeof rule.replace === 'string') {
        return norm.replace(rule.re, rule.replace);
      }
    }
  }

  return rawVi;
}

/**
 * Deeply traverses a DOM subtree, translating [data-i18n], [placeholder], [title],
 * and all Text nodes while preserving the original Vietnamese text in a WeakMap
 * for lossless switching across all 5 languages (VI / EN / TH / ZH / RU).
 */
export function translateDOMSubtree(root = document.body) {
  if (typeof document === 'undefined' || !root || isApplyingDOM) return;
  isApplyingDOM = true;

  try {
    const lang = getLanguage();

    // 1. Standard [data-i18n] elements
    const i18nEls = root.querySelectorAll ? root.querySelectorAll('[data-i18n]') : [];
    i18nEls.forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (key) {
        const trans = t(key);
        if (trans && trans !== key) {
          if (el.tagName === 'INPUT' && (el.type === 'button' || el.type === 'submit')) {
            el.value = trans;
          } else {
            el.textContent = trans;
          }
        }
      }
    });

    // 2. Placeholders & Titles
    const attrEls = root.querySelectorAll ? root.querySelectorAll('[placeholder], [title], [data-i18n-ph], [data-i18n-title]') : [];
    attrEls.forEach(el => {
      let savedAttrs = originalAttrMap.get(el);
      if (!savedAttrs) {
        savedAttrs = {
          placeholder: el.getAttribute('placeholder') || '',
          title: el.getAttribute('title') || ''
        };
        originalAttrMap.set(el, savedAttrs);
      }

      const phKey = el.getAttribute('data-i18n-ph');
      if (phKey) {
        const tr = t(phKey);
        if (tr && tr !== phKey) el.setAttribute('placeholder', tr);
      } else if (savedAttrs.placeholder) {
        el.setAttribute('placeholder', lang === 'vi' ? savedAttrs.placeholder : translateDynamicString(savedAttrs.placeholder, lang));
      }

      const titleKey = el.getAttribute('data-i18n-title');
      if (titleKey) {
        const tr = t(titleKey);
        if (tr && tr !== titleKey) el.setAttribute('title', tr);
      } else if (savedAttrs.title) {
        el.setAttribute('title', lang === 'vi' ? savedAttrs.title : translateDynamicString(savedAttrs.title, lang));
      }
    });

    // 3. Walk all Text nodes
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent) continue;
      const tag = parent.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') continue;
      if (parent.closest && parent.closest('#langPickerList')) continue;

      const currentVal = node.nodeValue;
      if (!currentVal || !currentVal.trim()) continue;

      let origVi = originalNodeTextMap.get(node);
      const lastTrans = lastTranslatedTextMap.get(node);

      if (origVi === undefined || (lastTrans !== undefined && currentVal !== lastTrans)) {
        origVi = currentVal;
        originalNodeTextMap.set(node, origVi);
      }

      const nextVal = lang === 'vi' ? origVi : translateDynamicString(origVi, lang);
      if (nextVal !== currentVal) {
        node.nodeValue = nextVal;
      }
      lastTranslatedTextMap.set(node, nextVal);
    }
  } finally {
    isApplyingDOM = false;
  }
}

export function applyTranslationsToDOM() {
  if (typeof document === 'undefined') return;
  const lang = getLanguage();

  const brandTitle = document.getElementById('topbarBrandTitle') || document.getElementById('brandTitle');
  if (brandTitle) {
    const sName = (typeof window !== 'undefined' && window.currentStoreConfig && window.currentStoreConfig.store_name) ||
                  (typeof localStorage !== 'undefined' && localStorage.getItem('vnaigc_store_name')) ||
                  '';
    const role = (typeof localStorage !== 'undefined') ? localStorage.getItem('vnaigc_role') : null;
    const name = (typeof localStorage !== 'undefined') ? localStorage.getItem('vnaigc_name') : null;
    if (role === 'STAFF' && name) {
      const firstName = name.trim().split(' ').pop();
      const prefix = sName || 'WFM';
      const rawGreet = firstName ? `${prefix} • Chào ${firstName}` : `${prefix} Chấm Công`;
      brandTitle.textContent = translateDynamicString(rawGreet, lang);
    } else {
      brandTitle.textContent = sName || t('brand.title', {}, 'WFM Vận Hành');
    }
    brandTitle.title = brandTitle.textContent;
  }

  const evalText = document.querySelector('#btnOpenEval .eval-text');
  if (evalText) evalText.textContent = t('topbar.report');

  if (document.body) {
    translateDOMSubtree(document.body);
  }
}

export function updateLanguageSheetUI(langCode) {
  if (typeof document === 'undefined') return;

  const meta = SUPPORTED_LANGUAGES.find(m => m.code === langCode) || viMeta;
  const lbl = document.getElementById('langCurrentLabel') || document.getElementById('langCurrentBadge');
  if (lbl && meta) {
    lbl.textContent = `${meta.flag} ${meta.native}`;
  }

  document.querySelectorAll('.lang-select-item, .lang-picker-item').forEach(item => {
    const code = item.getAttribute('data-lang-code') || item.getAttribute('data-lang');
    item.classList.toggle('active', code === langCode);
  });
}

export async function setLanguage(langCode) {
  if (!LOCALE_LOADERS[langCode]) {
    console.warn(`[i18n] Unsupported language code: ${langCode}`);
    return false;
  }
  await ensureLocaleLoaded(langCode);
  currentLang = langCode;
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, langCode);
    localStorage.setItem(LEGACY_STORAGE_KEY, langCode);
  }
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.setAttribute('lang', langCode);
  }

  applyTranslationsToDOM();
  updateLanguageSheetUI(langCode);

  listeners.forEach(cb => {
    try {
      cb(langCode);
    } catch (err) {
      console.error('[i18n] Listener error:', err);
    }
  });

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('wfm:languageChanged', { detail: { lang: langCode } }));
    window.dispatchEvent(new CustomEvent('fnbop:languageChanged', { detail: { lang: langCode } }));
  }
  return true;
}

function startReactiveDOMObserver() {
  if (typeof document === 'undefined' || !document.body || domObserver) return;

  let rafPending = false;
  domObserver = new MutationObserver(() => {
    if (isApplyingDOM || rafPending) return;
    rafPending = true;
    requestAnimationFrame(() => {
      rafPending = false;
      if (getLanguage() !== 'vi' && document.body) {
        translateDOMSubtree(document.body);
      }
    });
  });

  domObserver.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true
  });
}

export function initI18n() {
  const lang = getLanguage();
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.setAttribute('lang', lang);
  }
  if (lang !== 'vi' && LOCALE_LOADERS[lang] && !LOCALE_PACKAGES[lang]) {
    ensureLocaleLoaded(lang).then(() => {
      applyTranslationsToDOM();
      updateLanguageSheetUI(lang);
    });
  } else {
    applyTranslationsToDOM();
    updateLanguageSheetUI(lang);
  }
  startReactiveDOMObserver();
  return lang;
}

if (typeof window !== 'undefined') {
  window.t = t;
  window.setLanguage = setLanguage;
  window.getLanguage = getLanguage;
  window.initI18n = initI18n;
  window.ensureLocaleLoaded = ensureLocaleLoaded;
  window.applyTranslationsToDOM = applyTranslationsToDOM;
  window.translateDOMSubtree = translateDOMSubtree;
  window.translateDynamicString = translateDynamicString;
  window.SUPPORTED_LANGUAGES = SUPPORTED_LANGUAGES;
  window.LOCALE_PACKAGES = LOCALE_PACKAGES;
  window.LOCALE_LOADERS = LOCALE_LOADERS;
}
