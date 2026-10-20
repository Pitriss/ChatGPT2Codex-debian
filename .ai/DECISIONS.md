# Decisions and open verification items

Status as of 2026-10-20. Entries marked **Accepted** reflect user-stated requirements; entries marked **Proposed** or **Verify** must not be treated as implemented facts.

| Topic | Status | Decision or question |
| --- | --- | --- |
| Repository | Accepted | `Pitriss/ChatGPT2Codex-debian`, existing local repository; do not reinitialize. |
| Context layout | Accepted | One root `AGENTS.md` pointing to versioned Markdown documents under `.ai/`. |
| Shared project guidance | Proposed | Global `CODEX_GLOBAL.md` and optional per-project `.project_codex.md`, loaded explicitly by the bridge. |
| Runtime implementation | Accepted | Rust, aiming at MUSL; no Node.js, npm or Electron. |
| Local approval UI | Proposed | C++/Qt6 desktop dialog and CLI path for headless use. |
| Transport | Verify | Secure MCP Tunnel availability, workspace permissions and actual end-to-end connectivity. |
| Codex integration | Verify | app-server JSON-RPC support and scope of session monitoring/control. |
| Phase 1 | Accepted | Allowlisted read-only project context, results, diagnostics and Codex state. |
| Phase 2 | Accepted | Explicitly approved task submission and persistent progress tracking. |
| Phase 3 | Accepted | Patch-first review and separate approval before application, testing or other risky operations. |
| Main release target | Accepted | Debian 13 `amd64` is the only blocking CI job. |
| Experimental CI | Accepted | Debian 13 `armhf`/`arm64` and Devuan Excalibur `amd64`/`armhf`/`arm64`, non-blocking. |
| Init systems | Accepted design constraint | No hard runtime dependency on systemd; Debian systemd user service and a Devuan non-systemd solution. |
| Git publication | Accepted | Local-only development; no automatic commits, pushes, branch changes or PRs. |

## Next gate

Prepare and review a limited P0 proof of concept. Do not start bridge implementation until its scope and actions are approved. Update this table when explicit decisions change and preserve the difference between planned and experimentally verified behavior.
