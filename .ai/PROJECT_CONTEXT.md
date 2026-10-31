# Project context

The approved 2026-10-31 CI optimization separates always-on quick checks from
conditional full Debian amd64 CI. Release tags and manual full runs also build
experimental arm64/armhf. Devuan remains supported with optional non-blocking
`run_devuan=false` smoke; the mandatory release receipt is Debian for the same
complete amd64 bytes. Trusted default-branch jobs may cache Cargo archives;
PR and release-tag jobs use cold dependency fetches. CI #5 at `27473ca`
passed the previous full matrix and both smokes; the optimized workflow still
needs its own hosted verification. See [packaging](ALPHA_PACKAGING.md).

The approved 2026-10-28 alpha phase prepares Debian packaging
`0.1.0~alpha1` and pinned Debian 13 GitHub Actions builds for amd64 (required),
arm64/armhf (experimental). Clean Debian amd64 installation evidence gates
publication; Devuan evidence is optional under the newer approval above.
No publication, tag, commit or remote setting
change is authorized. See [packaging](ALPHA_PACKAGING.md),
[first-commit inventory](ALPHA_COMMIT_FILES.md) and the private handoff for
actual local results and blockers; prepared CI is not a passed hosted run.

The approved 2026-10-28 GUI phase adds project tab icons from a confined
`.icon.png` or KDE theme fallback, registered-root/actual-multiplexer tooltips
and empty layout space for a future indicator. No state indicator/Attention
Manager or lifecycle change is included. See [GUI](../gui/README.md) and the
latest handoff for tests and manual verification. This supersedes older
icon-deferral statements; yellow-artifact diagnosis remains deferred.

The 2026-10-27 approved extension adds optional retained tmux panes, distinct
program exit reporting and guarded explicit archive, with no automatic Codex
restart. See [lifecycle and archival](TMUX_LIFECYCLE.md) and the latest handoff
for validation results and legacy namespace-provenance limitations.

## Current local GUI/session extension (2026-10-22)

The optional Qt6 GUI supports Konsole KPart and QTermWidget independently from
GNU screen (default) or optional tmux. Each project has its own persistent
preference; actual multiplexer and process identity remain part of each session.
Original screen records/CLI and existing sessions are preserved. New sessions
require explicit local approval; GUI only attaches. See [architecture](ARCHITECTURE.md),
[GUI](../gui/README.md), [manual comparison](TMUX_COMPARISON.md), and the current
`.zzz.handoff-result.md` for verified results and limitations. The original
yellow artifacts are still unproven; further diagnosis is deferred.

## Identity and current state

- Name: `gpt2codex` (original repository name: `ChatGPT2Codex-debian`).
- GitHub target: `https://github.com/Pitriss/gpt2codex` (rename authorized; verify actual remote name).
- Local working tree: `/home/peva/TEMP/mycode/gpt2codex`.
- Target desktop: Debian 13, KDE Plasma 6, Brave.
- Status (2026-10-21): P0-G workspace migration and global policy v2 verified locally; four registered projects, 44 Rust tests passed after v2. P0-H local read-only MCP stdio is the next test candidate.
- Current milestone: P0-H local MCP stdio, without Secure MCP Tunnel (deferred pending workspace administrator access). Future screen/Qt6 behavior is an accepted design, not an implemented component.

## Goal

Build a reusable, secure connection between ChatGPT in the browser and local Codex for multiple independent Git repositories. Avoid repeatedly copying long prompts or uploading `CODEX_RESULTS.md` by hand.

Expected capabilities, introduced in gated phases:

- Phase 1: select a project; read allowlisted project context, local diagnostics and logs, saved Codex sessions and results.
- Phase 2: propose tasks, obtain explicit local approval, dispatch approved tasks to Codex, track events and retrieve results.
- Phase 3: inspect patches, obtain separate approval for applying them, and then run approved tests or other approved operations.

## Example managed projects

- `/home/peva/TEMP/mycode/k2-smb`
- `/home/peva/TEMP/mycode/reddit2tg`
- `/home/peva/TEMP/mycode/m365-tui`

Every managed project must have a separate TOML configuration with its working directory, context-file names, handoff protocol, operating mode, access policy, and approval requirements. These projects must not be modified while implementing the bridge unless separately approved.

## Scope and non-goals

- One reusable bridge, not one integration per Git repository.
- Local operations run as an unprivileged user by default.
- ChatGPT has no unrestricted shell or arbitrary file-access tool.
- No implicit commit, push, branch switch, package installation, or privileged operation.
- Security decisions must be enforced in code and process isolation, not only by prompting.
- No Node.js, npm, or Electron runtime requirement.

## Before starting implementation

Confirm the ChatGPT workspace permissions and Secure MCP Tunnel availability, verify local Codex app-server behavior, and demonstrate a small end-to-end read-only test. Record observed facts separately from unverified assumptions.

## Accepted P0-D additions

- Configurable `project_dir` (for example `/home/peva/TEMP/mycode`) with shared
  `.ai/` rules; independent projects each use their own TOML configuration.
- Optional per-project `.ai/.project_codex.md` and configurable context files.
- Global Codex display name and project override; session-name templates must
  contain `{project_id}`. Session creation/renaming is deferred.
- Bootstrap, Git clone/identity setup and `.tmp`/`.log` symlink creation will
  be performed exclusively by the bridge under separate approval, not by Codex.
- The public project must work without a particular ChatGPT workspace; MCP
  tunneling is optional and not a prerequisite to the local client/registry.

## Current milestone update: P0-E

Implement a local Managed Workspace CLI that registers and maintains this
repository under the stable ID `gpt2codex`. Include managed shared `.ai`
rules, local TOML configuration, private `/tmp/gpt2codex/` work directories
and checkout symlinks. No direct bootstrap by Codex or MCP write API yet.

## Current milestone: P0-F (2026-10-21)

P0-E was verified on Debian 13 with 30 passing Rust tests and ready status
for `gpt2codex` at `<project_dir>/gpt2codex`. P0-F prepares **explicit
adoption** of `k2-smb`, `reddit2tg` and `m365-tui`. Existing project
instructions and Git identities remain unchanged, and any conflicts will be
resolved with the user. Host results for P0-F must still be confirmed.

## P0-H and screen/Qt6 target (2026-10-21)

P0-H introduces read-only MCP stdio tool dispatch, project-ID-based registry selection, metadata-only Codex session tools, and optional bounded context reads with descriptor-constrained Linux openat2. MCP does not authorize writes, task starts, `screen` control or remote connections. Full limits and tests: `P0H_MCP_READONLY.md`.

Future GNU screen session IDs are derived from sanitized project IDs; a reserved `g2c-bridge` session backs a pinned, manual Qt6 `Bridge` tab. Closing the Qt6 window hides to tray and must not terminate tasks. Live processes cannot survive a workstation crash; recovery cannot automatically retry unknown work. This design remains future implementation: `P0I_SCREEN_QT6_DESIGN.md`.


## Verified local milestone and next integration gate (2026-10-21)

The local P0-H read-only MCP stdio gateway passed 42 Rust library tests, 7 CLI tests, release compilation and synthetic MCP protocol validation on the user's Debian 13 machine. It does not imply a working Secure MCP Tunnel. The proposed P0-Ia local screen CLI is a separate patch awaiting compilation/verification on the host; in this step the test helper does not start Codex or screen sessions. The Qt6/system-tray design is approved but not yet implemented. This recent milestone supersedes outdated planning-only language in earlier sections; do not treat it as approval to change other repositories or automatically drive active Codex turns.
