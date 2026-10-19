"""Start Madam Flasher QR.

    python app.py                  set up .venv if needed, start the server, open Chrome
    python app.py --no-browser     same, without opening Chrome
    python app.py --config PATH    use another config file

Works with any Python 3.11+: if not already running inside the project's .venv, it creates the venv,
installs requirements.txt (only when it changed) and re-runs itself with the venv's Python.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.installed"


def in_project_venv() -> bool:
    return Path(sys.prefix).resolve() == VENV.resolve()


def ensure_requirements(python: Path | str) -> None:
    wanted = REQUIREMENTS.read_bytes()
    if STAMP.exists() and STAMP.read_bytes() == wanted:
        return
    print("Installing requirements...")
    subprocess.check_call([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q",
                           "-r", str(REQUIREMENTS)])
    STAMP.write_bytes(wanted)


def bootstrap() -> int:
    """Create/update .venv and re-run this script inside it. Returns the child's exit code."""
    if not VENV_PY.exists():
        print(f"Creating virtual environment in {VENV} ...")
        venv.create(VENV, with_pip=True)
    ensure_requirements(VENV_PY)
    try:
        return subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT)
    except KeyboardInterrupt:
        return 0


def run() -> None:
    ensure_requirements(sys.executable)
    args = sys.argv[1:]
    if "--no-browser" in args:
        args.remove("--no-browser")
    elif "--open" not in args:
        args.append("--open")
    sys.argv = [sys.argv[0], *args]

    from app.main import main  # the app/ package takes precedence over this app.py module
    try:
        main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        sys.exit(f"Python 3.11+ is required (this is {sys.version.split()[0]}).")
    os.chdir(ROOT)
    if in_project_venv():
        run()
    else:
        sys.exit(bootstrap())
