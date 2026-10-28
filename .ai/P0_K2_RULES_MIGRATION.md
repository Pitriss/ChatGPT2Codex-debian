# P0-G: authorized k2-smb rule consolidation

This is a local-only, explicit migration; no MCP writes, network operations or Git commits.

- Reuse existing `k2-smb` project ID and its configured checkout.
- Keep root `AGENTS.md` as a short reference to shared `../.ai/CODEX_GLOBAL.md`, `.ai/.project_codex.md`, `.ai/PROJECT_CONTEXT.md` and `.ai/CODEX_RESULTS.md`.
- Preserve the complete original `AGENTS.md`, `PROJECT_CONTEXT.md`, `CODEX_RESULTS.md`, project override and registry TOML byte-for-byte in a private, locally ignored `.ai/.migration-backups/` directory before modifying them. No unsanitized content is included in logs.
- The migration helper extracts project-specific CIFS/Kerberos security rules, privilege/`sudo` and the **manual** handoff protocol into `.ai/.project_codex.md`; the original technical sections D and E, technical context section 2 and the still-unresolved workflow section 3 are copied intact into `.ai/PROJECT_CONTEXT.md`. The historically sensitive sixth rule in section A is copied intact, without interpreting or sanitizing it.
- The old scratch directory rules are superseded by global `.tmp`/`.log`. Old evidence is not automatically deleted in this migration.
- The `[contexts].files` registry list is changed to the new `.ai/` paths only after the files exist and are verified. Local Git exclusions are added without changing `.gitignore`.
- `CODEX_RESULTS.md` remains an explicit manual handoff until the MCP tunnel and a separately approved bridge-driven handoff are available.
- Context lines 84-89 describe a useful general workflow and remain in the migrated project context **pending user approval** before removal/relocation into global policy. Their substance is already compatible with shared rules.
- Each registered project gets a locally ignored `.bash_history` path. The bridge creates a new empty file only if the path does not already exist; existing user-defined files, symlinks, owners, permissions and contents are untouched. Nonstandard metadata is reported as a non-blocking notice. This is not automatic shell history configuration.
- Updating an installed `CODEX_GLOBAL.md` requires the explicit local `workspace sync-policy --id gpt2codex` command; modified managed markers halt the update. Future bootstrap templates already include the policy block.

All file migration and context-authority changes must be tested on local copies first. Do not stage, commit, push or switch branches.

## Binary and GitHub rename (separate authorized operation)

- The final CLI binary is `target/release/gpt2codex`; the Rust library, the config home `~/.config/chatgpt2codex/`, and the stable project ID `gpt2codex` are unchanged.
- The GitHub repository rename from `Pitriss/ChatGPT2Codex-debian` to `Pitriss/gpt2codex` is authorized but requires a separately authenticated GitHub action. Do not assert success until the GitHub repository ID has been verified after the operation. Preserve the local branch and worktree.
