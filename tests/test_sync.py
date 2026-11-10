from pathlib import Path
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from contribution_sync.config import Config, Source, load_config
from contribution_sync.git_history import git
from contribution_sync.planner import make_plan
from contribution_sync.writer import apply_plan
from contribution_sync.cli import main


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.repo("source")
        self.destination = self.repo("destination")
        self.config = Config(self.destination, "main", "Personal Name", "personal@example.test",
                             frozenset({"work@example.test"}), (Source(self.source, "refs/heads/main"),))

    def repo(self, name):
        path = self.root / name
        path.mkdir()
        git(path, "init", "-b", "main")
        git(path, "config", "user.name", "Local Default")
        git(path, "config", "user.email", "default@example.test")
        git(path, "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", "Initial")
        return path

    def commit(self, email="work@example.test", date="2024-06-12T15:16:17-04:00"):
        return git(self.source, "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", "Secret project details",
                   extra_env={"GIT_AUTHOR_NAME": "Work Name", "GIT_AUTHOR_EMAIL": email,
                              "GIT_COMMITTER_NAME": "Work Name", "GIT_COMMITTER_EMAIL": email,
                              "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})

    def test_filter_dates_privacy_idempotency_read_only_source(self):
        (self.source / "company-secret.txt").write_text("Proprietary source content")
        git(self.source, "add", "company-secret.txt")
        self.commit()
        self.commit("someone-work@example.test")
        self.commit(date="2024-06-13T09:12:13+05:30")
        source_head = git(self.source, "rev-parse", "HEAD")
        plan = make_plan(self.config)
        self.assertEqual(plan.preview()["new_empty_commits"], 2)
        old_tree = git(self.destination, "rev-parse", "HEAD^{tree}")
        self.assertEqual(apply_plan(self.config, plan), 2)
        self.assertEqual(git(self.destination, "rev-parse", "HEAD^{tree}"), old_tree)
        history = git(self.destination, "log", "-2", "--format=%an|%ae|%cn|%ce|%aI|%cI|%B")
        self.assertIn("Personal Name|personal@example.test|Personal Name|personal@example.test|2024-06-12T15:16:17-04:00|2024-06-12T15:16:17-04:00", history)
        self.assertIn("2024-06-13T09:12:13+05:30|2024-06-13T09:12:13+05:30", history)
        self.assertNotIn("Secret project", history)
        self.assertNotIn("work@example.test", history)
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), source_head)
        self.assertEqual(git(self.source, "status", "--porcelain"), "")
        self.assertEqual(apply_plan(self.config, make_plan(self.config)), 0)

    def test_overlapping_clones(self):
        self.commit()
        clone = self.root / "clone"
        git(self.root, "clone", str(self.source), str(clone))
        config = Config(self.destination, "main", self.config.name, self.config.email,
                        self.config.work_emails, (Source(self.source, "main"), Source(clone, "main")))
        self.assertEqual(len(make_plan(config).activities), 1)

    def test_dirty_and_wrong_branch_rejected(self):
        file = self.destination / "private.txt"
        file.write_text("Do not commit")
        with self.assertRaisesRegex(ValueError, "clean"):
            make_plan(self.config)
        git(self.destination, "add", "private.txt")
        with self.assertRaisesRegex(ValueError, "clean"):
            make_plan(self.config)
        git(self.destination, "reset", "--", "private.txt")
        file.unlink()
        git(self.destination, "checkout", "-b", "other")
        with self.assertRaisesRegex(ValueError, "checked out"):
            make_plan(self.config)

    def test_failure_does_not_advance_branch(self):
        self.commit()
        self.commit(date="2024-06-13T10:00:00+00:00")
        plan = make_plan(self.config)
        calls = 0

        def failing_git(path, *args, **kwargs):
            nonlocal calls
            if "commit-tree" in args:
                calls += 1
                if calls == 2:
                    raise ValueError("Simulated failure")
            return git(path, *args, **kwargs)

        with patch("contribution_sync.writer.git", side_effect=failing_git):
            with self.assertRaisesRegex(ValueError, "Simulated"):
                apply_plan(self.config, plan)
        self.assertEqual(git(self.destination, "rev-parse", "HEAD"), plan.head)
        self.assertEqual(len(make_plan(self.config).activities), 2)

    def test_stale_plan_rejected(self):
        self.commit()
        plan = make_plan(self.config)
        git(self.destination, "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", "Concurrent commit")
        with self.assertRaisesRegex(ValueError, "changed"):
            apply_plan(self.config, plan)

    def test_default_branch_excludes_feature_commits(self):
        self.commit()
        git(self.source, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.source, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        git(self.source, "checkout", "-b", "feature")
        self.commit(date="2024-06-14T10:00:00+00:00")
        config = Config(self.destination, "main", self.config.name, self.config.email,
                        self.config.work_emails, (Source(self.source),))
        self.assertEqual(len(make_plan(config).activities), 1)

    def config_file(self):
        path = self.root / "config.toml"
        path.write_text('work_emails = ["work@example.test"]\n[destination]\npath = "destination"\nname = "Personal"\nemail = "personal@example.test"\n[[sources]]\npath = "source"\nref = "main"\n')
        return path

    def test_config_relative_paths(self):
        config = load_config(self.config_file())
        self.assertEqual(config.destination, self.destination.resolve())
        self.assertEqual(config.sources[0].path, self.source.resolve())

    def test_cli_plan_then_apply(self):
        self.commit()
        path = self.config_file()
        runner = Path(__file__).resolve().parents[1] / "sync.py"
        old_head = git(self.destination, "rev-parse", "HEAD")
        for index, command in enumerate(("scan", "plan", "apply", "plan")):
            result = subprocess.run([sys.executable, str(runner), command, "--config", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if index < 2:
                self.assertEqual(git(self.destination, "rev-parse", "HEAD"), old_head)
        self.assertIn('"new_empty_commits": 0', result.stdout)

    def test_preview_output_rejected_inside_repository(self):
        path = self.config_file()
        runner = Path(__file__).resolve().parents[1] / "sync.py"
        output = self.destination / "preview.json"
        result = subprocess.run([sys.executable, str(runner), "plan", "--config", str(path), "--output", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("outside Git repositories", result.stderr)
        self.assertFalse(output.exists())

    def test_repo_grouping_cli_and_duplicate_attribution(self):
        self.commit()
        self.commit(date="2024-06-13T10:00:00+00:00")
        config_path = self.config_file()
        clone = self.root / "clone"
        git(self.root, "clone", str(self.source), str(clone))
        with config_path.open("a") as stream:
            stream.write('\n[[sources]]\npath = "clone"\nref = "main"\n')
        for command, key in (("scan", "repo_commits"), ("plan", "repo_new_commits")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([command, "--config", str(config_path), "--group-by", "repo"]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result[key], {"source": 2})
            self.assertEqual(result["matched_source_commits"], 2)
        plan = make_plan(load_config(config_path))
        apply_plan(load_config(config_path), plan)
        self.assertEqual(make_plan(load_config(config_path)).preview("repo")["repo_new_commits"], {})

    def test_same_name_sources_have_distinct_labels(self):
        self.commit()
        nested = self.root / "nested"
        nested.mkdir()
        other = nested / "source"
        git(self.root, "clone", str(self.source), str(other))
        config = Config(self.destination, "main", self.config.name, self.config.email,
                        self.config.work_emails, (Source(self.source, "main"), Source(other, "main")))
        self.assertEqual(make_plan(config).preview("repo")["repo_new_commits"], {self.source.as_posix(): 1})

    def test_apply_push_and_retry_without_new_commits(self):
        self.commit()
        remote = self.root / "remote.git"
        git(self.root, "init", "--bare", str(remote))
        git(self.destination, "remote", "add", "origin", str(remote))
        path = self.config_file()
        for expected_count in (1, 0):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["apply", "--config", str(path), "--push"]), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["created_empty_commits"], expected_count)
            self.assertTrue(result["pushed"])
            self.assertEqual(git(remote, "rev-parse", "refs/heads/main"), git(self.destination, "rev-parse", "HEAD"))

    def test_push_failure_retains_commits_and_retry_is_idempotent(self):
        self.commit()
        path = self.config_file()
        old_head = git(self.destination, "rev-parse", "HEAD")
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(["apply", "--config", str(path), "--push"]), 1)
        self.assertIn("Local commits are retained", error.getvalue())
        self.assertNotEqual(git(self.destination, "rev-parse", "HEAD"), old_head)
        self.assertEqual(len(make_plan(load_config(path)).activities), 0)

    def test_no_push_by_default_or_after_apply_failure(self):
        path = self.config_file()
        with patch("contribution_sync.cli.push_destination") as push:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["apply", "--config", str(path)]), 0)
            push.assert_not_called()
            with patch("contribution_sync.cli.apply_plan", side_effect=ValueError("Apply failed")):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["apply", "--config", str(path), "--push"]), 1)
            push.assert_not_called()

    def test_scan_and_plan_reject_push(self):
        for command in ("scan", "plan"):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main([command, "--config", "unused.toml", "--push"])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
