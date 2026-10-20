# Project context

## Identity and current state

- Name: `ChatGPT2Codex-debian`.
- Repository: `https://github.com/Pitriss/ChatGPT2Codex-debian`.
- Local working tree: `/home/peva/TEMP/mycode/ChatGPT2Codex-debian`.
- Target desktop: Debian 13, KDE Plasma 6, Brave.
- Status (2026-10-20): **architecture and requirements agreed in principle; no bridge implementation has been approved or completed**.
- Current milestone: P0, assess feasibility and permissions before implementation.

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
