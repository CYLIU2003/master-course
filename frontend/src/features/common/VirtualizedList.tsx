import { useMemo, useState } from "react";

interface Props<T> {
  items: T[];
  itemHeight: number;
  height: number;
  overscan?: number;
  renderItem: (item: T, index: number) => React.ReactNode;
  getKey?: (item: T, index: number) => string;
  className?: string;
}

export function VirtualizedList<T>({
  items,
  itemHeight,
  height,
  overscan = 6,
  renderItem,
  getKey,
  className,
}: Props<T>) {
  const [scrollTop, setScrollTop] = useState(0);

  const { startIndex, visibleItems } = useMemo(() => {
    const start = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
    const visibleCount = Math.ceil(height / itemHeight) + overscan * 2;
    const end = Math.min(items.length, start + visibleCount);
    return {
      startIndex: start,
      visibleItems: items.slice(start, end),
    };
  }, [height, itemHeight, items, overscan, scrollTop]);

  return (
    <div
      className={className}
      style={{ height, overflowY: "auto" }}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
    >
      <div style={{ height: items.length * itemHeight, position: "relative" }}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            transform: `translateY(${startIndex * itemHeight}px)`,
          }}
        >
          {visibleItems.map((item, index) => (
            <div
              key={getKey ? getKey(item, startIndex + index) : String(startIndex + index)}
              style={{ height: itemHeight }}
            >
              {renderItem(item, startIndex + index)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
