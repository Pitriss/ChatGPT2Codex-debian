# Architecture (target design; local P0-H read-only stdio gateway in progress)

## Approved local tmux lifecycle and archive (2026-10-27)

New tmux starts may opt into `--remain-on-exit`. A private startup config is
loaded before the initial program, so even immediate exits retain their pane.
Server identity and program state are separate. The original pane ID, chosen
policy, boot ID and PID namespace accompany new tmux records; old records remain
readable/attachable. Program metadata is numeric or a bounded signal name, never
terminal content. CLI metadata is opt-in (`--program-status`) for compatibility
with older running GUI clients. GUI reconnect attaches the retained pane and
never respawns Codex.

`tmux_archive.rs` implements local explicit archival bound to full ID and process
generation, with a separate approval flag. It checks project/record ownership,
process absence in the original boot/PID namespace and absence of an active
socket endpoint. Existing evidence is never overwritten. It persists an exact
snapshot and diagnostics, moves the stale socket, and frees the slot last by
moving the original JSON. Partial evidence is retained for manual inspection.
Legacy/pending records without sufficient provenance fail closed. No automatic
migration/recovery/restart and no GUI archive/start actions were added.
Details and manual verification: [TMUX_LIFECYCLE.md](TMUX_LIFECYCLE.md).

## Current local multiplexer extension (2026-10-22)

The user approved optional tmux per project, ahead of further yellow-artifact
diagnostics. `multiplexer.rs` holds preference/identity types; `session.rs` is
the local facade over the existing screen adapter and tmux. Safe record I/O,
registry/root/workspace validation and locks are shared with `screen.rs`.
The original `screen` CLI/output/record paths and read-only MCP are preserved.

`[sessions].multiplexer` defaults to screen and affects only a future approved
start. `project_preference.rs` writes it atomically, preserving other TOML
settings/comments without session operations. Bridge's future start uses the
gpt2codex project preference. Actual session identity always determines attach.

Slot identity is `(actual_multiplexer, project_id)`: legacy `<id>.json` and
separate `<id>.tmux.json`, including Bridge slots. tmux has a dedicated private
socket/server and records PID/procfs start ticks, session ID, creation time and
socket device/inode. It never adopts the user's default server. Existing slots
are never overwritten. Interrupted tmux slots now have the explicitly approved
archive path above; arbitrary extra task slots remain out of scope. No automatic
migration is required.

Both native GUI backends use the same facade with composite tab keys. Attach
carries actual multiplexer, full ID and process generation for revalidation.
tmux queries have time/output limits; start uses direct exec with multiple argv
entries, never a shell string from labels. Only metadata queries use locale C;
start/attach preserve the TUI locale. See [manual comparison](TMUX_COMPARISON.md).

## Technology

- Core daemon: Rust, with a preferred static MUSL build when dependencies allow it.
- Async runtime and serialization: Tokio and Serde are candidate libraries.
- MCP server: a Rust MCP SDK such as `rmcp`, subject to P0 compatibility checks.
- Codex integration: app-server JSON-RPC over local `stdio` by default.
- Project configuration: TOML; runtime state and audit: SQLite.
- Optional local approval UI: standalone C++/Qt6 dialog; CLI approval path for headless systems.
- Init and service supervision are adapters, not dependencies of the Rust daemon.

## Connectivity

```text
ChatGPT (Brave)
  -> private MCP integration / proposed Secure MCP Tunnel
  -> local MCP gateway
  -> registry + authorization policy + task/approval/audit managers
       -> allowlisted project files and filtered diagnostics
       -> Codex app-server via local JSON-RPC
       -> isolated patch preparation and approved patch application
```

Secure MCP Tunnel is a **candidate** transport. Workspace eligibility, tunnel authorization, installation, and real end-to-end behavior must be validated in P0. Do not assume ChatGPT can call arbitrary localhost ports.

## Planned components

