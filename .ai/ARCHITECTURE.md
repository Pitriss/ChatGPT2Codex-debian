# Architecture (target design, not yet implemented)

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
