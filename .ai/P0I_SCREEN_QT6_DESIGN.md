# P0-I / P1: GNU screen session manager and Qt6 tabbed GUI (approved target design)

**Decision:** accepted target architecture on 2026-10-21. P0-H is host-verified read-only MCP. P0-Ia/B GNU screen CLI and two live detached sessions were verified on the user workstation (2026-10-21). P0-Ic introduces optional Qt6 GUI source, **pending host build and GUI validation**. App-server active-turn control and remote execution remain unimplemented.
The workstation uses GNU screen, not tmux. Avoid introducing a tmux dependency or changing existing user terminal arrangements without explicit approval.

## Session identity and naming

- Bridge owns only sessions it has created and registered. It must not adopt, terminate, rename, attach to or control unrelated screen sessions by guessing their names.
- Validate/sanitize `project_id` to the registry-approved lowercase `[a-z0-9_-]` form; reject collision/ambiguity rather than transforming two project IDs into one name.
- Use `g2c-bridge` for the pinned manual Bridge shell (reserved name) and `g2c-<project_id>` for the initial project session. For simultaneous project tasks, append a stable collision-resistant task/session discriminator, e.g. `g2c-k2-smb-<short-id>`; never use raw task title as a screen name.
- Record screen's complete session identifier, owning UID, project ID, Codex UUID (if known), task label and lifecycle state in a future durable store. Do not treat a matching name alone as ownership proof.
- Human-visible GUI tab name is `<project_id> | <task>` and may differ from the safe screen identifier.

## Qt6 GUI behavior

- One top-level `gpt2codex-gui` Qt6 application with a pinned first tab `Bridge`, backed by a real interactive shell in `g2c-bridge`. It can run manual `gpt2codex` CLI commands independently of the MCP tunnel.
- Additional tabs display PTY-backed screen-attached interactive Codex sessions. Qt6/QTermWidget evaluation and exact licensing/packaging are separate approved tasks.
- Window close hides to KDE system tray; icon restores the same GUI, tab state and task status. An explicit "Exit GUI" disconnects presentation only, not a Codex task.
- Closing an individual tab detaches its screen view; termination is a separate, explicitly approved operation.
- Reopening GUI recovers registered running screen sessions without restarting them.
- After workstation restart/crash, live screen processes are gone. Restore saved Codex conversation metadata and show interrupted/unknown status; never replay an in-flight turn or command automatically.
- GUI can run without an MCP tunnel. All sensitive actions follow the same bridge approval boundary as eventual MCP operations.

## API and safety gates

GNU screen owns PTY/process persistence; it is **not** the authoritative task API. Do not use `screen -X stuff` for unattended task submission. The Rust bridge should eventually use structured Codex app-server RPC to read events and send separately approved work, but the ability to share/control an active TUI thread through app-server **has not yet been verified**. Verify this explicitly with a small local integration experiment before designing full bi-directional control.

Proposed modules: (1) local read-only MCP gateway (P0-H), (2) separately approved screen session manager with durable audit and safe recovery (P0-I), (3) GUI using a local restricted API (P1), (4) one-time local approval-gated task dispatch and structured Codex control (P2). No broad shell/file access over MCP. Do not expose a network port without explicit authentication, authorization, transport threat model and user approval.

## P0-Ia/B local CLI: host-verified GNU screen state and explicit launching

This phase implements only the Rust-backed, **local CLI** building blocks:

- `gpt2codex screen probe`: detect GNU screen without starting a session.
- `gpt2codex screen list`: show bridge-registered sessions and coarse lifecycle states.
- `gpt2codex screen status --bridge` or `--id k2-smb`: inspect a specific slot.
- `gpt2codex screen start --bridge --approve-start`: start an interactive user shell, detached in `g2c-bridge`.
- `gpt2codex screen start --id k2-smb --task 'CIFS diagnostics' --approve-start`: start the user's `codex` executable in the registered checkout under `g2c-k2-smb`.
- `gpt2codex screen attach --bridge` or `--id k2-smb`: attach to the **verified recorded** session. Use `Ctrl+A`, then `D` to detach without stopping Codex.

The `screen start` command is never part of test helpers and requires the explicit `--approve-start` flag, in addition to an actual local invocation. Other shell commands cannot be substituted. It does not implicitly send prompts, create Codex turns, or change existing Codex task state. Screen session names must be derived from registered IDs and do not contain arbitrary task text. The operator can always detach and continue working later.

