import { useTranslation } from "react-i18next";

export function ErrorBlock({ message }: { message: string }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3">
      <p className="text-sm font-medium text-red-800">{t("common.error")}</p>
      <p className="mt-1 text-sm text-red-600">{message}</p>
    </div>
  );
}
