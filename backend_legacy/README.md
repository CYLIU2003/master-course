# backend_legacy/ (Legacy)

`backend_legacy/` is a frozen legacy ODPT proxy workspace.

- The Tokyu research application officially runs on `bff/` + `frontend/`
- Producer-side catalog / explorer responsibilities now live under `data-prep/`
- Do not add new planning / dispatch / simulation APIs here
- Use this directory only when maintaining the old ODPT proxy flow

Standard startup for the current project:

```bash
python -m uvicorn bff.main:app --reload --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```
