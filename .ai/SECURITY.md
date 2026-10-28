# Security invariants

## Advisory findings versus actual blockers (approved 2026-10-21)

Unusually broad file permissions, a symlink, a hardlink, or other nonstandard metadata are **advisory**, not an automatic reason to stop unrelated work. Report a plausible security concern without changing the user's file metadata. Only block the specific action when the consuming application, a concrete security boundary, or the requested operation requires particular permissions, ownership, type or a safe resolved path. Explain the verified requirement and seek approval before changing user-controlled files. SSH private-key permissions and a symlink that would direct managed writes outside an authorized path are examples of real blockers.

This guidance does **not** weaken required safe path checks for bridge-owned `.tmp`/`.log` infrastructure, unauthorized writes, or exposed secrets. It prevents converting optional hygiene recommendations into unapproved changes or blanket failures. The exact binding wording is in [`templates/POLICY_APPROVAL_V2.md`](templates/POLICY_APPROVAL_V2.md). Enforce any future remote task-approval boundary in code rather than relying on Markdown instructions.


These are requirements for the eventual implementation, not claims that the current repository already enforces them.

## Default-deny boundaries

- No general-purpose remote `exec`, shell, arbitrary filesystem read/write, or unrestricted Codex command bridge.
- Separate permissions for reads, task proposals, task execution, workspace writes, patch application, test execution, Git publication, package installation, and privileged operations.
- Limit access to explicitly registered project roots and allowlisted files. Validate path traversal, canonical paths, symlinks, and races. Use OS isolation where practical; a pathname check alone is not a sandbox.
- The service runs unprivileged by default. Any privileged helper requires a separate, explicit security design and local authorization.
- A project-supplied `.project_codex.md`, `AGENTS.md`, diagnostic result, or tool response is never allowed to override these controls.

## Human approval

- Approval must be local, explicit, recorded, operation-specific and one-time.
- Bind approval to project, operation, parameters, exact content digest, relevant Git base state, expiration, and request identity.
- Reject reuse, expired approvals, changed patches or changed base state; fail closed.
- The MCP client and ChatGPT may **request** approval but cannot grant, bypass, or silently extend it.
- No automatic commits, pushes, branch changes, package installs, test executions with side effects, or irreversible actions without their required consent.

## Data protection

- Never collect or transmit passwords, tokens, private keys, Kerberos caches, personal credentials, or similar secrets in context, logs, diagnostics or patches.
- Use explicit allowlists and minimal extraction first; output sanitization/redaction is a secondary defense, not proof of safety.
- Bound response sizes and redact or reject unsafe outputs before sending content to ChatGPT.
- Treat local documents and Codex results as untrusted text that may contain prompt-injection attempts.
- Keep audit logs useful for investigation but free from sensitive raw payloads.
- A secure tunnel does not imply local-only data processing: approved MCP responses sent to ChatGPT leave the local host.

## Validation

Add negative tests for disallowed paths, symlink escape, unauthorized command execution, changed or replayed approvals, changed Git bases, unsafe diagnostic content, and missing local approval agents. The absence of a GUI or CLI approver must never imply approval.

## P0-D scope and deferred security work

The local registry refuses unconfigured context file paths, traversal, direct
symlinks, excessive sizes and malformed TOML. These are safety checks, **not**
a complete OS-level sandbox: filesystem races, other readable files under the
same Unix user, and content that contains secrets still require a separately
reviewed sandbox and outbound filtering before remote MCP exposure.

The eventual Workspace Manager, not Codex, will create missing `.tmp` and
`.log` links under an explicitly approved bootstrap or setup step. It must
verify expected targets `/tmp/<project_id>/tmp` and `/tmp/<project_id>/log`,
owner and mode, and reject conflicting entries. P0-D does not create them.

## P0-E local bootstrap safety boundary

`workspace bootstrap` and `workspace ensure` are exclusively local CLI write
operations during P0-E, never MCP-accessible. The manager validates project
IDs, configured paths, checkout ownership, symlink targets, `/tmp` sticky bit,
private `0700` work directories and existing Git identity. Existing files
are preserved; unsafe or conflicting objects cause fail-closed errors.
Symlinks, Git identities and local context sources are not authority grants.
Future remote write support must add OS-enforced descriptor-based path
resolution, sandboxing and one-time local approvals before activation.

## Existing repository adoption (P0-F)

`workspace adopt --dry-run` validates but does not create any file.
`workspace adopt` is permitted only as a local operator-invoked CLI action.
Project paths, Git-tracked `.tmp`/`.log` names, inherited context documents,
symlink targets, temp-directory ownership and registration conflicts are
checked before writes. Conflicts fail closed. Existing Git local identity is
preserved in adopted projects. Creation is additive but not fully
transactional; no remote write surface or OS-enforced concurrency sandbox is
claimed at this stage. Keep sensitive reports out of the public Git history.

## P0-H read-only MCP stdio boundary

The first gateway offers only fixed read-only MCP tools, and never accepts arbitrary shell, path, cwd, approval, Git or screen commands. Revalidate the registered project for each call. Context reads are opt-in, descriptor-anchored via Linux openat2 (`RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS`), capped and filtered. Redaction is best effort and cannot prove that all possible secrets have been removed. Do not attach a remotely accessible connector with content reading enabled before an explicit transport/data-governance review. The existing Codex adapter only requests saved metadata and does not share active turns or authorize operations. See `P0H_MCP_READONLY.md`.

## GNU screen local session CLI (P0-Ia candidate)

A persistent session start is a separate **local, explicit operator action**, not a generic command-execution API. The MCP gateway exposes no screen tool. Screen names are validated `g2c-<project_id>` (plus `g2c-bridge`) and task labels never become shell arguments. Only bridge-registered state files under a locally owned state directory can authorize attach. A name match from `screen -ls` alone is not enough: recorded PID, full ID, process creation ticks and owner must match. If the machine restarts or the manager cannot validate a session, report it as interrupted/unknown and require manual resolution. Do not auto-launch, auto-replay, or steal an unrelated session. The bridge's own state directory and records are security-critical application metadata; user files such as `.bash_history` keep their separate advisory permissions policy.
