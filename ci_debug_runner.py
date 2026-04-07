from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


LOG_PATH = Path("debug-beb7eb.log")
SESSION_ID = "beb7eb"


def _log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "sessionId": SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def _run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def main() -> int:
    run_id = f"pre-fix-{int(datetime.now(timezone.utc).timestamp())}"
    # region agent log
    _log(
        run_id,
        "H1",
        "ci_debug_runner.py:main",
        "Starting CI debug checks",
        {"cwd": str(Path.cwd()), "pythonExecutable": sys.executable},
    )
    # endregion

    ruff = _run_cmd([sys.executable, "-m", "ruff", "check", "."])
    # region agent log
    _log(
        run_id,
        "H1",
        "ci_debug_runner.py:main",
        "Ruff check finished",
        {
            "exitCode": ruff.returncode,
            "stdoutTail": ruff.stdout[-800:],
            "stderrTail": ruff.stderr[-800:],
        },
    )
    # endregion

    mypy = _run_cmd(
        [
            sys.executable,
            "-m",
            "mypy",
            "active_learning",
            "ais",
            "dashboard/backend",
            "detection",
            "ingestion",
            "shared",
            "tests",
        ]
    )
    # region agent log
    _log(
        run_id,
        "H2",
        "ci_debug_runner.py:main",
        "Mypy check finished",
        {
            "exitCode": mypy.returncode,
            "stdoutTail": mypy.stdout[-800:],
            "stderrTail": mypy.stderr[-800:],
        },
    )
    # endregion

    mypy_imports_ignored = _run_cmd(
        [
            sys.executable,
            "-m",
            "mypy",
            "--ignore-missing-imports",
            "active_learning",
            "ais",
            "dashboard/backend",
            "detection",
            "ingestion",
            "shared",
            "tests",
        ]
    )
    # region agent log
    _log(
        run_id,
        "H4",
        "ci_debug_runner.py:main",
        "Mypy with ignore-missing-imports finished",
        {
            "exitCode": mypy_imports_ignored.returncode,
            "stdoutTail": mypy_imports_ignored.stdout[-800:],
            "stderrTail": mypy_imports_ignored.stderr[-800:],
        },
    )
    # endregion

    mypy_relaxed = _run_cmd(
        [
            sys.executable,
            "-m",
            "mypy",
            "--ignore-missing-imports",
            "--disable-error-code",
            "attr-defined",
            "--disable-error-code",
            "arg-type",
            "--disable-error-code",
            "no-redef",
            "--disable-error-code",
            "misc",
            "--disable-error-code",
            "import-untyped",
            "active_learning",
            "ais",
            "dashboard/backend",
            "detection",
            "ingestion",
            "shared",
            "tests",
        ]
    )
    # region agent log
    _log(
        run_id,
        "H5",
        "ci_debug_runner.py:main",
        "Mypy with relaxed error codes finished",
        {
            "exitCode": mypy_relaxed.returncode,
            "stdoutTail": mypy_relaxed.stdout[-800:],
            "stderrTail": mypy_relaxed.stderr[-800:],
        },
    )
    # endregion

    # region agent log
    _log(
        run_id,
        "H3",
        "ci_debug_runner.py:main",
        "Final CI debug outcome",
        {
            "ruffFailed": ruff.returncode != 0,
            "mypyFailed": mypy.returncode != 0,
            "mypyIgnoreMissingFailed": mypy_imports_ignored.returncode != 0,
            "mypyRelaxedFailed": mypy_relaxed.returncode != 0,
        },
    )
    # endregion
    return 1 if (ruff.returncode != 0 or mypy.returncode != 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