Session metadata resides in the user's `XDG_STATE_HOME/gpt2codex/screen-sessions/` (or `~/.local/state/gpt2codex/screen-sessions/`). These are bridge-owned execution records; unlike user-controlled `.bash_history`, their integrity (owner, no writable-by-others directory, safe regular records) is an actual prerequisite. The bridge reserves names and records the full screen session ID, PID, process start ticks, owning UID (verified through procfs) and project root. It does not adopt a user-created screen by matching names. Interrupted or ambiguous records are never restarted/replayed automatically. After GUI crash, real screen processes remain independent. After host reboot there is no running process to attach, only interrupted metadata.

P0-Ia deliberately supports **one registered screen per project**, plus `g2c-bridge`. A completed/interrupted slot is retained for manual reconciliation; it cannot silently be reused or hijacked. Multiple concurrent task suffixes, archive/restart of ended slots, app-server/TUI shared-thread control, GUI, and Qt6 system tray belong to subsequent separately reviewed increments. To keep manual fallback usable, this phase does not require a tunnel, service, extra shell interpreter, tmux or any new Rust crate.

`gpt2codex mcp stdio` remains byte-for-byte read-only in P0-Ia, with no screen or command-launching tool. Tests verify naming, option validation, parsing, identity mismatch handling and availability without starting Codex or touching any other project's repository.

## P0-Ic Qt6/QTermWidget GUI candidate (2026-10-21; host verification pending)

Approved implementation scope: an **optional** `gui/` C++17/Qt6 component, built separately from Cargo with CMake and Debian's `libqtermwidget-dev`. On Debian 13 the QTermWidget6 exported link target also needs `libutf8proc-dev`, which provides the non-versioned `libutf8proc.so` linker file. The build must fail with a clear missing-dependency message rather than creating symlinks or changing system libraries. The initial GUI takes its project/session authority only from local `gpt2codex screen list` and opens interactive, PTY-backed `gpt2codex screen attach` processes. There is no `screen start`, task submission or process termination in the GUI; the existing Rust CLI enforces complete screen-session identity validation.

The GUI presents a fixed first Bridge tab, then tabs for registered active/interrupted project sessions. Closing a project tab only destroys its attached presentation; a per-run hidden-tab set prevents immediate reappearance during refresh. Restoring hidden tabs or restarting GUI re-lists sessions. Terminal exit never automatically triggers a repeated attach; the operator must request reconnect and the GUI first re-queries the bridge. A stale, duplicate or malformed listing is refused rather than launching a guessed session.

When a tray is available, the close button hides the Qt window instead of terminating it, and the tray menu can restore it or quit GUI only. If the tray integration is absent, it exits the GUI with no attempts to stop any screen sessions. The window does not launch new Codex processes, modify `.bash_history`, install packages, or require MCP networking. This phase does **not** establish simultaneous app-server control of the TUI; that remains a separately reviewed experiment.

`gpt2codex-p0ic-qt6-test.sh` must build and execute `--self-test` with the Qt offscreen platform (parsing fixture tests plus read-only local `screen list`) without attaching or creating sessions. Full GUI, tray and PTY life-cycle checks require an interactive KDE X11 desktop and must not be reported as passed based on offscreen testing alone. Do not modify Rust/MCP/CI workflows for this GUI candidate.

## P0-Ic desktop theme refinement

The Qt6 GUI must respect the effective Qt platform theme and palette, without
forcing Fusion, hard-coded light/dark UI colors or replacing the user's Qt style.
QTermWidget is a separate terminal color renderer: prefer the configured default
Konsole profile and its `.colorscheme`/font if present; otherwise choose the
QTermWidget light/dark fallback based on the Qt palette and use the system fixed
pitch font. Changes to the application palette should update attached terminals.
Reading theme/profile settings is read-only, never an authorization to modify KDE,
Konsole, Kitty or the user's files. Preserve GNU screen sessions, CLI and MCP behavior.
An optional `--theme-probe` is read-only and never opens or attaches sessions.
Specific Kitty theme importing is outside this approved KDE/Konsole scope.

### P0-I recovery of interrupted project sessions (explicit local CLI)

`gpt2codex screen recover --id k2-smb --approve-recover` releases **only** a
registered project slot whose original full screen identity is no longer alive.
The bridge verifies owner-validated record metadata, recorded PID and `/proc`
start time, and that GNU screen reports no session using the reserved name.
Missing/incomplete records, live original processes, or name collisions are
refused. The pinned `--bridge` slot cannot be recovered by this command.

Recovery preserves the original JSON record in the private bridge state
directory as `.recovered-<project>-<pid>-<startticks>.json`, without replacing
existing archives. It does **not** launch or attach Codex, send input,
kill screen, replay tasks or resume interrupted Codex turns. A second explicit
`screen start --id ... --task ... --approve-start` is required for a new
session. An old Codex conversation may be resumed manually, separately, after
its identity and available history have been verified. Test helpers must not
invoke an approved recover/start against a real workspace.
