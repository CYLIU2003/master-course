import type { ReactNode } from "react";
import { useState } from "react";

interface PageSectionProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  defaultExpanded?: boolean;
  onExpandChange?: (expanded: boolean) => void;
}

export function PageSection({ 
  title, 
  description, 
  actions, 
  children,
  defaultExpanded = true,
  onExpandChange,
}: PageSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const handleToggle = () => {
    const newValue = !expanded;
    setExpanded(newValue);
    onExpandChange?.(newValue);
  };

  return (
    <section className="mb-6">
      <div className="mb-4 flex items-start justify-between">
        <div className="flex items-center gap-2">
          <button
            onClick={handleToggle}
            className="flex items-center gap-1 text-left"
          >
            <svg
              className={`h-4 w-4 text-slate-400 transition-transform ${expanded ? "rotate-90" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            <h2 className="text-lg font-semibold text-slate-800">{title}</h2>
          </button>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {description && (
        <p className="mb-3 mt-0.5 text-sm text-slate-500">{description}</p>
      )}
      {expanded && children}
    </section>
  );
}
