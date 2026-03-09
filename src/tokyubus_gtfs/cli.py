"""
src.tokyubus_gtfs.cli — Command-line interface for the Tokyu Bus pipeline.

Usage::

    python -m src.tokyubus_gtfs archive   <source_dir> [--snapshot-id ID]
    python -m src.tokyubus_gtfs canonical <snapshot_dir> [--out-dir DIR]
    python -m src.tokyubus_gtfs gtfs      <canonical_dir> [--out-dir DIR]
    python -m src.tokyubus_gtfs features  <canonical_dir> [--out-dir DIR]
    python -m src.tokyubus_gtfs run       <source_dir> [--snapshot-id ID] [options]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_log = logging.getLogger("src.tokyubus_gtfs")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_archive(args: argparse.Namespace) -> None:
    from .archive import archive_raw_snapshot

    manifest = archive_raw_snapshot(
        Path(args.source_dir),
        snapshot_id=args.snapshot_id,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def cmd_canonical(args: argparse.Namespace) -> None:
    from .canonical import build_canonical

    out = Path(args.out_dir) if args.out_dir else None
    summary = build_canonical(Path(args.snapshot_dir), out_dir=out)
    print(json.dumps(summary.model_dump(mode="json"), indent=2, ensure_ascii=False))


def cmd_gtfs(args: argparse.Namespace) -> None:
    from .gtfs_export import export_gtfs

    out = Path(args.out_dir) if args.out_dir else None
    result = export_gtfs(Path(args.canonical_dir), out_dir=out)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_features(args: argparse.Namespace) -> None:
    from .features.trip_chains import build_trip_chains
    from .features.energy import build_energy_features
    from .features.depot import build_depot_candidates

    canonical_dir = Path(args.canonical_dir)
    out = Path(args.out_dir) if args.out_dir else Path("data/tokyubus/features")
    out.mkdir(parents=True, exist_ok=True)

    results = {}
    results["trip_chains"] = build_trip_chains(canonical_dir, out)
    results["energy"] = build_energy_features(canonical_dir, out)
    results["depot_candidates"] = build_depot_candidates(canonical_dir, out)
    print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_run(args: argparse.Namespace) -> None:
    from .pipeline import PipelineConfig, run_pipeline

    config = PipelineConfig(
        source_dir=Path(args.source_dir),
        snapshot_id=args.snapshot_id,
        skip_archive=args.skip_archive,
        skip_gtfs=args.skip_gtfs,
        skip_features=args.skip_features,
    )
    result = run_pipeline(config)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tokyubus-gtfs",
        description="Tokyu Bus ODPT → Canonical → GTFS pipeline",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command")

    # archive
    p_arch = sub.add_parser("archive", help="Archive raw ODPT snapshot (Layer A)")
    p_arch.add_argument("source_dir", help="Directory with raw ODPT JSON files")
    p_arch.add_argument("--snapshot-id", default=None, help="Custom snapshot ID")

    # canonical
    p_can = sub.add_parser("canonical", help="Build canonical model (Layer B)")
    p_can.add_argument("snapshot_dir", help="Raw snapshot directory (Layer A)")
    p_can.add_argument("--out-dir", default=None, help="Output directory")

    # gtfs
    p_gtfs = sub.add_parser("gtfs", help="Export GTFS feed (Layer C)")
    p_gtfs.add_argument("canonical_dir", help="Canonical JSONL directory")
    p_gtfs.add_argument("--out-dir", default=None, help="GTFS output directory")

    # features
    p_feat = sub.add_parser("features", help="Build research features (Layer D)")
    p_feat.add_argument("canonical_dir", help="Canonical JSONL directory")
    p_feat.add_argument("--out-dir", default=None, help="Feature output directory")

    # run (full pipeline)
    p_run = sub.add_parser("run", help="Run full pipeline (A → B → C → D)")
    p_run.add_argument("source_dir", help="Directory with raw ODPT JSON files")
    p_run.add_argument("--snapshot-id", default=None, help="Custom snapshot ID")
    p_run.add_argument("--skip-archive", action="store_true", help="Skip Layer A")
    p_run.add_argument("--skip-gtfs", action="store_true", help="Skip Layer C")
    p_run.add_argument("--skip-features", action="store_true", help="Skip Layer D")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    commands = {
        "archive": cmd_archive,
        "canonical": cmd_canonical,
        "gtfs": cmd_gtfs,
        "features": cmd_features,
        "run": cmd_run,
    }

    if not args.command:
        parser.print_help()
        sys.exit(1)

    fn = commands.get(args.command)
    if fn is None:
        parser.print_help()
        sys.exit(1)

    fn(args)
