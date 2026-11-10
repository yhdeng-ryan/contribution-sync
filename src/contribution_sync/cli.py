import argparse
import json
from pathlib import Path
import sys

from .config import load_config
from .git_history import git, scan
from .planner import make_plan
from .writer import apply_plan, push_destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Mirror work commit activity locally; optionally push after apply.")
    parser.add_argument("command", choices=("scan", "plan", "apply"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Write counts-only JSON preview outside all Git repositories")
    parser.add_argument("--push", action="store_true", help="After apply succeeds, push the destination branch to origin (no force)")
    parser.add_argument("--group-by", choices=("day", "repo"), default=None,
                        help="Group scan/plan counts by day (default) or source repository")
    args = parser.parse_args(argv)
    if args.output and args.command != "plan":
        parser.error("--output is only supported for plan")
    if args.push and args.command != "apply":
        parser.error("--push is only supported for apply")
    if args.group_by is not None and args.command == "apply":
        parser.error("--group-by is only supported for scan and plan")
    group_by = args.group_by or "day"
    try:
        config = load_config(args.config)
        if args.command == "scan":
            from collections import Counter
            activities = scan(config)
            result = {"matched_source_commits": len(activities),
                      "repo_commits" if group_by == "repo" else "daily_commits": dict(sorted(Counter(
                          a.repository if group_by == "repo" else a.timestamp[:10] for a in activities
                      ).items()))}
        else:
            plan = make_plan(config)
            result = plan.preview(group_by)
            if args.command == "apply":
                result["created_empty_commits"] = apply_plan(config, plan)
                if args.push:
                    push_destination(config)
                    result["pushed"] = True
        rendered = json.dumps(result, indent=2) + "\n"
        if args.output:
            output = args.output.resolve()
            # Keep previews outside Git repositories, including nested source clones.
            try:
                git(output.parent, "rev-parse", "--show-toplevel")
            except ValueError as exc:
                if "not a git repository" not in str(exc):
                    raise ValueError("Cannot verify preview output location; choose an existing directory outside Git repositories") from exc
            else:
                raise ValueError("Preview output must be outside Git repositories")
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
