import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import ja from "./locales/ja.json";
import zh from "./locales/zh.json";

export const SUPPORTED_LANGUAGES = [
  { code: "en", label: "EN" },
  { code: "ja", label: "日本語" },
  { code: "zh", label: "中文" },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]["code"];

const STORAGE_KEY = "ev-bus-lang";

const savedLang = localStorage.getItem(STORAGE_KEY);
const detectedLang =
  savedLang ?? navigator.language.split("-")[0] ?? "en";
const initialLang = ["en", "ja", "zh"].includes(detectedLang)
  ? detectedLang
  : "en";

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    ja: { translation: ja },
    zh: { translation: zh },
  },
  lng: initialLang,
  fallbackLng: "en",
  interpolation: {
    escapeValue: false,
  },
});

i18n.on("languageChanged", (lng) => {
  localStorage.setItem(STORAGE_KEY, lng);
  document.documentElement.lang = lng;
});

// Set initial lang attribute
document.documentElement.lang = initialLang;

export default i18n;
