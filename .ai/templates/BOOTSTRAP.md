# Bootstrap contract (informational for Codex)

The bridge, not Codex, is responsible for repository checkout and creation of
managed local infrastructure. A new project is ready for Codex only after the
bridge has validated its project ID, Git remote, local Git author identity,
shared rules, local context folder, and private `.tmp` / `.log` targets.

Bootstrap can write only after its own explicit approval gate. Ordinary P0-D
registry operations are read-only and do not perform bootstrap.
