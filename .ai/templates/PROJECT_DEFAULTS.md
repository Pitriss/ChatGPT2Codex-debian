# Default managed-project conventions

- Keep AI project documentation under `.ai/`; root `AGENTS.md` should only
  direct Codex to those instructions where an entry point is needed.
- Per-project guidance may be stored as `.ai/.project_codex.md`.
- Do not duplicate shared mandatory rules in each repository.
- Always keep volatile logs under `.log/` and scratch data under `.tmp/`
  once the bridge has successfully initialized those links.
- Context, result, configuration and log file names are configured per project.
- Local additions cannot weaken policy enforcement by the bridge.
- The bridge creates a missing, locally Git-ignored `.bash_history` but does not change or reject existing history, symlinks, owners or permissions.
