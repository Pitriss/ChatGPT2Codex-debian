# gpt2codex-gui – P0-Ic (Qt6 / QTermWidget6)

This is an **optional local GUI** for already running, bridge-registered GNU screen or tmux sessions. It does not launch or terminate a Codex task, register projects, change Git, send prompts, or expose new MCP commands. The existing Rust CLI remains the authority for project/session identity checks.

## Project multiplexer preference

Tmux can optionally retain an exited program's pane for **new** approved
starts (`--remain-on-exit`). GUI displays program exit separately from server
liveness, with no respawn. Interrupted slots have an explicit local archive
operation requiring a separate identity-bound approval; it never starts a new
session. See [lifecycle, archive safety and manual tests](../.ai/TMUX_LIFECYCLE.md).

Terminal backend (Konsole KPart / QTermWidget) and multiplexer (GNU screen /
tmux) are independent; all four combinations are supported. GNU screen remains
the default. **Nastavení → Terminál → Multiplexer projektu** selects a registered
project and saves only its preference using **Uložit preferenci projektu**.
The separate **Aplikovat** button still applies the backend/tab settings.
An unavailable multiplexer is disabled with an explanation. A stored unavailable
choice remains visible and never silently falls back.

The preference lives in that project's TOML under `[sessions]` as
`multiplexer = "screen"` or `"tmux"`. Missing values mean screen; existing
session records need no migration. Changing this field never starts, detaches,
stops, converts or removes a session. It only supplies the default for a future
explicit local `session start ... --approve-start` invocation. GUI has no start
operation. Bridge uses the gpt2codex project's preference for a future start.

Slots are keyed by `(multiplexer, project_id)`: the original screen record and
its CLI stay intact; a separately approved tmux start creates a distinct slot.
Tabs/tooltips show `[screen]` or `[tmux]`, and hidden tabs are tracked per slot.
One slot per multiplexer/project is supported; arbitrary additional task slots
and automatic reuse of interrupted tmux slots are not implemented.

Discovery uses `session list --program-status`; attach always supplies the actual multiplexer,
full session ID and process generation from that listing. tmux additionally
validates its private socket, server PID/start ticks, `$session_id` and creation
time. It never attaches to the user's default tmux server or guesses by name.
Missing/ambiguous identities stay disconnected. Screen uses `-r` / `-x`, never
takeover flags; tmux attaches without `-d`/`-x`/`-A`. Default tmux `Ctrl+B, D`
is respected as intentional detach just like screen `Ctrl+A, D`.

Local CLI examples (start commands require separate explicit operator approval):

```sh
./target/release/gpt2codex session probe
./target/release/gpt2codex session projects
./target/release/gpt2codex session prefer --id example --multiplexer tmux
./target/release/gpt2codex session list
./target/release/gpt2codex session status --id example --multiplexer screen
./target/release/gpt2codex session attach --id example --multiplexer screen
./target/release/gpt2codex session start --id example --multiplexer tmux --task 'Approved task' --approve-start
./target/release/gpt2codex session attach --id example --multiplexer tmux
```

Isolated regression tests: `python3 ./gpt2codex-multiplexer-test.py --backends`.
They replace Codex with a synthetic fixture-local executable, use private
registries/HOME/SCREENDIR/tmux sockets and leave all user sessions alone. If tmux
is absent its real PTY cases are reported as skipped. A test-only binary may be
supplied with `--tmux ABS --library-path ABS`; it is never installed globally.
See [manual Codex TUI comparison](../.ai/TMUX_COMPARISON.md) before testing real
Codex. The original yellow artifact cause remains unproven and is deferred.

## Phase A: safe terminal diagnostics

The live yellow horizontal artifacts are still unresolved in both backends.
The earlier QTermWidget wallpaper invalidation fix does not establish their
cause. No production terminal setting is changed speculatively.

Build with the existing root helper, then run from the repository root:

```sh
QT_QPA_PLATFORMTHEME=generic bash ./gpt2codex-p0ic-qt6-test-v2.sh
```

```sh
python3 ./gpt2codex-terminal-diagnostics.py --self-test
```

