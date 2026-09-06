# Remote SSH Development

Use this setup when the app runs on a remote Linux/Windows host via VS Code Remote SSH and you open the UI from your local PC.

## Ports

- Forward `8000` for the FastAPI BFF.
- Forward `5173` for the Vite frontend dev server.

## Backend

```bash
python -m uvicorn bff.main:app --host 0.0.0.0 --port 8000 --reload
```

## Frontend

Create `frontend/.env.development.local`:

```dotenv
VITE_DEV_HOST=0.0.0.0
VITE_DEV_PORT=5173
VITE_API_BASE_URL=/api
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
```

Then start Vite:

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

## GTFS-First Runtime Flow

For Tokyu Bus, build or refresh the layered pipeline on the remote host first:

```bash
python -m src.tokyubus_gtfs run --source-dir ./data/raw-odpt
```

Then inspect available runtime snapshots:

```bash
curl http://127.0.0.1:8000/api/catalog/runtime-snapshots
```

Import the latest runtime snapshot into a scenario:

```bash
curl -X POST http://127.0.0.1:8000/api/scenarios/<scenario_id>/import-runtime-snapshot
```

Or choose a specific snapshot:

```bash
curl -X POST http://127.0.0.1:8000/api/scenarios/<scenario_id>/import-runtime-snapshot \
  -H "Content-Type: application/json" \
  -d '{"snapshotId":"<snapshot_id>"}'
```
