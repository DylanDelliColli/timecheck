# Working on timecheck

timecheck is a fresh project built by an [Alleyoop](https://github.com/DylanDelliColli/alleyoop)
chief team: one long-lived chief that plans, dispatches and merges, and fresh
workers that each deliver one unit. The operator owns product direction, the PRD,
the release brief, taste and any authority the brief does not grant. The chief
talks to the operator directly.

## Product sources

- PRD: `docs/PRD.md`
- Current release brief: `docs/releases/v1.md`
- Release bead: `timecheck-wfn`

At setup (2026-10-08) both documents were placeholders and the operator had given
no product direction yet. Nothing in them is a product commitment until the
operator approves it and the approval is recorded on the release bead.

## Tracker and memory

This project uses **br** (Beads Rust) with the `timecheck` prefix: a SQLite + JSONL
store in `.beads/`, shared by every worktree of this repository. Never run `bd`
against it. Run `br prime` to get started. Use `br update`, never `br edit`
(it opens an editor). `--notes` replaces the field; append with
`br comments add ID --file PATH`.

Capture incidental discoveries with `jot` (path, symptom, repro). Durable lessons
go in `jot memory` / `jot remember`; no Markdown memory files. Workers write with
`JOT_AGENT=worker`; the chief curates that scope with `jot study --agent worker`.

## Branches, worktrees and merging

- `main` is the base branch. It stays frozen during a release except through the
  brief's interrupt policy. Merging into `main` and deploying belong to the
  operator unless the brief grants otherwise.
- The chief cuts `release/<name>` from `main` once the brief is approved and
  records the base commit on the release bead.
- Worker worktrees are siblings of this checkout:
  `/home/ddc/dev-env/timecheck-wk-<bead>`, on a branch of the same name cut
  from the release branch. Whoever creates a worktree removes it after checking
  for live processes and uncommitted or evidentiary content.
- Only the chief merges into the release branch. There is no Git remote yet;
  integration is by local merge until the operator establishes one.

## Engineering

- Write the failing behavioral test first, then the implementation. Integration
  tests exercise real composition, not mocks.
- The stack and the required check command are not chosen yet. The chief records
  them here once the design record settles them, so every worker runs the same
  checks.
- Run potentially long commands in the background and own their results.

## Non-interactive shell commands

Commands such as `cp`, `mv` and `rm` may be aliased to interactive mode. Use
`cp -f`, `mv -f`, `rm -f` / `rm -rf`, `-y` for package managers,
`-o BatchMode=yes` for ssh/scp, and `HOMEBREW_NO_AUTO_UPDATE=1` for brew.
`br init` must never overwrite a populated store.


<!-- br-agent-instructions-v1 -->

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

<!-- end-br-agent-instructions -->