```sh
python3 ./gpt2codex-terminal-diagnostics.py
```

The one root diagnostic helper creates its own `SCREENDIR`, HOME and screenrc
under `.tmp/`, and five short-lived synthetic cases: a reference Unix PTY,
each real backend with `screen -r`, and each backend with `screen -x` alongside
a reference client. It never selects managed/user sessions, detaches another
client, starts Codex, sends keystrokes, or reads private terminal output.
The fixture exits by itself; cleanup does not use screen quit/kill commands.
The tests need local PTY/socket access, which restricted sandboxes may deny.

Reports go to a new `.log/terminal-diagnostics-*/` directory: `summary.json`,
backend logs and synthetic-only PNGs before/after a full repaint. Environment
metadata is allowlisted and sanitized; no complete environment, TERMCAP,
process command-line or conversation dump is recorded. The user's configured
font is exercised, but profile files, palette and background are fixtures;
the user's wallpaper is not captured. The white reset text, ANSI color chart,
yellow underline and yellow box outline in those images are intentional.

For desktop comparison, launch from an ordinary standalone terminal outside
screen/tmux:

```sh
python3 ./gpt2codex-terminal-diagnostics.py --visual
```

This shows the same synthetic pattern in the ordinary terminal for seven
seconds, then in each backend for three sizes, including the shared-client
cases. It does not open the normal session-manager window or attach real
Codex. Compare extra stripes, not the intentional yellow underline/box.
Headless success does not prove a fix for the live Codex problem. In phase A
we stop for user feedback; tab icons/tmux (phase B) require explicit confirmation
that the original artifacts are gone in both backends.

## Clipboard paste with embedded terminals (P0-Jb)

- The `Upravit -> Vložit text ze schránky` action and `Ctrl+Shift+V` /
  `Shift+Insert` shortcuts use the active backend's native clipboard paste.
  Only terminal tabs enable this action; the Settings tab retains normal
  text-editing shortcuts.
- Konsole KPart triggers its session-controller `edit_paste` action, and
  QTermWidget uses `pasteClipboard()`; neither dispatches clipboard text via
  `screen -X stuff`, shell commands, nor synthetic key events.
- `Ctrl+V` remains reserved to Codex TUI (often used for image paste).
  An application event filter claims these two shortcuts only inside the
  selected terminal, before KPart shortcut handling, and triggers the same
  menu action. This avoids ambiguous shortcuts and Konsole forwarding the
  keys to the terminal. Settings editors keep their normal shortcuts.
- The main window owns both paste shortcuts. Embedded KPart actions have
  just those two bindings removed (also after a shortcut reload), while their
  native menu actions and other bindings remain available. No extra QShortcut
  is registered.
- Clipboard text is never logged. The GUI does not start/stop any Codex
  task or GNU screen session as part of pasting. Test with a harmless
  single line before attempting multiline paste.

## Keyboard focus and mouse-reporting diagnostics (P0-Ja)

The GUI explicitly focuses the real `TerminalDisplay` (when available) after
attaching a terminal, selecting a session tab, and restoring the window from
the tray. This addresses a keyboard-focus gap in the Qt6/Konsole KPart wrapper
without changing keyboard shortcuts, PTY content, or GNU screen sessions.

Literal strings such as `[<35;...M` on mouse movement indicate mouse-reporting
protocol bytes reaching a consumer that is not interpreting them. This can
independently originate in Codex TUI, GNU screen, or the terminal backend,
and **must not** be assumed to be fixed by the focus change. Use **Nastavení →
Terminál → QTermWidget → Aplikovat** as a safe, reversible comparison. If it
also occurs in a normal `gpt2codex screen attach --id k2-smb` client, investigate
the screen/Codex protocol rather than injecting terminal control sequences or
suppressing mouse events blindly. Do not restart registered sessions just to
clear mouse tracking.

## Supported behavior

