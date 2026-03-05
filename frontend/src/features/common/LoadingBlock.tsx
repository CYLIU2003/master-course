import { useTranslation } from "react-i18next";

export function LoadingBlock({ message }: { message?: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-center py-12">
      <div className="flex flex-col items-center gap-2 text-slate-400">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-primary-500" />
        <span className="text-sm">{message ?? t("common.loading")}</span>
      </div>
    </div>
  );
}
