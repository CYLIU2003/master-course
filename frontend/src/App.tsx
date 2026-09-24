import { useEffect, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  useIsFetching,
} from "@tanstack/react-query";
import {
  Activity,
  ArrowLeftRight,
  BatteryCharging,
  BusFront,
  CalendarDays,
  ChevronDown,
  CloudSun,
  Database,
  Gauge,
  Home,
  Layers3,
  Map,
  Plus,
  Search,
  Settings2,
  X,
} from "lucide-react";
import { api, post, put, type Page, type Scenario } from "./api";
import { ErrorBox, Pager } from "./components/common";
import Workspace from "./components/Workspace";
import ClusterPanel from "./components/ClusterPanel";
const routeGroups = [
  ["all", "すべて"],
  ["shibu24", "渋24"],
  ["shibu21_24", "渋21〜24"],
  ["shibu21_23", "渋21〜23"],
  ["other", "未分類・その他"],
] as const;
type RouteGroup = (typeof routeGroups)[number][0];
const pages = [
  ["overview", "概要と検証", Home],
  ["settings", "運行・計算設定", Settings2],
  ["fleet", "車両", BusFront],
  ["depots", "営業所・充電設備", Layers3],
  ["routes", "路線・運行パターン", Map],
  ["energy", "PV・BESS設備", BatteryCharging],
  ["weather", "気象・PVデータ", CloudSun],
  ["data", "データを確認", Database],
  ["periods", "期間別計画", CalendarDays],
  ["run", "実行", Activity],
  ["cluster", "分散計算", Layers3],
  ["results", "グラフ・費用明細", Gauge],
  ["compare", "シナリオ比較", ArrowLeftRight],
] as const;
export default function App() {
  const fetching = useIsFetching();
  useEffect(() => {
    document.body.dataset.fetching = String(fetching);
  }, [fetching]);
  const [selected, setSelected] = useState(
    localStorage.getItem("ev-scenario") ?? "",
  );
  const [page, setPage] = useState(() =>
    window.location.hash === "#cluster" ? "cluster" : "overview",
  );
  const [picker, setPicker] = useState(!selected);
  const [dirty, setDirty] = useState(false);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [routeGroup, setRouteGroup] = useState<RouteGroup>("all");
  const [periodKind, setPeriodKind] = useState<"reusable" | "dated_history">("reusable");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [dataset, setDataset] = useState("");
  const [seed, setSeed] = useState(42);
  const [creating, setCreating] = useState(false);
  const [editingScenario, setEditingScenario] = useState<Scenario | null>(null);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const client = useQueryClient();
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const list = useQuery({
    queryKey: ["scenarios", query, offset, routeGroup, periodKind],
    queryFn: ({ signal }) =>
      api<Page<Scenario>>(
        `/desktop/scenarios?q=${encodeURIComponent(query)}&offset=${offset}&limit=50&route_group=${routeGroup}&period_kind=${periodKind}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });
  useEffect(() => {
    document.body.dataset.ready = String(list.isSuccess);
  }, [list.isSuccess]);
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
  function select(id: string) {
    setSelected(id);
    localStorage.setItem("ev-scenario", id);
    setPicker(!id);
    setDirty(false);
    setPage("overview");
  }
  const create = useMutation({
    mutationFn: () =>
      post<Scenario>("/scenarios", {
        name: name.trim(),
        description: description.trim(),
        randomSeed: seed,
        ...(dataset.trim() ? { datasetId: dataset.trim() } : {}),
      }),
    onSuccess: (row) => {
      void client.invalidateQueries({ queryKey: ["scenarios"] });
      select(row.id);
      setCreating(false);
      setName("");
      setDescription("");
    },
  });
  const manage = useMutation({
    mutationFn: ({ action, scenario }: { action: "save" | "duplicate"; scenario: Scenario }) =>
      action === "duplicate"
        ? post<Scenario>(`/scenarios/${scenario.id}/duplicate`, {})
        : put<Scenario>(`/scenarios/${scenario.id}`, {
            name: editName.trim(), description: editDescription.trim(),
          }),
    onSuccess: (row, variables) => {
      void client.invalidateQueries({ queryKey: ["scenarios"] });
      if (variables.action === "duplicate") select(row.id);
      else {
        setEditingScenario(null);
        void client.invalidateQueries({ queryKey: ["overview", row.id] });
      }
    },
  });
  const title = pages.find(([key]) => key === page)?.[1] ?? "";
  return (
    <div className="app">
      <aside className="main-sidebar">
        <div className="brand">
          <div className="brand-icon">
            <BusFront size={23} />
          </div>
          <div>
            EV BUS<span>RESEARCH WORKSPACE</span>
          </div>
        </div>
        <button
          className="scenario-switch"
          aria-label="シナリオを切り替える"
          title="シナリオを切り替える"
          disabled={dirty}
          onClick={() => setPicker(true)}
        >
          <Layers3 size={18} />
          <span>シナリオを切り替える</span>
          <ChevronDown size={15} />
        </button>
        <div className="sidebar-label">計画と検証</div>
        <nav className="workspace-nav">
          {pages.map(([key, label, Icon]) => (
            <button
              key={key}
              aria-label={label}
              title={label}
              disabled={!selected && key !== "cluster"}
              className={
                page === key && (selected || key === "cluster") ? "active" : ""
              }
              aria-current={
                page === key && (selected || key === "cluster")
                  ? "page"
                  : undefined
              }
              onClick={() => {
                setPage(key);
                if (key === "cluster") window.location.hash = "cluster";
                else if (window.location.hash === "#cluster") {
                  window.history.replaceState(
                    null,
                    "",
                    window.location.pathname,
                  );
                }
              }}
            >
              <Icon size={18} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="dot" /> ローカル研究環境
          <br />
          <small>入力の準備 → 実行 → 結果の確認</small>
        </div>
      </aside>
      <main>
        <header>
          <span>
            研究ワークスペース{" "}
            <span className="crumb">
              / {selected || page === "cluster" ? title : "シナリオ"}
            </span>
          </span>
          <span className="local-tag">LOCAL</span>
        </header>
        {!selected && page === "cluster" ? (
          <div className="workspace">
            <ClusterPanel />
          </div>
        ) : selected ? (
          <Workspace
            key={selected}
            id={selected}
            page={page}
            onSelect={select}
            onDirty={setDirty}
          />
        ) : (
          <section className="welcome">
            <span className="eyebrow">DISPATCH · CHARGING · ENERGY</span>
            <h1>
              運行とエネルギーを、
              <br />
              ひとつの視点で。
            </h1>
            <p>シナリオを選び、運行計画から結果の比較まで進めましょう。</p>
            <button
              className="primary"
              onClick={() => {
                setPicker(true);
                setCreating(true);
              }}
            >
              <Plus size={17} />
              シナリオを作成
            </button>
            <div className="welcome-cards">
              {[
                [
                  CalendarDays,
                  "条件を整える",
                  "対象路線・日付・車両・電力設備を設定。",
                ],
                [
                  Activity,
                  "計算の状態が見える",
                  "入力の検査と計算の進み具合を確認。",
                ],
                [
                  ArrowLeftRight,
                  "結果を比べる",
                  "費用・残量・検証結果を出典と一緒に比較。",
                ],
              ].map(([Icon, label, detail], i) => {
                const Symbol = Icon as typeof Activity;
                return (
                  <article key={i}>
                    <Symbol />
                    <h3>{String(label)}</h3>
                    <p>{String(detail)}</p>
                  </article>
                );
              })}
            </div>
          </section>
        )}
      </main>
      {picker && (
        <div className="drawer-backdrop">
          <section
            className="scenario-picker"
            role="dialog"
            aria-modal="true"
            aria-label="シナリオを選ぶ"
          >
            <div className="section-title">
              <div>
                <span className="eyebrow">YOUR SCENARIOS</span>
                <h2>どの計画から始めますか</h2>
              </div>
              <button
                aria-label="シナリオ選択を閉じる"
                onClick={() => setPicker(false)}
              >
                <X size={19} />
              </button>
            </div>
            <div className="table-toolbar">
              <label className="search">
                <Search size={16} />
                <input
                  autoFocus
                  placeholder="名前で検索"
                  aria-label="シナリオ検索"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
              <button onClick={() => setCreating(!creating)}>
                <Plus size={16} />
                新しく作成
              </button>
            </div>
            {creating && (
              <form
                className="create-form panel"
                onSubmit={(e) => {
                  e.preventDefault();
                  create.mutate();
                }}
              >
                <div className="form-grid">
                  <label>
                    シナリオ名
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      required
                      maxLength={160}
                    />
                  </label>
                  <label>
                    説明
                    <input value={description} onChange={(e) => setDescription(e.target.value)}
                      placeholder="比較条件や用途を記録" />
                  </label>
                  <label>
                    データセットID
                    <input
                      value={dataset}
                      onChange={(e) => setDataset(e.target.value)}
                      placeholder="空欄は既定データセット"
                    />
                  </label>
                  <label>
                    乱数seed
                    <input
                      type="number"
                      step={1}
                      value={seed}
                      onChange={(e) => setSeed(Number(e.target.value))}
                    />
                  </label>
                </div>
                <button
                  className="primary"
                  disabled={create.isPending || !name.trim()}
                >
                  作成
                </button>
                <ErrorBox error={create.error} />
              </form>
            )}
            <ErrorBox error={list.error} />
            <ErrorBox error={manage.error} />
            <div className="segmented" role="group" aria-label="シナリオの表示">
              <button type="button" className={periodKind === "reusable" ? "active" : ""}
                onClick={() => { setPeriodKind("reusable"); setOffset(0); }}>
                再利用するシナリオ
              </button>
              <button type="button" className={periodKind === "dated_history" ? "active" : ""}
                onClick={() => { setPeriodKind("dated_history"); setOffset(0); }}>
                旧月別・日付別ファイル
              </button>
            </div>
            <p className="subtle">月別の旧ファイルは履歴として保持します。新しい期間は同じシナリオの「期間別計画」へ追加します。</p>
            <p className="subtle">ここで新規作成・複製・名前変更ができます。削除はシナリオを開いて「管理」から確認します。</p>
            <div className="scenario-group-filter">
              <label htmlFor="scenario-route-group">路線で分類</label>
              <select
                id="scenario-route-group"
                aria-label="路線別に絞り込む"
                value={routeGroup}
                onChange={(event) => {
                  setRouteGroup(event.target.value as RouteGroup);
                  setOffset(0);
                }}
              >
                {routeGroups.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <small>
                保存名による表示分類です。計算対象の路線は入力準備で確認します。
              </small>
            </div>
            {!!list.data?.warnings?.length && (
              <details className="warning">
                <summary>読み込めないシナリオがあります</summary>
                {list.data.warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </details>
            )}
            <div className="scenario-list">
              {list.isPending && <p>読み込み中…</p>}
              {routeGroups.slice(1).map(([group, label]) => {
                const rows = (list.data?.items ?? []).filter(
                  (row) => (row.routeGroup ?? "other") === group,
                );
                if (!rows.length) return null;
                return (
                  <section key={group} className="scenario-group">
                    <h3>
                      {label} <small>{rows.length}件（このページ）</small>
                    </h3>
                    {rows.map((row) => (
                      <div key={row.id} className="scenario-card">
                        <button className={"scenario " + (selected === row.id ? "selected" : "")}
                          disabled={list.isPlaceholderData || manage.isPending}
                          onClick={() => select(row.id)}>
                          <div className="scenario-symbol"><Layers3 size={20} /></div>
                          <span>{row.name}
                            <small>識別ID: {row.id.slice(0, 8)}</small>
                            <small>{row.description || "運行・充電・エネルギー計画"}</small>
                          </span>
                          <small>{row.updatedAt?.slice(0, 10)}<br />{row.status}</small>
                        </button>
                        <div className="scenario-card-actions">
                          <button type="button" disabled={manage.isPending || list.isPlaceholderData}
                            onClick={() => manage.mutate({ action: "duplicate", scenario: row })}>複製して新規作成</button>
                          <button type="button" disabled={manage.isPending || list.isPlaceholderData}
                            onClick={() => {
                              setEditingScenario(row);
                              setEditName(row.name);
                              setEditDescription(row.description ?? "");
                            }}>名前・説明を編集</button>
                        </div>
                        {editingScenario?.id === row.id && <form className="scenario-card-edit"
                          onSubmit={(event) => { event.preventDefault(); manage.mutate({ action: "save", scenario: row }); }}>
                          <label>シナリオ名<input required maxLength={160} value={editName}
                            onChange={(event) => setEditName(event.target.value)} /></label>
                          <label>説明<input value={editDescription}
                            onChange={(event) => setEditDescription(event.target.value)} /></label>
                          <button type="submit" className="primary" disabled={manage.isPending || !editName.trim()}>保存</button>
                          <button type="button" onClick={() => setEditingScenario(null)}>取り消す</button>
                        </form>}
                      </div>
                    ))}
                  </section>
                );
              })}
            </div>
            <Pager
              offset={offset}
              total={list.data?.total ?? 0}
              size={50}
              set={setOffset}
            />
          </section>
        </div>
      )}
    </div>
  );
}
