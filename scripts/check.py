#!/usr/bin/env python3
"""Run every gate that CI enforces, in one command.

This exists so an agent (or a person) can verify a change without knowing the
project's layout: run this, read the summary, and you know whether the tree is
sound. CI runs exactly these gates, so "green here" means "green there".

    python scripts/check.py            # the six fast gates
    python scripts/check.py --e2e      # ...and the Playwright suite

Every gate runs even if an earlier one fails, so one pass gives the whole
picture instead of surfacing problems one at a time.

Exit code is 0 only when every gate passed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def _venv_python() -> str:
    """The backend interpreter, without requiring the venv to be activated."""
    for candidate in (
        BACKEND / "venv" / "Scripts" / "python.exe",  # Windows
        BACKEND / "venv" / "bin" / "python",  # POSIX
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _backend_env() -> dict[str, str]:
    """Env for the Django commands.

    settings.py falls back to a local Postgres for both DATABASE_URL and
    LANDING_DATABASE_URL, and CLAUDE.md notes that without the landing URL the
    subscribers migration looks for a Postgres that isn't running. backend/.env
    is gitignored, so CI has no env at all — default both to sqlite here.

    setdefault, not assignment: a developer who has pointed DATABASE_URL at a
    real Postgres keeps it.
    """
    env = os.environ.copy()
    env.setdefault("DATABASE_URL", "sqlite:///db.sqlite3")
    env.setdefault("LANDING_DATABASE_URL", "sqlite:///landing.sqlite3")
    return env


@dataclass
class Gate:
    name: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str] | None = None
    passed: bool = field(default=False, init=False)
    seconds: float = field(default=0.0, init=False)


def _gates(include_e2e: bool = False) -> list[Gate]:
    py = _venv_python()
    env = _backend_env()

    # npm is npm.cmd on Windows; which() resolves the shim so subprocess can
    # exec it without a shell.
    npm = shutil.which("npm") or "npm"

    gates = [
        Gate("django-check", [py, "manage.py", "check"], BACKEND, env),
        # A model change with no migration is a classic silent agent error: tests
        # still pass locally, then the deploy fails or the column is missing.
        Gate(
            "migrations",
            [py, "manage.py", "makemigrations", "--check", "--dry-run"],
            BACKEND,
            env,
        ),
        Gate("backend-tests", [py, "manage.py", "test"], BACKEND, env),
        Gate("backend-lint", [py, "-m", "ruff", "check", "."], BACKEND, env),
        Gate("frontend-lint", [npm, "run", "lint"], FRONTEND),
        Gate("frontend-build", [npm, "run", "build"], FRONTEND),
    ]

    if include_e2e:
        # Boots its own servers and drives a real browser — see
        # frontend/playwright.config.ts. Kept out of the default run because it
        # is the slow gate and needs browsers installed.
        gates.append(Gate("e2e", [npm, "run", "test:e2e"], FRONTEND))

    return gates


def _run(gate: Gate) -> None:
    print(f"\n{'=' * 72}\n>> {gate.name}\n   $ {' '.join(gate.cmd)}\n{'=' * 72}", flush=True)
    started = time.monotonic()
    try:
        result = subprocess.run(gate.cmd, cwd=gate.cwd, env=gate.env, check=False)
        gate.passed = result.returncode == 0
    except FileNotFoundError as exc:
        # Missing tooling is a failed gate, not a crash — an agent should see it
        # in the summary like any other failure.
        print(f"  could not run: {exc}", flush=True)
        gate.passed = False
    gate.seconds = time.monotonic() - started


def main() -> int:
    # The Windows console defaults to a legacy codepage (cp1252 here) that cannot
    # encode anything outside it. Output is ASCII by design; this guard means a
    # stray non-ASCII character degrades to "?" instead of crashing the run.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--e2e",
        action="store_true",
        help="also run the Playwright suite (needs browsers; see README)",
    )
    args = parser.parse_args()

    gates = _gates(include_e2e=args.e2e)

    print(f"checking {ROOT}")
    for gate in gates:
        _run(gate)

    failed = [g for g in gates if not g.passed]

    print(f"\n{'=' * 72}\nSUMMARY\n{'=' * 72}")
    for gate in gates:
        mark = "PASS" if gate.passed else "FAIL"
        print(f"  [{mark}] {gate.name:<18} {gate.seconds:5.1f}s")

    if failed:
        print(f"\n{len(failed)} of {len(gates)} gates failed: "
              f"{', '.join(g.name for g in failed)}")
        return 1

    total = sum(g.seconds for g in gates)
    print(f"\nAll {len(gates)} gates passed in {total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
