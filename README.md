# contribution-sync

Mirror authored commits from local source repositories as backdated **empty placeholder commits** in a separate destination repository. This reproduces commit activity, not code or original contribution attribution.

Requires Python 3.11+ and command-line Git. No Python dependencies, browser, API token, or installation required. Sources can be existing local clones created with any Git client. Optional pushing uses the destination repository's existing Git authentication, whether HTTPS or SSH.

## Configuration

```text
github_sync/
  contribution-sync/       # Tool source; can be public
  contribution-history/    # Separate destination; private recommended
  local/
    config.toml           # Paths and identities; outside both repositories
    preview.json          # Optional counts-only preview
```

Copy `config.example.toml` to `../local/config.toml` and replace the placeholders. Create `../local/` first if it does not exist. Use the destination account's verified commit email or GitHub noreply address for generated commits. Relative paths resolve from the config file; Windows paths can use forward slashes.

`work_emails` lists the source author emails to include. Matching is exact and case-sensitive against historical commit metadata. A repository's current `user.email` setting affects future commits; it does not change the emails recorded in earlier commits. To inspect an existing commit's author email:

```text
git -C /path/to/source log -1 --format=%ae
```

Add any historical author email addresses you want to include, such as an account's GitHub noreply address. Source author names are not used for filtering. The destination name and email are explicit configuration values; the tool does not modify local or global `user.name` or `user.email` settings.

Sources default to their locally recorded `origin/HEAD` branch. If unavailable, set `ref` explicitly, such as `refs/remotes/origin/main`. Update local clones with your preferred Git client before scanning: this tool never fetches. It scans commits reachable from that reference, including authored merge commits. It does not collect reviews, PRs, issues, or co-author trailers. Squashed or rewritten history can differ from the original graph.

## Run from this directory

```powershell
python sync.py scan --config ../local/config.toml
python sync.py plan --config ../local/config.toml --output ../local/preview.json
python sync.py apply --config ../local/config.toml
```

To display counts by source repository instead of day:

```powershell
python sync.py scan --config ../local/config.toml --group-by repo
python sync.py plan --config ../local/config.toml --group-by repo
```

The default is `--group-by day`. Scan reports `repo_commits`; plan reports `repo_new_commits` for commits not yet imported. Groups with zero commits are omitted. Shared commits are counted once, under the first configured source containing them. Repositories with the same folder name use their full local paths to distinguish them. Repository names/paths appear only in local output (and `--output` previews), never in generated commits.

`scan` reports source daily counts. `plan` checks destination history and reports only missing commits. Neither changes Git history. `apply` recomputes the plan and creates missing empty commits locally. Preview JSON contains counts only and cannot be written inside a Git repository. A saved preview is informational, not executable input.

The destination must have at least one initial commit, a clean working tree/index, and the configured branch (normally `main`) checked out. That branch should be GitHub's default branch. Keep it dedicated to this mirror.

## Commit behavior

- One matching source commit produces one empty commit with your personal author and committer identity.
- Both timestamps reproduce the original **author timestamp and timezone**, including past dates.
- Messages explicitly say they are placeholders. No source code, messages, filenames, branch names, work identities, or raw source hashes are copied.
- A SHA-256-derived `Activity-ID` deduplicates source commits across clones and runs. These deterministic IDs are pseudonymous, not encryption: someone who already knows a source hash could recognize its marker.
- Destination history stores the imported markers. Rewritten source commits have new hashes and count as new. Existing history is never deleted or rewritten. There is no personal-profile check.
- Counts and timestamps still reveal work activity. Keep the destination private and enable private contribution counts on your profile.

The tool uses `git commit-tree` with the destination's unchanged tree, so staged files and source trees are never copied. Commit hooks and signing are bypassed for these generated placeholders. The branch advances once with an expected-old-head check after generation completes. On failure it stays unchanged; unreachable generated Git objects may remain until normal Git garbage collection. Do not edit the destination concurrently with an import.

Global Git settings are never changed. Each configured repository is explicitly trusted for that Git invocation. Inherited `GIT_*` overrides are stripped from local Git subprocesses; persistent Git configuration and credential helpers are still used.

## Keeping the tool repository public

Keep real configuration and generated reports outside the tool repository. The example configuration and tests contain placeholder identities only. Ignore rules provide additional protection for common local config, audit, and preview filenames; they do not remove files already committed to Git history.

Repository grouping displays source names or paths in terminal output and saved previews. Git errors can also display local paths or remote addresses. Review these before posting logs or screenshots. Ignored Python bytecode caches can contain absolute local paths; do not include them in manually assembled source archives.

Git commits expose author/committer names and emails, and the license includes copyright attribution. Review those separately before publishing. A public tool repository does not require its destination repository or local configuration to be public.

## Review and push

```powershell
git -C ../contribution-history log -5 --format=fuller
git -C ../contribution-history diff origin/main..main
git -C ../contribution-history push origin main
```

The import should produce no file changes. A rerun should report zero new commits. Apply stays local unless you explicitly add `--push`:

```powershell
python sync.py apply --config ../local/config.toml --push
```

This pushes only the configured destination branch to the same branch on `origin`, using existing Git authentication. It never force-pushes, mirrors other refs, or adds tags. Push runs only after apply succeeds, including when there are zero new commits (so you can retry a previous failed push). If push fails, the command exits with an error and retains the local commits. Resolve the cause and rerun the same command; already imported activity is not duplicated. `--push` is not accepted for scan or plan.

GitHub controls contribution eligibility and refresh timing; local success does not guarantee immediate profile updates.

Suggested public profile disclosure:

> Some contribution activity represents empty placeholders mirroring my authored commits in private workplace repositories. Only activity timestamps and counts are reproduced; company code and commit details remain private.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use temporary Git repositories, without accessing your accounts or work clones.
