# P0-D: read-only project registry and session-name configuration

## Current extension: per-project multiplexer (2026-10-22)

Project TOML accepts `[sessions].multiplexer = "screen"` (default when absent)
or `"tmux"`. There is no global multiplexer setting. The preference only selects
a future explicitly approved start; existing records retain their actual
multiplexer. `session projects` lists preferences; local `session prefer --id
ID --multiplexer screen|tmux` saves one without invoking any session operation.
Old configuration/records remain valid without migration. For the independent
GUI backend setting and safe manual test see [GUI](../gui/README.md) and
[comparison](TMUX_COMPARISON.md). Historical P0-D scope below predates this extension.

Status: implementation candidate, awaiting a successful local `cargo test`,
release build, and smoke test against Codex 0.163.0. No MCP gateway or writing
operation is present.

## Global configuration

The bridge reads `~/.config/chatgpt2codex/config.toml` (or the absolute path
provided with `--config`). If `XDG_CONFIG_HOME` is set to an absolute path,
the XDG equivalent is used. Project files are read from the adjacent `projects/`
folder, as `<project_id>.toml`. Samples are in `.ai/examples/`.

Example:

```toml
[workspace]
project_dir = "/home/peva/TEMP/mycode"
rules_dir = ".ai"
global_context_files = ["CODEX_GLOBAL.md", "BOOTSTRAP.md", "PROJECT_DEFAULTS.md"]

[codex]
name = "Kóďa"

[sessions]
name_template = "{project_id} | {codex_name} | {task}"
```

For each project, configure a direct child of `project_dir`:

```toml
[project]
id = "k2-smb"
directory = "k2-smb"
name = "K2 SMB"

[codex]
name = "Kóďa SMB"

[contexts]
files = ["AGENTS.md", ".ai/.project_codex.md", ".ai/PROJECT_CONTEXT.md", ".ai/CODEX_RESULTS.md"]
```

The project-level `[codex].name` and `[sessions].name_template` may override
global values. The name template supports exactly `{project_id}`, `{codex_name}`
and `{task}`, and **must include `{project_id}`**. The preview does not create,
rename or resume a Codex session. Future managed task execution will apply it
after `thread/start`, under its own approval policy.

## Supported local commands

Run from the repository root after building:

```sh
cargo test
cargo build --release
./target/release/gpt2codex projects list --config /absolute/config.toml
./target/release/gpt2codex project info --config /absolute/config.toml --id k2-smb
./target/release/gpt2codex project contexts --config /absolute/config.toml --id k2-smb
./target/release/gpt2codex project name --config /absolute/config.toml --id k2-smb --task 'Fix KIO'
./target/release/gpt2codex project sessions --config /absolute/config.toml --id k2-smb --limit 25
./target/release/gpt2codex project read --config /absolute/config.toml --id k2-smb --scope project --file .ai/.project_codex.md
```

`project read` is explicitly local and prints the selected text to stdout. Do
not send its raw output to ChatGPT automatically. The P0-D test helper avoids
recording any document contents. `project sessions` prints only validated
metadata using the existing read-only app-server adapter.

The registry refuses invalid/duplicate IDs, unknown TOML keys, project roots
outside `project_dir`, file/path symlinks, path traversal, non-allowlisted files,
large contexts, malformed name templates and control characters. Missing
optional Markdown files are listed as `missing`; they are not created.

## Important boundary: not a security sandbox

This implementation is a read-only local CLI and is **not ready to expose** as
MCP. The path checks do not yet eliminate time-of-check/time-of-use races or
all same-user filesystem access. A future remote read interface must use
kernel-enforced path resolution and proper outbound sanitization. Markdown
rules also do not grant executable permissions.

## Agreed bootstrap convention, deferred from P0-D

The eventual approved Workspace Manager will own project creation and validate
or create exactly these symlinks:

```text
project/.tmp -> /tmp/<project_id>/tmp
project/.log -> /tmp/<project_id>/log
```

It will validate ownership of `/tmp/<project_id>` and safely create private
subdirectories. A conflicting preexisting path fails closed. Changes to `.git`
ignore/exclude also belong to that separately authorized write phase. Codex
will be **informed** through Markdown but will not create/repair the layout.

The shared rules live in `project_dir/.ai/`, and templates for a future managed
installation live in `.ai/templates/` of this repository (template version in
`.ai/templates/VERSION`). P0-D does not write
to `project_dir/.ai/` or any target project.
