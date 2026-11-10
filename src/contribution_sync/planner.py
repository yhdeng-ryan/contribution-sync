from collections import Counter
from dataclasses import dataclass
import re

from .git_history import Activity, ensure_root, git, scan


@dataclass(frozen=True)
class Plan:
    head: str
    matched: int
    activities: tuple[Activity, ...]

    def preview(self, group_by: str = "day") -> dict:
        return {
            "matched_source_commits": self.matched,
            "already_imported": self.matched - len(self.activities),
            "new_empty_commits": len(self.activities),
            "repo_new_commits" if group_by == "repo" else "daily_new_commits": dict(sorted(Counter(
                a.repository if group_by == "repo" else a.timestamp[:10] for a in self.activities
            ).items())),
        }


def destination_head(config) -> str:
    ensure_root(config.destination)
    git(config.destination, "check-ref-format", f"refs/heads/{config.branch}")
    if git(config.destination, "symbolic-ref", "HEAD") != f"refs/heads/{config.branch}":
        raise ValueError(f"Destination must have branch {config.branch!r} checked out")
    if git(config.destination, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Destination must have a clean working tree and index")
    git_dir = config.destination / git(config.destination, "rev-parse", "--git-dir")
    if any((git_dir / name).exists() for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer")):
        raise ValueError("Finish the destination's in-progress Git operation first")
    return git(config.destination, "rev-parse", "--verify", "HEAD")


def make_plan(config) -> Plan:
    head = destination_head(config)
    history = git(config.destination, "log", "--no-show-signature", "--no-notes", "--format=%B", head, "--")
    imported = set(re.findall(r"^Activity-ID: ([0-9a-f]{64})$", history, flags=re.MULTILINE))
    activities = scan(config)
    return Plan(head, len(activities), tuple(a for a in activities if a.id not in imported))
