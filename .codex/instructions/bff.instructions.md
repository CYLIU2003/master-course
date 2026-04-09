---
applyTo: "bff/**/*.py"
---

Preserve backend contract integrity and artifact safety.

## Rules
- Preserve scenario and artifact contract behavior
- Avoid shallow-load plus full-save patterns that can erase large artifacts
- Surface readiness and contract errors explicitly
- Be careful with status updates, staging paths, and artifact invalidation
- Keep API behavior explicit and machine-readable where possible

## Before editing
- Identify whether the route mutates only metadata or also touches artifacts
- Check whether saves can null out omitted fields
- Call out any concurrency, file-lock, or staging side-effect risks