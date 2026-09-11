import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, put, type Row } from "../api";
import { vehicleFields } from "../entityFields";
import { ErrorBox } from "./common";

export default function VehicleBulkEditor({
  id,
  selected,
  depots,
  disabled,
  onSaved,
  onClear,
}: {
  id: string;
  selected: string[];
  depots: Row[];
  disabled: boolean;
  onSaved: () => void;
  onClear: () => void;
}) {
  const [field, setField] = useState("initialSoc");
  const [value, setValue] = useState("0.8");
  const [completed, setCompleted] = useState<string[]>([]);
  const mutation = useMutation({
    mutationFn: async () => {
      setCompleted([]);
      for (const vehicle of selected) {
        const path = `/scenarios/${id}/vehicles/${encodeURIComponent(vehicle)}`;
        const current = await api<Row>(path);
        if (field === "initialSoc" && current.type !== "BEV")
          throw new Error(
            `${vehicle} はBEVではありません。初期SOCを変更する対象から外してください。`,
          );
        const payload = Object.fromEntries(
          vehicleFields
            .filter((item) => current[item.key] !== undefined)
            .map((item) => [item.key, current[item.key]]),
        );
        payload[field] =
          field === "initialSoc"
            ? Number(value)
            : field === "enabled"
              ? value === "true"
              : value;
        await put(path, payload);
        setCompleted((previous) => [...previous, vehicle]);
      }
    },
    onSettled: onSaved,
    onSuccess: onClear,
  });
  return (
    <form
      className="panel bulk-editor"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate();
      }}
    >
      <h3>選択した {selected.length} 台をまとめて更新</h3>
      <p className="subtle">
        選択したIDだけを順番に更新します。途中で失敗した場合は更新済みIDを表示します。1回の上限は250台です。
      </p>
      <fieldset disabled={disabled || mutation.isPending}>
        <div className="form-grid">
          <label>
            変更する項目
            <select
              value={field}
              onChange={(event) => {
                setField(event.target.value);
                setValue(
                  event.target.value === "initialSoc"
                    ? "0.8"
                    : event.target.value === "enabled"
                      ? "true"
                      : String(depots[0]?.id ?? ""),
                );
              }}
            >
              <option value="initialSoc">BEVの初期SOC</option>
              <option value="enabled">使用可否</option>
              <option value="depotId">所属営業所</option>
            </select>
          </label>
          <label>
            変更後の値
            {field === "initialSoc" ? (
              <input
                required
                type="number"
                min={0}
                max={1}
                step="any"
                value={value}
                onChange={(event) => setValue(event.target.value)}
              />
            ) : (
              <select
                required
                value={value}
                onChange={(event) => setValue(event.target.value)}
              >
                {field === "enabled" ? (
                  <>
                    <option value="true">使用する</option>
                    <option value="false">使用しない</option>
                  </>
                ) : (
                  depots.map((depot) => (
                    <option key={String(depot.id)} value={String(depot.id)}>
                      {String(depot.name)}
                    </option>
                  ))
                )}
              </select>
            )}
          </label>
        </div>
        <div className="actions">
          <button
            className="primary"
            disabled={!selected.length || selected.length > 250}
          >
            選択車両に適用
          </button>
          <button type="button" onClick={onClear}>
            選択を解除
          </button>
        </div>
      </fieldset>
      <ErrorBox error={mutation.error} />
      {completed.length > 0 && (
        <details open={mutation.isError}>
          <summary>{completed.length} 台を更新済み</summary>
          <p>{completed.join(", ")}</p>
        </details>
      )}
    </form>
  );
}
