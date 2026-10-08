# Working on timecheck

timecheck is built by an [Alleyoop](https://github.com/DylanDelliColli/alleyoop)
chief team: one long-lived chief that plans, dispatches and merges, and fresh
workers that each deliver one unit. The operator owns product direction, the PRD,
the release brief, taste and any authority the brief does not grant. The chief
talks to the operator directly.

## Product sources

- PRD: `docs/PRD.md`
- Current release brief: `docs/releases/v1.md`
- Design record for v1: `docs/releases/v1-design.md` (interfaces every unit codes
  against; a change to one goes through the chief)
- Release bead: `timecheck-wfn`

Both product documents were approved on 2026-10-08 (release bead, comments 4 and 5).
A changed hash needs its operator-approved change established, not assumed.

## What v1 is

An openly licensed, provenance-first graph of wristwatch references and calibers,
delivered as data files in git compiled into SQLite with canonical views and a CLI.
There is no frontend in v1. Every relationship is a claim with evidence (pinned
archived snapshot, hash, exact quote). **No agent writes a catalogue fact from
memory; a claim you cannot cite is not entered.** Licence: `data/` under ODbL 1.0 +
DbCL, code under MIT, DCO sign-off on every commit (`git commit -s`).

## Tracker and memory

This project uses **br** (Beads Rust) with the `timecheck` prefix: a SQLite + JSONL
store in `.beads/`, shared by every worktree of this repository. Never run `bd`
against it. Use `br update`, never `br edit` (it opens an editor). `--notes` replaces
the field; append with `br comments add ID --file PATH`.

Capture incidental discoveries with `jot` (path, symptom, repro). Durable lessons
go in `jot memory` / `jot remember`; no Markdown memory files. Workers write with
`JOT_AGENT=worker`; the chief curates that scope with `jot study --agent worker`.

## Branches, worktrees and merging

- `main` is the base branch. It is frozen during the release except through the
  brief's interrupt policy. Merging into `main` belongs to the operator.
- Release branch: `release/v1`, cut from `main` at `a0953309e527ebac912b0f2e36336f0672320280`.
- Remote: `origin` = `git@github.com:DylanDelliColli/timecheck.git` (private).
- Worker worktrees are siblings of this checkout:
  `/home/ddc/dev-env/timecheck-wk-<bead>`, on a branch of the same name cut from
  `release/v1`. Whoever creates a worktree removes it after checking for live
  processes and uncommitted or evidentiary content.
- Workers push their branch and open a pull request into `release/v1`
  (`gh pr create --base release/v1`), with the unit's beads and the check output in
  the description. Workers never merge. Only the chief merges into `release/v1`, on
  the exact head whose checks passed, after an independent review.

## Stack and required checks

- Python 3.13 (`python3` on PATH). Each worktree has its own virtual environment:
  `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` (dependencies are
  pinned in `pyproject.toml`; add a dependency only with a pinned version and a
  reason on your bead).
- Package `timecheck` (src layout) with the console script `timecheck`
  (`build`, `query`, `id`, `snapshot` subcommands as the design record defines).
- SQLite via the standard library; no ORM; schemas are JSON Schema files under
  `schemas/`.
- Required check, run from the worktree root before every PR and by CI:
  `scripts/check.sh` = `.venv/bin/python -m pytest -q`, then
  `.venv/bin/timecheck build --strict --data-dir tests/fixtures/data --snapshot-dir tests/snapshots`
  (synthetic fixtures, evidence verified), then
  `.venv/bin/timecheck build --strict --no-evidence --data-dir data`
  (real seed, schema and integrity only). All three must pass with no network; real
  snapshot bytes are never committed. Report unexpected failures or warnings on your
  bead; do not dismiss them as pre-existing.

## Engineering

- Write the failing behavioral test first, then the implementation. Integration
  tests run the real build on fixture data and query the real SQLite file; no mocks
  of the build, the matcher or the database.
- Evidence verification against live archives needs the network; tests use
  `tests/snapshots/<sha256>.bin` fixtures through `--snapshot-dir`.
- Run potentially long commands in the background and own their results. The host
  is shared: one build or test run at a time per worker.

## Non-interactive shell commands

Commands such as `cp`, `mv` and `rm` may be aliased to interactive mode. Use
`cp -f`, `mv -f`, `rm -f` / `rm -rf`, `-y` for package managers,
`-o BatchMode=yes` for ssh/scp, and `HOMEBREW_NO_AUTO_UPDATE=1` for brew.
`br init` must never overwrite a populated store.


---

## Beads Workflow Integration

This project uses [beads_rust](https://github.com/Dicklesworthstone/beads_rust) (`br`/`bd`) for issue tracking. Issues are stored in `.beads/` and tracked in git.

### Essential Commands

```bash
# View ready issues (open, unblocked, not deferred)
br ready              # or: bd ready

# List and search
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br search "keyword"   # Full-text search

# Create and update
br create --title="..." --description="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>  # Close multiple issues at once

# Sync with git
br sync --flush-only  # Export DB to JSONL
br sync --status      # Check sync status
```

### Workflow Pattern

1. **Start**: Run `br ready` to find actionable work
2. **Claim**: Use `br update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `br close <id>`
5. **Sync**: Always run `br sync --flush-only` at session end

### Key Concepts

- **Dependencies**: Issues can block other issues. `br ready` shows only open, unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers 0-4, not words)
- **Types**: task, bug, feature, epic, chore, docs, question
- **Blocking**: `br dep add <issue> <depends-on>` to add dependencies

### Session Protocol

**Before ending any session, run this checklist:**

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync --flush-only    # Export beads changes to JSONL
git commit -m "..."     # Commit everything
git push                # Push to remote
```

### Best Practices

- Check `br ready` at session start to find available work
- Update status as you work (in_progress → closed)
- Create new issues with `br create` when you discover tasks
- Use descriptive titles and set appropriate priority/type
- Always sync before ending session