- First pinned `Bridge` tab: an interactive PTY attached through the already registered `g2c-bridge` screen session. When missing, it displays a message rather than starting a shell.
- The first valid startup listing automatically attaches an existing Bridge.
  Selecting a disconnected terminal tab requests one fresh identity check and
  reattaches the same session. Switching tabs keeps inactive terminal widgets,
  scrollback and processes alive. Periodic polling and terminal exit alone do
  not retry attachment, so failed reconnects cannot form a loop.
- **Relace → Odpojit aktuální terminál**, closing a project tab, and screen's
  default `Ctrl+A`, `D` (also `Ctrl+A`, `Ctrl+D`) are intentional disconnects.
  They do not automatically reconnect on tab activation or backend changes;
  use **Znovu připojit terminál** to reconnect explicitly. Custom screen
  detach bindings/commands cannot be distinguished from a transport failure;
  use the GUI detach action when automatic reconnect on later activation
  should remain disabled. No retry happens immediately after any exit.
- A changed or unavailable session identity blocks automatic reconnect;
  explicit reconnect still requires a fresh valid listing and CLI validation.
- Other tabs represent registered active or interrupted sessions. Their labels use `<project_id> | <task> [screen|tmux]`; Bridge tabs show their multiplexer too.
- Every terminal uses the selected native backend to launch `gpt2codex session attach --multiplexer ...` with verified identity and `--bridge` or `--id`, without a shell command string.
- Close a project tab to disconnect the view only. Use *Show hidden tabs* to re-open it. The Bridge tab cannot be closed individually.
- Window close hides into a KDE-compatible system tray when available; a tray action restores it or exits **GUI only**. If the tray is unavailable, window close exits the GUI; screen sessions remain independent.
- Periodic read-only refresh and a *Refresh* action show bridge-reported session status. A failed/malformed refresh cannot create a new terminal process.
- GUI restart reconstructs the tabs by asking the bridge again. After a workstation reboot, dead screen processes cannot be restored; the bridge shows interrupted records and the GUI never automatically replays them.

## Native theme integration (P0-Ic theme refinement)

