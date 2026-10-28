# P0-E: Managed Workspace bootstrap (local CLI only)

## Shared policy v2 synchronization

Global rules are versioned and read by Codex before each new or resumed managed task. A newly bootstrapped workspace receives the approved v2 block from `templates/CODEX_GLOBAL.md`. Existing installations require an operator-approved `gpt2codex workspace sync-policy --id gpt2codex` command; it validates known v1/v2 blocks, appends missing versions, preserves unrelated user text, and stops on unexpected edits inside a managed block. This does not grant remote MCP write access.


## Accepted behavior

The bridge owns managed-project bootstrap and persistent project configuration.
Codex reads instructions, but **does not** create `.tmp` / `.log` symlinks,
Git identity settings, checkout configuration, or shared rules.

The first managed project is this repository:

- `project_id = gpt2codex`
- Current local directory: `gpt2codex`, located directly under `project_dir` (GitHub naming is independent of the local checkout).
- GitHub target: `Pitriss/gpt2codex` (rename authorized; verify the result before treating the target as current).
- Private work areas: `./.tmp -> /tmp/gpt2codex/tmp` and `./.log -> /tmp/gpt2codex/log`
- Shared rules: `<project_dir>/.ai/`
- Persistent global configuration: `$XDG_CONFIG_HOME/chatgpt2codex/config.toml` (with fallback to `~/.config`)
- Per-project configuration: `.../chatgpt2codex/projects/gpt2codex.toml`
- Git author: only local `pitriss <5106460+Pitriss@users.noreply.github.com>`

The P0-E helper discovers the directory name from the real Git checkout root
instead of assuming it matches the GitHub repository name.

Bootstrap is a **local, explicit write operation**, not exposed to ChatGPT
through MCP in P0-E. `workspace bootstrap` registers an existing normal Git
checkout. It does not clone a repo or contact GitHub.

## Rust CLI

```
gpt2codex workspace bootstrap --project-dir /home/peva/TEMP/mycode --id gpt2codex --directory gpt2codex --git-name pitriss --git-email 5106460+Pitriss@users.noreply.github.com --codex-name Kóďa
gpt2codex workspace health --id gpt2codex
gpt2codex workspace ensure --id gpt2codex
gpt2codex project info --id gpt2codex
gpt2codex project sessions --id gpt2codex
```

`workspace bootstrap` and `workspace ensure` are idempotent, additive-only
operations. They install the versioned defaults packaged into the Rust binary
only where a file is missing. Existing AGENTS.md, project context, overrides
and shared rules are not overwritten. The bootstrap creates the global TOML
if missing and registers only the expressly requested project; it does **not**
automatically enroll neighboring repositories.

The exact `/tmp/<projectid>` location is deliberate. The bridge checks that
`/tmp` is a genuine sticky directory, the project work directory and its
`tmp` and `log` subdirectories are owned by the current user with mode `0700`,
and `.tmp` / `.log` are symlinks to the **exact** authorized destinations.
Conflicts abort the operation without overwriting the conflicting object.
If tmpfs is cleared on reboot, `workspace ensure` recreates the missing targets.

The bridge also appends `/.tmp`, `/.log`, and `/.ai/.project_codex.md` to the
**local** `.git/info/exclude`, preserving existing content. No `.gitignore`
change is required. Existing Git identity values are retained if correct;
conflicting values cause a hard error rather than silent replacement.

## Constraints and incomplete work

- Main Rust daemon, MCP gateway, persistent task state and approval agent are **not** part of P0-E.
- No arbitrary remote filesystem or command tool is introduced.
- P0-E supports ordinary `.git/` checkouts for write bootstrap, not linked worktrees.
- First-time initialization is additive; it is not a transactional filesystem rollback.
- OS path checks are suitable for a local operator-triggered bootstrap, not yet a
  security boundary against a concurrent, malicious process running as the same user.
  Before enabling remote write operations, use descriptor-relative/openat2 checks,
  strict sandboxing and recorded local approvals.
- Runtime `/tmp` directories and contents are volatile. Permanent audit / approvals
  will live elsewhere; never place secrets in generated logs.
- Shared templates installed into `<project_dir>/.ai` are user-editable and preserved
  by re-runs. Changes to template versions do not auto-overwrite local modifications.

## P0-E validation criteria

1. Unit tests for creation, rerun, recovery from cleaned `/tmp`, and denial of
   conflicting symlinks, insecure temp directories, unapproved Git identity
   replacement and invalid IDs.
2. Real host: run `workspace bootstrap` for `gpt2codex`, followed by `health`.
3. Confirm only `gpt2codex` was persistently registered and no other project changed.
4. Inspect workspace symlinks and Git exclusion, and confirm existing AI context
   documents remain untouched.
5. No commit, push, package installation, branch switch or service creation.

## P0-F extension

The `workspace adopt` operation integrates existing checkouts, preserving
existing `AGENTS.md`, project context and local Git identity. See
`P0_EXISTING_PROJECTS.md` for safe dry-run, conflict handling and per-project
configuration. The original P0-E `bootstrap` behavior for `gpt2codex` is
unchanged.
