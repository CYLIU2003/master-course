"""Exercise the actual Windows PowerShell 5.1 entrypoint, without modifying SSH."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows worker setup")
SCRIPT = Path(__file__).resolve().parents[1] / "tools/cluster/enable_worker_access.ps1"


@pytest.fixture
def release_bundle(tmp_path):
    """Validate the actual deliverable when explicitly selected by its packager."""
    selected = os.environ.get("MC_WORKER_SETUP_ZIP")
    if not selected:
        pytest.skip("Set MC_WORKER_SETUP_ZIP to validate an actual distribution ZIP")
    directory = tmp_path / "配布 ZIP の検査"
    directory.mkdir()
    with zipfile.ZipFile(selected) as archive:
        expected = {"manifest.json", "workers.json", "controller.pub", "SETUP.cmd", SCRIPT.name, "README.txt"}
        assert len(archive.namelist()) == len(expected)
        assert set(archive.namelist()) == expected  # no private keys, licenses or extra executable files
        manifest = json.loads(archive.read("manifest.json"))
        assert set(manifest["files"]) == expected - {"manifest.json"}
        for name, sha in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == sha, name
        archive.extractall(directory)
    return directory


def test_release_zip_matches_the_tested_code_and_has_a_real_public_key(release_bundle):
    assert (release_bundle / SCRIPT.name).read_bytes() == SCRIPT.read_bytes()
    assert (release_bundle / "SETUP.cmd").read_text() == SCRIPT.with_name("SETUP.cmd").read_text()
    result = subprocess.run(["ssh-keygen", "-l", "-f", str(release_bundle / "controller.pub")],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert b"ED25519" in result.stdout


@pytest.mark.parametrize("worker_index", range(11))
def test_release_zip_cmd_validates_each_registered_identity(release_bundle, tmp_path, worker_index):
    roster = json.loads((release_bundle / "workers.json").read_bytes())
    assert len(roster) == 11
    worker = roster[worker_index]
    # Simulate only the roster identity. This is not a remote PC or elevation test.
    environment = {**os.environ, "COMPUTERNAME": worker["name"], "USERNAME": worker["ssh_user"]}
    before = {p.name: p.read_bytes() for p in release_bundle.iterdir()}
    result = subprocess.run(["cmd.exe", "/d", "/c", str(release_bundle / "SETUP.cmd"), "-ValidateOnly"],
                            cwd=tmp_path, env=environment, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b'"validated":true' in result.stdout
    assert worker["ssh_user"].encode() in result.stdout
    assert before == {p.name: p.read_bytes() for p in release_bundle.iterdir()}


@pytest.mark.parametrize("fault,message", [
    ("wrong_pc", b"not uniquely registered"),
    ("wrong_user", b"Run this setup as"),
    ("duplicate_pc", b"not uniquely registered"),
    ("invalid_key", b"Expected the controller Ed25519"),
    ("missing_key", b"Missing controller.pub"),
])
def test_release_zip_refuses_invalid_inputs_before_changes(release_bundle, tmp_path, fault, message):
    roster = json.loads((release_bundle / "workers.json").read_bytes())
    worker = roster[0]
    environment = {**os.environ, "COMPUTERNAME": worker["name"], "USERNAME": worker["ssh_user"]}
    if fault == "wrong_pc":
        environment["COMPUTERNAME"] = "unregistered-test-pc"
    elif fault == "wrong_user":
        environment["USERNAME"] = "wrong-test-user"
    elif fault == "duplicate_pc":
        (release_bundle / "workers.json").write_text(json.dumps([worker, worker]), encoding="ascii")
    elif fault == "invalid_key":
        (release_bundle / "controller.pub").write_text("invalid key", encoding="ascii")
    elif fault == "missing_key":
        (release_bundle / "controller.pub").unlink()
    before = {p.name: p.read_bytes() for p in release_bundle.iterdir()}
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(release_bundle / SCRIPT.name)], cwd=tmp_path, env=environment,
                            capture_output=True, timeout=15)
    assert result.returncode != 0
    assert message in result.stderr
    assert before == {p.name: p.read_bytes() for p in release_bundle.iterdir()}


@pytest.mark.parametrize("explicit_directory", [False, True])
def test_setup_resolves_unicode_space_path_in_windows_powershell(tmp_path, explicit_directory):
    bundle = tmp_path / "子機 セットアップ"
    bundle.mkdir()
    shutil.copyfile(SCRIPT, bundle / SCRIPT.name)
    (bundle / "workers.json").write_text(json.dumps([{"name": os.environ["COMPUTERNAME"], "ssh_user": os.environ["USERNAME"]}]), encoding="utf-8")
    (bundle / "controller.pub").write_text("ssh-ed25519 AAAA regression-test", encoding="ascii")
    args = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(bundle / SCRIPT.name), "-ValidateOnly"]
    if explicit_directory:
        args += ["-BundleDirectory", str(bundle)]
    before = {p.name: p.read_bytes() for p in bundle.iterdir()}
    for _ in range(2):
        result = subprocess.run(args, cwd=tmp_path, capture_output=True, timeout=15)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        # PowerShell 5.1 emits the console code page, but the boolean is ASCII on every locale.
        assert b'"validated":true' in result.stdout
    assert before == {p.name: p.read_bytes() for p in bundle.iterdir()}


def test_setup_reports_missing_bundle_file_before_any_changes(tmp_path):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                             "-BundleDirectory", str(tmp_path), "-ValidateOnly"], capture_output=True, timeout=15)
    assert result.returncode != 0
    assert b"Missing workers.json" in result.stderr
    assert not list(tmp_path.iterdir())


def test_cmd_launcher_from_a_different_working_directory(tmp_path):
    bundle = tmp_path / "worker setup"
    bundle.mkdir()
    shutil.copyfile(SCRIPT, bundle / SCRIPT.name)
    shutil.copyfile(SCRIPT.with_name("SETUP.cmd"), bundle / "SETUP.cmd")
    (bundle / "workers.json").write_text(json.dumps([{"name": os.environ["COMPUTERNAME"], "ssh_user": os.environ["USERNAME"]}]), encoding="ascii")
    (bundle / "controller.pub").write_text("ssh-ed25519 AAAA regression-test", encoding="ascii")
    result = subprocess.run(["cmd.exe", "/d", "/c", str(bundle / "SETUP.cmd"), "-ValidateOnly"],
                             cwd=tmp_path, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b'"validated":true' in result.stdout


def test_actual_key_write_acl_backup_and_idempotent_rerun(tmp_path):
    # Extract the production function with the PowerShell parser; run against a disposable file only.
    program = tmp_path / "check.ps1"
    program.write_text(r'''
param($Source, $Target)
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$null, [ref]$null)
$function = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Install-ControllerPublicKey' }, $true)
. ([scriptblock]::Create($function.Extent.Text))
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$oldKey = 'ssh-ed25519 AAAA existing-controller'
$newKey = 'ssh-ed25519 BBBB new-controller'
New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
[IO.File]::WriteAllText($Target, $oldKey + "`n")
Install-ControllerPublicKey -keyPath $Target -publicKey $newKey -allowedSids @($sid, 'S-1-5-18') -ownerSid $sid
$once = [IO.File]::ReadAllText($Target)
Install-ControllerPublicKey -keyPath $Target -publicKey $newKey -allowedSids @($sid, 'S-1-5-18') -ownerSid $sid
if ($once -ne [IO.File]::ReadAllText($Target)) { throw 'Second run changed the key file' }
if (-not $once.Contains($oldKey)) { throw 'Existing key lost' }
if (@(Get-ChildItem -LiteralPath (Split-Path -Parent $Target) -Filter '*.backup-*').Count -ne 1) { throw 'Backup count mismatch' }
$acl = Get-Acl -LiteralPath $Target
if (-not $acl.AreAccessRulesProtected) { throw 'Inheritance still enabled' }
$actual = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | ForEach-Object { $_.IdentityReference.Value })
if ($actual.Count -ne 2 -or $actual -notcontains $sid -or $actual -notcontains 'S-1-5-18') { throw 'Unexpected ACL' }
Write-Output 'KEY_WRITE_ACL_RERUN_OK'
''', encoding="utf-8-sig")
    target = tmp_path / "isolated ssh" / "authorized_keys"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(program),
                             "-Source", str(SCRIPT), "-Target", str(target)], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"KEY_WRITE_ACL_RERUN_OK" in result.stdout
