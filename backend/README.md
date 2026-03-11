# backend/ (Legacy)

`backend/` is a legacy ODPT proxy workspace.

- The research application officially runs on `bff/` + `frontend/`
- Do not add new planning / dispatch / simulation APIs here
- Use this directory only when maintaining the old ODPT proxy flow

Standard startup for the current project:

```bash
python -m uvicorn bff.main:app --reload --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```
