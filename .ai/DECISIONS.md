# Decisions and open verification items

## Approved alpha preparation (2026-10-28)

- One `gpt2codex` Debian `0.1.0~alpha1` package per amd64/arm64/armhf, shared
  between Debian 13 and Devuan Excalibur; both native backends required for a
  complete alpha package. No distro-specific variants or init dependency.
- Freeze image/action/archive inputs and Cargo.lock; required amd64, independent
  experimental ARM jobs. Never label an incomplete or failed build functional.
- The same amd64 bytes must pass both clean install tests before publication.
  Missing local infrastructure is a NOT VERIFIED result, not permission to
  bypass APT dependency checks or manipulate real sessions.
- Future exact-tag pre-release requires a separate enabled publication gate
  and protected environment approval. No tag, remote settings, release, commit,
  push, PR or branch operation is approved now. Session lifecycle is unchanged.

## Approved project tab icons (2026-10-28)

- User approved `.icon.png` in registered project roots, KDE theme fallbacks,
  20-pixel artwork with preserved proportions and full-root/actual-mux tooltips.
- Icon reads must not follow symlinks outside or inside the project; files and
  decoded dimensions are bounded. Invalid/unusable images use a system icon.
- Keep native tab behavior and prepare only empty layout space for an indicator.
  No Attention Manager, status source, tmux recovery or process lifecycle change.
- Existing GUI/screen/tmux sessions remain untouched; build/test in isolation.
  This icon approval supersedes older deferral entries below.

## Approved tmux lifecycle and safe archive (2026-10-27)

- User explicitly approved optional remain-on-exit for new tmux sessions,
  separate server/program state and explicit archival of interrupted slots.
- Program exit never authorizes respawn. Archive approval is bound to project,
  multiplexer, full session ID and process start ticks; start approval is separate.
- Preserve original record/socket and diagnostics without overwriting existing
  archives; free the slot only after preservation. Fail closed on live or
  uncertain identity, PID namespace mismatch and missing legacy provenance.
- Test only isolated synthetic sessions. Original codex-test and all existing
  live screen/tmux registries/socket paths remain untouched. Tab icons, Attention
  Manager, Git publication/branches and system installs remain out of scope.

## Approved per-project tmux alternative (2026-10-22)

- Newer user instructions supersede the earlier Phase A/B ordering: implement
  optional tmux now and defer detailed yellow-artifact diagnostics.
- GNU screen remains default; missing preference/record fields mean screen.
- Project preference is independent of actual session identity. Saving it never
  starts, detaches, stops, converts, replaces or removes an existing session.
- Extend the slot to `(multiplexer, project_id)` with distinct durable records
  and tmux private sockets. Preserve original screen paths and local CLI.
- A new slot requires explicit local `--approve-start`; GUI has no start action.
  Existing/unmanaged sessions cannot be taken over or migrated.
- Preserve Bridge autoattach, bounded reconnect, both backends and paste keys.
  Test only synthetic isolated processes; real Codex comparison is manual.
- Icons, Attention Manager, Git publication/branches, system installs and
  restarts of existing GUI/screen remain outside the approved scope.

## Approved P0-H MCP and future terminals (2026-10-21)

- **Accepted for implementation:** local, read-only MCP stdio server using the registered project ID and existing allowlisted metadata APIs. Do not infer an authorized external ChatGPT tunnel.
- **Accepted design (future phase, not implementation permission to run live tasks):** GNU screen sessions named with sanitized project IDs, dedicated `g2c-bridge` manual terminal, Qt6 GUI with a pinned first `Bridge` tab, project/task tabs and tray behavior, persistent detached Codex sessions.
- **Accepted safety constraint:** after workstation restart, do not replay in-flight tasks; recover stored metadata and require verification. Structured shared TUI/app-server control must pass a local compatibility test before implementation.
- **Current gate:** run and inspect local P0-H Rust and stdio fixture tests. No remote listener, task dispatch, Qt6 implementation, commit or push.

## Approved global policy v2 (2026-10-21)

- **Accepted:** File permission breadth, symlinks, hardlinks and unusual metadata are informational unless there is a concrete application requirement or security invariant that prevents the requested action. Warn without changing user state; block only the affected action on a verified prerequisite.
- **Accepted:** Before new, unapproved code, configuration, documentation, workflow or rule changes, propose the exact scope and get user validation and approval. Do not deviate from established workflows; approved routine diagnostics and handoffs are exempt from repeated approval within their bounds.
- **Implementation:** The canonical Czech rules live in `templates/POLICY_APPROVAL_V2.md` and `templates/CODEX_GLOBAL.md`. Upgrading previously installed shared rules requires explicit local `workspace sync-policy`; unknown edits in managed blocks fail closed without replacing user additions.
- **Scope:** This approval covers project rules, local policy sync and documentation only. It is not authorization to commit, push, rename a GitHub repo, or run unapproved tasks.


