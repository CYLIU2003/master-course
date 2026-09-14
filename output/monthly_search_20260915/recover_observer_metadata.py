"""One reviewed migration of the stopped observer; never restart the solver."""
from copy import deepcopy
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
sys.path.insert(0, str(ROOT))
from scripts.watch_monthly_campaign import (
    config_hash, now, read_json, require, sha256, solver_is_alive,
    validate_configuration, write_json,
)


def main() -> None:
    output = BASE / "script_observer"
    archive = output / "recovery_metadata_20260915"
    require(not archive.exists(), "Recovery exists; inspect it before another action")
    config_path = output / "config.json"
    config = read_json(config_path)
    old_hash = config_hash(config)
    require(old_hash == "f3a135c076bc9a8a4c541db5734d14c97cff963b64d887fe8638a210a5d1fd2b",
            "Unexpected original observer configuration")
    require(read_json(output / "state.json")["status"] == "NEEDS_ATTENTION", "Observer not stopped")
    require(solver_is_alive(config["solver_pid"], config["solver_started_at_utc"]), "Original solver not alive")
    binding = BASE / "observer_binding.json"
    require(read_json(binding)["config_sha256"] == old_hash, "Binding mismatch")
    changed_helper = str(ROOT / "output/monthly_fair_weeks_20260914/audit_budget_week.py")
    for filename, digest in config["helper_hashes"].items():
        if filename != changed_helper:
            require(sha256(Path(filename)) == digest, f"Unreviewed helper change: {filename}")
    updated = deepcopy(config)
    updated["helper_hashes"][changed_helper] = sha256(Path(changed_helper))
    require(updated["helper_hashes"][changed_helper] != config["helper_hashes"][changed_helper], "No fix found")
    validate_configuration(updated)
    paths = [config_path, output / "state.json", output / "failure.json",
             output / "failure_dispatch.json", output / "commands.log", binding]
    archive.mkdir()
    snapshots = []
    for path in paths:
        backup = archive / path.name
        backup.write_bytes(path.read_bytes())
        require(sha256(backup) == sha256(path), "Recovery snapshot mismatch")
        snapshots.append({"original": str(path), "backup": str(backup), "sha256": sha256(path)})
    new_hash = config_hash(updated)
    write_json(archive / "migration.json", {
        "status": "PREPARED", "prepared_at_utc": now(), "old_config_sha256": old_hash,
        "new_config_sha256": new_hash, "snapshots": snapshots,
        "changed_helper": changed_helper, "solver_pid_unchanged": config["solver_pid"],
        "source_git_sha_unchanged": config["source_git_sha"],
        "reason": "Audit the complete saved adapter metadata; do not infer missing fields or change solver results.",
        "prior_failure_handled": True, "email_sent": False,
    })
    write_json(config_path, updated)
    write_json(binding, {"config_sha256": new_hash, "bound_at_utc": now(), "recovery": str(archive)})
    write_json(output / "state.json", {"status": "RECOVERED_AWAITING_RESTART", "checked_at_utc": now(),
               "config_sha256": new_hash, "source_git_sha": config["source_git_sha"], "observer_pid": 0})
    # Preserve the acknowledged old event in the verified archive before allowing
    # one new failure event. Completion deduplication and the subject stay intact.
    for name in ("failure.json", "failure_dispatch.json"):
        path = output / name
        require(sha256(path) == sha256(archive / name), "Old failure event changed during recovery")
        path.unlink()
    migration = read_json(archive / "migration.json")
    migration.update(status="MIGRATED", migrated_at_utc=now())
    write_json(archive / "migration.json", migration)
    print(new_hash)


if __name__ == "__main__":
    main()
