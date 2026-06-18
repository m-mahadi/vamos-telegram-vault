"""PyInstaller entry point for the Vamos Vault desktop app.

When frozen, the launcher (or the user double-clicking the exe) sets the working
directory. We resolve the app root by looking for ``vault.json`` starting from
the current directory and then walking up from the executable, so the bundled
exe finds the local catalog regardless of where it is launched from.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "vault.json").exists():
        return cwd
    exe = Path(sys.executable).resolve()
    for parent in [exe.parent, *exe.parents]:
        if (parent / "vault.json").exists():
            return parent
    return cwd


def main() -> None:
    os.chdir(_app_root())
    from vamos_vault.desktop import main as run

    run()


if __name__ == "__main__":
    main()
