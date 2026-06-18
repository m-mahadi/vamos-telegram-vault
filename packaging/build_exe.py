"""Build a standalone Windows executable for Vamos Vault.

Usage (from the repo root, inside your virtualenv):

    python -m pip install -e ".[build]"
    python packaging/build_exe.py            # one-file exe (default)
    python packaging/build_exe.py --onedir   # faster-starting folder build

The resulting executable is written to ``dist/`` (git-ignored). Ship it as a
GitHub Release asset, or copy it next to a ``vault.json`` to run it in place.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "Vamos Vault"


def build(onefile: bool) -> Path:
    entry = REPO_ROOT / "packaging" / "desktop_entry.py"
    icon = REPO_ROOT / "assets" / "vamos-vault.ico"
    src = REPO_ROOT / "src"
    dist = REPO_ROOT / "dist"
    work = REPO_ROOT / "build"
    spec = REPO_ROOT / "build" / "spec"

    for folder in (dist, work, spec):
        folder.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile" if onefile else "--onedir",
        "--name",
        APP_NAME,
        "--paths",
        str(src),
        "--hidden-import",
        "imageio_ffmpeg",
        "--collect-all",
        "imageio_ffmpeg",
        "--collect-submodules",
        "telethon",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(spec),
    ]
    if icon.exists():
        cmd += ["--icon", str(icon)]
    cmd.append(str(entry))

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    exe = dist / (f"{APP_NAME}.exe" if onefile else f"{APP_NAME}/{APP_NAME}.exe")
    if not exe.exists():
        raise SystemExit(f"Build finished but executable not found: {exe}")
    return exe


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Vamos Vault Windows executable.")
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="Build a folder distribution instead of a single-file exe.",
    )
    args = parser.parse_args()

    if shutil.which("pyinstaller") is None:
        try:
            import PyInstaller  # noqa: F401
        except ImportError:
            raise SystemExit(
                'PyInstaller is not installed. Run: python -m pip install -e ".[build]"'
            )

    exe = build(onefile=not args.onedir)
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"\nBuilt {exe} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
