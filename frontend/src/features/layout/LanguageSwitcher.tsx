import { useTranslation } from "react-i18next";
import { SUPPORTED_LANGUAGES, type LanguageCode } from "@/i18n";

export function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const current = i18n.language as LanguageCode;

  return (
    <div className="flex items-center gap-0.5 rounded-md border border-border bg-surface-raised p-0.5">
      {SUPPORTED_LANGUAGES.map((lang) => (
        <button
          key={lang.code}
          onClick={() => i18n.changeLanguage(lang.code)}
          className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
            current === lang.code
              ? "bg-primary-600 text-white"
              : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
          }`}
          aria-label={`Switch to ${lang.label}`}
        >
          {lang.label}
        </button>
      ))}
    </div>
  );
}
