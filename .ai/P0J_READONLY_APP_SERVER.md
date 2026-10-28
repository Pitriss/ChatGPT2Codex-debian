# P0-J: read-only Codex app-server diagnostics

Status: implementation candidate, **host build and real Codex verification pending**.
Scope approved: Codex app-server detection, bounded metadata and event diagnostics,
coexistence assessment with GNU screen Codex CLI, and one new Settings category.

## Interface

From the repository root:

```sh
./target/release/gpt2codex codex diagnostics --id gpt2codex
./target/release/gpt2codex codex diagnostics --id k2-smb --limit 10
./target/release/gpt2codex-gui
```

The registered `--id` is resolved through `ProjectRegistry`. `--config` must be
absolute if provided. The maximum `--limit` is 25, default 10. Raw arbitrary
`--cwd`, `--method`, shell commands and thread IDs are not accepted by the new
command. The historical local-only `codex sessions --cwd` and `codex session
--cwd` subcommands remain unchanged.

The new CLI command opens a *separate short-lived* `codex app-server` stdio
child. Requests are restricted to the existing `initialize`, `initialized`,
`thread/list` (with `useStateDbOnly:true`), and `thread/read` with
`includeTurns:false` for at most the newest listed thread. Project `cwd`
must match exactly. Errors and unexpected server-initiated requests fail
closed. Neither turns nor transcripts are hydrated. Raw replies, text,
previews, tokens, paths, thread UUIDs and notification payloads are not printed.

The CLI prints only these four sanitized records:

- `P0J=OK ...`: protocol and effective query mode;
- `P0J_SESSIONS=...`: bounded stored thread status counts;
- `P0J_EVENTS=...`: counts of notification method families observed while
  this diagnostic connection was reading replies;
- `P0J_TUI=...`: explicit disclosure that the independent TUI is not controlled
  or observed through this dedicated connection.

**An `active` stored thread is not proof of a live TUI turn.** A successful
`thread/list` may show saved metadata for threads originated by another process,
but this does not subscribe to their live events. `P0J_EVENTS` counts only
notifications delivered to the newly created app-server connection while its
requests were pending, and is commonly zero. No `thread/resume`, `turn/start`,
`thread/subscribe`, `thread/loaded/list`, or process injection occurs. A missing
Codex state DB is reported as an error, not silently repaired by filesystem
scanning. The target's active GNU screen process is never controlled.

## GUI

The Settings tab now has **Codex API** after Terminal and Tabs. It reads project
names through local `gpt2codex projects list` (not filesystem enumeration) and
runs diagnostics only after the user clicks **Ověřit app-server**. Both subprocesses
are asynchronous and bounded by timeouts; the GUI accepts only the four strict
output records, never arbitrary text from Codex or stderr. No auto-polling or
automatic task dispatch is introduced.

## Safety and validation

- No changes to existing screens, their process identity checks or approval.
- No changes to local MCP's read-only tool set or exposure. No network listener.
- No `screen -X`, arbitrary RPC passthrough, remote commands, commits or pushes.
- Mock Codex tests cover event counter classification and no notification text
  storage. GUI headless self-test checks strict output grammar.
- The root test helper builds Rust/GUI, runs bounded read-only self-tests, and
  compares recorded screen session identities before and after. It may try an
  optional real Codex read-only query; lack of a state DB does not trigger a
  repair. Actual live GUI/Codex behavior needs a host smoke test.

Follow-up work (requires separate approval): controlled app-server subscriptions
or event streaming, active TUI co-control investigation, and a user-authorized
write-operation gate. This milestone does not claim any of these capabilities.
