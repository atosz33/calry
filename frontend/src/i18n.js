import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en";
import hu from "./locales/hu";

const SUPPORTED_LANGUAGES = ["en", "hu"];
const LANGUAGE_STORAGE_KEY = "calry_language";

function resolveInitialLanguage() {
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (stored && SUPPORTED_LANGUAGES.includes(stored)) {
    return stored;
  }

  const browserLanguage = navigator.language?.toLowerCase() || "en";
  if (browserLanguage.startsWith("hu")) {
    return "hu";
  }

  return "en";
}

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    hu: { translation: hu },
  },
  lng: resolveInitialLanguage(),
  fallbackLng: "en",
  interpolation: {
    escapeValue: false,
  },
});

i18n.on("languageChanged", (language) => {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
});

export default i18n;
