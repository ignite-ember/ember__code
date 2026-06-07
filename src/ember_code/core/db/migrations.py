"""Programmatic alembic upgrade — runs on Database init.

Why programmatic vs. shell-out: callers (tests, the BE process) need a
synchronous "ensure schema is current" hook. Shelling out to ``alembic
upgrade head`` would couple us to a working CWD and the alembic CLI on
PATH; the Python API works from anywhere our package is importable.
"""

from __future__ import annotations

import threading
from pathlib import Path

from alembic import command
from alembic.config import Config

from ember_code.core.db.engine import sync_url

# ``alembic.ini`` and ``migrations/`` live inside the ``ember_code``
# package (``src/ember_code/alembic.ini``, ``src/ember_code/migrations/``)
# so non-source-tree installs (Homebrew, pipx, system pip) ship them as
# package data. ``parents[2]`` walks ``db/migrations.py → db → core →
# ember_code``.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _PACKAGE_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _PACKAGE_ROOT / "migrations"

_lock = threading.Lock()
_upgraded_paths: set[str] = set()


def _resolve_paths() -> tuple[Path, Path]:
    """Locate ``alembic.ini`` + ``migrations/`` inside the package.

    Both files are shipped as package data; the in-package layout is
    the only supported one. Raises if either is missing so a botched
    install fails loudly instead of silently re-running migrations
    against a half-set-up DB.
    """
    if _ALEMBIC_INI.exists() and _MIGRATIONS_DIR.is_dir():
        return _ALEMBIC_INI, _MIGRATIONS_DIR
    raise FileNotFoundError(
        f"alembic.ini and migrations/ missing from package at {_PACKAGE_ROOT}. "
        "This usually means the wheel was built without package-data — "
        "reinstall via `pip install --force-reinstall ignite-ember` or "
        "`brew reinstall ignite-ember`."
    )


def upgrade_to_head(db_path: str | Path) -> None:
    """Run alembic ``upgrade head`` against the SQLite file at ``db_path``.

    Idempotent and cached per resolved path so multiple constructions in
    the same process don't re-run migrations.
    """
    resolved_path = Path(str(db_path)).expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = str(resolved_path)
    with _lock:
        if resolved in _upgraded_paths:
            return

        ini_path, _ = _resolve_paths()
        cfg = Config(str(ini_path))
        cfg.set_main_option("sqlalchemy.url", sync_url(resolved))
        command.upgrade(cfg, "head")
        _upgraded_paths.add(resolved)
