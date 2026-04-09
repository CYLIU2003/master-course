---
applyTo: "frontend/src/**/*.{ts,tsx}"
---

Optimize for responsiveness, clarity, and safe state management.

## Rules
- Prefer selector-based store access and memoization where appropriate
- Avoid unnecessary global store writes and deep reactive loops
- Preserve existing lazy-loading and shallow-loading strategies
- Do not trigger loading of large graph artifacts by default
- Keep UI behavior explicit when readiness conditions are not met
- Preserve operator separation and scenario overlay assumptions in the UI

## When changing state flows
- Identify where data is fetched, normalized, cached, and rendered
- Watch for accidental rerender loops and repeated effect triggers
- Prefer minimal changes over broad state rewrites