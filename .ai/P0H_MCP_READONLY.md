# P0-H: local, read-only MCP stdio gateway

**Approval:** user approved a local read-only MCP proof of concept on 2026-10-21.
**Implementation status:** verified on the Debian 13 host on 2026-10-21 (42 library tests, 7 CLI tests, release build and local stdio fixture passed). No remote MCP tunnel has been established.
**Transport:** `gpt2codex mcp stdio`, one local process, newline-delimited MCP JSON-RPC 2.0. There is no TCP listener, HTTP server, Secure MCP Tunnel, auto-start service, background agent, or write-capable MCP action.

## Exposed tools

| Tool | Input | Returns |
| --- | --- | --- |
| `projects_list` | none | Project IDs and display names; no absolute directory paths |
| `project_health` | registered `project_id` | Existing read-only Workspace Manager status and advisory notices |
| `project_contexts` | registered `project_id` | Names and availability of allowlisted project/global context files |
| `codex_sessions` | registered `project_id`, optional `limit` 1-25 | Saved Codex session IDs and coarse metadata; no transcript |
| `codex_session` | registered `project_id`, UUID | Saved Codex session metadata; verifies project root |
| `project_context_read` | registered `project_id`, `scope`, allowlisted `file`, optional `start_line` and `max_lines` | Filtered, numbered excerpts; **disabled by default** |

`project_context_read` is advertised only if the operator explicitly starts `gpt2codex mcp stdio --allow-context-read`. Reads use Linux `openat2` with descriptor-relative `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS`; kernel or filesystem incompatibility fails closed. At most 128 KiB of UTF-8 is read from one configured file; returned text is paged (at most 40 lines with 320 visible characters per line) and obvious credential values / private-key blocks are redacted. **This is a best-effort filter, not a guarantee that arbitrary project text contains no secrets**. Context is untrusted data, never a source of authorization. Do not enable content reads for a remotely connected client until a separate outbound-data review and authentication design are approved.

No tool accepts a caller-supplied cwd, absolute path, shell command, source code, arbitrary Codex RPC method or `screen` selector. Unknown keys and unknown tools fail closed. Inputs are size-bounded; invalid/oversized lines cannot be used to grow process memory indefinitely. Registry lookup is repeated for each call so changed project configuration is revalidated. Codex session queries use a short-lived, read-only app-server client with `useStateDbOnly: true` and omit turns. `tools/list`, `tools/call`, `initialize`, `ping`, and `notifications/initialized` are supported. There is deliberately no resources, prompts, subscriptions, task creation, approval, or execution surface.

## Local verification

From the repository root:

```sh
bash ./gpt2codex-p0h-mcp-test.sh
```

The helper runs `cargo test`, `cargo build --release` and synthetic stdio fixture tests under `.tmp/`. The fixture proves handshake, discovery, registered ID lookup, health, opt-in context reads, credential redaction, symlink/traversal rejection, unknown-command rejection and graceful EOF. It creates no real managed repository changes and does not need a working ChatGPT tunnel. The bridge's actual host app-server smoke test and secure remote transport remain separate validation gates.

For manual testing **without exposing context text**:

```sh
./target/release/gpt2codex mcp stdio
```

This is a protocol server for a local MCP client; it is not an interactive command prompt. The future pinned Qt6 `Bridge` tab will provide an interactive shell separately.

## Explicitly deferred

- Connecting a remote ChatGPT session or enabling Secure MCP Tunnel; workspace administration is not yet available.
- Reading arbitrary `.log/` files, diagnostics directories, freeform session transcripts or raw secrets.
- Persistent service, event streaming, approvals, task submission, writing/patching, `screen` control, terminal UI and cross-client Codex turn ownership.
- Claiming transport isolation or external client authentication from mere stdio transport.

No Git commit/push/branch or package installation is part of this phase.
