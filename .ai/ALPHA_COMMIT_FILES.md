# First alpha commit candidates

Explicit candidate list from the current worktree, including untracked sources.
This is a review inventory, **not** staging/commit/push authorization. Do not
use `git add .`. The candidate audit uses this same allowlist; hash evidence
is stored separately under `.log/alpha-candidates-final.json`.

Excluded deliberately: private `.ai/.zzz.handoff-result.md` and local
`.ai/.project_codex.md`, history, runtime configs/registries/sockets, `.git`,
`.tmp`, `.log`, `target`, caches, downloaded tools/rootfs, build/package outputs,
historical duplicate patches and unrelated old migration/audit scripts.
All excluded pre-existing files remain in the worktree unchanged.

The reviewed synthetic-redaction-header exceptions are pinned to complete
file hashes; no credentials are exempted by path. Automated heuristic scanning
is useful evidence, not a mathematical proof of secret absence.

Count: **87 files**.

- `.ai/ALPHA_COMMIT_FILES.md`
- `.ai/ALPHA_PACKAGING.md`
- `.ai/ARCHITECTURE.md`
- `.ai/DECISIONS.md`
- `.ai/P0H_MCP_READONLY.md`
- `.ai/P0I_SCREEN_QT6_DESIGN.md`
- `.ai/P0J_READONLY_APP_SERVER.md`
- `.ai/P0_CODEX_CLIENT.md`
- `.ai/P0_EXISTING_PROJECTS.md`
- `.ai/P0_K2_RULES_MIGRATION.md`
- `.ai/P0_PROJECT_REGISTRY.md`
- `.ai/P0_WORKSPACE_MANAGER.md`
- `.ai/PLATFORMS_CI.md`
- `.ai/PROJECT_CONTEXT.md`
- `.ai/README.md`
- `.ai/SECURITY.md`
- `.ai/TMUX_COMPARISON.md`
- `.ai/TMUX_LIFECYCLE.md`
- `.ai/WORKFLOW.md`
- `.ai/examples/config.toml`
- `.ai/examples/projects/example.toml`
- `.ai/templates/.project_codex.md`
- `.ai/templates/BOOTSTRAP.md`
- `.ai/templates/CODEX_GLOBAL.md`
- `.ai/templates/POLICY_ADDENDUM.md`
- `.ai/templates/POLICY_APPROVAL_V2.md`
- `.ai/templates/PROJECT_DEFAULTS.md`
- `.ai/templates/VERSION`
- `.github/workflows/alpha.yml`
- `.gitignore`
- `AGENTS.md`
- `Cargo.lock`
- `Cargo.toml`
- `LICENSE`
- `README.md`
- `debian/README.Debian`
- `debian/changelog`
- `debian/clean`
- `debian/control`
- `debian/copyright`
- `debian/docs`
- `debian/gpt2codex-gui.1`
- `debian/gpt2codex.1`
- `debian/gpt2codex.desktop`
- `debian/gpt2codex.examples`
- `debian/manpages`
- `debian/rules`
- `debian/source/format`
- `gpt2codex-alpha-container.sh`
- `gpt2codex-alpha-infra.py`
- `gpt2codex-alpha-rootfs-test.py`
- `gpt2codex-alpha-test.py`
- `gpt2codex-alpha.py`
- `gpt2codex-ci-test.py`
- `gpt2codex-ci.py`
- `gpt2codex-multiplexer-test.py`
- `gpt2codex-p0ic-qt6-test-v2.sh`
- `gpt2codex-project-icons-test.py`
- `gpt2codex-terminal-diagnostics.py`
- `gui/CMakeLists.txt`
- `gui/README.md`
- `gui/backend_interface.h`
- `gui/backend_konsole.cpp`
- `gui/backend_qtermwidget.cpp`
- `gui/backend_tests.cpp`
- `gui/lifecycle_tests.h`
- `gui/main.cpp`
- `gui/paste_shortcut_filter.h`
- `gui/project_multiplexer_settings.h`
- `gui/project_tab_presentation.h`
- `gui/terminal_theme.h`
- `packaging/ci-lock.json`
- `packaging/reviewed-synthetic-secrets.json`
- `src/codex.rs`
- `src/lib.rs`
- `src/main.rs`
- `src/mcp.rs`
- `src/multiplexer.rs`
- `src/project_preference.rs`
- `src/registry.rs`
- `src/screen.rs`
- `src/session.rs`
- `src/tmux_archive.rs`
- `src/workspace.rs`
- `tests/fixtures/mock_app_server.py`
- `tests/fixtures/policy_addendum_v1_legacy.md`
- `tests/fixtures/test_mcp_stdio.py`
