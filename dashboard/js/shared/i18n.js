import en from '../locales/en.js';
import nl from '../locales/nl.js';
import fr from '../locales/fr.js';

const LOCALES = { en, nl, fr };
const VALID_LANGS = ['en', 'nl', 'fr'];
const STORAGE_KEY = 'ritaLanguage';

let _activeLang = 'en';

export function getLanguage() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return VALID_LANGS.includes(stored) ? stored : 'en';
  } catch {
    return 'en';
  }
}

export function t(key) {
  const dict = LOCALES[_activeLang] || LOCALES.en;
  if (key in dict) return dict[key];
  if (_activeLang !== 'en' && key in LOCALES.en) return LOCALES.en[key];
  return key;
}

export function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.querySelectorAll('.lang-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.lang === _activeLang);
  });
}

export function setLanguage(lang) {
  if (!VALID_LANGS.includes(lang)) return;
  _activeLang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // private browsing — in-memory only
  }
  applyTranslations();
}

export function initI18n() {
  _activeLang = getLanguage();
}
