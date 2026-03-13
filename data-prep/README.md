# data-prep

Producer app for Tokyu Bus research datasets.

- Fetches and refreshes public-data snapshots.
- Runs normalization / GTFS-style preprocessing.
- Publishes seed metadata under `data/seed/`.
- Publishes built research datasets under `data/built/`.

Current entrypoints:

```bash
# catalog / explorer API
uvicorn main:app --app-dir data-prep/api --reload --port 8100

# dataset build / refresh CLI
python catalog_update_app.py --help
```

The main research app must consume files from `data/` only and does not call this API at runtime.
