#!/usr/bin/env python3
"""KDD PR #20 / G0: isolated Termux regression; NEVER deploy or restart.

Source: private GitHub KDD branch pinned to one immutable commit. Retrieves
three explicitly allowlisted source files from an existing Git mirror, overlays
them into a PRIVATE temporary directory with copies of the running code and
two locally required private test fixtures, and runs the canonical offline test suite there.

This script does not deploy, restart, trade or directly write live KDD files.
The tests run in a temporary directory as the same Termux user, NOT inside an
OS-level sandbox; the live-file fingerprint is checked on success and failure.
The Git FETCH, when needed, modifies only mirror Git metadata/objects; no
checkout/commit/push/merge. Output contains only a bounded test summary.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

REPO = "gionatamartini66-rgb/KRAKEN_DECISION_DESK"
BRANCH = "experiments/kdd-any-spot-g2-20261024"
PIN = "de53603b3ee9f25d162e23aa6e8e92297b0f95c2"
FILES = {
    "grafico_4h.py": "b87ab1be6a0f6e80cf0597cbe6f38fa1c9f3c71d",
    "serve.py": "de54233f6f1ac3a4853ee46818767666909592ab",
    "test_decision_desk.py": "8bf2b6d7ddef2181f70825145c26f0fed986f98d",
}
REQUIRED = ("config.json", "portafoglio.json")
ASSETS = ("lightweight-charts-5.2.1.js", "LIGHTWEIGHT_CHARTS_LICENSE.txt",
          "LIGHTWEIGHT_CHARTS_NOTICE.txt")
TRUST_HASH = "KDD_T0_TRUSTED_SHA256"
TRUST_PROOF = "KDD_T0_TRUSTED_PROOF"
READ_TAG = re.compile(r"(?m)^<!-- CHECKPOINT_SORGENTI_SHA256: [a-f0-9]{64} -->$")
T0_NAME = re.compile(r"T0_\d{4}-\d{2}-\d{2}_\d{4}_KRAKEN_PRO")
REPORT = re.compile(r"Ran (\d+) tests? in |OK \(skipped=(\d+)\)|^OK$|^FAILED \(", re.M)

class Stop(Exception):
    pass


def run(args, *, cwd=None, timeout=90, text=True):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=text,
                          timeout=timeout, check=False)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for blob in iter(lambda: stream.read(65536), b""):
            h.update(blob)
    return h.hexdigest()


def private_file(path, *, required=True):
    if path.is_symlink():
        raise Stop("symlink in private input: " + path.name)
    if not path.is_file():
        if required:
            raise Stop("private fixture missing locally: " + path.name)
        return False
    if path.stat().st_size > 5_000_000:
        raise Stop("private fixture abnormally large: " + path.name)
    return True


def safe_copy(src, dst):
    private_file(src)
    dst.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    dst.chmod(0o600)


def source_fingerprint(root):
    h = hashlib.sha256()
    paths = sorted(root.glob("*.py"), key=lambda x: x.name)
    paths.append(root / "config.json")
    for p in paths:
        if not p.exists():
            continue
        if p.is_symlink():
            raise Stop("symlink in staging")
        h.update(p.name.encode("utf-8") + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def verify_source_checkpoint(root, *, label):
    """Authenticate the existing marker against the existing file bytes.

    This is a consistency check, NOT a cryptographic attestation of authorship.
    Never synthesize a live checkpoint or derive a historical T0 proof here.
    """
    text = (root / "README.md").read_text(encoding="utf-8")
    markers = READ_TAG.findall(text)
    if len(markers) != 1:
        raise Stop(label + " README checkpoint marker missing or duplicated")
    actual = "<!-- CHECKPOINT_SORGENTI_SHA256: " + source_fingerprint(root) + " -->"
    if markers[0] != actual:
        raise Stop(label + " source checkpoint MISMATCH; originals unchanged")


def git(repo, *args, timeout=60):
    return run(["git", "-C", str(repo), *args], timeout=timeout)


def validate_git_mirror(mirror):
    if mirror.is_symlink() or not (mirror / ".git").is_dir():
        raise Stop("safe Git mirror missing")
    r = git(mirror, "rev-parse", "--show-toplevel")
    if r.returncode or Path(r.stdout.strip()).resolve() != mirror.resolve():
        raise Stop("wrong Git checkout")
    r = git(mirror, "remote", "get-url", "origin")
    allowed = {f"https://github.com/{REPO}", f"https://github.com/{REPO}.git",
               f"ssh://git@github.com/{REPO}", f"ssh://git@github.com/{REPO}.git",
               f"git@github.com:{REPO}", f"git@github.com:{REPO}.git"}
    if r.returncode or r.stdout.strip() not in allowed:
        raise Stop("unexpected mirror remote")
    r = git(mirror, "branch", "--show-current")
    if r.returncode or r.stdout.strip() != "main":
        raise Stop("safe Git mirror is not on main; no checkout will be attempted")
    r = git(mirror, "status", "--porcelain")
    if r.returncode or r.stdout.strip():
        raise Stop("safe Git mirror is dirty; no checkout will be attempted")


def fetch_pinned(mirror):
    # Prefer the already-fetched immutable commit: zero network/disk writes.
    local = git(mirror, "cat-file", "-e", PIN + "^{commit}")
    if local.returncode:
        # Fetch only when truly absent. Never checkout, merge, install or push.
        r = git(mirror, "fetch", "--no-tags", "origin", "refs/heads/" + BRANCH,
                timeout=100)
        if r.returncode:
            raise Stop("Git fetch failed; check connectivity/authentication locally")
        # The branch can move forward for documentation and this very G0 tool:
        # the approved source files remain pinned to the original review commit.
        r = git(mirror, "rev-parse", "FETCH_HEAD")
        if r.returncode or not re.fullmatch(r"[a-f0-9]{40}", r.stdout.strip()):
            raise Stop("fetched PR ref is not a valid Git commit")
        pinned = git(mirror, "cat-file", "-e", PIN + "^{commit}")
        if pinned.returncode:
            raise Stop("reviewed PR commit absent from fetched history")
        ancestor = git(mirror, "merge-base", "--is-ancestor", PIN, "FETCH_HEAD")
        if ancestor.returncode:
            raise Stop("fetched PR branch no longer descends from reviewed commit")
    for name, expected_blob in FILES.items():
        p = git(mirror, "rev-parse", PIN + ":" + name)
        if p.returncode or p.stdout.strip() != expected_blob:
            raise Stop("unexpected Git blob for " + name)


def get_blob(mirror, name):
    p = run(["git", "-C", str(mirror), "cat-file", "blob", PIN + ":" + name],
            timeout=30, text=False)
    if p.returncode or not p.stdout or len(p.stdout) > 1_500_000:
        raise Stop("cannot load approved source blob " + name)
    # Confirm the approved Git SHA-1 of its byte stream.
    h = hashlib.sha1(b"blob " + str(len(p.stdout)).encode() + b"\0" + p.stdout).hexdigest()
    if h != FILES[name]:
        raise Stop("approved source bytes do not match Git blob " + name)
    return p.stdout


def validate_local(live):
    if live.is_symlink() or not live.is_dir():
        raise Stop("live KDD directory missing")
    for name in ("decision_desk.py", "serve.py", "grafico_4h.py",
                 "test_decision_desk.py", "README.md", *REQUIRED):
        private_file(live / name)
    if not (live / "vendor").is_dir() or (live / "vendor").is_symlink():
        raise Stop("local chart vendor directory missing")
    for name in ASSETS:
        private_file(live / "vendor" / name)
    # Do not inspect or print account contents here.
    # Crucial: validate LIVE before deriving the distinct staged checkpoint.
    verify_source_checkpoint(live, label="LIVE")


def has_independent_proof():
    trusted = os.environ.get(TRUST_HASH, "")
    proof = os.environ.get(TRUST_PROOF, "")
    return bool(re.fullmatch(r"[a-f0-9]{64}", trusted) or
                re.fullmatch(r"[a-f0-9]{24}", proof))


def obtain_historical_proof():
    """Ask only on the Samsung console if an independent historical proof
    is not already in the process environment; never save or print the value.
    """
    if has_independent_proof():
        return
    try:
        answer = getpass.getpass("Prova storica T0 locale (24 o 64 cifre hex; non incollare in chat): ")
    except (EOFError, KeyboardInterrupt, OSError):
        raise Stop("historical T0 proof unavailable locally") from None
    if re.fullmatch(r"[a-f0-9]{24}", answer):
        os.environ[TRUST_PROOF] = answer
    elif re.fullmatch(r"[a-f0-9]{64}", answer):
        os.environ[TRUST_HASH] = answer
    else:
        raise Stop("historical T0 proof format invalid")


def original_t0_path(live):
    """Identify and validate the existing historical T0 input, without echoing it."""
    private_file(live / "portafoglio.json")
    try:
        portfolio = json.loads((live / "portafoglio.json").read_text(encoding="utf-8"))
        identifier = portfolio.get("t0_id")
    except (ValueError, TypeError, OSError):
        raise Stop("local T0 reference unreadable") from None
    if not isinstance(identifier, str) or not T0_NAME.fullmatch(identifier):
        raise Stop("local T0 reference invalid")
    path = live / "storico_portafoglio" / (identifier + ".json")
    private_file(path)
    return path


def stage_private(live, stage, mirror):
    stage.chmod(0o700)
    # Only Python sources plus the fixtures strictly required by the two local tests.
    py_files = list(live.glob("*.py"))
    if not py_files:
        raise Stop("live Python sources absent")
    for f in py_files:
        if f.is_symlink():
            raise Stop("symlink among live sources")
        if f.stat().st_size > 1_500_000:
            raise Stop("unexpectedly large Python source")
        safe_copy(f, stage / f.name)
    for name in FILES:
        dst = stage / name
        dst.write_bytes(get_blob(mirror, name))
        dst.chmod(0o600)
    for name in REQUIRED:
        safe_copy(live / name, stage / name)
    # Store T0 only inside this restricted temporary staging. Its historical
    # fingerprint must come from environment, NEVER calculated into env here.
    source_t0 = original_t0_path(live)
    safe_copy(source_t0, stage / "storico_portafoglio" / source_t0.name)
    for name in ASSETS:
        safe_copy(live / "vendor" / name, stage / "vendor" / name)
    original = (live / "README.md").read_text(encoding="utf-8")
    aligned = READ_TAG.sub("<!-- CHECKPOINT_SORGENTI_SHA256: " +
                           source_fingerprint(stage) + " -->", original)
    (stage / "README.md").write_text(aligned, encoding="utf-8")
    (stage / "README.md").chmod(0o600)
    verify_source_checkpoint(stage, label="STAGING")
    # A run must never start when a required historical T0 proof is absent.
    if not has_independent_proof():
        raise Stop("historical independent T0 attestation missing; no tests run")


def execute_tests(stage):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    # Restricted module runner; no shell interpolation and no API credentials.
    for key in list(env):
        if (key.startswith("KRAKEN_") or key.startswith("OPENAI_")
                or key.startswith("DEEPSEEK_") or key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")):
            env.pop(key, None)
    try:
        result = subprocess.run([sys.executable, "-B", "-m", "unittest", "-q", "test_decision_desk"],
                                cwd=stage, env=env, capture_output=True, text=True,
                                timeout=160, check=False)
    except subprocess.TimeoutExpired:
        raise Stop("offline regression timed out") from None
    # Deliberately do NOT print traceback/assertion details; they could quote
    # account data and should stay exclusively inside the private process.
    raw = (result.stdout or "") + "\n" + (result.stderr or "")
    ran = re.search(r"Ran (\d+) tests? in", raw)
    skipped = re.search(r"OK \(skipped=(\d+)\)", raw)
    failures = re.search(r"FAILED \(", raw)
    if ran:
        print("TEST_DISCOVERED:", ran.group(1))
    if skipped:
        print("TEST_SKIPPED:", skipped.group(1))
    elif re.search(r"(?m)^OK\s*$", raw):
        print("TEST_SKIPPED: 0")
    else:
        print("TEST_SKIPPED: unknown")
    if result.returncode or failures or not ran or not re.search(r"(?m)^OK(?: \(skipped=\d+\))?\s*$", raw):
        raise Stop("regression not passing; details intentionally NOT exposed")
    if skipped and int(skipped.group(1)) > 0:
        raise Stop("tests skipped; Samsung local gate not closed")
    if int(ran.group(1)) < 163:
        raise Stop("fewer than the expected 163 tests")
    print("G0_REGRESSION_LOCAL: PASS (no skips)")


def staging_budget(live, mirror):
    """Small, bounded local staging; refuse when even that will crowd Termux."""
    inputs = list(live.glob("*.py"))
    inputs += [live / n for n in ("README.md", *REQUIRED)]
    inputs += [live / "vendor" / n for n in ASSETS]
    # Include one private historical T0 file, bounded by private_file() later.
    for file in inputs:
        private_file(file)
    estimated = sum(file.stat().st_size for file in inputs) + 5_000_000
    # No arbitrary huge staging: allow at most the actual app-size + overhead.
    free = shutil.disk_usage(Path.home()).free
    if free < estimated * 2:
        raise Stop("insufficient free phone storage for safe temporary staging")
    return estimated


def preflight(mirror, live):
    validate_git_mirror(mirror)
    validate_local(live)
    staging_budget(live, mirror)
    print("KDD_PR20_PIN:", PIN)
    print("MODE: READ-ONLY live; no order, no deploy, no restart")
    obtain_historical_proof()
    # Snapshot limited to existing executable+config/README files. No values printed.
    targets = [p for p in live.glob("*.py") if p.is_file()]
    targets += [live / n for n in ("README.md", "config.json", "portafoglio.json")]
    targets += [live / "vendor" / n for n in ASSETS]
    targets.append(original_t0_path(live))
    before = {str(p):sha(p) for p in targets}
    try:
        fetch_pinned(mirror)
        with tempfile.TemporaryDirectory(prefix="kdd-pr20-g0-", dir=str(Path.home())) as work:
            stage = Path(work)
            stage.chmod(0o700)
            stage_private(live, stage, mirror)
            execute_tests(stage)
    finally:
        # Check the originals even when test/fetch fails; do not mask changes.
        after = {str(p):sha(p) for p in targets}
        if after != before:
            raise Stop("live source/README/fixture changed during check; no deploy performed")
    print("LIVE_HASHES_BEFORE_AFTER: SAME")
    print("FINAL: G0_LOCAL_TEST_PASS / no runtime modification")
    print("NOTE: independent review and Android Chrome demonstration still needed")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mirror", type=Path,
                    default=Path.home() / "kraken-decision-desk" / "KDD_GITHUB_SAFE")
    ap.add_argument("--live", type=Path,
                    default=Path.home() / "kraken-decision-desk" / "KRAKEN_DECISION_DESK_V001")
    args = ap.parse_args(argv)
    try:
        preflight(args.mirror, args.live)
    except Stop as exc:
        print("STOP_G0:", exc, file=sys.stderr)
        return 2
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        print("STOP_G0:", type(exc).__name__, "(no private file contents)", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
