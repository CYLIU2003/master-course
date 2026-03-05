// ── DrawerTabs ────────────────────────────────────────────────
// Horizontal tab bar inside an editor drawer, for switching
// between sections (基本情報 / 性能 / コスト / etc.)

interface DrawerTabItem {
  key: string;
  label: string;
}

interface DrawerTabsProps {
  tabs: DrawerTabItem[];
  activeKey: string;
  onChange: (key: string) => void;
}

export function DrawerTabs({ tabs, activeKey, onChange }: DrawerTabsProps) {
  return (
    <div className="flex border-b border-border mb-4">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={`px-3 py-2 text-xs font-medium transition-colors ${
            activeKey === tab.key
              ? "border-b-2 border-primary-500 text-primary-700"
              : "text-slate-500 hover:text-slate-700"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
