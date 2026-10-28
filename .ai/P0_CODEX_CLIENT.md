# P0 local Codex app-server client

Status: **verified locally** on Debian 13 / amd64 with Codex 0.163.0.
The returned smoke-test log showed 11 passed tests, a successful release build,
app-server initialization, and metadata-only session lookup. A subsequent local
check found one saved `k2-smb` session and none for two other sampled projects.

## Scope

The `gpt2codex` Rust binary speaks a narrow subset of the Codex
app-server protocol over a dedicated child process' stdin/stdout. P0-C alone did
**not** expose a listening port, MCP endpoint, arbitrary JSON-RPC forwarding,
or a shell to ChatGPT.

Only these JSON-RPC methods are implemented:

- `initialize` and the required `initialized` notification.
- `thread/list` with an explicit absolute project cwd, fixed source filters,
  bounded page size and `useStateDbOnly: true` (no rollout scan/repair).
- `thread/read` with `includeTurns: false` and a required UUID; the returned
  cwd must match the explicitly provided project directory.

The CLI omits prompts, transcript turns, previews, model provider details,
configuration, and raw JSON-RPC errors. It only displays session UUID, coarse
status and timestamps. All unexpected server-initiated requests (including
approval requests) are rejected by terminating the child process. No task
start, resume, shell or file-write RPCs are available.

Do not infer that a saved thread is live simply because it has a status.
The first adapter must be verified on Codex 0.163.0 and later against the
actual version used for deployment.

## Build and run from repository root

```sh
cargo test
cargo build --release
./target/release/gpt2codex codex probe
./target/release/gpt2codex codex sessions --cwd /home/peva/TEMP/mycode/gpt2codex --limit 25
./target/release/gpt2codex codex session --cwd /home/peva/TEMP/mycode/gpt2codex --id UUID
```

`codex sessions` accepts `--pages 1..10`, defaults to 1 page, and returns a
project-scoped list. The real CLI is strictly local; never expose it as a
remote executor. Once MCP transport is added, a registry-checked project ID
must replace caller-provided paths at the network boundary.

`cargo test` invokes a Python 3 mock *test fixture*; there is no Python or
Node.js runtime dependency for the release binary. The bridge does not add
system packages or create/modify managed Git repositories. Cargo itself
creates `target/` and `Cargo.lock` locally when building.

## Limitations and next gates

- `useStateDbOnly: true` can yield no sessions when the Codex state DB has no
  cached entries. Do not automatically fall back to scan-and-repair; that
  may modify Codex's internal state.
- Each invocation spawns a short-lived app-server child. A future daemon will
  need an event loop, process recovery and persistent subscriptions.
- No MCP gateway or tunnel is implemented here. The user will approach the
  Business workspace administrator later.
- A local CLI flag allowing a cwd is **not** the same as an enforced project
  allowlist. Do not expose this CLI directly through MCP.
- A process running under the same user can potentially access other files;
  OS-enforced isolation remains a prerequisite for remote access and task
  execution.
- This is a limited P0 verification, not proof of safe remote task execution.
  P0-D registry checks, OS sandboxing, transport and approval paths remain
  independent later gates.

## Later P0-H addition

A separate `mcp stdio` gateway now provides local, project-ID-checked read-only MCP tools on top of this adapter. It still cannot start/resume active turns or share an interactive TUI with another controlling client. See `P0H_MCP_READONLY.md`; the earlier P0-C "no MCP" notes describe the historical scope of this adapter, not the full current binary.
