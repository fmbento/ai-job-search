"""Local-pristine detection for guard tests that assert sentinel content.

Guards like test_placeholder_integrity assert that a template file still
carries its /setup placeholder sentinels. That premise holds on CI and on
fresh clones, but not on a fork whose local file was legitimately
personalized. git status cannot provide this: skip-worktree files are
reported clean regardless of content, so the bytes are compared directly
against HEAD's copy.
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def file_is_pristine(rel_path: str) -> bool:
    """True when the working-tree file is byte-identical to HEAD's copy."""
    head = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        cwd=REPO,
        capture_output=True,
    )
    if head.returncode != 0:
        return False
    return (REPO / rel_path).read_bytes() == head.stdout
