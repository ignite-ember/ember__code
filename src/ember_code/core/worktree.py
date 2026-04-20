"""Git worktree lifecycle manager for isolated parallel sessions."""

import logging
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

WORKTREE_DIR = Path.home() / ".ember" / "worktrees"


class WorktreeInfo(BaseModel):
    """Information about an active git worktree."""

    worktree_path: Path
    branch_name: str
    original_dir: Path


class WorktreeManager:
    """Create, inspect, and clean up git worktrees for isolated sessions.

    Worktrees are created under ``~/.ember/worktrees/<branch_name>/``
    so they don't clutter the project directory.
    """

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir.resolve()
        self._info: WorktreeInfo | None = None
        self._validate_git_repo()

    def _validate_git_repo(self) -> None:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Not a git repository: {self.repo_dir}")

    def create(self, branch_name: str | None = None, session_id: str | None = None) -> WorktreeInfo:
        """Create a new git worktree on a fresh branch.

        Args:
            branch_name: Explicit branch name. Auto-generated if None.
            session_id: Used for auto-generated branch name.

        Returns:
            WorktreeInfo with the worktree path and branch name.
        """
        if branch_name is None:
            suffix = session_id or _short_uuid()
            branch_name = f"ember-worktree-{suffix}"

        WORKTREE_DIR.mkdir(parents=True, exist_ok=True)
        worktree_path = WORKTREE_DIR / branch_name

        if worktree_path.exists():
            raise RuntimeError(
                f"Worktree path already exists: {worktree_path}. "
                f"Run 'git worktree remove {worktree_path}' to clean up."
            )

        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {result.stderr.strip()}")

        self._info = WorktreeInfo(
            worktree_path=worktree_path,
            branch_name=branch_name,
            original_dir=self.repo_dir,
        )
        logger.info("Created worktree at %s (branch: %s)", worktree_path, branch_name)
        return self._info

    @property
    def info(self) -> WorktreeInfo | None:
        return self._info

    def has_changes(self) -> bool:
        """Check if the worktree has uncommitted or staged changes."""
        if self._info is None:
            return False
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self._info.worktree_path,
            capture_output=True,
            text=True,
        )
        return bool(result.stdout.strip())

    def cleanup(self) -> bool:
        """Remove the worktree and its branch if no changes were made.

        Returns:
            True if cleaned up, False if changes exist (worktree preserved).
        """
        if self._info is None:
            return True

        if self.has_changes():
            logger.info(
                "Worktree has changes — preserving at %s (branch: %s)",
                self._info.worktree_path,
                self._info.branch_name,
            )
            return False

        wt_path = self._info.worktree_path
        branch = self._info.branch_name

        # Remove worktree
        subprocess.run(
            ["git", "worktree", "remove", str(wt_path), "--force"],
            cwd=self._info.original_dir,
            capture_output=True,
            text=True,
        )

        # Delete the branch (safe — no changes)
        subprocess.run(
            ["git", "branch", "-d", branch],
            cwd=self._info.original_dir,
            capture_output=True,
            text=True,
        )

        logger.info("Cleaned up worktree at %s (branch: %s)", wt_path, branch)
        self._info = None
        return True


def cleanup_stale_worktrees(repo_dir: Path) -> list[str]:
    """Remove stale worktrees that reference missing directories.

    Returns list of cleaned-up branch names.
    """
    cleaned: list[str] = []
    if not WORKTREE_DIR.exists():
        return cleaned

    # Prune worktrees that reference missing dirs
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )

    # Remove empty directories left behind
    for child in WORKTREE_DIR.iterdir():
        if child.is_dir() and not any(child.iterdir()):
            shutil.rmtree(child, ignore_errors=True)
            cleaned.append(child.name)

    return cleaned


def _short_uuid() -> str:
    import uuid

    return str(uuid.uuid4())[:8]
