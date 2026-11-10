from collections import Counter

from .git_history import git
from .planner import destination_head


def push_destination(config) -> None:
    ref = f"refs/heads/{config.branch}"
    try:
        git(config.destination, "-c", "remote.origin.mirror=false", "push", "--no-follow-tags",
            "origin", f"{ref}:{ref}")
    except (ValueError, OSError) as exc:
        raise ValueError(
            "Apply completed locally, but push failed. Local commits are retained. "
            "Resolve the connection/authentication or remote-branch conflict, then rerun apply --push. "
            f"No force push was attempted. Details: {exc}"
        ) from exc


def apply_plan(config, plan) -> int:
    if destination_head(config) != plan.head:
        raise ValueError("Destination changed since planning; run again")
    if not plan.activities:
        return 0
    tree = git(config.destination, "rev-parse", f"{plan.head}^{{tree}}")
    totals = Counter(a.timestamp[:10] for a in plan.activities)
    positions = Counter()
    parent = plan.head
    for activity in plan.activities:
        day = activity.timestamp[:10]
        positions[day] += 1
        message = (
            f"Record private work activity: {day} ({positions[day]}/{totals[day]})\n\n"
            "Empty placeholder representing one authored work commit.\n"
            "Contains no source code or original commit message.\n\n"
            f"Activity-ID: {activity.id}\n"
        )
        parent = git(config.destination, "-c", "commit.gpgSign=false", "commit-tree", tree, "-p", parent,
                     input=message, extra_env={
                         "GIT_AUTHOR_NAME": config.name, "GIT_AUTHOR_EMAIL": config.email,
                         "GIT_COMMITTER_NAME": config.name, "GIT_COMMITTER_EMAIL": config.email,
                         "GIT_AUTHOR_DATE": activity.timestamp, "GIT_COMMITTER_DATE": activity.timestamp,
                     })
    if destination_head(config) != plan.head:
        raise ValueError("Destination changed during generation; branch was not updated")
    git(config.destination, "update-ref", "-m", "contribution-sync: import activity",
        f"refs/heads/{config.branch}", parent, plan.head)
    return len(plan.activities)
