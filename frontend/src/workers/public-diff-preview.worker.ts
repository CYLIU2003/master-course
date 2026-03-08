type PublicDiffItem = {
  id: string;
  entity_type: string;
  display_name: string;
  change_type: string;
  suggested_action: string;
  field_diff?: Record<string, unknown>;
};

export type PreparedPublicDiffItem = PublicDiffItem & {
  changedFieldCount: number;
  changedFieldPreview: string;
};

function scoreItem(item: PublicDiffItem): number {
  const actionScore =
    item.suggested_action === "conflict"
      ? 0
      : item.change_type === "new"
        ? 1
        : item.change_type === "changed"
          ? 2
          : 3;
  return actionScore;
}

function prepare(items: PublicDiffItem[]): PreparedPublicDiffItem[] {
  return [...items]
    .map((item) => {
      const fields = Object.keys(item.field_diff ?? {});
      return {
        ...item,
        changedFieldCount: fields.length,
        changedFieldPreview: fields.slice(0, 3).join(", "),
      };
    })
    .sort((left, right) => {
      const scoreCmp = scoreItem(left) - scoreItem(right);
      if (scoreCmp !== 0) {
        return scoreCmp;
      }
      const typeCmp = left.entity_type.localeCompare(right.entity_type, "ja");
      if (typeCmp !== 0) {
        return typeCmp;
      }
      return left.display_name.localeCompare(right.display_name, "ja");
    });
}

self.onmessage = (
  event: MessageEvent<{ requestId: string; items: PublicDiffItem[] }>,
) => {
  self.postMessage({
    requestId: event.data.requestId,
    items: prepare(event.data.items),
  });
};
