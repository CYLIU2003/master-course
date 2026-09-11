import { useEffect, useState } from "react";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Activity,
  BusFront,
  Database,
  Layers3,
  Plus,
  Search,
  Settings2,
} from "lucide-react";
import { api, post, type Page, type Scenario } from "./api";
import { ErrorBox, Pager } from "./components/common";
import Workspace from "./components/Workspace";
export default function App() {
  const [selected, setSelected] = useState(
    localStorage.getItem("ev-scenario") ?? "",
  );
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const client = useQueryClient();
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const list = useQuery({
    queryKey: ["scenarios", query, offset],
    queryFn: ({ signal }) =>
      api<Page<Scenario>>(
        `/desktop/scenarios?q=${encodeURIComponent(query)}&offset=${offset}&limit=50`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });
  useEffect(() => {
    document.body.dataset.ready = String(list.isSuccess);
  }, [list.isSuccess]);
  function select(id: string) {
    setSelected(id);
    localStorage.setItem("ev-scenario", id);
  }
  const create = useMutation({
    mutationFn: () => post<Scenario>("/scenarios", { name: name.trim() }),
    onSuccess: (row) => {
      void client.invalidateQueries({ queryKey: ["scenarios"] });
      select(row.id);
      setCreating(false);
      setName("");
    },
  });
  return (
    <div className="app">
      <aside>
        <div className="brand">
          <div className="brand-icon">
            <BusFront size={23} />
          </div>
          <div>
            EV BUS<span>RESEARCH WORKSPACE</span>
          </div>
        </div>
        <div className="sidebar-label">ワークスペース</div>
        <div className="nav-active">
          <Layers3 size={18} /> シナリオ <span>{list.data?.total ?? "—"}</span>
        </div>
        <div className="sidebar-title">
          <h2>シナリオを選ぶ</h2>
          <button
            aria-label="新しいシナリオ"
            onClick={() => setCreating(!creating)}
          >
            <Plus size={18} />
          </button>
        </div>
        <label className="search">
          <Search size={16} />
          <input
            placeholder="名前で検索"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        {creating && (
          <form
            className="create-form"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <input
              autoFocus
              aria-label="シナリオ名"
              placeholder="シナリオ名"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={160}
            />
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
          {list.data?.items.map((row) => (
            <button
              key={row.id}
              className={"scenario " + (selected === row.id ? "selected" : "")}
              onClick={() => select(row.id)}
            >
              <span>{row.name}</span>
              <small>
                {row.status} · {row.updatedAt?.slice(0, 10)}
              </small>
            </button>
          ))}
        </div>
        <Pager
          offset={offset}
          total={list.data?.total ?? 0}
          size={50}
          set={setOffset}
        />
        <div className="sidebar-footer">
          <span className="dot" /> ローカル研究環境
          <br />
          <small>TypeScript · React · Electron</small>
        </div>
      </aside>
      <main>
        <header>
          <span>
            研究ワークスペース <span className="crumb">/ シナリオ</span>
          </span>
          <span className="local-tag">LOCAL</span>
        </header>
        {selected ? (
          <Workspace key={selected} id={selected} onSelect={select} />
        ) : (
          <section className="welcome">
            <span className="eyebrow">DISPATCH · CHARGING · ENERGY</span>
            <h1>
              運行とエネルギーを、
              <br />
              ひとつの視点で。
            </h1>
            <p>シナリオを選び、入力の準備から診断結果まで確認できます。</p>
            <button className="primary" onClick={() => setCreating(true)}>
              <Plus size={17} /> シナリオを作成
            </button>
            <div className="welcome-cards">
              <article>
                <Database />
                <h3>必要なデータから</h3>
                <p>時刻表・車両・仕業をページ単位で読み込みます。</p>
              </article>
              <article>
                <Settings2 />
                <h3>条件をそろえる</h3>
                <p>営業所・系統・対象日を確認して入力を準備します。</p>
              </article>
              <article>
                <Activity />
                <h3>根拠をたどる</h3>
                <p>実行状態と検証結果を個別に確認できます。</p>
              </article>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
