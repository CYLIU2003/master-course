"""Operator CLI: members' tokens, the lab pool and the server.

    python -m tools.lab_gateway.admin token-add alice          # prints the token once; give it to alice only
    python -m tools.lab_gateway.admin token-list
    python -m tools.lab_gateway.admin token-revoke alice
    python -m tools.lab_gateway.admin serve --host 127.0.0.1 --port 8899

Data (queue, results, token digests, audit log) lives in output/lab-gateway/ unless MC_LAB_GATEWAY_DIR is set.
The pool is config.json in that directory: {"machines": ["desktop-0srs8pr", ...]} using ids from the cluster ledger
(config/cluster/workers.local.json). Thesis PCs are not listed there.
Optional "thesis_overflow": {"controller": "http://127.0.0.1:8891", "max_minutes": 360, "keep_idle": 2} lets jobs
borrow a thesis PC only while the thesis controller reports it idle (see tools/lab_gateway/overflow.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.lab_gateway.dispatcher import Dispatcher
from tools.lab_gateway.overflow import ThesisOverflow
from tools.lab_gateway.remote import Machine
from tools.lab_gateway.server import Gateway
from tools.lab_gateway.store import JobStore, Tokens


def data_dir() -> Path:
    return Path(os.environ.get("MC_LAB_GATEWAY_DIR", ROOT / "output" / "lab-gateway"))


def load_machines(directory: Path) -> dict[str, Machine]:
    from bff.services.cluster.contracts import read_config
    wanted = json.loads((directory / "config.json").read_text(encoding="utf-8"))["machines"]
    ledger = {w.id: w for w in read_config().workers}
    missing = [m for m in wanted if m not in ledger]
    if missing:
        raise SystemExit(f"not in the cluster ledger: {missing}")
    return {m: Machine(ledger[m]) for m in wanted}


def load_overflow(directory: Path) -> ThesisOverflow | None:
    settings = json.loads((directory / "config.json").read_text(encoding="utf-8")).get("thesis_overflow")
    if not settings:
        return None
    return ThesisOverflow(directory, base_url=settings["controller"], max_minutes=int(settings.get("max_minutes", 360)),
                          keep_idle=int(settings.get("keep_idle", 2)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("token-add")
    add.add_argument("name")
    add.add_argument("--admin", action="store_true")
    sub.add_parser("token-list")
    revoke = sub.add_parser("token-revoke")
    revoke.add_argument("name")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8899)
    args = parser.parse_args(argv)
    directory = data_dir()
    tokens = Tokens(directory / "tokens.json")
    if args.command == "token-add":
        print(tokens.add(args.name, admin=args.admin))
        print("Shown once. Hand it to the member privately; only its SHA-256 is stored.", file=sys.stderr)
    elif args.command == "token-list":
        print(json.dumps(tokens.list(), indent=1))
    elif args.command == "token-revoke":
        print(f"revoked {tokens.revoke(args.name)} token(s)")
    else:
        store = JobStore(directory / "jobs.sqlite3")
        overflow = load_overflow(directory)
        dispatcher = Dispatcher(store, load_machines(directory), directory, overflow=overflow)
        gateway = Gateway((args.host, args.port), store=store, tokens=tokens, dispatcher=dispatcher, data_dir=directory)
        dispatcher.start()
        borrow = f"; borrows idle thesis PCs from {overflow.base_url}" if overflow else ""
        print(f"lab gateway on http://{args.host}:{args.port} (pool: {', '.join(dispatcher.machines)}{borrow})", flush=True)
        try:
            gateway.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            dispatcher.stop_event.set()
            gateway.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
