import { useRouteFamily } from "@/hooks";
import { EmptyState, LoadingBlock } from "@/features/common";
import { RouteFamilyDetailPanel } from "@/features/common/RouteFamilyDetailPanel";

interface RouteFamilyInspectorCardProps {
  scenarioId: string;
  routeFamilyId: string;
  onClose?: () => void;
}

export function RouteFamilyInspectorCard({
  scenarioId,
  routeFamilyId,
  onClose,
}: RouteFamilyInspectorCardProps) {
  const { data, isLoading, error } = useRouteFamily(scenarioId, routeFamilyId);
  const detail = data?.item;

  if (isLoading) {
    return <LoadingBlock message="route family を読み込んでいます" />;
  }

  if (error || !detail) {
    return (
      <EmptyState
        title="route family 詳細を読み込めません"
        description={error?.message ?? "対象 family が見つかりません。"}
      />
    );
  }

  return (
    <RouteFamilyDetailPanel detail={detail} onClose={onClose} contextLabel="planning" />
  );
}