Status as of 2026-10-20. Entries marked **Accepted** reflect user-stated requirements; entries marked **Proposed** or **Verify** must not be treated as implemented facts.

| Topic | Status | Decision or question |
| --- | --- | --- |
| Repository | Accepted | `Pitriss/gpt2codex` (renaming approved from `Pitriss/ChatGPT2Codex-debian`); existing local repository; do not reinitialize. |
| Context layout | Accepted | One root `AGENTS.md` pointing to versioned Markdown documents under `.ai/`. |
| Shared project guidance | Accepted | Configurable `project_dir/.ai/` and project-specific `.ai/.project_codex.md`, loaded explicitly by the bridge. |
| Runtime implementation | Accepted | Rust, aiming at MUSL; no Node.js, npm or Electron. |
| Local approval UI | Proposed | C++/Qt6 desktop dialog and CLI path for headless use. |
| Transport | Verify | Secure MCP Tunnel availability, workspace permissions and actual end-to-end connectivity. |
| Codex integration | Partially verified | P0-C metadata JSON-RPC and filtered session lookup verified locally on Codex 0.163.0; managed execution not tested. |
| Phase 1 | Accepted | Allowlisted read-only project context, results, diagnostics and Codex state. |
| Phase 2 | Accepted | Explicitly approved task submission and persistent progress tracking. |
| Phase 3 | Accepted | Patch-first review and separate approval before application, testing or other risky operations. |
| Main release target | Accepted | Debian 13 `amd64` is the only blocking CI job. |
| Experimental CI | Accepted | Debian 13 `armhf`/`arm64` and Devuan Excalibur `amd64`/`armhf`/`arm64`, non-blocking. |
| Init systems | Accepted design constraint | No hard runtime dependency on systemd; Debian systemd user service and a Devuan non-systemd solution. |
| Git publication | Accepted | Local-only development; no automatic commits, pushes, branch changes or PRs. |
| P0-D Project Registry | Accepted scope / awaiting local tests | Read-only TOML registry, explicit context allowlists, project ID lookup and preview names. |
| Codex display name | Accepted | Global TOML name with per-project override; names use a template containing `{project_id}`. |
| Project bootstrap | Accepted design, deferred | Only bridge creates/clones/configures Git workspaces and manages `.tmp -> /tmp/<project_id>/tmp` plus `.log -> /tmp/<project_id>/log`. Markdown merely informs Codex. |
| ChatGPT workspace independence | Accepted | Standalone local operations and generic MCP support remain usable without a ChatGPT Business administrator. |

## Next gate

Test P0-D locally. Do not treat read-only registry checks as an OS sandbox or begin task creation / bootstrap without their own approval. Update statuses only after observing test results.

## Approved P0-E workspace decisions (2026-10-20)

- **Accepted:** The bridge, not Codex, owns local bootstrap, TOML registration,
  Git author defaults, mandatory shared rules, and `.tmp` / `.log` symlinks.
- **Accepted:** This repository is managed as `project_id = gpt2codex` with
  local directory name `gpt2codex` (independent of the GitHub repository name).
- **Accepted:** Exact targets are `/tmp/<project_id>/tmp` and
  `/tmp/<project_id>/log`, and only the registered project is initialized.
- **Accepted:** Existing files and differing symlinks are never overwritten.
- **P0-E limit:** first registration and repair are invoked explicitly from
  local CLI, not via ChatGPT MCP. Future remotely triggered writes require a
  separately approved and enforced authorization design.

## Approved P0-F existing-project onboarding (2026-10-21)

- **Accepted:** Enroll existing checkouts `k2-smb`, `reddit2tg` and `m365-tui`
  under the common `project_dir` using Rust Workspace Manager, without
  overwriting context files or existing Git author identities.
- **Accepted:** Keep legacy root `PROJECT_CONTEXT.md` as an allowlisted source;
  do not create a competing `.ai/PROJECT_CONTEXT.md` when one already exists.
- **Accepted:** Perform a read-only dry run for each target before writing;
  skip conflicting projects and surface their failures for user resolution.
- **Accepted:** Preserve the shared `.tmp`/`.log` layout and Git-local excludes.
- **Scope:** CLI-only local initialization. Not MCP writable; do not commit,
  push, change branch, clone, install packages or alter live services.

## P0-Ia screen manager CLI candidate (2026-10-21)

Following the successful host P0-H test (42 library and 7 CLI tests, release build, synthetic MCP stdio), the next reviewed increment adds local-only GNU screen session state, explicit start, status/list and attach. The owner-approved design remains Qt6 tray-first with a pinned Bridge tab; **this patch does not implement Qt6 or MCP execution permissions**. No screen session starts during the helper. The user must review the exact command before any persistent session is launched. A live host screen smoke test and follow-up design review are required before moving to multi-session management or GUI.