The Qt6 interface deliberately does not force a Qt widget style, application palette,
font or Fusion theme. It uses the current Qt platform theme (including Plasma/Breeze
when KDE's Qt6 platform integration is active) and follows system palette changes.

Each embedded QTermWidget is themed separately because terminal colors are independent
of Qt widget colors. If `konsolerc` selects an installed default Konsole profile,
read that profile **without changing it**, use its configured terminal font and load
its `.colorscheme` from the user's/system's Konsole data directory. Symlinked user
profile files are not rewritten or rejected solely for being symlinks. If no usable
Konsole color scheme exists, choose a bundled QTermWidget light/dark color scheme
based on the effective Qt `Base` palette; use the system fixed-pitch font. A GUI
palette change also refreshes the attached QTermWidget colors. The active Konsole `.colorscheme` also supplies its `[General] Opacity` setting
and, if configured, a readable local `Wallpaper` image. QTermWidget supports
background images and opacity, but **is not the Konsole renderer**: effects such
as the Konsole/Plasma desktop blur, wallpaper alpha blending, and exact Konsole
wallpaper scaling are not guaranteed to match. A missing/unreadable image is
ignored without modifying the scheme. **Qt's INI reader maps Konsole's literal
`[General]` section to top-level keys** (`Opacity`, `Wallpaper`, `FillStyle`),
not `General/...`; this fixes the previous silent fallback to `1.00`/`none`.
`--theme-probe` reports `background_opacity=...`,
`wallpaper=none|available|missing`, and `background_color=#RRGGBB|unknown`.
The color reports the source `[Background] Color`, not sampled rendered pixels;
`available` means the image passed basic checks, not that rendering has been
visually tested. A solid Konsole scheme may legitimately have `Wallpaper=` empty.

Wallpaper placement (P0-Ic refinement): Konsole and QTermWidget have different
wallpaper fill-style enums. The GUI renders a **static viewport-sized image**
using the selected Konsole `[General] FillStyle` (`Tile`, `Stretch`, `Crop`,
`Adapt`, `NoScaling`), `Anchor`, `WallpaperOpacity`, and `WallpaperFlipType`.
It refreshes that image after terminal resizing and hands it to QTermWidget
without a second transform. Images are held in private temporary files that
are deleted when the GUI terminates normally; the GUI does not modify Konsole's
profile, scheme or source image. Very large images/terminal surfaces are
skipped to bound memory usage. This approach does **not** provide animated
wallpapers or guarantee identical KDE compositor effects such as blur.
`--theme-probe` additionally reports `wallpaper_fill`, `wallpaper_anchor`,
`wallpaper_opacity`, and `wallpaper_flip` to help diagnose real profiles.

The **Settings tab (Nastavení → Otevřít nastavení)** configures the
maximum title length (12–128 characters, default 32). Existing tabs update
immediately; the full title remains accessible in the tooltip and the Bridge
tab stays pinned. The only written configuration is the GUI's own per-user
`gpt2codex/gpt2codex-gui` Qt INI settings, key `tabs/maxLabelChars`. This
is separate from the Rust bridge's TOML files, and is written **only when the
user confirms a change** using **Aplikovat** in the settings tab. `--settings-probe` prints the
effective limit and user-specific configuration location without starting
terminals. Qt still elides visually on very narrow tab bars and provides
scroll arrows when necessary.

Changing the Konsole profile itself while the GUI is open requires restarting
the GUI (not the screen sessions). Other terminal emulators such as Kitty can
have independent profiles; this implementation does not claim to import their
private theme formats.

To inspect which style and terminal theme the GUI selected without opening a window
or attaching any `screen` session, run:

```sh
QT_QPA_PLATFORM=offscreen ./target/release/gpt2codex-gui --theme-probe
```

The `offscreen` UI style may not be the same style as a desktop session; run without
`QT_QPA_PLATFORM=offscreen` in a real Plasma session to inspect the desktop theme.

## Build (Debian 13)

Required core build packages: `qt6-base-dev`, `cmake`, `g++`. Install at least one backend development stack described below. **No package installation is performed by the helper.** Debian 13 provides Qt6 QTermWidget development files in `libqtermwidget-dev` (not in a package named `libqtermwidget6-dev`).

From the project root use `bash ./gpt2codex-p0ic-qt6-test-v2.sh`. The GUI build uses the installed Qt6 and qtermwidget6 CMake package configuration, not a combined pkg-config preflight. Debian 13 QTermWidget6 also needs the unversioned `libutf8proc.so` development linker library; `libutf8proc3` alone is insufficient. Install `libutf8proc-dev` using `sudo apt-get install libutf8proc-dev` before building. CMake checks this dependency and reports a focused error if it is absent. It compiles an executable at `target/release/gpt2codex-gui` and invokes its read-only `--self-test`. It does **not** open GUI windows or attach existing sessions during testing.

To open the GUI separately:

```sh
./target/release/gpt2codex-gui
```

With CMake's default `BUILD_TESTING=ON`, the helper also builds
`target/release/gpt2codex-gui-tests` (Qt6 Test from `qt6-base-dev`). Run
`QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=generic ./target/release/gpt2codex-gui-tests`
or `ctest --test-dir BUILD_DIRECTORY --output-on-failure` for lifecycle and
shortcut regression tests. These use an in-memory backend, with no PTY or
screen attachment. The generic platform theme avoids desktop theme dialogs
during headless testing; it does not change saved GUI/KDE settings. Interactive
Konsole rendering, clipboard safety prompts and tray behavior still need a
desktop check.

`ctest` also runs `gui-konsole-integration` when Konsole is built and
`gui-qterm-render` when QTermWidget is built. The former creates two actual
KParts without starting a program, checks the native paste action/menu and
both shortcuts, and rejects ambiguous-shortcut/null-widget warnings. KPart
initialization needs access to a local PTY even though no child is launched.
The latter feeds synthetic ANSI output directly into an unstarted QTermWidget
session, comparing the existing raster backing store against a complete
repaint after scrolling, erasing, resizing and TUI-style updates, with and
without wallpaper. It also verifies that yellow ANSI text stays colored.
Both use temporary fixture profiles and leave the user's Konsole files alone.

Konsole 25.04's hidden KPart tab bar inserts null widgets for disabled corner
buttons ([upstream fix](https://github.com/KDE/konsole/commit/e67e3226c6317aa1b2247704a11ae1e9d34d7b93)).
The backend keeps those hidden buttons present using nonpersistent, in-memory
KConfig entries; it does not save `konsolerc`. Our tab bar remains the visible
one. QTermWidget 2.1's `setTerminalBackgroundImage()` replaces the pixmap without
scheduling repaint. The backend now invalidates its viewport once after each
wallpaper replacement, preventing stale horizontal strips after resize. This
is a verified wallpaper repaint fix; it does not establish that every reported
yellow artifact in a live screen/Codex TUI has the same cause.

The GUI discovers the `gpt2codex` Rust CLI next to its own binary by default. Optionally pass `--bridge-cli /absolute/path/gpt2codex` and `--config /absolute/path/config.toml`.

## Boundaries and remaining work

This is a **terminal view**, not an API for programmatic task submission. It intentionally does not send `screen -X stuff`, drive the Codex UI remotely, or bypass approvals. Concurrent manual attachments share one interactive screen session; avoid typing in two clients simultaneously. Structured bridge/Codex app-server coordination and QTermWidget/GUI runtime integration tests are future, separately reviewed work.

QTermWidget is an external library: consult the installed Debian copyright notice and upstream LGPL licensing before packaging/distribution. The Rust MIT core remains independent of the optional GUI.


## P0-Id/e – selectable terminal backends and Settings tab

`gpt2codex-gui` is now Qt6-only and discovers up to two **optional**, separately
loadable terminal modules (`gpt2codex-backends/libgpt2codex-backend-*.so`
beside the development executable, or under the install-time GNUInstallDirs
library path). It does not directly link against either Konsole KPart or
QTermWidget6. Compile QTermWidget with `qt6-base-dev libqtermwidget-dev
libutf8proc-dev`, Konsole KPart with `qt6-base-dev libkf6parts-dev
libkf6coreaddons-dev`; system `konsole-kpart` supplies the KF6 runtime plugin.
When only one backend is available the GUI still runs. The default Auto mode
prefers Konsole KPart; otherwise QTermWidget. Explicit selection never silently
falls back. With both, **Nastavení** menu opens a reusable, closeable
Settings tab, containing extensible Terminal and Tabs categories. **Aplikovat**
persists the `terminal/backend` (`auto`, `konsole`, `qtermwidget`) and
`tabs/maxLabelChars` settings. Until then edits are provisional. Backend
changes synchronously destroy only old terminal view widgets, then recheck
managed session identities via the bridge's read-only `session list` before
recreating the views; they never restart Codex or GNU screen processes.
A failed or unavailable backend does not silently change running sessions;
reconnection requires verification, and failed refreshes leave views detached.

`--backend-probe`, `--settings-probe` and `--self-test` are read-only and never
attach to screen sessions. The `--backend-probe` output shows which modules are
actually usable on this desktop. The `--settings-probe` keeps `config=...` last
for compatibility with existing tests.

Debian packaging should split the core Qt6 application and backend modules.
When shipping both modules, use the alternative dependency
`gpt2codex-gui-backend-konsole | gpt2codex-gui-backend-qtermwidget` on the GUI
package, and use `dpkg-shlibdeps` to discover individual backend runtime
library dependencies. Do not mistakenly treat `konsole-kpart` as providing the
QTermWidget linker library. The KF6 Konsole plugin dynamically starts only the
validated `gpt2codex session attach` CLI (no shell injection or screen stuffing).

## P0-If: session identity across GUI backend changes

After **Apply** switches the terminal backend, the GUI destroys only the
transient attached PTY widgets. It records each previously live screen's full
`session_id` and reattaches automatically **only** after a new, valid `screen
list` confirms that the ID has not changed. A replacement session at the same
project slot is left detached with a visible warning and requires the user's
manual **Znovu připojit terminál** action; that action rechecks the ID again.
Unexpected identity changes detected during ordinary polling also detach stale
views. When a slot is unconfirmed/interrupted it is not automatically
reattached later. The Rust CLI still performs its independent procfs identity
check during `screen attach`. The GUI never starts/replays a Codex task.

The earlier Konsole null-widget layout warning was traced to its hidden tab
corner controls and addressed with a nonpersistent KConfig compatibility fix.
Regression tests reject that warning and ambiguous paste shortcuts. A
`KPtyProcess` `SIGHUP` notice when destroying an attachment concerns the
transient client; isolated screen/tmux tests verify that servers survive.

## P0-J: Codex API diagnostics (read-only)

The **Nastavení → Codex API** category lists registered projects using the
local Rust bridge, then runs `gpt2codex codex diagnostics --id PROJECT_ID`
only after an explicit click. It does not attach to or control any screen TUI.
The diagnostic connection is a separate short-lived Codex app-server child;
its notification counts are not live TUI event subscriptions. Unexpected
stdout, stderr and server-provided text are never shown by the GUI.
See `.ai/P0J_READONLY_APP_SERVER.md` for the CLI and security boundary.

## Project icons in terminal tabs (2026-10-28)

Each terminal tab has a project icon before its existing title. The GUI reads
the project root from the existing local `projects list` registry command;
Bridge maps to the registered `gpt2codex` root. It never derives a filesystem
path from a task label, project display name or preferred multiplexer.
The tooltip includes the full registered root and the **actual** screen/tmux
value of that session. Tooltip paths/labels are escaped as text.

Place an optional `.icon.png` directly in a registered project's root. The GUI
only reads a regular PNG, at most 1 MiB and 1024 by 1024 pixels. Directory and
file symlinks are not followed, including symlinks to another file inside the
project. Every path component and the final file are opened relative to held
directory descriptors; the final file is nonblocking and size bounded. Invalid,
oversized, missing, fully transparent or otherwise unusable images fall back
to KDE's `utilities-terminal` icon, or `network-connect` for Bridge. When the
theme lacks that name, Qt supplies a standard terminal/computer or network
fallback. User files, permissions and KDE configuration are never modified.

Artwork fits a 20 by 20 logical-pixel square without distortion, with source
pixels retained for high-DPI displays. An empty 8-pixel horizontal space after
the icon prepares the layout for a future state indicator; no indicator,
Attention Manager or state feed is implemented. Native Qt tab text, elision,
close buttons, theme and keyboard navigation remain in use. Palette/style
changes refresh the themed icons. Registry refresh invalidates icon caches,
so replacing/removing `.icon.png` is visible on the next refresh. A failed
registry read removes custom images and marks the path as unverified without
affecting session polling or terminal attachments.

Run from the repository root:

```sh
python3 ./gpt2codex-project-icons-test.py
```

This root helper invokes the existing release GUI build/self-test workflow and
CTest with private HOME/config/state/SCREENDIR. Its registry contains only an
empty synthetic Bridge project. No Codex, screen or tmux server is started;
no existing session is selected. GUI tests cover unsafe paths/images, fallback,
aspect ratio and high DPI, project/actual-multiplexer mapping, preference saves,
refresh/reordering/closing/restoring tabs, reconnect, and the existing paste
and backend regressions. The helper requires installed build dependencies and
local PTY access for unstarted Konsole KParts. No packages are installed.

For manual desktop verification use a **separate isolated GUI**, for example
the synthetic lifecycle fixture in [TMUX_LIFECYCLE.md](../.ai/TMUX_LIFECYCLE.md),
without restarting the production GUI. Use only your own new fixture project:
add a small visible `.icon.png` to its root, refresh the list, check the title,
tooltip and 20-pixel artwork. Replace it with a wide/tall PNG, then remove it or
use an invalid file/symlink and check fallback. Switch Qt light/dark themes,
compare both backends, reconnect and restore a closed fixture tab. Verify that
the root and actual screen/tmux tooltip follow the project rather than its tab
position or preference. Do not enter test text into live Codex sessions. A
synthetic fixture start still needs its own explicit approval; icons themselves
never start, detach, archive or restart sessions. Desktop visual verification
is separate from offscreen regression results.
