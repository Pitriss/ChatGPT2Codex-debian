# Development and handoff rules

## Approval-first workflow

Use this sequence: **proposal -> user approval -> local patch -> focused tests -> review of results**. Do not infer approval of the next step from approval of an earlier step.

- Development is local. No unrequested changes in existing managed repositories.
- No Git commit, push, branch switch, remote PR, or release publication without an explicit user request.
- Inspect the real state before applying patches; do not overwrite an existing `AGENTS.md` or other project context file blindly.
- Keep one-off helper scripts and patch files in the affected repository root and execute them from there.
- Show shell commands as single-line, directly copyable commands. For one-off scripts, prefer `bash script.sh` over changing executable bits.
- Communicate with the user in Czech. Separate observed facts, assumptions, and decisions.
- Do not run destructive or privileged operations without separate authorization.

## Git identity

For this repository, the requested Git identity is `pitriss` with its GitHub noreply address `5106460+Pitriss@users.noreply.github.com`. Configure it **locally for this repository**, not globally. A context document does not set Git config by itself.

## Working artifacts

- `AGENTS.md` in the root only points into `.ai/`.
- The durable project specification lives in `.ai/` and is intended to be versioned.
- Project-specific runtime results, diagnostic dumps and credentials should stay outside the public repository; `CODEX_RESULTS.md` and other handoff paths are configurable.
- Changes to these documents follow the same approval and patch review workflow as code.

## P0 exit criteria

1. Verify the user's access to a private ChatGPT MCP integration and any necessary tunnel privileges.
2. Confirm the installed Codex app-server transport, supported requests, and session behavior.
3. Demonstrate a minimal end-to-end **read-only** operation without exposing sensitive data.
4. Document limitations and a threat model before requesting approval for Phase 1 implementation.
