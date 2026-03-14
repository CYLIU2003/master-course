import i18n from "i18next";
import { initReactI18next } from "react-i18next";

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

const loadedLanguages = new Set<string>();

const loadLanguage = async (lang: string) => {
  if (loadedLanguages.has(lang)) return;
  
  try {
    let module;
    switch (lang) {
      case "ja":
        module = await import("./locales/ja.json");
        break;
      case "zh":
        module = await import("./locales/zh.json");
        break;
      default:
        module = await import("./locales/en.json");
    }
    i18n.addResourceBundle(lang, "translation", module.default, true);
    loadedLanguages.add(lang);
  } catch (error) {
    console.error(`Failed to load language ${lang}:`, error);
  }
};

i18n.use(initReactI18next).init({
  resources: {},
  lng: initialLang,
  fallbackLng: "en",
  interpolation: {
    escapeValue: false,
  },
  ns: ["translation"],
  defaultNS: "translation",
});

loadLanguage(initialLang);

i18n.on("languageChanged", (lng) => {
  localStorage.setItem(STORAGE_KEY, lng);
  document.documentElement.lang = lng;
  loadLanguage(lng);
});

document.documentElement.lang = initialLang;

export default i18n;