- **MCP gateway:** narrowly scoped, typed actions instead of arbitrary commands or file paths.
- **Project registry:** one validated TOML configuration per project, stable project identifiers, explicit read and write boundaries.
- **Codex adapter:** initialization, session lookup, managed tasks, notifications and approval request handling.
- **Task manager:** persistent task IDs, lifecycle states and event history; long tasks must not depend on one long MCP request.
- **Artifact manager:** bounded and sanitized result/log retrieval, paging for large outputs, patch metadata and SHA-256 digests.
- **Policy and approval manager:** deny-by-default rules and local, operation-specific approvals.
- **Audit store:** records decisions and outcomes, without storing secrets.

## Session visibility

Sessions started by the bridge and sessions independently started through Codex CLI must be distinguished. Saved history may be available for externally started sessions, but live control or monitoring of such sessions is **not guaranteed** until tested.

## Patch flow

1. Record the original Git state and relevant file digests.
2. Prepare a patch in an OS-enforced isolated workspace, not by writing into the target working tree.
3. Validate and review the resulting diff and affected paths.
4. Obtain local approval bound to the exact patch and base state.
5. Revalidate the unchanged base state; apply only the approved patch.
6. Run tests only under their separately approved policy.

The isolation and approval design must be threat-modeled before Phase 3; plain text instructions or a Codex read-only setting alone are insufficient.

## P0-D local project registry

The initial registry is a local Rust CLI module, not a remotely callable API.
It loads one global TOML configuration and separate project TOMLs, validates
immediate child project roots, allowlists project and shared `.ai/` files,
rejects ordinary symlinks, and previews session display names. Project IDs
are stable names independent of paths and Codex UUIDs.

A future bootstrap component will own git clone, local Git identity, managed
`.ai/` installation, private `/tmp/<project_id>/tmp` and `log` directories,
symlinks `.tmp` and `.log`, and lifecycle checks. Codex must never implement
this bootstrap by interpreting Markdown alone. This requires separate approval
and is not part of the read-only P0-D registry.

After an approved managed `thread/start`, a later Session Manager may call
`thread/name/set` with the validated TOML-rendered name. No such RPC is issued
in P0-D. The actual Codex session UUID remains authoritative.

## Local Managed Workspace bootstrap (P0-E)

The `workspace` module performs explicit, local-only registration and maintenance
of registered Git checkouts. It installs shared rules into
`<project_dir>/.ai`, configures the registry under XDG config, creates exact
`/tmp/<project_id>/{tmp,log}` work directories, and links `.tmp` / `.log` in
the checkout. This does not introduce any MCP write surface or Codex task
execution. See `P0_WORKSPACE_MANAGER.md` for the operation boundaries.

## P0-F: adopted checkouts

The local Rust Workspace Manager now has a separate `workspace adopt` path
for pre-existing Git checkouts. A per-project TOML `git.identity = "preserve"`
mode prevents `workspace ensure` from imposing the global author identity.
The registry allowlists both `.ai/` documents and legacy root context/report
names where explicitly configured. Bootstrap for a new project remains
separate and uses the global identity. No MCP write endpoint exists.

## P0-H local MCP gateway versus future session manager

`src/mcp.rs` implements a local MCP tools-only stdio gateway using existing Rust dependencies. It is not an HTTP listener or an authenticated ChatGPT connector. Project selection uses the registry ID, not caller-supplied paths, and context reads are explicitly opted in with descriptor-confined openat2 access and bounded/redacted pages. Details and security limitations: `P0H_MCP_READONLY.md`.

The approved future screen/Qt6 architecture is documented in `P0I_SCREEN_QT6_DESIGN.md`. It separates (a) persistent screen PTYs from (b) structured Codex app-server task control and (c) Qt6 presentation. No screen management or Qt6 frontend exists in P0-H, and cross-client active-turn ownership is unverified.


## P0-Ia local GNU screen manager (candidate for Debian host test)

P0-Ia adds the local Rust CLI `screen probe|list|status|start|attach` and durable, owner-validated session records. `screen start` requires `--approve-start`; test helpers intentionally do not start or terminate live sessions. The `g2c-bridge` tab is a manual shell fallback and registered `g2c-<project_id>` terminal sessions run `codex` from their own project root. Bridge is not allowed to infer control of an unrelated GNU screen session from its name alone. No `screen -X stuff`, arbitrary shell forwarding, MCP write tool, Qt6 GUI or active Codex thread synchronization is introduced in this increment. See `P0I_SCREEN_QT6_DESIGN.md`.
