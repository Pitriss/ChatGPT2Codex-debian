#!/usr/bin/env bash
# P0-Ic Qt6/QTermWidget6 build and read-only self-test.
# Does not install packages, start GUI, create screen sessions, commit or push.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo 'P0IC=FAIL reason=not_a_git_repository'; exit 2; }
if [[ "$PWD" != "$ROOT" ]]; then echo 'P0IC=FAIL reason=run_from_repository_root'; exit 2; fi
if [[ ! -x "$ROOT/target/release/gpt2codex" ]]; then echo 'P0IC=FAIL reason=missing_rust_bridge'; exit 2; fi
if [[ ! -f "$ROOT/gui/CMakeLists.txt" || ! -f "$ROOT/gui/main.cpp" ]]; then echo 'P0IC=FAIL reason=missing_gui_sources'; exit 2; fi
if [[ ! -d "$ROOT/.tmp" || ! -d "$ROOT/.log" ]]; then echo 'P0IC=FAIL reason=workspace_not_ready'; exit 2; fi
for cmd in cmake g++ mktemp; do
  if ! command -v "$cmd" >/dev/null 2>&1; then echo "P0IC=NEEDS_DEPENDENCY missing=$cmd"; exit 3; fi
done

LOG="$(mktemp "$ROOT/.log/p0ic-qt6-v2-XXXXXXXX.log")"
BUILD="$(mktemp -d "$ROOT/.tmp/p0ic-qt6-v2-XXXXXXXX")"
BIN="$ROOT/target/release/gpt2codex-gui"

report_failure() {
  local step="$1"
  printf 'P0IC=FAIL step=%s\n' "$step"
  printf 'DETAILS=%s\n' "$LOG"
  tail -n 45 "$LOG"
  exit 1
}

printf 'P0-Ic: configuring Qt6/QTermWidget6 via CMake packages...\n'
cmake -S "$ROOT/gui" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release -DCMAKE_RUNTIME_OUTPUT_DIRECTORY="$ROOT/target/release" >"$LOG" 2>&1 || report_failure configure
printf 'P0-Ic: compiling GUI...\n'
cmake --build "$BUILD" --parallel 2 >>"$LOG" 2>&1 || report_failure compile
if [[ ! -x "$BIN" ]]; then report_failure missing_binary; fi
printf 'P0-Ic: running read-only/offscreen self-test...\n'
QT_QPA_PLATFORM=offscreen "$BIN" --bridge-cli "$ROOT/target/release/gpt2codex" --self-test >>"$LOG" 2>&1 || report_failure self_test
if ! grep -q '^P0IC_GUI=OK ' "$LOG"; then report_failure unexpected_self_test; fi
printf 'P0IC=OK build=release gui=%s screens_started=0 terminals_attached=0\n' "$BIN"
printf 'DETAILS=%s\n' "$LOG"
printf 'LAUNCH=%s\n' "$BIN"
