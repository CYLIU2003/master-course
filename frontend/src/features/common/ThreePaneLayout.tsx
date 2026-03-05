// ── ThreePaneLayout ───────────────────────────────────────────
// Left filter pane + Center content + Right editor drawer.
// The right pane is conditionally rendered.

import type { ReactNode } from "react";

interface ThreePaneLayoutProps {
  left?: ReactNode;
  center: ReactNode;
  right?: ReactNode;
  leftWidth?: string;
}

export function ThreePaneLayout({
  left,
  center,
  right,
  leftWidth = "w-56",
}: ThreePaneLayoutProps) {
  return (
    <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0 }}>
      {/* Left pane */}
      {left && (
        <div
          className={`${leftWidth} shrink-0 overflow-y-auto border-r border-border bg-surface-raised`}
        >
          {left}
        </div>
      )}

      {/* Center pane */}
      <div className="flex-1 overflow-y-auto">{center}</div>

      {/* Right pane (drawer) */}
      {right}
    </div>
  );
}
