# Security invariants

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
