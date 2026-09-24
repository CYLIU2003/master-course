import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Copy, Plus, Save, Trash2, X } from "lucide-react";
import { api, post, put, remove, type Page, type Row } from "../api";
import { depotFields, routeFields, vehicleFields } from "../entityFields";
import { FieldGrid } from "./Fields";
import { ErrorBox } from "./common";
import type { EditorProps } from "./SettingsPanel";
import DataTable from "./DataTable";
import VehicleBulkEditor from "./VehicleBulkEditor";
import RouteBrowser from "./RouteBrowser";

export default function EntityManager({
  id,
  onSaved,
  onDirty,
  kind = "vehicles",
}: EditorProps & { kind?: "vehicles" | "depots" | "routes" }) {
  const [selected, setSelected] = useState<string[]>([]);
  const editor = useRef<HTMLFormElement>(null);
  const [templates, setTemplates] = useState(false);
  const [editing, setEditing] = useState<Row | null>(null);
  const [changed, setChanged] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [deleting, setDeleting] = useState(false);
  const [routeSource, setRouteSource] = useState<"odpt" | "full" | "scenario">("odpt");
  const [routeError, setRouteError] = useState<Error | null>(null);
  useEffect(() => {
    if (editing)
      editor.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [editing?.id, Boolean(editing)]);
  const collection = templates ? "vehicle_templates" : kind;
  const endpoint = templates ? "vehicle-templates" : kind;
  const depots = useQuery({
    queryKey: ["table", id, "depot-options"],
    queryFn: () =>
      api<Page<Row>>(`/desktop/scenarios/${id}/tables/depots?limit=250`),
  });
  const templateData = useQuery({
    queryKey: ["table", id, "template-options"],
    enabled: kind === "vehicles",
    queryFn: () =>
      api<Page<Row>>(
        `/desktop/scenarios/${id}/tables/vehicle_templates?limit=250`,
      ),
  });
  useEffect(() => {
    onDirty(changed);
  }, [changed, onDirty]);
  const fields = (
    kind === "depots"
      ? depotFields
      : kind === "routes"
        ? routeFields
        : templates
          ? [
              { key: "name", label: "テンプレート名", required: true },
              ...vehicleFields.filter(
                (field) => !["depotId", "initialSoc"].includes(field.key),
              ),
            ]
          : vehicleFields
  ).map((field) =>
    field.key === "depotId"
      ? {
          ...field,
          options: (depots.data?.items ?? []).map(
            (row) => [String(row.id), String(row.name ?? row.id)] as const,
          ),
        }
      : field,
  );
  const path = `/scenarios/${id}/${endpoint}`;
  const mutation = useMutation({
    mutationFn: async (action: "save" | "delete" | "duplicate") => {
      if (!editing) return;
      const existing = editing.id
        ? `${path}/${encodeURIComponent(String(editing.id))}`
        : "";
      if (action === "delete") return remove(existing);
      if (action === "duplicate")
        return post(`${existing}/duplicate-bulk`, {
          quantity,
          targetDepotId: editing.depotId,
        });
      const payload = Object.fromEntries(
        fields
          .filter((field) => editing[field.key] !== undefined)
          .map((field) => [field.key, editing[field.key]]),
      );
      return existing
        ? put(existing, payload)
        : post(path + (kind === "vehicles" && !templates ? "/bulk" : ""), {
            ...payload,
            ...(kind === "vehicles" && !templates ? { quantity } : {}),
          });
    },
    onSuccess: () => {
      setEditing(null);
      setChanged(false);
      setDeleting(false);
      onSaved();
    },
  });
  function open(row: Row) {
    setEditing({ ...row });
    setQuantity(1);
    setChanged(!row.id);
    setDeleting(false);
    mutation.reset();
  }
  return (
    <>
      <div className="section-title">
        <div>
          <h2>
            {kind === "vehicles"
              ? "車両とテンプレート"
              : kind === "depots"
                ? "営業所・充電設備"
                : "路線と運行パターン"}
          </h2>
          <p className="subtle">
            {kind === "routes" ? "営業所・系統から運行パターンを確認し、シナリオ内の路線を編集できます。" : "一覧から対象を選び、必要な項目を編集できます。"}
          </p>
        </div>
        <button
          disabled={changed}
          onClick={() => {
            if (kind === "routes") setRouteSource("scenario");
            open({
              ...(kind === "vehicles"
                ? {
                    type: "BEV",
                    enabled: true,
                    depotId: String(depots.data?.items[0]?.id ?? ""),
                  }
                : { enabled: true }),
            });
          }}
        >
          <Plus size={16} />
          {kind === "routes" ? "シナリオへ追加" : "追加"}
        </button>
      </div>
      {kind === "vehicles" && (
        <div className="segmented">
          {[false, true].map((value) => (
            <button
              disabled={changed}
              key={String(value)}
              className={templates === value ? "active" : ""}
              onClick={() => {
                setTemplates(value);
                setEditing(null);
              }}
            >
              {value ? "車両テンプレート" : "保有車両"}
            </button>
          ))}
        </div>
      )}
      {kind === "routes" && <div className="segmented">
        <button type="button" disabled={changed} className={routeSource === "odpt" ? "active" : ""} onClick={() => setRouteSource("odpt")}>ODPT全域</button>
        <button type="button" disabled={changed} className={routeSource === "full" ? "active" : ""} onClick={() => setRouteSource("full")}>GTFS参考</button>
        <button type="button" disabled={changed} className={routeSource === "scenario" ? "active" : ""} onClick={() => setRouteSource("scenario")}>このシナリオの路線・編集</button>
      </div>}
      {kind === "routes" && <ErrorBox error={routeError} />}
      {kind === "routes" ? <RouteBrowser id={id} source={routeSource} onEdit={routeSource === "scenario" ? async (routeId) => {
        if (changed) return;
        try {
          setRouteError(null);
          const row = await api<Row>(`/scenarios/${id}/routes/${encodeURIComponent(routeId)}`);
          open(row);
        } catch (error) {
          setRouteError(error instanceof Error ? error : new Error(String(error)));
        }
      } : undefined} /> : <DataTable
        key={collection}
        id={id}
        fixed={collection}
        selected={kind === "vehicles" && !templates ? selected : undefined}
        onSelection={
          kind === "vehicles" && !templates ? setSelected : undefined
        }
        onEdit={(row) => {
          if (!changed) open(row);
        }}
      />}
      {kind === "vehicles" && !templates && selected.length > 0 && (
        <VehicleBulkEditor
          id={id}
          selected={selected}
          depots={depots.data?.items ?? []}
          disabled={changed}
          onSaved={onSaved}
          onClear={() => setSelected([])}
        />
      )}
      {editing && (
        <form
          ref={editor}
          className="panel editor-panel"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate("save");
          }}
        >
          <div className="section-title">
            <h2>
              {editing.id ? `編集 · ${String(editing.id)}` : "新しく追加"}
            </h2>
            <button
              type="button"
              aria-label="編集を閉じる"
              onClick={() => {
                setEditing(null);
                setChanged(false);
              }}
            >
              <X size={16} />
              {changed ? "変更を破棄" : "閉じる"}
            </button>
          </div>
          <fieldset disabled={mutation.isPending}>
            {kind === "vehicles" && !templates && !editing.id && (
              <label>
                テンプレートから入力
                <select
                  defaultValue=""
                  onChange={(e) => {
                    const template = templateData.data?.items.find(
                      (row) => row.id === e.target.value,
                    );
                    if (template) {
                      const { id: _id, name: _name, ...values } = template;
                      setEditing({ ...editing, ...values });
                      setChanged(true);
                    }
                  }}
                >
                  <option value="">手動で入力する</option>
                  {templateData.data?.items.map((row) => (
                    <option key={String(row.id)} value={String(row.id)}>
                      {String(row.name)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <FieldGrid
              fields={fields}
              value={editing}
              onChange={(key, value) => {
                setEditing({ ...editing, [key]: value });
                setChanged(true);
              }}
            />
            {kind === "vehicles" && !templates && (
              <label className="quantity">
                {editing.id ? "複製する台数" : "作成する台数"}
                <input
                  type="number"
                  min={1}
                  max={1000}
                  step={1}
                  value={quantity}
                  onChange={(e) => setQuantity(Number(e.target.value))}
                />
              </label>
            )}
            <div className="actions">
              <button className="primary">
                <Save size={16} />
                {editing.id ? "保存" : "作成"}
              </button>
              {!!editing.id && (
                <>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => setDeleting(true)}
                  >
                    <Trash2 size={16} />
                    削除
                  </button>
                  {kind === "vehicles" && !templates && (
                    <button
                      type="button"
                      disabled={
                        changed || quantity < 1 || !Number.isInteger(quantity)
                      }
                      onClick={() => mutation.mutate("duplicate")}
                    >
                      <Copy size={16} />
                      この車両を複製
                    </button>
                  )}
                </>
              )}
            </div>
            {deleting && (
              <div className="warning">
                この項目を削除します。参照している入力は再確認が必要です。
                <div className="actions">
                  <button
                    type="button"
                    className="danger"
                    onClick={() => mutation.mutate("delete")}
                  >
                    削除を確定
                  </button>
                  <button type="button" onClick={() => setDeleting(false)}>
                    キャンセル
                  </button>
                </div>
              </div>
            )}
          </fieldset>
          <ErrorBox error={mutation.error} />
        </form>
      )}
    </>
  );
}
