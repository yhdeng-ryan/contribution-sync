from dataclasses import dataclass
from collections import Counter
from datetime import datetime
import hashlib
import os
from pathlib import Path
import subprocess


def git(path: Path, *args: str, input: str | None = None, extra_env: dict | None = None) -> str:
    # Do not inherit an unrelated repository, index, author, or SSH override.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(extra_env or {})
    result = subprocess.run(
        ["git", "-c", f"safe.directory={path.resolve().as_posix()}", "-C", str(path), *args],
        input=input, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    if result.returncode:
        raise ValueError(f"Git failed in {path}: {result.stderr.strip()}")
    return result.stdout.strip()


def ensure_root(path: Path) -> None:
    root = Path(git(path, "rev-parse", "--show-toplevel")).resolve()
    if root != path.resolve():
        raise ValueError(f"Configure the repository root, not a subdirectory: {path}")


@dataclass(frozen=True)
class Activity:
    id: str
    timestamp: str
    repository: str


def scan(config) -> list[Activity]:
    activities = {}
    name_counts = Counter(source.path.name for source in config.sources)
    for source in config.sources:
        label = source.path.name if name_counts[source.path.name] == 1 else source.path.as_posix()
        ensure_root(source.path)
        ref = source.ref
        if ref is None:
            try:
                ref = git(source.path, "symbolic-ref", "refs/remotes/origin/HEAD")
            except ValueError as exc:
                raise ValueError(f"Cannot detect default branch for {source.path}; set sources.ref explicitly") from exc
        head = git(source.path, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        history = git(source.path, "log", "--no-show-signature", "--no-notes", "--format=%H%x00%ae%x00%aI", head, "--")
        for line in history.splitlines():
            sha, email, timestamp = line.split("\x00")
            if email not in config.work_emails:
                continue
            # One stable ID across clones; no source hashes or names are published.
            identifier = hashlib.sha256(f"contribution-sync:v1:{sha}".encode()).hexdigest()
            datetime.fromisoformat(timestamp)
            # Credit shared history to the first configured source only.
            activities.setdefault(identifier, Activity(identifier, timestamp, label))
    return sorted(activities.values(), key=lambda a: (datetime.fromisoformat(a.timestamp), a.id))
