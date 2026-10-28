# P0-F: Adopt existing projects without replacing their instructions

## Approved scope

Register these existing ordinary Git checkouts beneath the configured `project_dir`:

- `k2-smb` -> `<project_dir>/k2-smb`
- `reddit2tg` -> `<project_dir>/reddit2tg`
- `m365-tui` -> `<project_dir>/m365-tui`

The previously bootstrapped `gpt2codex` project is retained. P0-F is a **local
explicit** operation, not an MCP write capability, Git clone or Codex task.

## Command

```text
gpt2codex workspace adopt --id k2-smb --directory k2-smb --dry-run
gpt2codex workspace adopt --id k2-smb --directory k2-smb
gpt2codex workspace health --id k2-smb
gpt2codex project contexts --id k2-smb
```

Run the separately distributed `chatgpt2codex-p0f-test.sh` with `bash
./chatgpt2codex-p0f-test.sh` from the gpt2codex repository root. It builds,
executes tests, dry-runs all three checkouts, adopts only individually validated
checkouts and prints a short per-project summary. Detailed build and adoption
results stay in `gpt2codex/.log/` (`/tmp/gpt2codex/log/`). If one checkout
conflicts, the helper continues with the other safe checkouts and returns a
nonzero exit status at the end.

## What the bridge may create

For each **explicitly selected** checkout, the Rust Workspace Manager may:

- Create `~/.config/chatgpt2codex/projects/<project_id>.toml` with Git identity
  policy `preserve`; do not edit the global Git defaults or the project's
  existing local `user.name` / `user.email`.
- Initialize `<project_root>/.tmp -> /tmp/<project_id>/tmp` and
  `<project_root>/.log -> /tmp/<project_id>/log`. The destination directories
  must be private `0700`, owned by the current user and under real sticky `/tmp`.
- Append missing patterns for `.tmp`, `.log`, `.ai/.project_codex.md`,
  `.ai/CODEX_RESULTS.md` and root `CODEX_RESULTS.md` to local
  `.git/info/exclude`. Keep any existing exclusions unchanged.
- Create missing `.ai/.project_codex.md` and missing `AGENTS.md` entry point.
- If neither root `PROJECT_CONTEXT.md` nor `.ai/PROJECT_CONTEXT.md` exists,
  create a minimal `.ai/PROJECT_CONTEXT.md` placeholder. An existing root
  `PROJECT_CONTEXT.md` is **retained in place** and is added to the
  allowlisted read sources; the bridge must not generate a competing context.

## Explicit non-goals

- **No changes** to the content of existing `AGENTS.md`, existing `.ai/`
  Markdown files, original `PROJECT_CONTEXT.md`, Git author settings, tracked
  source, branch, commits, remotes or remote repository.
- No automatic copying or moving of legacy context files into `.ai/`.
- No attempt to automatically reconcile contradictory instructions. A
  `context_review=required` result means existing instructions should be
  reviewed together with the user **later**, not overwritten automatically.
- No source of remote command execution or permissions via context Markdown.
- No permanent audit/approval records or secrets inside volatile `/tmp`.

## Preflight and conflicts

`workspace adopt --dry-run` makes **no filesystem modifications**. It checks
project identity, registered roots, ordinary Git checkout metadata, context
and symlink path safety, `/tmp` ownership/modes and reserved tracked paths.
Wrong existing links, non-regular or unsafe context objects, duplicate
registrations and foreign/insecure temporary directories are errors. A failed
checkout is skipped by the helper; never repair it by silently overwriting
files. The operation is additive/idempotent but **not transactional** in the
case of an unexpected I/O failure partway through creation; inspect status
before retrying.

Adopted projects explicitly preserve Git identity. `workspace ensure` and
`workspace health` respect this and must not compare their author settings
against global defaults intended for newly bootstrapped repositories.

The CLI-only path remains a trusted local operator action, not a complete
kernel-enforced sandbox against concurrent modification from processes under
the same Unix user. That stronger isolation is required before MCP writes.
