# Development and handoff rules

## Approved project documentation and workflow policy (2026-10-21)

The binding policy is versioned in [`templates/POLICY_APPROVAL_V2.md`](templates/POLICY_APPROVAL_V2.md), embedded in `templates/CODEX_GLOBAL.md`. For **every new or resumed task**, Codex reads the installed global and project instructions, and checks the real worktree before planning. Existing user-approved workflows are not to be changed implicitly.

Before **any as-yet-unapproved** source, configuration, rules, workflow or documentation change, present the precise scope, affected files, impacts and unchanged areas for the user's validation and approval. Apply approval only to that scope; request approval again for material new work. Documentation must describe observed and tested behavior accurately. Previously approved routine handoff writes or diagnostic recording do not require repeated approval within their approved limits. No automatic commit or push.

An explicit local `gpt2codex workspace sync-policy --id gpt2codex` installs new approved policy blocks into an existing `project_dir/.ai/CODEX_GLOBAL.md` after validating known managed blocks. It preserves external user text and refuses unknown managed-block edits; `workspace ensure` does not silently upgrade policy. The integration remains local CLI-only until MCP approvals are separately implemented.


## Approval-first workflow

Use this sequence: **proposal -> user approval -> local patch -> focused tests -> review of results**. Do not infer approval of the next step from approval of an earlier step.

- Development is local. No unrequested changes in existing managed repositories.
- No Git commit, push, branch switch, remote PR, or release publication without an explicit user request.
- Inspect the real state before applying patches; do not overwrite an existing `AGENTS.md` or other project context file blindly.
- Keep one-off helper scripts and patch files in the affected repository root and execute them from there.
- Show shell commands as single-line, directly copyable commands. For one-off scripts, prefer `bash script.sh` over changing executable bits.
- Communicate with the user in Czech. Separate observed facts, assumptions, and decisions.
- Do not run destructive or privileged operations without separate authorization.

## Git identity

For this repository, the requested Git identity is `pitriss` with its GitHub noreply address `5106460+Pitriss@users.noreply.github.com`. Configure it **locally for this repository**, not globally. A context document does not set Git config by itself.

## Working artifacts

- `AGENTS.md` in the root only points into `.ai/`.
- The durable project specification lives in `.ai/` and is intended to be versioned.
- Project-specific runtime results, diagnostic dumps and credentials should stay outside the public repository; `CODEX_RESULTS.md` and other handoff paths are configurable.
- Changes to these documents follow the same approval and patch review workflow as code.

## P0 exit criteria

1. Verify the user's access to a private ChatGPT MCP integration and any necessary tunnel privileges.
2. Confirm the installed Codex app-server transport, supported requests, and session behavior.
3. Demonstrate a minimal end-to-end **read-only** operation without exposing sensitive data.
4. Document limitations and a threat model before requesting approval for Phase 1 implementation.

## Common project directory and workspace lifecycle

A configurable `project_dir` contains the shared `.ai/` rules directory and
independent Git checkouts. The bridge owns any authorized bootstrap activity:
cloning, local Git identity, context installation and verified volatile links.
Codex is informed of the rules but never creates or repairs the links itself.

Workspace layout after separately approved initialization:

- `.tmp -> /tmp/<project_id>/tmp` for disposable files.
- `.log -> /tmp/<project_id>/log` for transient logs.

The P0-D registry only reads config and allowlisted text, lists session metadata,
and previews names. It does not alter project checkouts or install shared rules.

## Managed Workspace operations

For a newly registered project, call the Rust bridge's local
`workspace bootstrap` command. The bridge configures project registry,
Git identity and volatile work areas, then reports readiness. Codex reads the
status and the `.ai/` rules; it must never initialize these assets itself.
`workspace ensure` may be used later to restore missing working directories,
without replacing conflicting symlinks or context files. Tests and logs should
use `.log/` once the workspace is ready; disposable artifacts use `.tmp/`.

## Existing project adoption (P0-F)

The bridge, not Codex or Markdown, provisions existing repositories using
`workspace adopt` after a clean `--dry-run`. Never overwrite a pre-existing
`AGENTS.md`, root context, `.ai/` documentation or local Git identity; report
conflicts. An existing root `PROJECT_CONTEXT.md` remains authoritative until
the user approves a migration. Reserve `.tmp` and `.log` symlinks for bridge
management. Refer to `P0_EXISTING_PROJECTS.md`.

## Shared shell history and local policy synchronization

The Rust bridge creates an empty `.bash_history` with default mode `0600` when absent in any managed project, and excludes its path via `.git/info/exclude`. It never truncates, follows, replaces, chmods or chowns an existing history file or symlink. A symlink or nonstandard permissions produce advisory `history_notice` output without failing workspace readiness. A Git-tracked history is likewise reported rather than automatically untracked. Existing per-project Bash HISTFILE selection remains external to the bridge. Global policy updates of already-installed rules require explicit `workspace sync-policy --id ID`.

## P0-H gateway and approved terminal design

P0-H exposes only local MCP `stdio` read-only tools. The `--allow-context-read` switch is explicit and remains local-only pending review of outbound sensitive-data filtering and remote transport. Run the provided one-shot local helper from the project root; it writes logs under `.log/` and synthetic fixture files under `.tmp/`. Do not equate MCP capability with user permission to execute a task. The subsequent GNU screen / Qt6 work is a separate approved implementation step (see `P0I_SCREEN_QT6_DESIGN.md`). The pinned `Bridge` terminal is an interactive CLI fallback, not the MCP protocol stdin.

## P0-Ia/B screen controls (local-only; host-verified)

The `screen` command family is an explicitly invoked local CLI, **not** an MCP endpoint. `screen start` requires `--approve-start`, validated project registration and workspace readiness. Manual `screen attach` uses the recorded full screen ID and procfs identity check instead of finding a session by prefix. Qt6 GUI sources are provided separately in P0-Ic and await host validation; bridge-driven Codex app-server interaction is not implemented. Do not imply automatic remote task dispatch from this milestone. Do not terminate the user's Codex processes, adopt unrelated screens, or automatically replay interrupted work. Review `.ai/P0I_SCREEN_QT6_DESIGN.md` before proposing a next change.

## Optional Qt6 presentation (P0-Ic; host validation pending)

The separately approved `gui/` CMake component uses QTermWidget6 to attach to existing bridge-owned screen sessions. It is not a task-dispatch API and does not change Rust CLI or MCP. Build and self-test it only using the root helper `gpt2codex-p0ic-qt6-test.sh`; it neither starts screen sessions nor opens GUI windows during tests. Interactive Qt/tray behavior must be reviewed separately on the workstation. Follow the existing approval-first workflow for any GUI lifecycle changes or Qt package installation.
